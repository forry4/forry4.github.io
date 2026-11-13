"""What a Render cold start does NOT load any more, and that loading it later
serves the same thing.

Prod reported a 12.1s import of our own code on its first measured boot
(core.build_info, 2026-11-13). The retired AZ net (and numpy with it) and the
5MB puzzle bank were parsed at import although no first request needs them;
both now load on first use. A later edit that touches either at import compiles
and passes every other test, so this asserts it from a clean interpreter."""
import json
import subprocess
import sys
import threading
from pathlib import Path

from games.spender.ai.serving import legacy_variants as legacy
from games.spender.puzzle import serve

ROOT = Path(__file__).resolve().parents[3]


def test_importing_the_app_loads_neither_numpy_nor_the_bank_nor_the_az_net():
    probe = (
        "import json, sys\n"
        "import app\n"
        "from games.spender.puzzle import serve\n"
        "from games.spender.ai.serving import legacy_variants as legacy\n"
        "print(json.dumps({'numpy': 'numpy' in sys.modules,"
        " 'bank': serve._BANK is not None, 'az': legacy._AZ_TRIED}))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True,
                         text=True, timeout=120, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == {"numpy": False, "bank": False, "az": False}


def test_the_lazy_bank_is_the_eager_bank(monkeypatch):
    monkeypatch.setattr(serve, "_BANK", None)
    eager = serve._load_bank()
    assert serve.list_puzzles() == [serve._meta(eager[pid]) for pid in sorted(eager)]
    some = sorted(eager)[0]
    assert serve.get_puzzle(some) == eager[some]
    assert serve.get_puzzle("no-such-puzzle") is None
    assert len(eager) > 50   # the bank is really there, not an empty glob


def test_concurrent_first_requests_parse_the_bank_once(monkeypatch):
    monkeypatch.setattr(serve, "_BANK", None)
    calls, real = [], serve._load_bank
    gate = threading.Event()

    def slow_load():
        calls.append(1)
        gate.wait(1)
        return real()

    monkeypatch.setattr(serve, "_load_bank", slow_load)
    threads = [threading.Thread(target=serve.list_puzzles) for _ in range(6)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert calls == [1]


def test_the_az_net_loads_on_first_use_and_only_once(monkeypatch):
    monkeypatch.setattr(legacy, "AZ_EVALUATE", None)
    monkeypatch.setattr(legacy, "_AZ_TRIED", False)
    loads = []
    real = legacy.load_az_model
    monkeypatch.setattr(legacy, "load_az_model", lambda: (loads.append(1), real()))
    first = legacy.az_evaluator()
    assert first is not None, "ai/models/az_model.npz ships; variant Z must still serve old saves"
    assert legacy.az_evaluator() is first and loads == [1]


def test_a_missing_az_net_is_tried_once(monkeypatch):
    monkeypatch.setattr(legacy, "AZ_EVALUATE", None)
    monkeypatch.setattr(legacy, "_AZ_TRIED", False)
    monkeypatch.setattr(legacy, "AZ_MODEL_PATH", str(ROOT / "no-such-model.npz"))
    assert legacy.az_evaluator() is None and legacy._AZ_TRIED
    monkeypatch.setattr(legacy, "load_az_model", lambda: (_ for _ in ()).throw(AssertionError))
    assert legacy.az_evaluator() is None
