"""SERVER↔CLIENT CONTRACT: every field Dontminion.jsx reads off the wire must
actually be shipped.

Both frontend bugs found in live play were drift on this seam, not logic
errors — the client re-derived prices the server owned (Peddler showed printed
costs, so discounted piles never lit up and the buy was refused), and it
rendered a button off a fact the server never sent (Play-all-treasures offered
itself for a hand of nothing but manual treasures, doing nothing when clicked).
Neither is visible to the Python suite (which never renders) or to
`npm run screens` (which mounts the route but plays no Dontminion game), so
this reads the JSX source and checks the field names against a real view.

It is deliberately a NAME check, not a render test: it cannot prove the client
uses a field correctly, only that the server still sends it. That is exactly
the failure both bugs had — the client asking for something that wasn't there.
"""

import pathlib
import re

import pytest

from games.dontminion import engine
from games.dontminion.cards import KINGDOM

A, B = "alice", "bob"
JSX = "games/dontminion/Dontminion.jsx"
MAIN = "games/dontminion/main.py"

# Reads that are NOT wire fields — locals, client-derived state, or optional
# chaining onto something built in the component. Keep this SHORT and justified;
# a growing allowlist means the check is being worked around.
ALLOW_GAME = {
    # nested reads the regex flattens (game.turn_ctx.bought, game.seats[pid]...)
    "seats", "turn_ctx",
}
ALLOW_SEAT = set()


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fn_body(src, decl):
    """The WHOLE body of a JS function, by brace matching from its declaration.

    This used to be `src[src.find(decl):][:12000]` — a fixed character window —
    and that is the lose-track guard's own history repeating: "an earlier regex
    version scanned a 6-line window and comments pushed two real sites out of
    it, so it passed while checking 5 of 7". `fmtLog` grew past 12000
    characters, so the LAST four cases (`abandon`, `game_over`, `lost_track`,
    `undo`) fell off the end and the guard silently stopped covering them —
    found when adding one more case pushed them over and the test reported four
    events missing that were plainly right there in the file.

    A window is never the right tool for "the whole of this function": it fails
    OPEN, and it fails on the additions the guard exists to catch."""
    i = src.index(decl)
    start = src.index("{", i)
    depth = 0
    for j in range(start, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(f"unbalanced braces after {decl!r}")


def _reads(src, obj):
    """Every `obj.X` / `obj?.X` property read in the source."""
    return set(re.findall(rf"\b{obj}\??\.(\w+)", src))


def _views():
    """Wire views across every shape the client can be looking at: owner,
    opponent, spectator, and a finished game (which reveals everything)."""
    kingdom = sorted(KINGDOM["prosperity"])[:10]
    g = engine.new_game([A, B], ["prosperity"], seed=5, kingdom=kingdom)
    engine.apply_move(g, A, {"type": "end_phase"})
    out = [engine.player_view(g, v) for v in (A, B, None)]
    g["over"] = True
    out.append(engine.player_view(g, A))
    return out


def test_every_game_field_the_client_reads_is_shipped():
    views = _views()
    shipped = set().union(*(set(v) for v in views))
    missing = _reads(_src(JSX), "game") - shipped - ALLOW_GAME
    assert not missing, (
        f"Dontminion.jsx reads game.{{{', '.join(sorted(missing))}}} but "
        f"player_view does not ship it — the client will silently render "
        f"undefined (the Peddler-cost bug's shape)")


@pytest.mark.parametrize("obj", ["mySeat", "seat", "opp"])
def test_every_seat_field_the_client_reads_is_shipped(obj):
    views = _views()
    shipped = set()
    for v in views:
        for s in v["seats"].values():
            shipped |= set(s)
    missing = _reads(_src(JSX), obj) - shipped - ALLOW_SEAT
    assert not missing, (
        f"Dontminion.jsx reads {obj}.{{{', '.join(sorted(missing))}}} but no "
        f"seat view ships it")


def test_every_catalog_field_the_client_reads_is_shipped():
    """/catalog is the other wire surface — it carries the static card data
    plus MANUAL_TREASURES (which the Play-all button needs to not render
    itself for a hand it cannot act on)."""
    main_src = _src(MAIN)
    body = main_src.split("async def catalog()", 1)[1].split("\n@", 1)[0]
    shipped = set(re.findall(r'"(\w+)":', body))
    missing = _reads(_src(JSX), "catalog") - shipped
    assert not missing, (
        f"Dontminion.jsx reads catalog.{{{', '.join(sorted(missing))}}} but "
        f"/catalog does not return it")


def test_every_log_event_the_engine_emits_has_a_fmtLog_case():
    """The unknown-event FALLBACK exists so a new event is never silent — but
    it renders raw field names, which can actively mislead: `off_turn_bonus`
    came out as "bob off turn bonus: coins 2", reading as though he got the
    coins when the point is that he lost them. So the fallback is the safety
    net, not the destination: every event the engine actually emits owes a
    case. (A future set may add an event before its UI wording — that is what
    the fallback covers, and this test is what stops it staying that way.)"""
    events = set()
    for path in pathlib.Path("games/dontminion").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        events |= set(re.findall(r'_log\(\s*game\s*,\s*[^,]+,\s*"([a-z_]+)"', src))
        events |= set(re.findall(r'"event":\s*"([a-z_]+)"', src))

    jsx = _src(JSX)
    body = _fn_body(jsx, "function fmtLog")
    cased = set(re.findall(r'case "([a-z_]+)"', body))

    assert len(events) > 20, "the emit scan found almost nothing — regex rotted"
    missing = sorted(events - cased)
    assert not missing, (
        f"engine emits {missing} with no fmtLog case — they will render as raw "
        f"field names in the game log")


def test_no_log_call_passes_a_count_as_n():
    """`_log` stamps the log SEQUENCE into entry["n"] LAST, so core fields can
    never be clobbered by an event kwarg — which means an `n=` kwarg is
    silently thrown away. Three call sites did it anyway (`coffers`, `spend`,
    `end_draw`) and the client rendered the sequence number: "gets +917
    Coffers". Counts go in `count=`, and this is the guard, because the failure
    is invisible in every test that doesn't read the rendered string."""
    offenders = []
    for path in sorted(pathlib.Path("games/dontminion").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'_log\(\s*game\s*,\s*[^,]+,\s*"([a-z_]+)"([^)]*)\)', src):
            if re.search(r'\bn\s*=', m.group(2)):
                offenders.append(f"{path.name}: {m.group(1)}")
    assert not offenders, (
        f"these _log calls pass n= and it is discarded: {offenders} — use count=")


def test_every_bot_tier_the_picker_offers_is_one_the_server_accepts():
    """The create modal's bot ids are the same seam as any other wire field,
    and it FAILS SILENTLY: `_valid_difficulty` coerces anything it doesn't
    recognise to the default, so a picker id that has drifted out of
    AI_DIFFICULTIES doesn't error — it quietly seats a different bot than the
    one the player chose. Plain `bigmoney` leaving the ladder is exactly the
    move that can strand an id here."""
    # The picker's list lives in shared/botTiers.js (the profile page names bots too).
    assert "DONTMINION_BOTS as BOTS" in _src(JSX), "Dontminion.jsx no longer renders the shared bot list"
    tiers = _src("shared/botTiers.js")
    block = tiers[tiers.find("const DONTMINION_BOTS = ["):]
    block = block[:block.find("]")]
    offered = set(re.findall(r'id:\s*"(\w+)"', block))
    assert offered, "the BOTS picker list was not found — regex rotted"

    main_src = _src(MAIN)
    tuple_src = re.search(r"AI_DIFFICULTIES = \(([^)]*)\)", main_src).group(1)
    names = re.findall(r'"(\w+)"|bot\.(\w+)', tuple_src)
    from games.dontminion import bot
    accepted = {lit or getattr(bot, attr) for lit, attr in names}

    assert offered <= accepted, (
        f"Dontminion.jsx offers bot tiers {sorted(offered - accepted)} that "
        f"main.AI_DIFFICULTIES does not accept — the server will silently "
        f"substitute the default instead of seating what was picked")
    assert bot.BIG_MONEY not in accepted, (
        "plain bigmoney is a strict subset of bmplus and was retired as an "
        "opponent — it must stay a research-only tier")


def test_every_pinned_ambiguity_names_a_test_that_exists():
    """The OPEN AMBIGUITIES list in CLAUDE.md claims each entry is pinned by a
    test. A list that cites a test which has been renamed or deleted is worse
    than no list — it reads as "this is covered" when nothing is watching. So
    every `test_...` name the section mentions must actually exist."""
    doc = _src("games/dontminion/CLAUDE.md")
    start = doc.find("## OPEN AMBIGUITIES")
    assert start != -1, "the ambiguity list is gone from CLAUDE.md"
    section = doc[start:doc.find("\n## ", start + 10)]
    cited = set(re.findall(r"`(test_\w+)`", section))
    assert cited, "the ambiguity list cites no tests at all"

    defined = set()
    for path in pathlib.Path("games/dontminion/tests").glob("test_*.py"):
        defined |= set(re.findall(r"^def (test_\w+)",
                                  path.read_text(encoding="utf-8"), re.M))
    missing = sorted(cited - defined)
    assert not missing, (
        f"CLAUDE.md's ambiguity list cites tests that do not exist: {missing}")


def test_the_contract_check_actually_resolves_fields():
    """Guard against the checks passing because the regex found nothing."""
    src = _src(JSX)
    assert len(_reads(src, "game")) > 15, "game.X reads not being found"
    assert len(_reads(src, "mySeat")) > 2, "mySeat.X reads not being found"
    assert "manual_treasures" in _reads(src, "catalog")
    assert "costs" in _reads(src, "game")     # the two fields the bugs added
