"""Fast native baseline generation with checksummed, observation-only shards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from ..ai.selfplay import board_configurations
from ..ai.state import SCHEMA_VERSION,rules_fingerprint
from ..cards import FACTIONS
from .value_campaign import game_seed


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path);p.add_argument("--games",type=int,default=1536)
    p.add_argument("--namespace",choices=("train-native-v1","development-native-v1","train-native-v2","development-native-v2",
                                         "train-search-v1","development-search-v1"),required=True)
    p.add_argument("--checkpoint",type=Path,action="append",default=[],help="Newest first; optional frozen league checkpoints")
    p.add_argument("--simulations",type=int,default=64)
    p.add_argument("--threads",type=int,default=max(1,min((os.cpu_count() or 1)-2,8)))
    p.add_argument("--binary",type=Path,default=Path(__file__).resolve().parents[3]/"rust-cores/orbit-core/target/release/value_generate.exe")
    args=p.parse_args()
    families=["hard-v2","exploratory-v2","random"]+[f"neural-{i}" for i in range(len(args.checkpoint))]
    block=16*len(families)
    if args.games<block or args.games%block or not 1<=args.threads<=8:
        p.error(f"games must be a multiple of {block}; threads 1..8")
    if bool(args.checkpoint)!=("-search-" in args.namespace):
        p.error("Search pools require checkpoints; baseline pools cannot use them")
    if not 1<=args.simulations<=10000:p.error("simulations must be 1..10000")
    models=[];teachers=[]
    if args.checkpoint:
        import torch
        from ..ai.attention import load_checkpoint,export_model
        torch.set_num_threads(1)
        for path in args.checkpoint:
            model,_,_,_=load_checkpoint(path)
            artifact=export_model(model);models.append(artifact)
            teachers.append({"sha256":hashlib.sha256(json.dumps(artifact,sort_keys=True).encode()).hexdigest(),
                             "checkpoint":str(path)})
    args.output.mkdir(parents=True,exist_ok=False)
    boards=board_configurations();jobs=[]
    for index in range(args.games):
        pair=index//2;board=boards[pair%8]
        names=["neural-0" if models else "hard-v2",families[(index//16)%len(families)]]
        if index%2:names.reverse()
        jobs.append({"seed":game_seed(args.namespace,pair),"pair":pair,"assignment":index%2,
                     "board":board,"sides":[board[f] for f in FACTIONS],"policies":names})
    manifest={"version":1,"rules":rules_fingerprint(),"schema":SCHEMA_VERSION,
              "namespace":args.namespace,"backend":"rust","rng":"orbit-chance-v1",
              "history":"omitted-ablation","views":"both-seats-per-decision","games":[]}
    if models:
        manifest.update({"teachers":teachers,"simulations":args.simulations,
                         "belief":"current-observation prior","search_opponent":"hard-v2",
                         "purpose":"bounded teacher experiment; improvement operator unproven"})
    started=time.perf_counter()
    process=subprocess.Popen([str(args.binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8")
    try:
        process.stdin.write(json.dumps({"jobs":jobs,"threads":args.threads,"models":models,
                                        "simulations":args.simulations})+"\n");process.stdin.close()
        for line in process.stdout:
            result=json.loads(line)
            if "error" in result:raise RuntimeError(result["error"])
            record=result["game"];index=result["index"]
            raw=json.dumps(record,separators=(",",":"));name=f"game-{index:05d}.json"
            (args.output/name).write_text(raw,encoding="utf-8")
            manifest["games"].append({"file":name,"sha256":hashlib.sha256(raw.encode()).hexdigest(),
                                      "seed":record["seed"],"censored":record["censored"]})
            if len(manifest["games"])%192==0:print(json.dumps({"generated":len(manifest["games"]),"seconds":time.perf_counter()-started}),flush=True)
    finally:
        process.stdout.close();process.wait(timeout=10)
    if process.returncode or len(manifest["games"])!=args.games:raise RuntimeError("Incomplete native generation")
    manifest["games"].sort(key=lambda x:x["file"])
    manifest["seconds"]=time.perf_counter()-started
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"games":args.games,"seconds":manifest["seconds"],"censored":sum(g["censored"] for g in manifest["games"])}))


if __name__=="__main__":main()
