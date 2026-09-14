"""Python/Rust differential gate with explicit chance outcomes.

Build first: cargo build --release --manifest-path rust-cores/orbit-core/Cargo.toml
Run: python -m games.orbit.tools.native_parity --games 64

This verifies the PORT, not BGA rules fidelity. Every automatic task/choice and
shuffle is interpreted independently by Rust; Python supplies only source data,
initial state, the selected action, and random shuffle outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import random
import subprocess
from unittest.mock import patch

from games.orbit import engine as E
from games.orbit.ai.state import native_state, observation, rules_fingerprint
from games.orbit.cards import CARDS, FACTIONS, PLANETS
from games.orbit.effects import BONUS_EFFECTS

ROOT = Path(__file__).resolve().parents[3]


def first_difference(expected, actual, path="state"):
    if type(expected) is not type(actual):
        return f"{path}: expected {expected!r}, got {actual!r}"
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return f"{path}: keys expected {sorted(expected)}, got {sorted(actual)}"
        for key in expected:
            diff = first_difference(expected[key], actual[key], f"{path}.{key}")
            if diff:
                return diff
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: lengths {len(expected)} != {len(actual)}"
        for i, (a, b) in enumerate(zip(expected, actual)):
            diff = first_difference(a, b, f"{path}[{i}]")
            if diff:
                return diff
    elif expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


class Bridge:
    def __init__(self, binary: Path):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1)
        self.decisions = 0
        self.shuffles = 0
        self.kinds = Counter()
        self.rules = rules_fingerprint()

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        if self.process.returncode:
            raise AssertionError(f"Native bridge exited {self.process.returncode}")

    def step(self, game, pid, move, label, *, perturb=False):
        before = native_state(game)
        if perturb:
            # Deliberately corrupt only Rust's input, proving the end-to-end
            # comparison catches a mechanical disagreement (not just its helper).
            before["players"][0]["credits"] += 1
        before_moves = [E.legal_moves(game, p) for p in game["order"]]
        tape = []
        make_rng = E._make_rng

        class RecordingRng:
            def __init__(self, state):
                self.rng = make_rng(state)

            def shuffle(self, pile):
                self.rng.shuffle(pile)
                tape.append(list(pile))

            def getstate(self):
                return self.rng.getstate()

        self.kinds[game["pending"]["queue"][0]["type"] if game["pending"] else game["phase"]] += 1
        with patch.object(E, "_make_rng", RecordingRng):
            ok, error = E.apply_move(game, pid, move)
        E.validate_state(game)
        request = {"state": before, "seat": game["order"].index(pid), "move": move, "shuffles": tape}
        self.process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(f"{label}: bridge exited at move {move}")
        actual = json.loads(line)
        if "bridge_error" in actual:
            raise AssertionError(f"{label}: {actual['bridge_error']}")
        expected = {"rules": self.rules, "ok": ok, "error": error,
                    "before_moves": before_moves, "moves": [E.legal_moves(game, p) for p in game["order"]],
                    "observations": [observation(game, p) for p in game["order"]],
                    "state": native_state(game), "shuffles_consumed": len(tape)}
        diff = first_difference(expected, actual, label)
        if diff:
            raise AssertionError(f"{diff}; action={move}")
        self.decisions += 1
        self.shuffles += len(tape)


def actor(game):
    if game["phase"] == "mulligan":
        return next(p for p in game["order"] if p not in game["mulligan_done"])
    return game["pending_pid"] if game["pending"] else game["turn_pid"]


def rich_game(seed=0):
    """Conserving synthetic fixture with real cards in their own planet columns."""
    g = E.new_game(["A", "B"], seed=seed, configuration="random")
    for pid in g["order"]:
        E.apply_move(g, pid, {"action": "mulligan", "card_ids": []})
    for pid in g["order"]:
        p = g["players"][pid]
        p.update(credits=30, zenithium=20, hand=[])
        p["columns"] = {planet: [] for planet in PLANETS}
    g["agent_deck"] = list(CARDS)
    g["agent_discard"] = []
    for planet in PLANETS:
        candidates = [cid for cid in g["agent_deck"] if CARDS[cid]["planet"] == planet]
        for seat, pid in enumerate(g["order"]):
            for cid in candidates[seat * 7:(seat + 1) * 7]:
                g["agent_deck"].remove(cid)
                g["players"][pid]["columns"][planet].append(cid)
    for pid in g["order"]:
        E._draw_to(g, pid, 4)
    g["influence"] = dict(zip(PLANETS, [-2, 0, 1, 2, -1]))
    E.validate_state(g)
    return g


def put_in_hand(g, pid, card_id):
    if card_id in g["players"][pid]["hand"]:
        return
    locations = [g["agent_deck"], g["agent_discard"]]
    for player in g["players"].values():
        locations += [player["hand"], *player["columns"].values()]
    pile = next(pile for pile in locations if card_id in pile)
    pile.remove(card_id)
    g["players"][pid]["hand"].append(card_id)
    E.validate_state(g)


def resolve(bridge, game, rng, label):
    for _ in range(200):
        if not game["pending"] or E.is_over(game):
            return
        pid = actor(game)
        moves = E.legal_moves(game, pid)
        assert moves, label
        bridge.step(game, pid, rng.choice(moves), label)
    raise AssertionError(f"{label}: pending did not resolve")


def targeted(bridge):
    rng = random.Random(1234)
    # Exercise each real program with both leader states and multiple choices.
    for card_id in CARDS:
        for variant in range(3):
            g = rich_game(variant)
            pid = g["turn_pid"]
            put_in_hand(g, pid, card_id)
            if variant == 1:
                g["leader"] = {"owner": pid, "level": 2}
            elif variant == 2:
                g["players"][pid]["credits"] = max(0, CARDS[card_id]["cost"] - len(g["players"][pid]["columns"][CARDS[card_id]["planet"]]))
                g["players"][pid]["zenithium"] = 0
            label = f"card/{card_id}/{variant}"
            bridge.step(g, pid, {"action": "recruit", "card_id": card_id}, label)
            resolve(bridge, g, rng, label)
    for faction in FACTIONS:
        for side in (1, 2):
            for level in range(1, 6):
                g = rich_game()
                pid = g["turn_pid"]
                cid = next(cid for cid, c in CARDS.items() if c["faction"] == faction)
                put_in_hand(g, pid, cid)
                g["board_sides"][faction] = side
                g["players"][pid]["technology"][faction] = level - 1
                label = f"tech/{faction}/{side}/{level}"
                bridge.step(g, pid, {"action": "technology", "card_id": cid}, label)
                resolve(bridge, g, rng, label)
    for token in BONUS_EFFECTS:
        g = rich_game()
        pid = g["turn_pid"]
        # Resolve a real token from a board slot: no invented bonus inventory.
        for pile in (g["bonus_deck"], g["bonus_discard"]):
            if token in pile:
                pile.remove(token)
                old = g["planet_bonus"]["mercury"]
                if old is not None:
                    pile.append(old)
                g["planet_bonus"]["mercury"] = token
                break
        else:
            board, slot = next((board, slot) for board in (g["planet_bonus"], g["technology_bonus"])
                               for slot, value in board.items() if value == token)
            board[slot], g["planet_bonus"]["mercury"] = g["planet_bonus"]["mercury"], token
        g["pending"] = {"source": "fixture", "queue": [{"type": "take_board_bonus", "actor": pid}], "context": {}}
        g["pending_pid"] = pid
        label = f"bonus/{token}"
        bridge.step(g, pid, {"action": "choose", "bonus_area": "planet", "slot": "mercury"}, label)
        resolve(bridge, g, rng, label)


def boundaries(bridge):
    rng = random.Random(81)
    # All victory routes, both seats, including an opponent capture during the
    # active player's turn. BGA drains the already-open effect queue before
    # declaring the win, so the queued credit reward still resolves.
    for who in (0, 1):
        for captures, p in ((["mars", "mars"], "mars"),
                            (["mercury", "venus", "terra"], "jupiter"),
                            (["mercury", "mercury", "venus", "venus"], "terra")):
            g = rich_game()
            active, other = g["order"]
            beneficiary = g["order"][who]
            # Copy the fixture so a capture in one seat/route cannot mutate the
            # list reused by the next boundary case.
            g["players"][beneficiary]["captured"] = list(captures)
            g["influence"][p] = 3 if who == 0 else -3
            g["pending_pid"] = active
            g["pending"] = {"source": "victory fixture", "context": {}, "queue": [
                {"type": "influence", "amount": 7, "target": "self" if who == 0 else "opponent", "actor": active},
                {"type": "credits", "amount": 100, "actor": active},
            ]}
            credits = g["players"][active]["credits"]
            label = f"victory/{who}/{len(captures)}"
            bridge.step(g, active, {"action": "choose", "planet": p}, label)
            if not E.is_over(g):
                resolve(bridge, g, rng, label)
            assert E.winner(g) == beneficiary
            # A capture may also award a board token before the queued reward;
            # the parity bridge compares the exact resulting state below, so
            # keep this local boundary check agnostic to that token's effect.
            assert g["players"][active]["credits"] >= credits
    # Capture a bonus whose resolution belongs to the opponent. The main turn
    # owner stays unchanged while the pending decision owner changes.
    g = rich_game()
    active, other = g["order"]
    for board in (g["planet_bonus"], g["technology_bonus"]):
        for slot, token in list(board.items()):
            if token == 3:
                board[slot], g["planet_bonus"]["mars"] = g["planet_bonus"]["mars"], token
                break
        else:
            continue
        break
    else:
        pile = next(p for p in (g["bonus_deck"], g["bonus_discard"]) if 3 in p)
        pile.remove(3)
        pile.append(g["planet_bonus"]["mars"])
        g["planet_bonus"]["mars"] = 3
    g["influence"]["mars"] = -3
    g["pending_pid"] = active
    g["pending"] = {"source": "opponent bonus", "context": {}, "queue": [
        {"type": "influence", "amount": 1, "target": "opponent", "actor": active}]}
    bridge.step(g, active, {"action": "choose", "planet": "mars"}, "opponent-bonus")
    assert g["pending_pid"] == other and g["turn_pid"] == active
    resolve(bridge, g, rng, "opponent-bonus")
    # Cross all row thresholds together; row rewards follow the technology chain.
    g = rich_game()
    pid = g["turn_pid"]
    g["players"][pid]["technology"] = {f: 3 for f in FACTIONS}
    g["pending_pid"] = pid
    g["pending"] = {"source": "rows", "context": {}, "queue": [
        {"type": "optional", "actor": pid, "cost": {"resource": "credits", "amount": 0},
         "then": [{"type": "row_bonus_check"}]}]}
    bridge.step(g, pid, {"action": "choose", "accept": True}, "all-row-bonuses")
    assert g["players"][pid]["row_bonuses"] == [1, 2, 3]
    resolve(bridge, g, rng, "all-row-bonuses")
    # Both reshuffle types in a single resolution, with exact scripted outcomes.
    g = rich_game()
    pid = g["turn_pid"]
    g["agent_discard"].extend(g["agent_deck"])
    g["agent_deck"] = []
    g["bonus_discard"].extend(g["bonus_deck"])
    g["bonus_deck"] = []
    g["pending_pid"] = pid
    g["pending"] = {"source": "reshuffles", "context": {}, "queue": [
        {"type": "optional", "actor": pid, "cost": {"resource": "credits", "amount": 0},
         "then": [{"type": "mobilize", "count": 1}, {"type": "draw_bonus"}]}]}
    old = bridge.shuffles
    bridge.step(g, pid, {"action": "choose", "accept": True}, "both-reshuffles")
    assert bridge.shuffles - old == 2
    resolve(bridge, g, rng, "both-reshuffles")
    # Reject an illegal move without advancing the state or chance stream.
    bridge.step(g, g["order"][0], {"action": "recruit", "card_id": 999}, "illegal-atomic")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--games", type=int, default=64)
    parser.add_argument("--binary", type=Path, default=ROOT / "rust-cores/orbit-core/target/release/bridge")
    args = parser.parse_args()
    if args.games < 8:
        parser.error("--games must be at least 8 to cover all boards")
    binary = args.binary
    if not binary.exists() and binary.with_suffix(".exe").exists():
        binary = binary.with_suffix(".exe")
    bridge = Bridge(binary)
    try:
        probe = E.new_game(["A", "B"], seed=0)
        try:
            bridge.step(probe, actor(probe), {"action": "mulligan", "card_ids": []}, "fault-probe", perturb=True)
        except AssertionError as error:
            assert "credits" in str(error), error
        else:
            raise AssertionError("Deliberately changed credits were not detected")
        targeted(bridge)
        boundaries(bridge)
        for seed in range(args.games):
            sides = {f: 1 + ((seed >> i) & 1) for i, f in enumerate(FACTIONS)}
            g = E.new_game(["A", "B"], seed=seed, configuration=sides)
            rng = random.Random(seed + 3001)
            for decision in range(2000):
                if E.is_over(g):
                    break
                pid = actor(g)
                moves = E.legal_moves(g, pid)
                bridge.step(g, pid, rng.choice(moves), f"game/{seed}/{decision}")
            else:
                raise AssertionError(f"game {seed}: censored at 2000 decisions")
        assert bridge.shuffles > 0, "No reshuffles tested"
        print(json.dumps({"games": args.games, "decisions": bridge.decisions, "shuffles": bridge.shuffles,
                          "decision_kinds": dict(bridge.kinds), "rules": bridge.rules}, sort_keys=True))
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
