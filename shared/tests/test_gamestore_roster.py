"""Every game server keeps its table through core.gamestore — none grows its own copy.

Twelve copies of the same write thread, state read and lobby queries drifted
apart until 2026-11 (the History caps were 20/30/30/30). The extraction is only
worth keeping if the thirteenth game does not bring a fourteenth copy, so this
reads each `games/*/main.py` and refuses the old shape: a write executor or
write connection of its own, or SQL against its game table outside the store.
The roster is the tree.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAINS = sorted((ROOT / "games").glob("*/main.py"))

# SQL that is not the persistence family, by (game, function). Schema creation in
# a game's own `*init_db` is always allowed.
SANCTIONED_SQL = {
    ("spender", "_db_ping"): "the SELECT 1 database health probe",
}


def _problems(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    out = []
    if not re.search(r"^STORE = GameStore\(", text, re.M):
        out.append("builds no `STORE = GameStore(...)`")
    if re.search(r"^_DB_WRITE_EXEC = (?!STORE\.executor$)", text, re.M):
        out.append("has a write executor of its own")
    if re.search(r"^_save_conn\b", text, re.M):
        out.append("keeps a write connection of its own")
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"):
            continue
        fn = next((f for f in ast.walk(tree)
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and f.lineno <= node.lineno <= f.end_lineno), None)
        name = fn.name if fn is not None else ""
        if name.endswith("init_db") or (path.parent.name, name) in SANCTIONED_SQL:
            continue                                  # schema work is the game's own
        out.append(f"line {node.lineno}: runs SQL outside core.gamestore")
    return out


def test_the_roster_is_the_whole_tree():
    assert len(MAINS) >= 12, [str(m) for m in MAINS]


def test_every_game_persists_through_the_shared_store():
    bad = {p.parent.name: probs for p in MAINS if (probs := _problems(p))}
    assert not bad, f"games with their own persistence code: {bad}"


def test_the_check_is_not_vacuous(tmp_path):
    old = tmp_path / "games" / "x" / "main.py"
    old.parent.mkdir(parents=True)
    old.write_text('''
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_save_conn = None

def x_init_db():
    conn.execute("CREATE TABLE x (id TEXT)")

def list_open_games():
    cur.execute("SELECT id FROM x WHERE status='open'")
''', encoding="utf-8")
    assert _problems(old) == ["builds no `STORE = GameStore(...)`",
                              "has a write executor of its own",
                              "keeps a write connection of its own",
                              "line 9: runs SQL outside core.gamestore"]
