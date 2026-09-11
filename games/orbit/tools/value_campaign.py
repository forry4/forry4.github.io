"""Offline observation-only value baseline: generate, train, inspect holdout.

Game shards stream from disk. No hidden state or display log is written.
Development predictions are diagnostics, not promotion or playing strength.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import time

from .. import engine
from ..ai.features import encode_features
from ..ai.selfplay import board_configurations
from ..ai.serving import choose_move
from ..ai.state import observation, rules_fingerprint, SCHEMA_VERSION
from ..ai.tensors import Vocabulary


def game_seed(namespace, pair):
    return int.from_bytes(hashlib.sha256(f"orbit-value:{namespace}:{pair}".encode()).digest()[:8], "big")


def generate(output, games, namespace):
    if games < 16 or games % 16:
        raise ValueError("Games must be a positive multiple of 16 (boards x seat swaps)")
    if namespace not in ("train-v1", "development-v1"):
        raise ValueError("This bootstrap only uses named training/development pools")
    output.mkdir(parents=True, exist_ok=False)
    boards = board_configurations()
    manifest = {"version":1, "rules":rules_fingerprint(), "schema":SCHEMA_VERSION,
                "namespace":namespace, "games":[], "history":"omitted-ablation"}
    started = time.perf_counter()
    for index in range(games):
        pair = index//2
        seed = game_seed(namespace,pair)
        game = engine.new_game(["A","B"],seed=seed,configuration=boards[pair%8])
        rng = random.Random(seed ^ index%2)
        # Rotate whole 16-game board/seat blocks through opponent families.
        opponent = ("hard-v2", "exploratory-v2", "random")[(index//16)%3]
        names = ["hard-v2",opponent]
        if index%2:
            names.reverse()
        steps=[]
        for _ in range(1600):
            if game["phase"]=="over":
                break
            pid=next(p for p in game["order"] if engine.legal_moves(game,p))
            obs=observation(game,pid)
            seat=obs["seat"]
            moves=obs["legal_moves"]
            if names[seat]=="random" or (names[seat]=="exploratory-v2" and rng.random()<0.2):
                move=rng.choice(moves)
            else:
                move=choose_move(obs,moves,None,5000,seed).move
            for viewer in (0,1):
                steps.append({"actor_seat":seat,"observer_seat":viewer,
                              "observation":obs if viewer==seat else observation(game,game["order"][viewer])})
            ok,error=engine.apply_move(game,pid,move)
            if not ok:
                raise AssertionError(error)
        winner=game["order"].index(game["winner"]) if game["winner"] is not None else None
        record={"seed":seed,"pair":pair,"assignment":index%2,"board":boards[pair%8],
                "policies":names,"censored":game["phase"]!="over", "winner":winner,"steps":steps}
        raw=json.dumps(record,separators=(",",":"))
        name=f"game-{index:05d}.json"
        (output/name).write_text(raw,encoding="utf-8")
        manifest["games"].append({"file":name,"sha256":hashlib.sha256(raw.encode()).hexdigest(),
                                  "seed":seed,"censored":record["censored"]})
        if (index+1)%16==0:
            print(json.dumps({"generated":index+1,"seconds":round(time.perf_counter()-started,1)}),flush=True)
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")


def load_manifest(directory):
    m=json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    if m["rules"]!=rules_fingerprint() or m["schema"]!=SCHEMA_VERSION:
        raise ValueError("Dataset rules/schema mismatch")
    return m


def read_game(directory,item):
    raw=(directory/item["file"]).read_text(encoding="utf-8")
    if hashlib.sha256(raw.encode()).hexdigest()!=item["sha256"]:
        raise ValueError("Dataset shard checksum mismatch")
    return json.loads(raw)


def samples(game, *, per_seat=4, root_value_beta=0.0):
    if game["censored"]:
        return [],[]
    if not 0.0 <= root_value_beta <= 1.0:
        raise ValueError("root_value_beta must be between 0 and 1")
    inputs,labels=[],[]
    for seat in (0,1):
        steps=[s for s in game["steps"] if s["observation"]["seat"]==seat]
        if not steps:
            continue
        # Fixed stratified positions bound per-game weight and include pending decisions.
        for k in range(per_seat):
            step=steps[k*(len(steps)-1)//max(1,per_seat-1)]
            inputs.append(encode_features(step["observation"]))
            outcome=0.5 if game["winner"] is None else float(game["winner"]==seat)
            # Search root values are a teacher signal, not an input feature.
            # Blend only actor-seat rows that carry one; observer rows and old
            # foundation shards remain pure terminal-outcome targets.  Keeping
            # beta opt-in makes the outcome-only baseline an exact control.
            teacher=step.get("search_value")
            if root_value_beta and isinstance(teacher,(int,float)):
                if not isinstance(teacher,bool) and math.isfinite(float(teacher)) and -1.0 <= float(teacher) <= 1.0:
                    teacher_target=(float(teacher)+1.0)/2.0
                    outcome=(1.0-root_value_beta)*outcome+root_value_beta*teacher_target
            labels.append(outcome)
    return inputs,labels


def _fit_vocabulary_sources(sources):
    from ..ai.features import GROUP_FIELDS,PLAYER_GROUPS,validate_observation
    from ..cards import CARDS
    paths=set();categories=set()
    def collect(path,value):
        paths.add(path)
        if isinstance(value,dict):
            for key,v in value.items():collect((*path,key),v)
        elif isinstance(value,list):
            for v in value:collect((*path,None),v)
        elif isinstance(value,str):categories.add(value)
    seen=0
    for directory,manifest in sources:
      for index,item in enumerate(manifest["games"]):
        game=read_game(directory,item)
        if game["censored"]:continue
        for step in game["steps"]:
            obs=step["observation"];validate_observation(obs)
            for fields in GROUP_FIELDS.values():
                for key in fields:collect((key,),obs[key])
            for player in obs["players"]:
                for fields in PLAYER_GROUPS.values():
                    for key in fields:
                        if key not in player:continue
                        path=("players",None,key);collect(path,player[key])
                        piles=[player[key]] if key=="hand" else player[key] if key=="columns" else []
                        attrpath=(*path,None,"attributes") if key=="hand" else (*path,None,None,"attributes")
                        for pile in piles:
                            for card_id in pile:
                                card=CARDS[card_id]
                                collect(attrpath,{k:card[k] for k in ("id","cost","planet","faction")})
        seen+=1
        if seen%384==0:print(json.dumps({"vocabulary_games":seen}),flush=True)
    return Vocabulary(tuple(sorted(json.dumps(p,ensure_ascii=False,separators=(",",":")) for p in paths)),
                      tuple(sorted(categories)),rules_fingerprint())


def fit_vocabulary(directory,manifest):
    """Backward-compatible single-source vocabulary fitting helper."""
    return _fit_vocabulary_sources([(directory,manifest)])


def train(directory,development,output,epochs,device,resume=None,indexed_features=False,fused_adam=False,training_seed=9400,
          extra_data=None,allow_data_change=False,per_seat=4,root_value_beta=0.0):
    import torch
    from ..ai.attention import AttentionValue,ModelConfig,train_prepared,save_checkpoint,load_checkpoint
    if fused_adam and device != "cuda":
        raise ValueError("--fused-adam requires --device cuda")
    train_sources=[(directory,load_manifest(directory))]
    for extra in extra_data or []:
        train_sources.append((extra,load_manifest(extra)))
    train_manifest=train_sources[0][1]
    dev_manifest=load_manifest(development)
    if not train_manifest["namespace"].startswith("train-") or not dev_manifest["namespace"].startswith("development-"):
        raise ValueError("Wrong seed partition")
    train_seeds={g["seed"] for _,manifest in train_sources for g in manifest["games"]}
    if train_seeds&{g["seed"] for g in dev_manifest["games"]}:
        raise ValueError("Training/development seed overlap")
    torch.set_num_threads(2)
    torch.manual_seed(training_seed)
    train_fingerprints=[hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest() for _,manifest in train_sources]
    fingerprints={"train":train_fingerprints[0] if len(train_fingerprints)==1 else train_fingerprints,
                  "development":hashlib.sha256(json.dumps(dev_manifest,sort_keys=True).encode()).hexdigest()}
    if resume:
        model,optimizer,step,meta=load_checkpoint(resume,device=device,
                                                   fused_adam=fused_adam)
        if meta["datasets"]!=fingerprints and not allow_data_change:
            raise ValueError("Resume dataset mismatch")
        if meta["datasets"]!=fingerprints and allow_data_change:
            candidate_vocab=_fit_vocabulary_sources(train_sources)
            if candidate_vocab.as_dict()!=model.vocabulary.as_dict():
                raise ValueError("Changed training data requires an identical vocabulary")
        first_epoch=meta["epoch"]+1
        training_seed=meta.get("training_seed",9400)
        output.mkdir(parents=True,exist_ok=True)
    else:
        output.mkdir(parents=True,exist_ok=False)
        print("Building training-only vocabulary",flush=True)
        model=AttentionValue(_fit_vocabulary_sources(train_sources),ModelConfig(indexed_features=indexed_features)).to(device)
        optimizer=torch.optim.AdamW(model.parameters(),lr=0.0003,weight_decay=0.0001,fused=fused_adam)
        step=0;first_epoch=0
    # Immutable batches are cached without changing sample order, counts or math.
    # Bound memory rather than loading an unbounded full campaign onto the GPU.
    cache={};cache_bytes=0
    cache_limit=min(1024*1024*1024,torch.cuda.mem_get_info()[0]//4) if device=="cuda" else 256*1024*1024
    def prepared(root,item):
        nonlocal cache_bytes
        key=(str(root),item["sha256"])
        if key in cache:return cache[key]
        inputs,labels=samples(read_game(root,item),per_seat=per_seat,root_value_beta=root_value_beta)
        if not inputs:return None,labels
        batch=model.tensor_batch(inputs)
        size=sum(v.numel()*v.element_size() for v in batch.values() if torch.is_tensor(v))
        if cache_bytes+size<=cache_limit:
            cache[key]=(batch,labels);cache_bytes+=size
        return batch,labels
    # Preflight both partitions once, including all vocabulary coverage, before updates.
    for root,manifest in [*train_sources,(development,dev_manifest)]:
        for item in manifest["games"]:prepared(root,item)
    print(json.dumps({"cached_batches":len(cache),"cache_bytes":cache_bytes}),flush=True)
    for epoch in range(first_epoch,first_epoch+epochs):
        order=[(root,item) for root,manifest in train_sources for item in manifest["games"]]
        random.Random(training_seed+epoch).shuffle(order)
        losses=[];started=time.perf_counter()
        for root,item in order:
            batch,labels=prepared(root,item)
            if batch is not None:
                losses.append(train_prepared(model,optimizer,batch,labels));step+=1
        squared=[];logloss=[]
        import math
        for item in dev_manifest["games"]:
            batch,labels=prepared(development,item)
            if batch is None:
                continue
            model.eval()
            with torch.no_grad():predictions=model(batch).sigmoid().cpu().tolist()
            for p,y in zip(predictions,labels):
                squared.append((p-y)**2)
                p=max(1e-7,min(1-1e-7,p));logloss.append(-y*math.log(p)-(1-y)*math.log(1-p))
        if not losses or not squared:
            raise ValueError("No uncensored training or development examples")
        report={"epoch":epoch,"step":step,"train_loss":sum(losses)/len(losses),
                "development_brier":sum(squared)/len(squared),"development_logloss":sum(logloss)/len(logloss),
                "seconds":time.perf_counter()-started,"datasets":fingerprints,
                "history":"omitted-ablation","strength":"not evaluated","training_seed":training_seed,
                "indexed_features":model.config.indexed_features,"fused_adam":optimizer.param_groups[0].get("fused",False),
                "per_seat":per_seat,"training_sources":[str(root) for root,_ in train_sources],
                "root_value_beta":root_value_beta,
                "parent_checkpoint":str(resume) if resume else None}
        save_checkpoint(output/f"epoch-{epoch:03d}.pt",model,optimizer,step=step,
                        metadata={"epoch":epoch,"datasets":fingerprints,"history":"omitted-ablation","training_seed":training_seed,
                                  "per_seat":per_seat,"root_value_beta":root_value_beta,
                                  "parent_checkpoint":str(resume) if resume else None})
        with (output/"metrics.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(report)+"\n")
        print(json.dumps(report),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    g=sub.add_parser("generate")
    g.add_argument("output",type=Path);g.add_argument("--games",type=int,default=192)
    g.add_argument("--namespace",choices=("train-v1","development-v1"),required=True)
    t=sub.add_parser("train")
    t.add_argument("data",type=Path);t.add_argument("development",type=Path);t.add_argument("output",type=Path)
    t.add_argument("--epochs",type=int,default=3);t.add_argument("--device",default="cuda",choices=("cpu","cuda"))
    t.add_argument("--resume",type=Path)
    t.add_argument("--indexed-features",action="store_true")
    t.add_argument("--fused-adam",action="store_true")
    t.add_argument("--training-seed",type=int,default=9400)
    t.add_argument("--extra-data",type=Path,action="append",default=[],
                   help="Additional training dataset; repeated sources are mixed in every epoch")
    t.add_argument("--allow-data-change",action="store_true",
                   help="Allow --resume when the cumulative training manifest changed")
    t.add_argument("--per-seat",type=int,default=4,
                   help="Stratified positions sampled from each seat per game")
    t.add_argument("--root-value-beta",type=float,default=0.0,
                   help="Optional blend of search root values into terminal targets (0 keeps outcome-only control)")
    args=p.parse_args()
    if args.command=="generate":generate(args.output,args.games,args.namespace)
    else:
        if args.epochs<1: p.error("epochs must be positive")
        if args.per_seat<1: p.error("per-seat must be positive")
        if not 0.0<=args.root_value_beta<=1.0: p.error("root-value-beta must be between 0 and 1")
        train(args.data,args.development,args.output,args.epochs,args.device,args.resume,args.indexed_features,args.fused_adam,args.training_seed,
              extra_data=args.extra_data,allow_data_change=args.allow_data_change,per_seat=args.per_seat,
              root_value_beta=args.root_value_beta)


if __name__=="__main__":main()
