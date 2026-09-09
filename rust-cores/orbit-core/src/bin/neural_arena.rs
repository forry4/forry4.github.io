//! Development arena for native search versus frozen Hard v2. Not a ship gate.
use orbit_core::{State,search::{choose,Config},attention::Model};
use serde_json::{json,Value};
use std::io::{self,BufRead,Write};
fn main() {
    let line=io::stdin().lock().lines().next().unwrap().unwrap();
    let request:Value=serde_json::from_str(&line).unwrap();
    let model=Model::load(&request["model"]).expect("valid model");
    let opponent=request.get("opponent_model").map(|v|Model::load(v).expect("valid opponent model"));
    let fixed_sims=request.get("simulations").and_then(Value::as_u64);
    assert!(fixed_sims.is_none_or(|n|n>0 && n<=10000),"Invalid fixed simulation count");
    let jobs=request["jobs"].as_array().unwrap();
    let mut out=io::BufWriter::new(io::stdout().lock());
    for job in jobs {
        let seed=job["seed"].as_u64().unwrap();let candidate=job["candidate"].as_u64().unwrap() as usize;
        let sides:[i32;3]=serde_json::from_value(job["sides"].clone()).unwrap();
        let budget=request["budget_ms"].as_u64().unwrap_or(100);
        let (mut state,mut chance)=State::new(seed,sides);let mut turn=state.turn_number;
        let mut remaining=[budget;2];let mut sims=0u64;let mut calls=0;let mut decisions=0;
        let mut failure=None;
        while let Some(seat)=state.actor() {
            if decisions>=1600 {break;}
            if state.turn_number!=turn {turn=state.turn_number;remaining=[budget;2];}
            let evaluator=if seat==candidate {Some(&model)}else{opponent.as_ref()};
            let mv=if let Some(evaluator)=evaluator {
                let config=Config{simulations:fixed_sims.unwrap_or(100000) as usize,max_depth:96,
                    budget_ms:if fixed_sims.is_some(){60000}else{remaining[seat]}};
                match choose(&state,seat,seed.wrapping_add(decisions),config,Some(evaluator)) {
                    Ok(result)=> {
                        if fixed_sims.is_some_and(|n|result["simulations"].as_u64()!=Some(n)) {
                            failure=Some("Fixed-simulation arena exceeded safety deadline".into());break;
                        }
                        remaining[seat]=remaining[seat].saturating_sub(result["elapsed_ms"].as_f64().unwrap().ceil() as u64);
                        sims+=result["simulations"].as_u64().unwrap();calls+=1;result["move"].clone()
                    },
                    Err(error)=>{failure=Some(error);break;}
                }
            }else{
                let obs=state.observation(seat);
                orbit_core::serving::choose_move(&obs,obs["legal_moves"].as_array().unwrap(),&Value::Null,budget as i64,seed)["move"].clone()
            };
            if let Err(error)=state.apply(seat,&mv,&mut chance) {failure=Some(error);break;}
            decisions+=1;
        }
        writeln!(out,"{}",json!({"seed":seed,"candidate":candidate,"sides":sides,
            "winner":state.winner,"censored":state.phase!="over","error":failure,
            "simulations":sims,"calls":calls,"decisions":decisions})).unwrap();out.flush().unwrap();
        if failure.is_some(){break;}
    }
}
