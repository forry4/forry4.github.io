"""Export a development-only float model/fixture for browser inference parity."""
import argparse
import json
from pathlib import Path

import torch

from ..ai.attention import load_checkpoint,export_model
from ..ai.features import encode_features
from .value_campaign import load_manifest,read_game


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path);p.add_argument("development",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    torch.set_num_threads(1)
    model,_,_,_=load_checkpoint(args.checkpoint);model.eval()
    manifest=load_manifest(args.development)
    if not manifest["namespace"].startswith("development-"):raise ValueError("Expected development pool")
    fixtures=[]
    for item in manifest["games"][:16]:
        game=read_game(args.development,item)
        for step in (game["steps"][0],game["steps"][-1]):
            obs=step["observation"]
            with torch.no_grad():logit=float(model(model.tensor_batch([encode_features(obs)]))[0])
            fixtures.append({"observation":obs,"logit":logit})
    args.output.write_text(json.dumps({"model":export_model(model),"fixtures":fixtures}),encoding="utf-8")
    print(json.dumps({"fixtures":len(fixtures),"output":str(args.output)}))


if __name__=="__main__":main()
