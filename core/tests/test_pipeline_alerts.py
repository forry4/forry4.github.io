"""Every pipeline that can fail where nobody is looking is on pipeline-alerts.yml.

That workflow names the runs it watches by their `name:`, so a new data job — or a
renamed one — silently drops off it: no alert, and nothing failing to say so. The
roster here is DERIVED: every workflow that publishes to the data store or deploys.
"""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _watched():
    doc = yaml.safe_load((WF / "pipeline-alerts.yml").read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))           # YAML 1.1 reads a bare `on:` as True
    return set(on["workflow_run"]["workflows"])


def _must_watch():
    out = {}
    for f in sorted(WF.glob("*.yml")):
        text = f.read_text(encoding="utf-8")
        if f.name == "pipeline-alerts.yml":
            continue
        if "datastore.py" in text or f.name.startswith("deploy-") or f.name == "python-app.yml":
            out[f.name] = yaml.safe_load(text)["name"]
    return out


def test_every_data_and_deploy_pipeline_is_watched():
    must = _must_watch()
    assert len(must) >= 10, must          # a broken walk would find nothing and pass
    missing = {f: n for f, n in must.items() if n not in _watched()}
    assert not missing, f"add these to pipeline-alerts.yml's workflow_run list: {missing}"


def test_every_watched_name_is_a_real_workflow():
    names = {yaml.safe_load(f.read_text(encoding="utf-8"))["name"] for f in WF.glob("*.yml")}
    assert _watched() <= names, _watched() - names     # a typo watches nothing
