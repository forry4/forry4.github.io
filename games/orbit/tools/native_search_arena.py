"""Run the native development search probe on fresh, paired all-board games."""
import argparse,json,os,subprocess,time
from pathlib import Path
from ..ai.selfplay import ArenaResult,board_configurations,board_key
from ..cards import FACTIONS
from .value_campaign import game_seed


def summarise(results,*,pairs,boards,candidate,opponent,settings):
    """Fold native game rows into the shared paired ArenaResult.

    Rows arrive in job order, so pair ``i`` is ``results[2i]`` (candidate seat 0)
    and ``results[2i+1]`` (candidate seat 1) on one common-random-number deal.
    A ``winner`` of ``None`` is the deck-exhaustion draw, not a candidate loss;
    a censored or errored game invalidates its whole pair.
    """
    wins=losses=draws=censored=0;score_sum=0.0
    pair_scores=[];pair_scores_by_index=[]
    by_board={board_key(c):{"pairs":0,"wins":0,"losses":0,"draws":0,"censored":0,"score":0.0} for c in boards}
    for index in range(pairs):
        key=board_key(boards[index%len(boards)]);pair=0.0;valid=True
        for row in results[2*index:2*index+2]:
            if row["censored"] or row["error"]:
                censored+=1;by_board[key]["censored"]+=1;valid=False;continue
            if row["winner"] is None:outcome=0.5;draws+=1;by_board[key]["draws"]+=1
            elif row["winner"]==row["candidate"]:outcome=1.0;wins+=1;by_board[key]["wins"]+=1
            else:outcome=0.0;losses+=1;by_board[key]["losses"]+=1
            score_sum+=outcome;by_board[key]["score"]+=outcome;pair+=outcome
        by_board[key]["pairs"]+=1
        pair_scores_by_index.append(pair/2.0 if valid else None)
        if valid:pair_scores.append(pair/2.0)
    for stats in by_board.values():
        denominator=2*stats["pairs"]-stats["censored"]
        stats["scored_games"]=denominator
        stats["score"]=stats["score"]/denominator if denominator else 0.5
    return ArenaResult(candidate=candidate,opponent=opponent,games=wins+losses+draws+censored,
                       pairs=pairs,wins=wins,losses=losses,draws=draws,censored=censored,
                       score_sum=score_sum,pair_scores=pair_scores,by_board=by_board,
                       pair_scores_by_index=pair_scores_by_index,
                       settings={**settings,"pairs":pairs,"balanced_boards":pairs%len(boards)==0,
                                 "boards":[dict(c) for c in boards]})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path,help="Checkpoint, or the literal 'heuristic' for the no-network leaf ablation")
    p.add_argument("output",type=Path)
    p.add_argument("--pairs",type=int,default=8);p.add_argument("--budget-ms",type=int,default=250,help="Whole-turn budget")
    p.add_argument("--main-action-ms",type=int,help="Cap on the turn's main action; default is the whole turn")
    p.add_argument("--followup-ms",type=int,help="Cap on each follow-up decision; default is the whole turn")
    p.add_argument("--workers",type=int,default=1,help="Root-parallel worker pool, as the browser serves it")
    p.add_argument("--via-observation",action="store_true",
                   help="Search a world rebuilt from the observation and rank pending chains, as the browser must")
    p.add_argument("--pool",default="development-native-search-v1")
    p.add_argument("--opponent",type=Path,help="Frozen neural opponent; otherwise Hard v2")
    p.add_argument("--simulations",type=int,help="Deterministic control only; overrides time budget")
    # Cargo emits `neural_arena.exe` on Windows and `neural_arena` everywhere else.
    p.add_argument("--binary",type=Path,default=Path(__file__).resolve().parents[3]/"rust-cores/orbit-core/target/release"/("neural_arena.exe" if os.name=="nt" else "neural_arena"))
    args=p.parse_args()
    if args.pairs<8 or args.pairs%8:p.error("pairs must balance all eight boards")
    if not args.pool.startswith("development-"):p.error("Development namespace required")
    if args.simulations is not None and not 1<=args.simulations<=10000:p.error("simulations must be 1..10000")
    # The heuristic leaf runs the identical search with no network, which is the
    # control that separates search strength from the value model.
    heuristic=str(args.checkpoint)=="heuristic"
    # Only a checkpoint needs the optional training environment (torch), so import
    # it only when one is actually being loaded: the heuristic arm HAS no network,
    # and it is the arm that attributes a win to search rather than to the model.
    # Requiring the training environment to measure "no network" gates the control
    # on the thing it controls for. `summarise` above must stay importable too, or
    # it drags torch into test collection, where CI has only the server's
    # requirements -- same reason, one level down.
    if not heuristic or args.opponent:
        from ..ai.attention import load_checkpoint,export_model
    model=None if heuristic else load_checkpoint(args.checkpoint)[0]
    boards=board_configurations();jobs=[]
    for pair in range(args.pairs):
        for seat in (0,1):jobs.append({"seed":game_seed(args.pool,pair),"candidate":seat,
                                     "sides":[boards[pair%8][f] for f in FACTIONS]})
    request={"model":None if heuristic else export_model(model),"jobs":jobs,"budget_ms":args.budget_ms}
    if not 1<=args.workers<=8:p.error("workers must be 1..8")
    if args.workers>1:request["pool"]=args.workers
    if args.via_observation:request["via_observation"]=True
    for key,value in (("main_action_ms",args.main_action_ms),("followup_ms",args.followup_ms)):
        if value is not None:
            if not 1<=value<=args.budget_ms:p.error(f"{key} must be within the whole-turn budget")
            request[key]=value
    if args.opponent:
        other,_,_,_=load_checkpoint(args.opponent)
        request["opponent_model"]=export_model(other)
    if args.simulations is not None:request["simulations"]=args.simulations
    mirror=args.simulations is not None and not heuristic and request.get("opponent_model")==request["model"]
    process=subprocess.Popen([str(args.binary.resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8")
    results=[];started=time.perf_counter()
    try:
        process.stdin.write(json.dumps(request)+"\n")
        process.stdin.close()
        for line in process.stdout:
            result=json.loads(line);results.append(result)
            print(json.dumps({"games":len(results),"wins":sum(r["winner"]==r["candidate"] for r in results),"last_error":result["error"]}),flush=True)
    finally:process.stdout.close();process.wait(timeout=10)
    opponent_name=str(args.opponent) if args.opponent else "hard-v2"
    report={"purpose":"development, not promotion","pool":args.pool,"budget_ms":args.budget_ms,
            "main_action_ms":args.main_action_ms,"followup_ms":args.followup_ms,"workers":args.workers,"via_observation":args.via_observation,
            "fixed_simulations":args.simulations,"checkpoint":str(args.checkpoint),
            "opponent":opponent_name,
            "games":results,"seconds":time.perf_counter()-started,
            "mirror_control":mirror,
            "complete":process.returncode==0 and len(results)==len(jobs) and not any(r["error"] or r["censored"] for r in results)}
    if len(results)==len(jobs):
        report["arena"]=summarise(results,pairs=args.pairs,boards=boards,
                                  candidate=str(args.checkpoint),opponent=opponent_name,
                                  settings={"pool":args.pool,"budget_ms":args.budget_ms,
                                            "fixed_simulations":args.simulations,
                                            "turn_budget":args.budget_ms/1000.0}).as_dict()
    if mirror:
        report["mirror_passed"]=report["complete"] and all(
            all(results[i][key]==results[i+1][key] for key in ("seed","winner","simulations","decisions"))
            for i in range(0,len(results),2)) and sum(r["winner"]==r["candidate"] for r in results)*2==len(results)
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["complete"]:raise RuntimeError("Native arena incomplete; inspect report")
    if mirror and not report["mirror_passed"]:raise RuntimeError("Deterministic mirror control failed")
    arena=report.get("arena",{})
    print(json.dumps({"score":arena.get("score"),"pair_score":arena.get("pair_score"),
                      "pair_ci95":arena.get("pair_ci95"),"seconds":report["seconds"]}))


if __name__=="__main__":main()
