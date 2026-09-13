"""Run the native development search probe on fresh, paired all-board games."""
import argparse,json,os,subprocess,time
from pathlib import Path
from ..ai.selfplay import ArenaResult,board_configurations,board_key
from ..cards import FACTIONS
from .value_campaign import game_seed


def summarise(results,*,pairs,boards,candidate,opponent,settings):
    """Fold native game rows into the shared paired ArenaResult.

    Rows are normalized to job order before this function, so pair ``i`` is
    ``results[2i]`` (candidate seat 0) and ``results[2i+1]`` (candidate seat 1)
    on one common-random-number deal.
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


def mirror_control(*,simulations,opponent_simulations,heuristic,models_match,
                   leaf,opponent_leaf,determinization_period,opponent_determinization_period):
    """Are both seats provably the SAME player?

    A mirror is held to reading exactly 0.5000, so claiming one when the seats
    differ turns a sanity check into a false assertion. Every per-seat control
    is compared: before asymmetric simulations existed this could be read off
    the models alone, but a differing count, leaf or determinization regime is
    just as much a different player. Fixed simulations are required because an
    equal-time arena is load-dependent and cannot reproduce itself exactly.
    """

    if simulations is None or heuristic or not models_match:
        return False
    effective=opponent_simulations if opponent_simulations is not None else simulations
    return (effective==simulations and opponent_leaf==leaf
            and opponent_determinization_period==determinization_period)


def main():
    # Checkpoint loading needs the optional training environment (torch); the
    # row folding above must not, or importing this module for `summarise`
    # drags torch into test collection, where CI has only the server's
    # requirements. Keep this import inside main().
    from ..ai.attention import load_checkpoint,export_model
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path,help="Checkpoint, or the literal 'heuristic' for the no-network leaf ablation")
    p.add_argument("output",type=Path)
    p.add_argument("--pairs",type=int,default=8);p.add_argument("--budget-ms",type=int,default=250,help="Whole-turn budget")
    p.add_argument("--main-action-ms",type=int,help="Cap on the turn's main action; default is the whole turn")
    p.add_argument("--followup-ms",type=int,help="Cap on each follow-up decision; default is the whole turn")
    default_workers=max(1,min((os.cpu_count() or 1)-1,16))
    p.add_argument("--workers",type=int,default=default_workers,
                   help="Native root-parallel workers; offline arenas may use up to sixteen")
    p.add_argument("--game-workers",type=int,default=1,
                   help="Concurrent independent games; keep workers*game-workers within sixteen")
    p.add_argument("--via-observation",action="store_true",
                   help="Search a world rebuilt from the observation and rank pending chains, as the browser must")
    p.add_argument("--pool",default="development-native-search-v1")
    p.add_argument("--opponent",type=Path,help="Frozen neural opponent; otherwise Hard v2")
    p.add_argument("--opponent-expert",action="store_true",help="Use the current heuristic-leaf Expert search as the opponent")
    p.add_argument("--simulations",type=int,help="Deterministic control only; overrides time budget")
    # Equal-time is the ship criterion; a fixed-simulation screen that gives both
    # seats the same count measures equal-SIMS, a question this campaign already
    # answered. Calibrate each seat to what it actually achieves at serving shape
    # (see tools/calibrate_fixed_sims.py) to keep the equal-time meaning while
    # making the arena deterministic and load-independent.
    p.add_argument("--opponent-simulations",type=int,
                   help="Opponent seat's fixed count; defaults to --simulations")
    p.add_argument("--model-stride",type=int,default=1,
                   help="Evaluate a neural leaf every Nth simulation; intervening leaves use the heuristic")
    p.add_argument("--model-weight",type=float,default=1.0,
                   help="Blend weight for the neural value on evaluated leaves (0..1)")
    p.add_argument("--model-temperature",type=float,default=2.0,
                   help="Positive logit temperature for neural leaf values")
    # The 2026-09-11 leaf port is the default on both sides; the control arm is
    # the capture-only leaf the Rust search shipped before it.
    leaves=("state-value","capture-progress-only","state-value-v2","state-value-v3")
    p.add_argument("--leaf",choices=leaves,default="state-value",
                   help="Candidate seat's nonterminal leaf evaluator")
    p.add_argument("--opponent-leaf",choices=leaves,default="state-value",
                   help="Opponent seat's nonterminal leaf evaluator")
    # Simulations sharing one determinization: 1 is the historical per-simulation
    # resampling, 0 is one coherent world per call (PIMC), N is N-sim groups.
    # The learned PUCT prior. Zero is the frozen hand-written action_score the
    # campaign has always used, and is what every number before 2026-09-12 was
    # measured with. A model that carries a policy head and is given zero weight
    # is refused by the search rather than silently searched with the old prior.
    p.add_argument("--policy-prior-weight",type=float,default=0.0,
                   help="Candidate seat: share of the PUCT prior taken from the policy head")
    p.add_argument("--opponent-policy-prior-weight",type=float,default=0.0,
                   help="Opponent seat: same, defaults to the hand-written prior")
    # Named --opponent-search, NOT --opponent-model: `opponent_model` is already
    # the request key carrying the opponent's model ARTIFACT, and colliding with
    # it made the arena try to load the string "ranker" as a neural net.
    # How the opponent's decisions are answered INSIDE the tree. "ranker" is the
    # historical search: nodes for the searching seat only, every opponent
    # decision answered by an external 1-ply heuristic call that costs 43% of
    # search time. "minimax" gives the opponent its own nodes. Per request, not
    # per seat: one side searching its opponent and the other not is two
    # different algorithms.
    p.add_argument("--minimax",action="store_true",
                   help="Candidate seat: give the opponent its own nodes instead of "
                        "answering its decisions with the 1-ply ranker")
    p.add_argument("--opponent-minimax",action="store_true",
                   help="Opponent seat: the same. PER SEAT on purpose -- the comparison "
                        "worth running needs exactly one side to search its opponent")
    # DEPTH instead of width. Per seat, for the same reason minimax is: the
    # comparison worth running is one side depth-first against one side MCTS.
    # A root ensemble is refused by the arena when either seat is alpha-beta --
    # it is one deterministic tree, so four workers of it is four workers of
    # nothing, and allowing it would quietly measure one thread against four.
    # PER REQUEST on purpose. The MCTS ALWAYS resamples hidden information from
    # the seat's observation, so handing it the true state changes nothing --
    # which means comparing a perfect-information alpha-beta against a normal
    # MCTS measures the hidden-information cheat (0.6094 on its own) and reads
    # as a depth result. This flag turns resampling off for BOTH seats so the
    # only remaining difference is the search architecture.
    p.add_argument("--perfect-information",action="store_true",
                   help="Both seats search the TRUE world with no resampling. "
                        "Contradicts --via-observation and is refused with it")
    p.add_argument("--alphabeta",action="store_true",
                   help="Candidate seat: iterative-deepening alpha-beta instead of MCTS")
    p.add_argument("--opponent-alphabeta",action="store_true",
                   help="Opponent seat: the same")
    p.add_argument("--ab-no-table",action="store_true",
                   help="Alpha-beta: disable the transposition table. Orbit barely "
                        "transposes (1.4%% hit rate at depth 4), so whether the table "
                        "pays is a measurement, not a default")
    p.add_argument("--ab-worlds",type=int,default=1,
                   help="Alpha-beta PIMC: vote over this many sampled worlds, each "
                        "at budget/K. K=1 measured 0.5625 against the Expert while "
                        "the same search at perfect information measured 0.9609 -- "
                        "the gap is strategy fusion and this is the lever")
    p.add_argument("--ab-quiescence",action="store_true",
                   help="Candidate seat: do not stop the search inside a half-finished "
                        "turn. 39.6%% of Orbit decision points are inside a pending "
                        "chain, so the leaf otherwise scores a transient position")
    p.add_argument("--ranker-v1",action="store_true",
                   help="Candidate seat: the PRE-2026-09-13 ranker, as a control arm. "
                        "That policy scored a planet by the seat's OWN progress, so a "
                        "contested one was a PENALTY, and paid a flat bonus for any "
                        "capture. Paired over 300 games it blocked a game-ending "
                        "capture in 0 of 97 positions where blocking was legal")
    p.add_argument("--opponent-ranker-v1",action="store_true",
                   help="Opponent seat: the same control arm. PER SEAT because the "
                        "arena drives both from one process for common random numbers")
    p.add_argument("--search-pending",action="store_true",
                   help="Candidate seat: SEARCH effect-resolution sub-decisions instead "
                        "of handing them to the 1-ply ranker. An observation redacts the "
                        "effect queue to its first task, so a rebuilt world could not "
                        "carry a pending chain -- and 45.0%% of all decisions with a real "
                        "choice are inside one (10,537 of 23,394 over 300 games)")
    p.add_argument("--opponent-search-pending",action="store_true",
                   help="Opponent seat: the same. PER SEAT, in one binary, because the "
                        "arena drives both seats from one process for common random numbers")
    p.add_argument("--ab-max-depth",type=int,default=64,
                   help="Alpha-beta: iterative-deepening cap in decisions")
    p.add_argument("--determinization-period",type=int,default=1,
                   help="Candidate seat: simulations per determinization; 0 = coherent")
    p.add_argument("--opponent-determinization-period",type=int,default=1,
                   help="Opponent seat: simulations per determinization; 0 = coherent")
    repo_root=Path(__file__).resolve().parents[3]
    portable_binary=repo_root/"rust-cores/orbit-core/target/release/neural_arena.exe"
    native_binary=repo_root/"games/orbit/ai/runs/target-native/release/neural_arena.exe"
    p.add_argument("--binary",type=Path,default=native_binary if native_binary.is_file() else portable_binary)
    args=p.parse_args()
    if args.pairs<8 or args.pairs%8:p.error("pairs must balance all eight boards")
    if not args.pool.startswith("development-"):p.error("Development namespace required")
    if args.simulations is not None and not 1<=args.simulations<=10000:p.error("simulations must be 1..10000")
    if args.opponent_simulations is not None:
        if not 1<=args.opponent_simulations<=10000:p.error("opponent-simulations must be 1..10000")
        if args.simulations is None:p.error("--opponent-simulations requires --simulations")
    if args.model_stride<1:p.error("model-stride must be positive")
    if not 0.0<=args.model_weight<=1.0:p.error("model-weight must be between 0 and 1")
    if args.model_temperature<=0:p.error("model-temperature must be positive")
    for name in ("determinization_period","opponent_determinization_period"):
        if getattr(args,name)<0:p.error(f"--{name.replace('_','-')} must be zero or positive")
    for name in ("policy_prior_weight","opponent_policy_prior_weight"):
        if not 0.0<=getattr(args,name)<=1.0:p.error(f"--{name.replace('_','-')} must be between 0 and 1")
    # The heuristic leaf runs the identical search with no network, which is the
    # control that separates search strength from the value model.
    if args.perfect_information and args.via_observation:
        p.error("--perfect-information and --via-observation are contradictory")
    if args.ab_worlds<1: p.error("--ab-worlds must be positive")
    if (args.search_pending or args.opponent_search_pending) and not args.via_observation:
        p.error("--search-pending needs --via-observation: a pending chain is only "
                "reconstructed when the world is rebuilt from an observation at all")
    if args.ab_worlds>1 and not args.via_observation:
        p.error("--ab-worlds needs --via-observation: nothing is hidden to sample otherwise")
    if args.alphabeta and args.workers>1 and args.ab_worlds<=1:
        p.error("a single-world alpha-beta cannot use a root ensemble: raise --ab-worlds "
                "or run --workers 1")
    heuristic=str(args.checkpoint)=="heuristic"
    model=None if heuristic else load_checkpoint(args.checkpoint)[0]
    boards=board_configurations();jobs=[]
    for pair in range(args.pairs):
        for seat in (0,1):jobs.append({"seed":game_seed(args.pool,pair),"candidate":seat,
                                     "sides":[boards[pair%8][f] for f in FACTIONS]})
    request={"model":None if heuristic else export_model(model),"jobs":jobs,"budget_ms":args.budget_ms}
    if not 1<=args.workers<=16:p.error("workers must be 1..16")
    if not 1<=args.game_workers<=16 or args.workers*args.game_workers>16:
        p.error("game-workers must be 1..16 and workers*game-workers must be <=16")
    if args.workers>1:request["pool"]=args.workers
    if args.game_workers>1:request["game_workers"]=args.game_workers
    if args.via_observation:request["via_observation"]=True
    for key,value in (("main_action_ms",args.main_action_ms),("followup_ms",args.followup_ms)):
        if value is not None:
            if not 1<=value<=args.budget_ms:p.error(f"{key} must be within the whole-turn budget")
            request[key]=value
    if args.opponent:
        if args.opponent_expert:p.error("choose one of --opponent and --opponent-expert")
        other,_,_,_=load_checkpoint(args.opponent)
        request["opponent_model"]=export_model(other)
    if args.opponent_expert:request["opponent_expert"]=True
    if args.simulations is not None:request["simulations"]=args.simulations
    if args.opponent_simulations is not None:request["opponent_simulations"]=args.opponent_simulations
    request["leaf"]=args.leaf
    request["opponent_leaf"]=args.opponent_leaf
    request["minimax"]=args.minimax
    request["opponent_minimax"]=args.opponent_minimax
    request["perfect_information"]=args.perfect_information
    request["alphabeta"]=args.alphabeta
    request["opponent_alphabeta"]=args.opponent_alphabeta
    request["ab_table"]=not args.ab_no_table
    request["ab_max_depth"]=args.ab_max_depth
    request["ab_worlds"]=args.ab_worlds
    request["ab_quiescence"]=args.ab_quiescence
    request["search_pending"]=args.search_pending
    request["opponent_search_pending"]=args.opponent_search_pending
    request["ranker_v1"]=args.ranker_v1
    request["opponent_ranker_v1"]=args.opponent_ranker_v1
    request["policy_prior_weight"]=args.policy_prior_weight
    request["opponent_policy_prior_weight"]=args.opponent_policy_prior_weight
    request["determinization_period"]=args.determinization_period
    request["opponent_determinization_period"]=args.opponent_determinization_period
    request["model_stride"]=args.model_stride
    request["model_weight"]=args.model_weight
    request["model_temperature"]=args.model_temperature
    effective_opponent_simulations=(args.opponent_simulations
                                    if args.opponent_simulations is not None else args.simulations)
    mirror=mirror_control(simulations=args.simulations,
                          opponent_simulations=args.opponent_simulations,
                          heuristic=heuristic,
                          models_match=request.get("opponent_model")==request["model"],
                          leaf=args.leaf,opponent_leaf=args.opponent_leaf,
                          determinization_period=args.determinization_period,
                          opponent_determinization_period=args.opponent_determinization_period)
    process=subprocess.Popen([str(args.binary.resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8")
    results=[];started=time.perf_counter()
    try:
        process.stdin.write(json.dumps(request)+"\n")
        process.stdin.close()
        for line in process.stdout:
            result=json.loads(line);results.append(result)
            print(json.dumps({"games":len(results),"wins":sum(r["winner"]==r["candidate"] for r in results),"last_error":result["error"]}),flush=True)
    finally:process.stdout.close();process.wait(timeout=10)
    # The current native arena emits ordered rows even when game workers are
    # concurrent.  Sort defensively as well so a future streaming emitter can
    # return jobs as they finish without silently breaking CRN pair folding.
    if all(isinstance(row.get("index"), int) for row in results):
        results.sort(key=lambda row: row["index"])
    opponent_name=str(args.opponent) if args.opponent else ("expert" if args.opponent_expert else "hard-v2")
    report={"purpose":"development, not promotion","pool":args.pool,"budget_ms":args.budget_ms,
            "main_action_ms":args.main_action_ms,"followup_ms":args.followup_ms,"workers":args.workers,
            "game_workers":args.game_workers,"via_observation":args.via_observation,
            "fixed_simulations":args.simulations,
            "fixed_opponent_simulations":effective_opponent_simulations,
            "checkpoint":str(args.checkpoint),
            "opponent":opponent_name,
            "model_stride":args.model_stride,"model_weight":args.model_weight,
            "model_temperature":args.model_temperature,
            "leaf":args.leaf,"opponent_leaf":args.opponent_leaf,
            "determinization_period":args.determinization_period,
            "opponent_determinization_period":args.opponent_determinization_period,
            "policy_prior_weight":args.policy_prior_weight,
            "opponent_policy_prior_weight":args.opponent_policy_prior_weight,
            "minimax":args.minimax,"opponent_minimax":args.opponent_minimax,
            "perfect_information":args.perfect_information,
            "alphabeta":args.alphabeta,"opponent_alphabeta":args.opponent_alphabeta,
            "ab_table":not args.ab_no_table,"ab_max_depth":args.ab_max_depth,
            "ab_worlds":args.ab_worlds,"ab_quiescence":args.ab_quiescence,
            "ranker_v1":args.ranker_v1,"opponent_ranker_v1":args.opponent_ranker_v1,
            "search_pending":args.search_pending,
            "opponent_search_pending":args.opponent_search_pending,
            "games":results,"seconds":time.perf_counter()-started,
            "mirror_control":mirror,
            "complete":process.returncode==0 and len(results)==len(jobs) and not any(r["error"] or r["censored"] for r in results)}
    if len(results)==len(jobs):
        report["arena"]=summarise(results,pairs=args.pairs,boards=boards,
                                  candidate=str(args.checkpoint),opponent=opponent_name,
                                  settings={"pool":args.pool,"budget_ms":args.budget_ms,
                                            "fixed_simulations":args.simulations,
                                            "fixed_opponent_simulations":effective_opponent_simulations,
                                            "turn_budget":args.budget_ms/1000.0,
                                            "workers":args.workers,
                                            "leaf":args.leaf,
                                            "opponent_leaf":args.opponent_leaf,
                                            "determinization_period":args.determinization_period,
                                            "opponent_determinization_period":args.opponent_determinization_period,
                                            "game_workers":args.game_workers}).as_dict()
    if mirror:
        report["mirror_passed"]=report["complete"] and all(
            all(results[i][key]==results[i+1][key] for key in ("seed","winner","simulations","decisions"))
            for i in range(0,len(results),2)) and sum(r["winner"]==r["candidate"] for r in results)*2==len(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["complete"]:raise RuntimeError("Native arena incomplete; inspect report")
    if mirror and not report["mirror_passed"]:raise RuntimeError("Deterministic mirror control failed")
    arena=report.get("arena",{})
    print(json.dumps({"score":arena.get("score"),"pair_score":arena.get("pair_score"),
                      "pair_ci95":arena.get("pair_ci95"),"seconds":report["seconds"]}))


if __name__=="__main__":main()
