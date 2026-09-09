"""Alternating native forward benchmark on identical frozen model/observations."""
import argparse
import json
from pathlib import Path
import statistics

from ..ai.native_value import NativeValueGuide


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixture",type=Path);p.add_argument("before",type=Path)
    p.add_argument("after",type=Path);p.add_argument("output",type=Path)
    args=p.parse_args();fixture=json.loads(args.fixture.read_text(encoding="utf-8"))
    times=[[],[]];errors=[[],[]]
    with NativeValueGuide(fixture["model"],binary=args.before.resolve()) as before, \
            NativeValueGuide(fixture["model"],binary=args.after.resolve()) as after:
        guides=[before,after]
        for repeat in range(4):
            for index,row in enumerate(fixture["fixtures"]):
                for build in ((0,1) if (index+repeat)%2 else (1,0)):
                    result=guides[build]._call({"observation":row["observation"]})
                    error=abs(result["logit"]-row["logit"])
                    if error>1e-4:raise AssertionError(f"Forward parity failed: {error}")
                    if repeat:
                        times[build].append(result["elapsed_ms"]);errors[build].append(error)
    report={"scope":"alternating native observation-to-value, one warmup pass; no strength claim",
            "evaluations_per_build":len(times[0]),
            "before_median_ms":statistics.median(times[0]),"after_median_ms":statistics.median(times[1]),
            "total_time_speedup":sum(times[0])/sum(times[1]),
            "max_logit_errors":[max(e) for e in errors]}
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
