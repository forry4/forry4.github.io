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
    p.add_argument("--namespace",required=True,
                   help="Namespaced pool beginning with train- or development-. Search pools contain '-search-'.")
    p.add_argument("--checkpoint",type=Path,action="append",default=[],help="Newest first; optional frozen league checkpoints")
    p.add_argument("--primary",help="Primary policy name (expert or neural-N); defaults to neural-0 with checkpoints")
    p.add_argument("--opponents",default="expert,hard-v2,exploratory-v2,random",help="Comma-separated opponent families (racer, developer and denier are targeted specialists)")
    p.add_argument("--simulations",type=int,default=64)
    p.add_argument("--model-stride",type=int,default=1)
    p.add_argument("--model-weight",type=float,default=1.0)
    p.add_argument("--model-temperature",type=float,default=2.0)
    p.add_argument("--threads",type=int,default=max(1,min((os.cpu_count() or 1)-1,16)))
    repo_root=Path(__file__).resolve().parents[3]
    portable_binary=repo_root/"rust-cores/orbit-core/target/release/value_generate.exe"
    native_binary=repo_root/".orbit-target-native/release/value_generate.exe"
    p.add_argument("--binary",type=Path,default=native_binary if native_binary.is_file() else portable_binary)
    args=p.parse_args()
    if not (args.namespace.startswith("train-") or args.namespace.startswith("development-")):
        p.error("namespace must begin with train- or development-")
    search_pool="-search-" in args.namespace
    families=[name.strip() for name in args.opponents.split(",") if name.strip()]
    allowed={"hard-v2","exploratory-v2","random","expert","racer","racer-soft","developer","denier"}|{f"neural-{i}" for i in range(len(args.checkpoint))}
    if not families or any(name not in allowed for name in families):
        p.error(f"opponents must be named from {sorted(allowed)}")
    block=16*len(families)
    if args.games<block or args.games%block or not 1<=args.threads<=16:
        p.error(f"games must be a multiple of {block}; threads 1..16")
    if args.checkpoint and not search_pool:
        p.error("Baseline pools cannot use checkpoints; put neural data in a -search- namespace")
    primary=args.primary or ("neural-0" if args.checkpoint else "expert")
    if primary.startswith("neural-"):
        try:
            primary_index=int(primary.split("-",1)[1])
        except (ValueError, IndexError):
            p.error("--primary neural policy must be named neural-N")
        if primary_index<0 or primary_index>=len(args.checkpoint):
            p.error("--primary neural index has no matching --checkpoint")
    elif primary not in {"expert","hard-v2","exploratory-v2","random","racer","racer-soft","developer","denier"}:
        p.error("--primary must be expert, hard-v2, exploratory-v2, random, racer, developer, denier, or neural-N")
    if not 1<=args.simulations<=10000:p.error("simulations must be 1..10000")
    if args.model_stride<1:p.error("model-stride must be positive")
    if not 0.0<=args.model_weight<=1.0:p.error("model-weight must be between 0 and 1")
    if args.model_temperature<=0:p.error("model-temperature must be positive")
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
    # A native worker can be interrupted after it has flushed some shards.
    # Keep those verified files and submit only the missing jobs on the next
    # invocation; this is important because a generation is deliberately long
    # and the campaign runner promises resumability.
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Dataset manifest already exists: {manifest_path}")
    args.output.mkdir(parents=True,exist_ok=True)
    boards=board_configurations();jobs=[]
    for index in range(args.games):
        pair=index//2;board=boards[pair%8]
        names=[primary,families[(index//16)%len(families)]]
        if index%2:names.reverse()
        jobs.append({"seed":game_seed(args.namespace,pair),"pair":pair,"assignment":index%2,
                     "board":board,"sides":[board[f] for f in FACTIONS],"policies":names})
    existing_games={}
    for shard in args.output.glob("game-*.json"):
        try:
            index=int(shard.stem.removeprefix("game-"))
        except ValueError:
            continue
        if not 0<=index<args.games:
            raise ValueError(f"Existing shard is outside this dataset: {shard.name}")
        try:
            raw=shard.read_text(encoding="utf-8")
            record=json.loads(raw)
        except (OSError,json.JSONDecodeError):
            # A process killed during write leaves this index pending; the
            # next worker response replaces the incomplete file atomically at
            # the logical dataset level.
            continue
        expected=jobs[index]
        # The native record intentionally omits the derived ``sides`` array;
        # the board configuration is the durable identity for this job.
        if any(record.get(key)!=expected[key] for key in ("seed","pair","assignment","board","policies")):
            raise ValueError(f"Existing shard does not match the requested job: {shard.name}")
        existing_games[index]={"file":shard.name,"sha256":hashlib.sha256(raw.encode()).hexdigest(),
                              "seed":record["seed"],"censored":bool(record.get("censored",False))}
    pending_indices=[index for index in range(args.games) if index not in existing_games]
    pending_jobs=[jobs[index] for index in pending_indices]
    manifest={"version":1,"rules":rules_fingerprint(),"schema":SCHEMA_VERSION,
              "namespace":args.namespace,"backend":"rust","rng":"orbit-chance-v1",
              "history":"omitted-ablation","views":"both-seats-per-decision","primary":primary,
              "opponents":families,"games":list(existing_games.values()),
              "resumed_games":len(existing_games)}
    if search_pool:
        manifest.update({"simulations":args.simulations,"model_stride":args.model_stride,"model_weight":args.model_weight,
                         "model_temperature":args.model_temperature,
                         "belief":"current-observation prior","search_opponent":"mixed",
                         "search_opponents":families,
                         "purpose":"bounded observation-only search teacher; improvement operator unproven",
                         "root_value":"recorded on searched actor rows; optional target blend"})
    if models:
        manifest["teachers"] = teachers
    started=time.perf_counter()
    if pending_jobs:
        process=subprocess.Popen([str(args.binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8")
        seen=set()
        try:
            process.stdin.write(json.dumps({"jobs":pending_jobs,"threads":args.threads,"models":models,
                                            "simulations":args.simulations,"model_stride":args.model_stride,
                                            "model_weight":args.model_weight,"model_temperature":args.model_temperature})+"\n");process.stdin.close()
            for line in process.stdout:
                result=json.loads(line)
                if "error" in result:raise RuntimeError(result["error"])
                ordinal=result["index"]
                if not isinstance(ordinal,int) or not 0<=ordinal<len(pending_indices) or ordinal in seen:
                    raise RuntimeError(f"Native worker returned an invalid job index: {ordinal!r}")
                seen.add(ordinal)
                record=result["game"];index=pending_indices[ordinal]
                raw=json.dumps(record,separators=(",",":"));name=f"game-{index:05d}.json"
                (args.output/name).write_text(raw,encoding="utf-8")
                manifest["games"].append({"file":name,"sha256":hashlib.sha256(raw.encode()).hexdigest(),
                                          "seed":record["seed"],"censored":record["censored"]})
                if len(manifest["games"])%192==0:print(json.dumps({"generated":len(manifest["games"]),"seconds":time.perf_counter()-started}),flush=True)
        finally:
            process.stdout.close();process.wait(timeout=10)
    else:
        process=None
    if (process is not None and process.returncode) or len(manifest["games"])!=args.games:raise RuntimeError("Incomplete native generation")
    manifest["games"].sort(key=lambda x:x["file"])
    manifest["seconds"]=time.perf_counter()-started
    temporary_manifest=manifest_path.with_name("manifest.json.tmp")
    temporary_manifest.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    print(json.dumps({"games":args.games,"seconds":manifest["seconds"],"censored":sum(g["censored"] for g in manifest["games"])}))


if __name__=="__main__":main()
