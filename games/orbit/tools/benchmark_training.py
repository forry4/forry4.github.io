"""Compare float32 AdamW implementations on identical prepared updates."""
import argparse,copy,json,time
from pathlib import Path
import torch
from ..ai.attention import load_checkpoint,train_prepared
from .value_campaign import load_manifest,read_game,samples


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path);p.add_argument("data",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--steps",type=int,default=40)
    args=p.parse_args();torch.set_num_threads(2)
    reference,_,_,_=load_checkpoint(args.checkpoint,device="cuda")
    inputs,labels=samples(read_game(args.data,load_manifest(args.data)["games"][0]))
    batch=reference.tensor_batch(inputs)
    results=[];states=[]
    for fused in (False,True):
        model=copy.deepcopy(reference)
        optimizer=torch.optim.AdamW(model.parameters(),lr=0.0003,weight_decay=0.0001,fused=fused)
        for _ in range(5):train_prepared(model,optimizer,batch,labels)
        torch.cuda.synchronize();started=time.perf_counter();loss=0
        for _ in range(args.steps):loss=train_prepared(model,optimizer,batch,labels)
        torch.cuda.synchronize()
        results.append({"fused":fused,"ms_per_update":(time.perf_counter()-started)*1000/args.steps,"loss":loss})
        states.append({k:v.detach().cpu().clone() for k,v in model.state_dict().items()})
        del model,optimizer
    difference=max(float((states[0][k]-states[1][k]).abs().max()) for k in states[0])
    report={"results":results,"max_weight_difference":difference,
            "scope":"same FP32 samples, batch size, loss, learning rate and update count; numerical equivalence probe"}
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
