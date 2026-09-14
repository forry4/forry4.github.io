"""Export reviewed mechanical data, never a second hand-transcribed card set.

python -m games.orbit.tools.export_native [--check]
"""
import argparse
import json
from pathlib import Path

from games.orbit.ai.state import rules_fingerprint
from games.orbit.cards import CARDS, BONUS_POOL
from games.orbit.effects import CARD_EFFECTS, TECH_EFFECTS, BONUS_EFFECTS

OUTPUT = Path(__file__).resolve().parents[3] / "rust-cores/orbit-core/data/rules.json"


def render() -> str:
    # Keyed on CARDS so the native core stays the BASE 90. CARD_EFFECTS also holds
    # the Secret Agents programs, which exist only so that real BGA tables can be
    # replayed in Python; the Rust core implements neither those ten cards nor the
    # `raise_to` / `who: opponent` vocabulary they introduced, and `new_game` never
    # deals them unless a caller asks for `secret_agents=True`.
    base_effects = {card_id: CARD_EFFECTS[card_id] for card_id in sorted(CARDS)}
    payload = {"rules": rules_fingerprint(), "cards": CARDS, "bonus_pool": BONUS_POOL,
               "card_effects": base_effects, "bonus_effects": BONUS_EFFECTS,
               "tech_effects": {f"{f}/{s}/{l}": v for (f, s, l), v in TECH_EFFECTS.items()}}
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("Native Orbit rules are stale; run python -m games.orbit.tools.export_native")
        print("Orbit native rules match Python")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(expected, encoding="utf-8")
        print(OUTPUT)


if __name__ == "__main__":
    main()
