"""Run the native development search probe on fresh, paired all-board games."""
import argparse,json,subprocess,time
from pathlib import Path
from ..ai.attention import load_checkpoint,export_model
from ..ai.selfplay import board_configurations
from ..cards import FACTIONS
from .value_campaign import game_seed


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--pairs",type=int,default=8);p.add_argument("--budget-ms",type=int,default=250)
    p.add_argument("--pool",default="development-native-search-v1")
    p.add_argument("--opponent",type=Path,help="Frozen neural opponent; otherwise Hard v2")
    p.add_argument("--simulations",type=int,help="Deterministic control only; overrides time budget")
    p.add_argument("--binary",type=Path,default=Path(__file__).resolve().parents[3]/"rust-cores/orbit-core/target/release/neural_arena.exe")
    args=p.parse_args()
    if args.pairs<8 or args.pairs%8:p.error("pairs must balance all eight boards")
    if not args.pool.startswith("development-"):p.error("Development namespace required")
    if args.simulations is not None and not 1<=args.simulations<=10000:p.error("simulations must be 1..10000")
    model,_,_,_=load_checkpoint(args.checkpoint)
    boards=board_configurations();jobs=[]
    for pair in range(args.pairs):
        for seat in (0,1):jobs.append({"seed":game_seed(args.pool,pair),"candidate":seat,
                                     "sides":[boards[pair%8][f] for f in FACTIONS]})
    request={"model":export_model(model),"jobs":jobs,"budget_ms":args.budget_ms}
    if args.opponent:
        other,_,_,_=load_checkpoint(args.opponent)
        request["opponent_model"]=export_model(other)
    if args.simulations is not None:request["simulations"]=args.simulations
    mirror=args.simulations is not None and request.get("opponent_model")==request["model"]
    process=subprocess.Popen([str(args.binary.resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8")
    results=[];started=time.perf_counter()
    try:
        process.stdin.write(json.dumps(request)+"\n")
        process.stdin.close()
        for line in process.stdout:
            result=json.loads(line);results.append(result)
            print(json.dumps({"games":len(results),"wins":sum(r["winner"]==r["candidate"] for r in results),"last_error":result["error"]}),flush=True)
    finally:process.stdout.close();process.wait(timeout=10)
    report={"purpose":"development, not promotion","pool":args.pool,"budget_ms":args.budget_ms,
            "fixed_simulations":args.simulations,"checkpoint":str(args.checkpoint),
            "opponent":str(args.opponent) if args.opponent else "hard-v2",
            "games":results,"seconds":time.perf_counter()-started,
            "mirror_control":mirror,
            "complete":process.returncode==0 and len(results)==len(jobs) and not any(r["error"] or r["censored"] for r in results)}
    if mirror:
        report["mirror_passed"]=report["complete"] and all(
            all(results[i][key]==results[i+1][key] for key in ("seed","winner","simulations","decisions"))
            for i in range(0,len(results),2)) and sum(r["winner"]==r["candidate"] for r in results)*2==len(results)
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["complete"]:raise RuntimeError("Native arena incomplete; inspect report")
    if mirror and not report["mirror_passed"]:raise RuntimeError("Deterministic mirror control failed")
    print(json.dumps({"score":sum(r["winner"]==r["candidate"] for r in results)/len(results),"seconds":report["seconds"]}))


if __name__=="__main__":main()
