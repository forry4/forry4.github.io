//! Development arena for native search versus frozen Hard v2. Not a ship gate.
use orbit_core::{State,search::{choose,Config},attention::Model};
use serde_json::{json,Value};
use std::io::{self,BufRead,Write};
/// Run `pool` independent trees on one decision and sum their root visits.
///
/// This is the shipped serving arrangement: the browser fans the same decision
/// out to a capped worker pool and aggregates at the root, so a single tree
/// under-reports the strength the product actually has. Each tree gets the
/// whole allowance because the workers are concurrent, and the elapsed time
/// charged to the turn is the slowest tree, not their sum.
fn choose_pooled(state:&State,seat:usize,seed:u64,config:Config,model:Option<&Model>,pool:usize)->Result<Value,String> {
    if pool<=1 {return choose(state,seat,seed,config,model);}
    let trees:Vec<Result<Value,String>>=std::thread::scope(|scope| {
        let handles:Vec<_>=(0..pool).map(|k|{
            let seed=seed.wrapping_add((k as u64).wrapping_mul(0x9E3779B97F4A7C15));
            scope.spawn(move||choose(state,seat,seed,config,model))
        }).collect();
        handles.into_iter().map(|h|h.join().unwrap_or_else(|_|Err("Search worker panicked".into()))).collect()
    });
    let mut roots=Vec::new();
    for tree in trees {roots.push(tree?);}
    let first=&roots[0];
    let width=first["stats"].as_array().ok_or("Missing root statistics")?.len();
    // Move order is a deterministic sort inside the search, so equal-width
    // statistics arrays are aligned; anything else means the trees disagree
    // about the position and must not be summed.
    let mut visits=vec![0u64;width];let mut totals=vec![0f64;width];
    let mut simulations=0u64;let mut evaluations=0u64;let mut elapsed:f64=0.0;
    for root in &roots {
        let stats=root["stats"].as_array().ok_or("Missing root statistics")?;
        if stats.len()!=width {return Err("Pooled trees disagree about the move list".into());}
        for (index,entry) in stats.iter().enumerate() {
            if entry["move"]!=first["stats"][index]["move"] {return Err("Pooled trees disagree about move order".into());}
            let n=entry["visits"].as_u64().unwrap_or(0);
            visits[index]+=n;
            totals[index]+=entry["value"].as_f64().unwrap_or(0.0)*n as f64;
        }
        simulations+=root["simulations"].as_u64().unwrap_or(0);
        evaluations+=root["evaluations"].as_u64().unwrap_or(0);
        elapsed=elapsed.max(root["elapsed_ms"].as_f64().unwrap_or(0.0));
    }
    let mean=|i:usize|if visits[i]==0 {0.0} else {totals[i]/visits[i] as f64};
    let best=(0..width).max_by(|a,b|visits[*a].cmp(&visits[*b]).then_with(||mean(*a).total_cmp(&mean(*b)))).ok_or("Empty root")?;
    let stats:Vec<Value>=(0..width).map(|i|json!({"move":first["stats"][i]["move"],"visits":visits[i],"value":mean(i)})).collect();
    Ok(json!({"move":first["stats"][best]["move"],"simulations":simulations,"evaluations":evaluations,
              "elapsed_ms":elapsed,"stats":stats,"pool":pool,"belief":"current-observation prior"}))
}

fn main() {
    let line=io::stdin().lock().lines().next().unwrap().unwrap();
    let request:Value=serde_json::from_str(&line).unwrap();
    // A null model runs the same search with the heuristic leaf, so an arena can
    // separate the contribution of search from the contribution of the network.
    let model=if request["model"].is_null() {None} else {Some(Model::load(&request["model"]).expect("valid model"))};
    let opponent=request.get("opponent_model").map(|v|Model::load(v).expect("valid opponent model"));
    let fixed_sims=request.get("simulations").and_then(Value::as_u64);
    assert!(fixed_sims.is_none_or(|n|n>0 && n<=10000),"Invalid fixed simulation count");
    let pool=request["pool"].as_u64().unwrap_or(1).max(1) as usize;
    assert!(pool<=8,"Worker pool is capped at eight");
    let jobs=request["jobs"].as_array().unwrap();
    let mut out=io::BufWriter::new(io::stdout().lock());
    for job in jobs {
        let seed=job["seed"].as_u64().unwrap();let candidate=job["candidate"].as_u64().unwrap() as usize;
        let sides:[i32;3]=serde_json::from_value(job["sides"].clone()).unwrap();
        let budget=request["budget_ms"].as_u64().unwrap_or(100);
        // Mirror the serving allocation: the turn's main action is capped, the
        // remainder is reserved for follow-up decisions, and a forced move is
        // played without search so it cannot consume the turn's budget.
        let main_ms=request["main_action_ms"].as_u64().unwrap_or(budget);
        let followup_ms=request["followup_ms"].as_u64().unwrap_or(budget);
        let (mut state,mut chance)=State::new(seed,sides);let mut turn=state.turn_number;
        let mut remaining=[budget;2];let mut acted=[0u32;2];let mut sims=0u64;let mut calls=0;let mut decisions=0;
        let mut failure=None;
        while let Some(seat)=state.actor() {
            if decisions>=1600 {break;}
            if state.turn_number!=turn {turn=state.turn_number;remaining=[budget;2];acted=[0;2];}
            let legal=state.legal_moves(seat);
            let evaluator=if seat==candidate {model.as_ref()}else{opponent.as_ref()};
            let mv=if legal.len()==1 {legal[0].clone()}
            else if seat==candidate||opponent.is_some() {
                let allowance=remaining[seat].min(if acted[seat]==0 {main_ms}else{followup_ms});
                let config=Config{simulations:fixed_sims.unwrap_or(100000) as usize,max_depth:96,
                    budget_ms:if fixed_sims.is_some(){60000}else{allowance}};
                match choose_pooled(&state,seat,seed.wrapping_add(decisions),config,evaluator,if seat==candidate {pool} else {1}) {
                    Ok(result)=> {
                        let quota=fixed_sims.map(|n|n*if seat==candidate {pool as u64} else {1});
                        if quota.is_some_and(|n|result["simulations"].as_u64()!=Some(n)) {
                            failure=Some("Fixed-simulation arena exceeded safety deadline".into());break;
                        }
                        remaining[seat]=remaining[seat].saturating_sub(result["elapsed_ms"].as_f64().unwrap().ceil() as u64);
                        acted[seat]+=1;
                        sims+=result["simulations"].as_u64().unwrap();calls+=1;result["move"].clone()
                    },
                    Err(error)=>{failure=Some(error);break;}
                }
            }else{
                let obs=state.observation(seat);
                orbit_core::serving::choose_move(&obs,obs["legal_moves"].as_array().unwrap(),&Value::Null,budget as i64,seed)["move"].clone()
            };
            let _=&legal;
            if let Err(error)=state.apply(seat,&mv,&mut chance) {failure=Some(error);break;}
            decisions+=1;
        }
        writeln!(out,"{}",json!({"seed":seed,"candidate":candidate,"sides":sides,
            "winner":state.winner,"censored":state.phase!="over","error":failure,
            "simulations":sims,"calls":calls,"decisions":decisions})).unwrap();out.flush().unwrap();
        if failure.is_some(){break;}
    }
}
