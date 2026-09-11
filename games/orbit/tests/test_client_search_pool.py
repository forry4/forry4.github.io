"""The browser's root ensemble must hand every worker a DIFFERENT seed.

`Orbit.jsx` fans one decision out to a capped worker pool and sums the root
visit counts. Each worker's seed is what selects the hidden world its tree
searches, so distinct seeds are the whole reason the pool is an ensemble rather
than four copies of one answer.

This became load-bearing on 2026-09-11. Under per-simulation determinization a
shared seed would have been merely wasteful; under the coherent search measured
that day -- one sampled world held for the whole call, which scored 0.6349
[0.5938, 0.6777] against per-simulation at the four-worker serving width -- a
shared seed would make all four trees IDENTICAL and silently collapse the
ensemble to K=1, while every offline arena kept measuring K=4 because
`neural_arena.rs::choose_pooled` derives its own per-tree seeds.

So the check reads the JSX AS TEXT, the same trick `test_client_glossary.py` and
`core/tests/test_history_limit.py` use for a constant seen from two ends. It
asserts the SHAPE of the seed expression, not a particular hash: the property
that matters is that the worker index reaches it.
"""

from __future__ import annotations

from pathlib import Path
import re


JSX = Path(__file__).resolve().parents[1] / "Orbit.jsx"


def _source() -> str:
    return JSX.read_text(encoding="utf-8")


def test_every_pooled_worker_gets_a_distinct_seed():
    source = _source()
    match = re.search(r"seed:\s*(.+?),\n", source)
    assert match, "Orbit.jsx no longer sets a per-request seed for its worker pool"
    expression = match.group(1)
    assert "index" in expression, (
        "the pooled worker seed must vary with the worker index, or the four "
        f"root trees search the same world; found: {expression}"
    )


def test_the_pool_is_capped_and_never_asks_for_zero_workers():
    # The repo-wide rule: a client-WASM pool must leave the compositor a thread,
    # and `max(1, ...)` is load-bearing rather than decoration -- a bare
    # `min(hc - 1, cap)` asks a single-core phone for ZERO workers, which is the
    # server bot wearing the Expert label.
    source = _source()
    match = re.search(r"Math\.max\(1,\s*Math\.min\(hardware\s*-\s*1,\s*(\w+)\)\)", source)
    assert match, "the Orbit worker pool no longer clamps to max(1, min(hc - 1, cap))"
    cap = match.group(1)
    assert re.search(rf"const {re.escape(cap)}\s*=\s*\d+", source), f"{cap} must be a constant cap"


def test_pooled_trees_are_combined_by_summing_visits():
    # Summing root visits is what makes independent trees an ensemble; counting
    # one vote per worker throws away how sure each tree was, and the coherent
    # gain is carried by exactly that confidence.
    source = _source()
    assert "summed" in source, "Orbit.jsx no longer sums pooled root visits"
    assert re.search(r"visits\s*\)?;?\s*\n", source), "pooled visit aggregation is gone"
