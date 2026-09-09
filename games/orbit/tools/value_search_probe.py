"""Development-only native-value search integration probe; not a promotion gate."""
import argparse
import json
from pathlib import Path
import time

from ..ai.attention import load_checkpoint,export_model
from ..ai.native_value import NativeValueGuide
from ..ai.search import InformationSetSearch,SearchConfig,SearchPolicy
from ..ai.selfplay import run_arena
from ..ai.serving import choose_move


class HardV2:
    name="hard-v2"
    def choose(self,game,pid,rng,*,observation=None,**kwargs):
        return choose_move(observation,observation["legal_moves"],None,5000,0).move


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--pairs",type=int,default=8);p.add_argument("--budget",type=float,default=0.2)
    p.add_argument("--depth",type=int,default=8);p.add_argument("--seed",type=int,default=95100)
    p.add_argument("--opponent",choices=("hard-v2","heuristic-search"),default="heuristic-search")
    args=p.parse_args()
    import torch
    torch.set_num_threads(1)
    model,_,_,_=load_checkpoint(args.checkpoint)
    config=SearchConfig(simulations=100000,time_limit=args.budget,max_depth=args.depth)
    opponent=HardV2() if args.opponent=="hard-v2" else SearchPolicy(InformationSetSearch(config),name="heuristic-search")
    started=time.perf_counter()
    with NativeValueGuide(export_model(model)) as guide:
        candidate=SearchPolicy(InformationSetSearch(config,guide=guide),name="native-value-search")
        result=run_arena(candidate,opponent,pairs=args.pairs,seed=args.seed,turn_budget=args.budget)
        report=result.as_dict()
        report.update({"purpose":"development integration probe, not promotion", "depth":args.depth,
                       "leaf_calls":guide.calls,"leaf_cache_hits":guide.cache_hits,
                       "wall_seconds":time.perf_counter()-started})
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
