"""Night actions: swaps keep the dealt (night) role immutable, seer peeks, and the
player_view redaction boundary."""
from games.wherewolf import engine
from .conftest import make_game, at_step


def setup(step, role_map, players=("a", "b", "c", "d"), seed=0):
    g = make_game(players, seed=seed)
    return at_step(g, step, role_map)


# ── Robber ────────────────────────────────────────────────────────────────────
def test_robber_swaps_cards_only():
    g = setup(engine.STEP_ROBBER, {"a": "robber", "b": "villager"})
    ok, err = engine.apply_move(g, "a", {"type": "robber_swap", "target": "b"})
    assert ok, err
    # dealt_role (the night role) is immutable for both
    assert g["players"]["a"]["dealt_role"] == "robber"
    assert g["players"]["b"]["dealt_role"] == "villager"
    # only the CARDS moved
    assert g["players"]["a"]["card"] == "villager"
    assert g["players"]["b"]["card"] == "robber"
    assert g["robber_swap"] == {"target": "b"}
    assert g["acted"]["robber"] is True


def test_robber_cannot_target_self():
    g = setup(engine.STEP_ROBBER, {"a": "robber"})
    assert not engine.apply_move(g, "a", {"type": "robber_swap", "target": "a"})[0]


def test_non_robber_cannot_rob():
    g = setup(engine.STEP_ROBBER, {"a": "robber", "b": "villager"})
    assert not engine.apply_move(g, "b", {"type": "robber_swap", "target": "a"})[0]


def test_robber_sees_new_card_victim_does_not():
    g = setup(engine.STEP_ROBBER, {"a": "robber", "b": "villager"})
    assert engine.player_view(g, "a")["players"]["a"]["card"] == "robber"  # own current card
    engine.apply_move(g, "a", {"type": "robber_swap", "target": "b"})
    assert engine.player_view(g, "a")["players"]["a"]["card"] == "villager"  # new card
    # the robbed player is NOT told their card changed
    assert engine.player_view(g, "b")["players"]["b"]["card"] is None


# ── Troublemaker ──────────────────────────────────────────────────────────────
def test_troublemaker_swaps_two_others():
    g = setup(engine.STEP_TMAKER, {"a": "troublemaker", "b": "villager", "c": "werewolf"})
    bc, cc = g["players"]["b"]["card"], g["players"]["c"]["card"]
    ok, err = engine.apply_move(g, "a", {"type": "troublemaker_swap", "a": "b", "b": "c"})
    assert ok, err
    assert g["players"]["b"]["card"] == cc
    assert g["players"]["c"]["card"] == bc
    assert g["players"]["a"]["dealt_role"] == "troublemaker"
    assert g["players"]["b"]["dealt_role"] == "villager"
    assert g["players"]["c"]["dealt_role"] == "werewolf"


def test_troublemaker_may_include_self():
    g = setup(engine.STEP_TMAKER, {"a": "troublemaker", "b": "villager"})
    ac, bc = g["players"]["a"]["card"], g["players"]["b"]["card"]
    ok, err = engine.apply_move(g, "a", {"type": "troublemaker_swap", "a": "a", "b": "b"})
    assert ok, err
    assert g["players"]["a"]["card"] == bc
    assert g["players"]["b"]["card"] == ac


def test_troublemaker_same_target_rejected():
    g = setup(engine.STEP_TMAKER, {"a": "troublemaker", "b": "villager"})
    assert not engine.apply_move(g, "a", {"type": "troublemaker_swap", "a": "b", "b": "b"})[0]


# ── Seer ──────────────────────────────────────────────────────────────────────
def test_seer_peek_player_visible_to_seer_only():
    g = setup(engine.STEP_SEER, {"a": "seer", "b": "werewolf"})
    ok, err = engine.apply_move(g, "a", {"type": "seer_peek_player", "target": "b"})
    assert ok, err
    assert engine.player_view(g, "a")["players"]["b"]["card"] == "werewolf"
    assert engine.player_view(g, "c")["players"]["b"]["card"] is None


def test_seer_peek_center_visible_to_seer_only():
    g = setup(engine.STEP_SEER, {"a": "seer"})
    ok, err = engine.apply_move(g, "a", {"type": "seer_peek_center", "indices": [0, 2]})
    assert ok, err
    v = engine.player_view(g, "a")
    assert v["center"][0] == g["center"][0]
    assert v["center"][2] == g["center"][2]
    assert v["center"][1] is None
    # a non-seer sees no center cards
    assert engine.player_view(g, "b")["center"] == [None, None, None]


def test_seer_cannot_do_both_player_and_center():
    g = setup(engine.STEP_SEER, {"a": "seer", "b": "villager"})
    assert engine.apply_move(g, "a", {"type": "seer_peek_player", "target": "b"})[0]
    assert not engine.apply_move(g, "a", {"type": "seer_peek_center", "indices": [0, 1]})[0]


def test_seer_center_needs_two_distinct():
    g = setup(engine.STEP_SEER, {"a": "seer"})
    assert not engine.apply_move(g, "a", {"type": "seer_peek_center", "indices": [0, 0]})[0]
    assert not engine.apply_move(g, "a", {"type": "seer_peek_center", "indices": [0]})[0]


# ── Werewolves & step legality ────────────────────────────────────────────────
def test_werewolves_see_each_other_only():
    g = setup(engine.STEP_WOLVES, {"a": "werewolf", "b": "werewolf", "c": "villager"},
              players=("a", "b", "c"))
    va = engine.player_view(g, "a")
    assert va["players"]["b"]["card"] == "werewolf"   # wolf a sees wolf b
    assert va["players"]["c"]["card"] is None          # but not villager c
    vc = engine.player_view(g, "c")
    assert vc["players"]["a"]["card"] is None           # villager sees no wolves
    assert vc["players"]["b"]["card"] is None


def test_wrong_step_rejected():
    g = setup(engine.STEP_ROBBER, {"a": "seer"})
    assert not engine.apply_move(g, "a", {"type": "seer_peek_center", "indices": [0, 1]})[0]


def test_night_move_rejected_outside_night():
    g = make_game(["a", "b", "c"], seed=1)  # still in DEALING
    assert not engine.apply_move(g, "a", {"type": "robber_swap", "target": "b"})[0]


# ── Drunk (blind swap with a center card) ─────────────────────────────────────
def test_drunk_blind_swap_moves_card_no_leak():
    g = setup(engine.STEP_DRUNK, {"a": "drunk", "b": "villager"})
    old_center0 = g["center"][0]
    ok, err = engine.apply_move(g, "a", {"type": "drunk_swap", "center_index": 0})
    assert ok, err
    assert g["players"]["a"]["dealt_role"] == "drunk"        # night role immutable
    assert g["players"]["a"]["card"] == old_center0          # took the center card
    assert g["center"][0] == "drunk"                         # drunk card went to center
    # the whole point: the drunk does NOT see their new card
    assert engine.player_view(g, "a")["players"]["a"]["card"] is None


def test_drunk_rejects_bad_center_index():
    g = setup(engine.STEP_DRUNK, {"a": "drunk"})
    assert not engine.apply_move(g, "a", {"type": "drunk_swap", "center_index": 9})[0]
    assert not engine.apply_move(g, "b", {"type": "drunk_swap", "center_index": 0})[0]


# ── Lone wolf optional center peek ────────────────────────────────────────────
def test_lone_wolf_center_peek_is_private():
    g = setup(engine.STEP_WOLVES, {"a": "werewolf", "b": "villager", "c": "villager"},
              players=("a", "b", "c"))
    ok, err = engine.apply_move(g, "a", {"type": "wolf_peek_center", "index": 0})
    assert ok, err
    assert engine.player_view(g, "a")["center"][0] == g["center"][0]
    assert engine.player_view(g, "a")["center"][1] is None
    assert engine.player_view(g, "b")["center"] == [None, None, None]


def test_two_wolves_cannot_peek_center():
    g = setup(engine.STEP_WOLVES, {"a": "werewolf", "b": "werewolf", "c": "villager"},
              players=("a", "b", "c"))
    assert not engine.apply_move(g, "a", {"type": "wolf_peek_center", "index": 0})[0]


# ── Minion / Masons / Insomniac (info reveals) ────────────────────────────────
def test_minion_sees_wolves_not_vice_versa():
    g = setup(engine.STEP_MINION, {"a": "minion", "b": "werewolf", "c": "villager"},
              players=("a", "b", "c"))
    assert engine.player_view(g, "a")["players"]["b"]["card"] == "werewolf"   # minion sees wolf
    assert engine.player_view(g, "b")["players"]["a"]["card"] is None          # wolf does NOT see minion


def test_masons_see_each_other():
    g = setup(engine.STEP_MASONS, {"a": "mason", "b": "mason", "c": "villager"},
              players=("a", "b", "c"))
    assert engine.player_view(g, "a")["players"]["b"]["card"] == "mason"
    assert engine.player_view(g, "b")["players"]["a"]["card"] == "mason"
    assert engine.player_view(g, "c")["players"]["a"]["card"] is None


def test_insomniac_sees_own_changed_card():
    g = setup(engine.STEP_INSOMNIAC, {"a": "insomniac", "b": "villager"})
    g["players"]["a"]["card"] = "robber"        # simulate having been robbed/troublemade
    assert engine.player_view(g, "a")["players"]["a"]["card"] == "robber"
    # at a different step the insomniac does NOT see their own card
    engine.set_step(g, engine.STEP_MASONS)
    assert engine.player_view(g, "a")["players"]["a"]["card"] is None
