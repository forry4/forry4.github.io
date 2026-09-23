"""User / session / admin auth, shared by all site features.

All of this used to live in ``games/spender/main.py``; it is site-wide
infrastructure, not Spender-specific, so it lives in ``core`` and feature
packages import it directly (no more lazy imports to dodge a circular dep).

Identity model:
  * Accounts are rows in ``users``; each LOGIN is a row in ``user_sessions`` — one
    per signed-in device, so signing in on the laptop no longer signs the phone out.
    A session lasts SESSION_TTL from its LAST USE (sliding), not from the login.
    Tokens are stored as their SHA-256, never raw. ``users.session_token`` is the
    pre-2026-09-23 single-token column: still honoured once, then migrated.
  * ``admins`` is a durable role table. The SITE_OWNER env var (a username) is
    the bootstrap: that account is auto-granted admin on login, durable after.
``init_core_schema`` (in ``core.db``) owns the table definitions.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import string
import time

from .db import get_db_conn

LOG = logging.getLogger("core.auth")

_TOKEN_ALPHABET = string.ascii_letters + string.digits


def gen_token(n=32):
    # CSPRNG (secrets), not random.choices — these strings are session tokens,
    # account ids, reconnect tokens, AND password salts. random's Mersenne Twister
    # is predictable from observed output; secrets is not.
    return ''.join(secrets.choice(_TOKEN_ALPHABET) for _ in range(n))


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


# ─── Registration input validation ───────────────────────────────────────────
# Usernames: 1-16 chars, basic letters/digits only. Passwords: 1-16 chars. These
# are enforced at registration (the /auth/register route); login stays permissive
# so pre-existing accounts that predate these limits can still sign in.
USERNAME_MAX = 16
PASSWORD_MIN = 1
PASSWORD_MAX = 16
_USERNAME_RE = re.compile(r"[A-Za-z0-9]+")


def validate_credentials(name: str, password: str) -> str | None:
    """Return a human-readable error message if (name, password) is invalid for
    registration, or None if it's acceptable."""
    name = name or ""
    password = password or ""
    if len(name) < 1:
        return "Username is required."
    if len(name) > USERNAME_MAX:
        return f"Username must be {USERNAME_MAX} characters or fewer."
    if not _USERNAME_RE.fullmatch(name):
        return "Username may only contain letters and numbers."
    if len(password) < PASSWORD_MIN:
        return "Password is required."
    if len(password) > PASSWORD_MAX:
        return f"Password must be {PASSWORD_MAX} characters or fewer."
    return None


def create_user(name: str, password: str) -> dict | None:
    uid = gen_token(10)
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        # Enforce unique usernames explicitly, CASE-INSENSITIVELY ("Forrestm" == "forrestm").
        # The users.name column has no UNIQUE constraint (and on the libsql driver a constraint
        # violation isn't a sqlite3.IntegrityError anyway), so the old IntegrityError-only guard
        # never fired and duplicate names slipped through. Check before inserting; the matching
        # NOCASE unique index (init_core_schema) is the race backstop.
        cur.execute("SELECT 1 FROM users WHERE name = ? COLLATE NOCASE", (name,))
        if cur.fetchone() is not None:
            conn.close()
            return None  # name already taken
        cur.execute("INSERT INTO users (id,name,password_hash) VALUES (?,?,?)",
                    (uid, name, hash_password(password)))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - includes a UNIQUE-index race; treat as not-created
        LOG.error("create_user failed for %r: %s", name, e)
        conn.close()
        return None
    conn.close()
    return {"id": uid, "name": name}


def authenticate_user(name: str, password: str) -> dict | None:
    conn = get_db_conn()
    cur = conn.cursor()
    # Case-insensitive lookup so login matches registration ("Forrestm" logs in as "forrestm").
    cur.execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE", (name,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    stored = row["password_hash"]
    if not verify_password(stored, password):
        conn.close()
        return None
    token = gen_token(32)
    # Upgrade legacy (non-PBKDF2) hashes on successful login.
    if not (stored or "").startswith("pbkdf2$"):
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row["id"]))
    _add_session(conn, row["id"], token)
    conn.commit()
    # Bootstrap the admin role: the SITE_OWNER username is auto-granted admin on
    # login (durable thereafter via the admins table).
    if _name_is_owner(row["name"]):
        grant_admin(conn, row["id"])
    admin = is_admin_id(conn, row["id"])
    conn.close()
    return {"id": row["id"], "name": row["name"], "session_token": token, "is_admin": admin}


# ─── Sessions ─────────────────────────────────────────────────────────────────
# SLIDING: a session expires SESSION_TTL after it was last USED. It used to be a
# fixed 7 days from login, so someone on the site every day was still asked to sign
# in again every week. The expiry is pushed out at most once per SESSION_REFRESH,
# so an ordinary request costs one read, not a write.
SESSION_TTL = 90 * 24 * 3600
SESSION_REFRESH = 24 * 3600
MAX_SESSIONS_PER_USER = 20   # oldest (least recently used) beyond this are dropped


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _add_session(conn, user_id: str, token: str, now: int | None = None) -> None:
    now = int(time.time()) if now is None else now
    conn.execute(
        "INSERT OR REPLACE INTO user_sessions (token_hash, user_id, created_at, expires_at, last_used) "
        "VALUES (?, ?, ?, ?, ?)",
        (_token_hash(token), user_id, now, now + SESSION_TTL, now),
    )
    # Housekeeping rides on login (rare), never on the per-request read path.
    conn.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now,))
    cur = conn.cursor()
    cur.execute("SELECT token_hash FROM user_sessions WHERE user_id=? ORDER BY last_used DESC", (user_id,))
    for r in cur.fetchall()[MAX_SESSIONS_PER_USER:]:
        conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (r[0],))


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    conn = get_db_conn()
    cur = conn.cursor()
    now = int(time.time())
    th = _token_hash(token)
    # A plain JOIN — NOT a correlated subquery (those read NULL on the libsql driver).
    cur.execute(
        "SELECT u.id, u.name, s.last_used FROM user_sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>?",
        (th, now),
    )
    row = cur.fetchone()
    if row:
        if now - (row[2] or 0) >= SESSION_REFRESH:
            conn.execute("UPDATE user_sessions SET last_used=?, expires_at=? WHERE token_hash=?",
                         (now, now + SESSION_TTL, th))
            conn.commit()
    else:
        # A token minted before user_sessions existed lives in users.session_token.
        # Honour it once and move it over, so the deploy signs nobody out.
        cur.execute(
            "SELECT id, name FROM users WHERE session_token=? AND session_expiry>?",
            (token, now),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        _add_session(conn, row[0], token, now)
        conn.execute("UPDATE users SET session_token=NULL, session_expiry=NULL WHERE id=?", (row[0],))
        conn.commit()
    # is_admin = durable admins-table grant (via the SAME direct query the login path uses,
    # is_admin_id — NOT a correlated subquery, which read NULL on the prod libsql driver and so
    # reported any admin as non-admin on every session refresh) OR a live SITE_OWNER username
    # match (so the owner is recognized even if the login-time grant never ran). Mirrors is_site_owner.
    is_admin = is_admin_id(conn, row[0]) or _name_is_owner(row[1])
    conn.close()
    return {"id": row[0], "name": row[1], "is_admin": is_admin}


def end_session(token: str) -> None:
    """Sign THIS device out (the logout button). Other devices stay signed in."""
    if not token:
        return
    conn = get_db_conn()
    conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (_token_hash(token),))
    conn.execute("UPDATE users SET session_token=NULL, session_expiry=NULL WHERE session_token=?", (token,))
    conn.commit()
    conn.close()


# ─── Site owner / admin identity ──────────────────────────────────────────────
# Admin is a durable role stored in the `admins` table; the SITE_OWNER env var
# (a username) is the bootstrap that auto-grants admin on login. `is_site_owner`
# is the canonical "is this an admin" check used by features (books is the first
# consumer). SITE_OWNER is read at call time so an env change takes effect on the
# next restart with no code change.
def site_owner_name() -> str | None:
    v = os.environ.get("SITE_OWNER")
    return v.strip() if v and v.strip() else None


def _name_is_owner(name: str | None) -> bool:
    """SITE_OWNER match, CASE-INSENSITIVELY — usernames are unique NOCASE and login is NOCASE, so
    the owner bootstrap must compare the same way. A case-sensitive `==` meant `SITE_OWNER=forrestm`
    never matched a stored `Forrestm`, so the owner silently lost admin on every path."""
    owner = site_owner_name()
    return bool(owner and name and name.casefold() == owner.casefold())


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
    return _name_is_owner(user.get("name"))


# Reconnect tokens are short-lived (120s) and single-use, so used/expired rows are
# pure dead weight. Prune them opportunistically when new ones are minted, throttled
# to at most once per hour per process (the DELETE is idempotent, so races are fine).
_RT_CLEANUP_MIN_INTERVAL = 3600
_rt_last_cleanup = 0


def cleanup_reconnect_tokens() -> int:
    """Delete every used or expired reconnect token. Returns the number removed."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        now = int(time.time())
        cur.execute("SELECT COUNT(*) FROM reconnect_tokens WHERE used=1 OR expires_at < ?", (now,))
        n = cur.fetchone()[0]
        if n:
            cur.execute("DELETE FROM reconnect_tokens WHERE used=1 OR expires_at < ?", (now,))
            conn.commit()
            LOG.info("cleanup_reconnect_tokens: removed %d stale token(s)", n)
        return n
    finally:
        conn.close()


def maybe_cleanup_reconnect_tokens() -> int:
    """Throttled `cleanup_reconnect_tokens` — a no-op unless an hour has passed since
    this process last pruned. Never raises (cleanup must not break token minting)."""
    global _rt_last_cleanup
    now = int(time.time())
    if now - _rt_last_cleanup < _RT_CLEANUP_MIN_INTERVAL:
        return 0
    _rt_last_cleanup = now
    try:
        return cleanup_reconnect_tokens()
    except Exception as e:  # noqa: BLE001
        LOG.warning("maybe_cleanup_reconnect_tokens failed: %s", e)
        return 0


def create_reconnect_token(user_id: str, room_id: str, player_id: str, ttl: int = 120) -> str:
    maybe_cleanup_reconnect_tokens()  # throttled (<=1/h): prune used/expired rows
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
