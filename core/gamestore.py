"""One game's table: the persistence every game server shares.

Each game keeps a row per room in its own table — `id`, `status`, a few seat and
host columns that exist only to be QUERIED, and `state_json`, the room itself.
Twelve servers grew a copy each of the code around that table: the upsert on a
dedicated write thread, the state read, and the open / mine / active / history
lobby queries. They had the same shape and drifted in the details (the History
caps were 20/30/30/30 until `HISTORY_LIMIT`), so the plumbing lives here and a
game describes only what is really its own:

  * its table and how many seat columns it has;
  * which columns its UPDATE rewrites (a game builds the two column maps in its
    `_persist_row`, which stays in the game as the one place that says so);
  * its codec — `connect` and `decode` are CALLABLES, looked up when used, so
    the game's `_db` / `_decode_state` stay the seams its tests monkeypatch;
  * the shaping of each lobby row, which is a game's own vocabulary and is
    passed in as `shape(row, state)`.

The traps it keeps, all paid for once already:
  * writes go to ONE thread with ONE reused connection, in submission order, and
    a failed write drops the connection so the next one reconnects;
  * an existing row is found by SELECT, never by `cur.rowcount` (the libsql
    wrapper had none and the HTTP client has none);
  * every state read goes through the game's codec;
  * a lobby list never 500s on one unreadable row — `shape` gets `{}` for it;
  * `mine` excludes `status='over'`, `history` is capped at `HISTORY_LIMIT`.

`core/` imports no game; a game constructs its store at import.
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable

from core.rooms import HISTORY_LIMIT

LOG = logging.getLogger("gamestore")

Shape = Callable[[Any, dict], "dict | None"]


class GameStore:
    def __init__(self, table: str, *, seats: int, connect: Callable[[], Any],
                 decode: Callable[[Any], Any], label: str,
                 cleanup: Callable[[], None] | None = None) -> None:
        self.table = table
        self.label = label
        self.seat_ids = tuple(f"player{i}_id" for i in range(1, seats + 1))
        self._connect = connect
        self._decode = decode
        self._cleanup = cleanup
        # The write thread and its connection. Only that thread touches `_conn`.
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"{label}-db-write")
        self._conn = None

    # ── writes (on `executor` only) ─────────────────────────────────────────
    def reset_writer(self) -> None:
        """Forget the write connection, so the next write opens a fresh one
        (tests that point the database somewhere new call this)."""
        self._conn = None

    def upsert(self, room_id: str, *, update: dict, insert: dict) -> None:
        """Write one row: UPDATE the `update` columns if the row exists, else
        INSERT `insert`. Never raises — a save must not crash a room."""
        try:
            if self._conn is None:
                self._conn = self._connect()
            cur = self._conn.cursor()
            cur.execute(f"SELECT id FROM {self.table} WHERE id=?", (room_id,))
            if cur.fetchone() is not None:
                sets = ", ".join(f"{col}=?" for col in update)
                cur.execute(f"UPDATE {self.table} SET {sets} WHERE id=?",
                            (*update.values(), room_id))
            else:
                cols = ["id", *insert]
                cur.execute(f"INSERT INTO {self.table} ({','.join(cols)}) "
                            f"VALUES ({','.join('?' * len(cols))})",
                            (room_id, *insert.values()))
            self._conn.commit()
        except Exception:  # noqa: BLE001 - drop the (maybe stale) connection
            LOG.warning("%s save failed for %s; dropping the connection so the next "
                        "save reconnects", self.label, room_id, exc_info=True)
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None

    def remove(self, room_id: str) -> None:
        """DELETE one row ON THE WRITE THREAD, so it lands after every save that
        was submitted before it. Never raises."""
        try:
            if self._conn is None:
                self._conn = self._connect()
            cur = self._conn.cursor()
            cur.execute(f"DELETE FROM {self.table} WHERE id=?", (room_id,))
            self._conn.commit()
        except Exception:  # noqa: BLE001
            LOG.warning("%s delete failed for %s; dropping the connection", self.label,
                        room_id, exc_info=True)
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None

    @staticmethod
    def seat_columns(seats, first: int = 1) -> dict:
        """`[(pid, name), ...]` as `player{n}_id` / `player{n}_name` columns,
        numbered from `first`."""
        out = {}
        for n, (pid, name) in enumerate(seats, start=first):
            out[f"player{n}_id"] = pid
            out[f"player{n}_name"] = name
        return out

    # ── reads ────────────────────────────────────────────────────────────────
    def fetch(self, cols: str, where: str = "", params: tuple = (), *,
              order: str | None = None, limit: int | None = None) -> list:
        sql = f"SELECT {cols} FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit is not None:
            sql += " LIMIT ?"
            params = (*params, limit)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.close()

    def row(self, room_id: str, cols: str):
        rows = self.fetch(cols, "id=?", (room_id,))
        return rows[0] if rows else None

    def load_state(self, room_id: str):
        """The room's stored state through the game's codec, or None if there
        is no row, an empty blob, or one that will not decode."""
        row = self.row(room_id, "state_json")
        if not row or not row["state_json"]:
            return None
        try:
            return self._decode(row["state_json"])
        except Exception:
            LOG.warning("%s state for %s does not decode", self.label, room_id,
                        exc_info=True)
            return None

    def delete(self, room_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(f"DELETE FROM {self.table} WHERE id=?", (room_id,))
            conn.commit()
        finally:
            conn.close()

    def safe_state(self, blob) -> dict:
        """A stored blob as a dict, or `{}` — never a raise."""
        try:
            state = self._decode(blob)
        except Exception:
            return {}
        return state if isinstance(state, dict) else {}

    # ── the lobby lists ─────────────────────────────────────────────────────
    def _shaped(self, cols: str, rows, shape: Shape) -> list[dict]:
        has_state = "state_json" in cols
        out = []
        for r in rows:
            state = self.safe_state(r["state_json"]) if has_state else {}
            item = shape(r, state)
            if item is not None:
                out.append(item)
        return out

    def _seated(self, user_id: str) -> tuple[str, tuple]:
        where = " OR ".join(f"{col}=?" for col in self.seat_ids)
        return f"({where})", (user_id,) * len(self.seat_ids)

    def open_games(self, cols: str, shape: Shape, *, order: str = "updated_at DESC",
                   limit: int | None = 50) -> list[dict]:
        """Tables waiting for players. Runs the game's throttled retention sweep
        first, as every lobby did."""
        if self._cleanup is not None:
            self._cleanup()
        return self._shaped(cols, self.fetch(cols, "status='open'", order=order, limit=limit),
                            shape)

    def active_games(self, cols: str, shape: Shape, *, order: str = "updated_at DESC",
                     limit: int | None = 100) -> list[dict]:
        return self._shaped(cols, self.fetch(cols, "status='playing'", order=order,
                                             limit=limit), shape)

    def user_games(self, user_id: str, cols: str, shape: Shape, *,
                   order: str = "updated_at DESC", limit: int | None = None) -> list[dict]:
        """A player's unfinished games (any seat; never `status='over'`)."""
        seated, params = self._seated(user_id)
        return self._shaped(cols, self.fetch(cols, f"{seated} AND status != 'over'", params,
                                       order=order, limit=limit), shape)

    def user_history(self, user_id: str, cols: str, shape: Shape, *,
                     limit: int = HISTORY_LIMIT) -> list[dict]:
        """A player's finished games, newest first, at most `limit`."""
        seated, params = self._seated(user_id)
        return self._shaped(cols, self.fetch(cols, f"{seated} AND status='over'", params,
                                       order="updated_at DESC", limit=limit), shape)
