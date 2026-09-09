//! Parallel offline baseline generation. Policies only receive observations.
use orbit_core::{State,Chance};
use serde_json::{json,Value};
use std::io::{self,BufRead,Write};

fn game(job:&Value,models:&[orbit_core::attention::Model],simulations:usize) -> Result<Value,String> {
    let seed=job["seed"].as_u64().ok_or("Missing seed")?;
    let sides:[i32;3]=serde_json::from_value(job["sides"].clone()).map_err(|e|e.to_string())?;
    if sides.iter().any(|s|!(1..=2).contains(s)) { return Err("Invalid board sides".into()); }
    let names=job["policies"].as_array().ok_or("Missing policies")?;
    let model_index=|name:&Value|name.as_str().and_then(|n|n.strip_prefix("neural-")).and_then(|n|n.parse::<usize>().ok());
    if names.len()!=2 || names.iter().any(|n|!matches!(n.as_str(),Some("hard-v2"|"exploratory-v2"|"random"))
        && !model_index(n).is_some_and(|i|i<models.len())) {
        return Err("Unknown policy".into());
    }
    let (mut state,mut chance)=State::new(seed,sides);
    let mut policy_rng=Chance::seeded(seed ^ job["assignment"].as_u64().unwrap_or(0));
    let mut steps=Vec::new();
    let mut search_evaluations=0u64;
    for decision in 0..1600 {
        let Some(seat)=state.actor() else { break; };
        let obs=state.observation(seat);
        let moves=obs["legal_moves"].as_array().ok_or("Missing legal actions")?;
        if moves.is_empty() { return Err("Nonterminal actor without moves".into()); }
        let mv=if let Some(index)=model_index(&names[seat]) {
            let config=orbit_core::search::Config{simulations,max_depth:96,budget_ms:60000};
            let result=orbit_core::search::choose(&state,seat,seed.wrapping_add(decision),config,Some(&models[index]))?;
            if result["simulations"].as_u64()!=Some(simulations as u64) {
                return Err("Fixed-simulation teacher exceeded safety deadline".into());
            }
            search_evaluations+=result["evaluations"].as_u64().unwrap();
            result["move"].clone()
        }else if names[seat]=="random" || (names[seat]=="exploratory-v2" && policy_rng.index(100)<20) {
            moves[policy_rng.index(moves.len())].clone()
        } else {
            let result=orbit_core::serving::choose_move(&obs,moves,&Value::Null,5000,seed);
            result.get("move").filter(|m|moves.contains(m)).ok_or("Ranker returned illegal move")?.clone()
        };
        for viewer in 0..2 {
            steps.push(json!({"actor_seat":seat,"observer_seat":viewer,
                "observation":if viewer==seat {obs.clone()} else {state.observation(viewer)}}));
        }
        state.apply(seat,&mv,&mut chance)?;
    }
    state.validate()?;
    Ok(json!({"seed":seed,"pair":job["pair"],"assignment":job["assignment"],
        "board":job["board"],"policies":names,"censored":state.phase!="over", "winner":state.winner,
        "steps":steps,"search_evaluations":search_evaluations}))
}
fn main() {
    let input=io::stdin().lock().lines().next().expect("request").expect("read");
    let request:Value=serde_json::from_str(&input).expect("JSON");
    if let Some(obs)=request.get("observation") {
        let result=orbit_core::serving::choose_move(obs,obs["legal_moves"].as_array().expect("moves"),&Value::Null,5000,0);
        println!("{result}");return;
    }
    let jobs=request["jobs"].as_array().expect("jobs").clone();
    let models:Vec<orbit_core::attention::Model>=request["models"].as_array().into_iter().flatten()
        .map(|v|orbit_core::attention::Model::load(v).expect("valid teacher model")).collect();
    let simulations=request["simulations"].as_u64().unwrap_or(64) as usize;
    assert!(simulations>0 && simulations<=10000,"Invalid simulation budget");
    let total=jobs.len();
    let threads=request["threads"].as_u64().unwrap_or(1).clamp(1,8) as usize;
    let jobs=std::sync::Mutex::new(jobs.into_iter().enumerate().collect::<std::collections::VecDeque<_>>());
    let (tx,rx)=std::sync::mpsc::channel();
    std::thread::scope(|scope| {
        for _ in 0..threads {
            let tx=tx.clone();let jobs=&jobs;let models=&models;
            scope.spawn(move ||loop {
                let Some((index,job))=jobs.lock().unwrap().pop_front() else {break};
                let value=match game(&job,models,simulations) {Ok(g)=>json!({"index":index,"game":g}),Err(e)=>json!({"index":index,"error":e})};
                tx.send(value).unwrap();
            });
        }
        let mut out=io::BufWriter::new(io::stdout().lock());
        for _ in 0..total {writeln!(out,"{}",rx.recv().unwrap()).unwrap();out.flush().unwrap();}
    });
}
