//! Independent observation-to-semantic extraction. Never accepts privileged State.
use serde_json::{json,Value};
use std::collections::BTreeSet;

const GROUPS: &[(&str,&[&str])] = &[
    ("turn", &["schema","seat","phase","turn_pid","turn_number","mulligan_done","winner"]),
    ("captures", &["influence","captured_this_turn"]), ("technology", &["board_sides"]),
    ("bonuses", &["planet_bonus","technology_bonus","bonus_discard","bonus_deck_count"]),
    ("leader", &["leader"]), ("public_cards", &["agent_discard","agent_deck_count"]),
    ("pending", &["pending","pending_pid"]), ("legal_actions", &["legal_moves"]),
];
const PLAYERS: &[(&str,&[&str])] = &[
    ("resources", &["credits","zenithium","hand_count"]), ("tableau", &["columns"]),
    ("technology", &["technology"]), ("bonuses", &["row_bonuses"]),
    ("captures", &["captured"]), ("own_hand", &["hand"]),
];
const TASK: &[&str] = &["type","amount","target","planet","exclude","restriction","distinct_from",
    "selected","amounts","label","cost","count","done","used","owner","distinct","reward",
    "faction","discount","lowest","tiers","planets","index","center","neighbor","influence_each",
    "require_full","one_at_a_time","options","branch_labels"];

fn keys(v:&Value, allowed:&[&str], exact:bool) -> Result<(),String> {
    let object = v.as_object().ok_or("Expected observation object")?;
    let permitted:BTreeSet<&str> = allowed.iter().copied().collect();
    if object.keys().any(|k|!permitted.contains(k.as_str())) || (exact && object.len()!=permitted.len()) {
        return Err("Unreviewed or incomplete observation fields".into());
    }
    Ok(())
}
pub fn validate(obs:&Value) -> Result<(),String> {
    let mut fields:Vec<&str> = GROUPS.iter().flat_map(|(_,f)|f.iter().copied()).collect();
    fields.push("players");
    keys(obs,&fields,true)?;
    let seat = obs["seat"].as_u64().ok_or("Invalid seat")?;
    if obs["schema"] != 1 || seat>1 { return Err("Observation schema/seat mismatch".into()); }
    let players = obs["players"].as_array().ok_or("Missing players")?;
    if players.len()!=2 { return Err("Expected two players".into()); }
    for (i,p) in players.iter().enumerate() {
        let fields:Vec<&str> = PLAYERS.iter().flat_map(|(_,f)|f.iter().copied()).filter(|f|*f!="hand" || i==seat as usize).collect();
        keys(p,&fields,true)?;
    }
    keys(&obs["leader"],&["owner","level"],false)?;
    let p = &obs["pending"];
    if !p.is_null() {
        keys(p,&["source","task","last_planet","waiting"],false)?;
        if p.get("task").is_some() {
            if obs["pending_pid"]!=obs["seat"] { return Err("Opposing private task".into()); }
            keys(&p["task"],TASK,false)?;
        }
    }
    Ok(())
}
fn walk(group:&str,path:Vec<Value>,v:&Value,out:&mut Vec<Value>) {
    let (kind,value) = match v {
        Value::Object(o)=>("object",json!(o.len())), Value::Array(a)=>("sequence",json!(a.len())),
        Value::Null=>("missing",Value::Null),Value::Bool(_)=>("boolean",v.clone()),
        Value::Number(_)=>("number",v.clone()),Value::String(_)=>("category",v.clone())
    };
    out.push(json!({"group":group,"path":path,"kind":kind,"value":value}));
    match v {
        Value::Object(o)=>for (key,value) in o { let mut p=path.clone();p.push(json!(key));walk(group,p,value,out); },
        Value::Array(a)=>for (i,value) in a.iter().enumerate() { let mut p=path.clone();p.push(json!(i));walk(group,p,value,out); },
        _=>{}
    }
}
fn attributes(group:&str,path:Vec<Value>,cards:&Value,out:&mut Vec<Value>) -> Result<(),String> {
    for (i,id) in cards.as_array().ok_or("Expected cards")?.iter().enumerate() {
        let id = id.as_u64().filter(|i|*i<=u16::MAX as u64).ok_or("Invalid card ID")? as u16;
        let c=crate::rules().cards.get(&id).ok_or("Unknown card")?;
        let mut p=path.clone();p.extend([json!(i),json!("attributes")]);
        walk(group,p,&json!({"id":c.id,"cost":c.cost,"planet":c.planet,"faction":c.faction}),out);
    }
    Ok(())
}
pub fn encode(obs:&Value,history:Option<&Value>) -> Result<Value,String> {
    validate(obs)?;
    let mut out=Vec::new();
    for (group,fields) in GROUPS { for key in *fields { walk(group,vec![json!(key)],&obs[key],&mut out); } }
    for (seat,player) in obs["players"].as_array().unwrap().iter().enumerate() {
        for (group,fields) in PLAYERS { for key in *fields {
            if let Some(value)=player.get(key) {
                let p=vec![json!("players"),json!(seat),json!(key)];
                walk(group,p.clone(),value,&mut out);
                if *key=="hand" { attributes(group,p,value,&mut out)?; }
                else if *key=="columns" { for (i,column) in value.as_array().ok_or("Expected columns")?.iter().enumerate() {
                    let mut p=p.clone();p.push(json!(i));attributes(group,p,column,&mut out)?;
                } }
            }
        } }
    }
    if let Some(history)=history.filter(|h|!h.is_null()) {
        keys(history,&["initial","events"],true)?;
        let mut current=history["initial"].clone();validate(&current)?;
        if current["seat"]!=obs["seat"] { return Err("History seat mismatch".into()); }
        for event in history["events"].as_array().ok_or("Expected history events")? {
            keys(event,&["actor","changes","public_action","own_action"],false)?;
            if event.get("own_action").is_some() && event["actor"]!=obs["seat"] { return Err("Opposing private history".into()); }
            for (k,v) in event["changes"].as_object().ok_or("Expected observation changes")? { current[k]=v.clone(); }
            validate(&current)?;
            if current["seat"]!=obs["seat"] { return Err("History seat mismatch".into()); }
        }
        if current!=*obs { return Err("History does not reconstruct observation".into()); }
        walk("history",vec![json!("history")],history,&mut out);
    }
    Ok(json!(out))
}
