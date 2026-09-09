"""Offline native leaf evaluator for the existing information-set search.

The process receives only an allowlisted observation. This baseline explicitly
omits history; no private simulator state is serialized across the boundary.
"""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import subprocess

from .features import validate_observation
from .state import SCHEMA_VERSION


class NativeValueGuide:
    def __init__(self,artifact,*,binary=None,cache_size=1024):
        self.artifact=artifact
        self.rules=artifact["vocabulary"]["rules"]
        self.schema=SCHEMA_VERSION
        self.encoder=artifact["vocabulary"]["encoder"]
        self.model_version=artifact["version"]
        self.digest=hashlib.sha256(json.dumps(artifact,sort_keys=True).encode()).hexdigest()
        self.cache_size=cache_size;self.cache=OrderedDict();self.calls=0;self.cache_hits=0
        binary=binary or Path(__file__).resolve().parents[3]/"rust-cores/orbit-core/target/release/attention_bridge.exe"
        self.process=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      text=True,encoding="utf-8")
        try:
            self._call({"model":artifact})
        except Exception:
            self.close();raise

    def _call(self,payload):
        self.process.stdin.write(json.dumps(payload,separators=(",",":"))+"\n")
        self.process.stdin.flush()
        line=self.process.stdout.readline()
        if not line:raise RuntimeError("Native evaluator exited")
        result=json.loads(line)
        if "error" in result:raise ValueError(result["error"])
        return result

    def priors(self,obs,legal_moves,*,history=None):
        return {}  # Preserve the existing audited heuristic priors.

    def value(self,obs,*,history=None):
        import math
        validate_observation(obs)
        key=json.dumps(obs,sort_keys=True,separators=(",",":"))
        if key in self.cache:
            self.cache_hits+=1;self.cache.move_to_end(key);return self.cache[key]
        logit=self._call({"observation":obs})["logit"]
        self.calls+=1
        value=math.tanh(logit/2)  # 2*sigmoid(logit)-1, in the observing seat's frame.
        if self.cache_size>0:
            self.cache[key]=value
            if len(self.cache)>self.cache_size:self.cache.popitem(last=False)
        return value

    def as_dict(self):
        return {"digest":self.digest,"version":self.model_version,"rules":self.rules,
                "history":"omitted-ablation"}

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        self.process.wait(timeout=10)
        if self.process.stdout:self.process.stdout.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
