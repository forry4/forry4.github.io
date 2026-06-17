"""User / session / admin auth, shared by all site features.

All of this used to live in ``games/spender/main.py``; it is site-wide
infrastructure, not Spender-specific, so it lives in ``core`` and feature
packages import it directly (no more lazy imports to dodge a circular dep).

Identity model:
  * Accounts + sessions are rows in the ``users`` table; a login mints a 7-day
    session token (one per user — a new login supersedes the old token).
  * ``admins`` is a durable role table. The SITE_OWNER env var (a username) is
    the bootstrap: that account is auto-granted admin on login, durable after.
``init_core_schema`` (in ``core.db``) owns the table definitions.
"""
import hashlib
import hmac
import logging
import os
import random
import sqlite3
import string
import time

from .db import get_db_conn

LOG = logging.getLogger("core.auth")


def gen_token(n=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


# Password hashing: PBKDF2-HMAC-SHA256 (stdlib) stored as "pbkdf2$<iters>$<salt>$<hex>".
# verify_password also accepts the legacy "<salt>$<sha256hex>" format and the caller
# transparently upgrades those to PBKDF2 on the next successful login.
PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    salt = gen_token(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERS).hex()
    return f"pbkdf2${PBKDF2_ITERS}${salt}${h}"


def verify_password(stored: str, password: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2":
        try:
            calc = hashlib.pbkdf2_hmac("sha256", password.encode(), parts[2].encode(), int(parts[1])).hex()
        except ValueError:
            return False
        return hmac.compare_digest(calc, parts[3])
    if len(parts) == 2:  # legacy salt$sha256
        salt, h = parts
        return hmac.compare_digest(hashlib.sha256((salt + password).encode()).hexdigest(), h)
    return False


def create_user(name: str, password: str) -> dict | None:
    uid = gen_token(10)
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (id,name,password_hash) VALUES (?,?,?)",
                    (uid, name, hash_password(password)))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return None  # name already taken
    except Exception as e:  # noqa: BLE001 - don't 500 the endpoint; surface in logs
        LOG.error("create_user failed for %r: %s", name, e)
        conn.close()
        return None
    conn.close()
    return {"id": uid, "name": name}


def authenticate_user(name: str, password: str) -> dict | None:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = ?", (name,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    stored = row["password_hash"]
    if not verify_password(stored, password):
        conn.close()
        return None
    token = gen_token(32)
    expiry = int(time.time()) + 7 * 24 * 3600
    # Upgrade legacy (non-PBKDF2) hashes on successful login.
    if not (stored or "").startswith("pbkdf2$"):
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row["id"]))
    cur.execute("UPDATE users SET session_token=?, session_expiry=? WHERE id=?", (token, expiry, row["id"]))
    conn.commit()
    # Bootstrap the admin role: the SITE_OWNER username is auto-granted admin on
    # login (durable thereafter via the admins table).
    owner = site_owner_name()
    if owner and row["name"] == owner:
        grant_admin(conn, row["id"])
    admin = is_admin_id(conn, row["id"])
    conn.close()
    return {"id": row["id"], "name": row["name"], "session_token": token, "is_admin": admin}


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    conn = get_db_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "SELECT id, name FROM users WHERE session_token=? AND session_expiry>?",
        (token, now),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    # is_admin = durable admins-table grant (via the SAME direct query the login path uses,
    # is_admin_id — NOT a correlated subquery, which read NULL on the prod libsql driver and so
    # reported any admin as non-admin on every session refresh) OR a live SITE_OWNER username
    # match (so the owner is recognized even if the login-time grant never ran). Mirrors is_site_owner.
    owner = site_owner_name()
    is_admin = is_admin_id(conn, row[0]) or (owner is not None and row[1] == owner)
    conn.close()
    return {"id": row[0], "name": row[1], "is_admin": is_admin}


# ─── Site owner / admin identity ──────────────────────────────────────────────
# Admin is a durable role stored in the `admins` table; the SITE_OWNER env var
# (a username) is the bootstrap that auto-grants admin on login. `is_site_owner`
# is the canonical "is this an admin" check used by features (books is the first
# consumer). SITE_OWNER is read at call time so an env change takes effect on the
# next restart with no code change.
def site_owner_name() -> str | None:
    v = os.environ.get("SITE_OWNER")
    return v.strip() if v and v.strip() else None


def grant_admin(conn, user_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO admins (user_id, granted_at) VALUES (?, ?)",
                 (user_id, int(time.time())))
    conn.commit()


def is_admin_id(conn, user_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cur.fetchone() is not None


def is_site_owner(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    owner = site_owner_name()
    return bool(owner and user.get("name") == owner)


def create_reconnect_token(user_id: str, room_id: str, player_id: str, ttl: int = 120) -> str:
    token = gen_token(12)
    expires_at = int(time.time()) + ttl
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO reconnect_tokens (token,user_id,room_id,player_id,expires_at,used) VALUES (?,?,?,?,?,0)",
                (token, user_id, room_id, player_id, expires_at))
    conn.commit()
    conn.close()
    return token


def validate_reconnect_token(token: str) -> dict | None:
    conn = get_db_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT * FROM reconnect_tokens WHERE token=? AND expires_at>? AND used=0", (token, now))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"token": row["token"], "user_id": row["user_id"], "room_id": row["room_id"], "player_id": row["player_id"]}


def mark_reconnect_token_used(token: str):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE reconnect_tokens SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()
