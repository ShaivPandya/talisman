"""First-party users, roles, and opaque server-side auth sessions."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
from cachetools import TTLCache

from api.postgres import retry_read, use_postgres_state
from api.postgres_state import PostgresStateConnection

DB_PATH = Path(__file__).parent / "auth.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None  # SQLite fallback only; Postgres is always scoped.
_seeded = False
_session_cache_lock = threading.RLock()
_session_cache: TTLCache[str, _ValidatedSession] = TTLCache(maxsize=4096, ttl=30)
_session_cache_generation = 0

_CREATE_AUTH_USERS = """
CREATE TABLE IF NOT EXISTS auth_users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    email         TEXT UNIQUE,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""

_CREATE_AUTH_USER_ROLES = """
CREATE TABLE IF NOT EXISTS auth_user_roles (
    user_id TEXT NOT NULL,
    role    TEXT NOT NULL,
    PRIMARY KEY (user_id, role),
    FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
)
"""

_CREATE_AUTH_SESSIONS = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    id               TEXT PRIMARY KEY,
    token_hash       TEXT NOT NULL UNIQUE,
    user_id          TEXT NOT NULL,
    csrf_token_hash  TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    revoked_at       TEXT,
    created_at       TEXT NOT NULL,
    user_agent       TEXT,
    ip_address       TEXT,
    FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
)
"""


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    roles: tuple[str, ...]
    email: str | None = None


@dataclass(frozen=True)
class AuthSession:
    session_id: str
    user: AuthUser
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class _ValidatedSession:
    session: AuthSession
    csrf_token_hash: str


def _invalidate_session_cache(session_token: str | None = None) -> None:
    global _session_cache_generation
    with _session_cache_lock:
        # Prevent a read started before a revocation/rotation from refilling the cache.
        _session_cache_generation += 1
        if session_token is None:
            _session_cache.clear()
        else:
            _session_cache.pop(_hash_secret(session_token), None)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _session_ttl_hours() -> int:
    raw = (os.environ.get("SESSION_TTL_HOURS") or os.environ.get("JWT_TTL_HOURS") or "12").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 12


def default_admin_username() -> str:
    return (os.environ.get("AUTH_DEFAULT_USERNAME") or "admin").strip() or "admin"


def _close_conn() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def reset_auth_store_for_tests() -> None:
    """Clear in-memory connection and re-seed on next access. Tests only."""
    global _conn, _seeded
    with _lock:
        _close_conn()
        _seeded = False
        _invalidate_session_cache()
        if not use_postgres_state() and DB_PATH.exists():
            DB_PATH.unlink(missing_ok=True)


@contextmanager
def _get_conn(*, read_only: bool = False) -> Iterator[sqlite3.Connection | PostgresStateConnection]:
    global _conn
    if use_postgres_state():
        with PostgresStateConnection(read_only=read_only) as conn:
            yield conn
        return
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _init_db(_conn)
        try:
            yield _conn
        except BaseException:
            _conn.rollback()
            raise


def _init_db(conn: sqlite3.Connection | PostgresStateConnection) -> None:
    conn.execute(_CREATE_AUTH_USERS)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_auth_users_email_lower ON auth_users (lower(email))")
    conn.execute(_CREATE_AUTH_USER_ROLES)
    conn.execute(_CREATE_AUTH_SESSIONS)
    conn.commit()


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _roles_for_user(conn: sqlite3.Connection | PostgresStateConnection, user_id: str) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT role FROM auth_user_roles WHERE user_id = ? ORDER BY role",
        (user_id,),
    ).fetchall()
    return tuple(str(r["role"] if isinstance(r, dict) else r[0]) for r in rows)


def _user_from_row(conn: sqlite3.Connection | PostgresStateConnection, row: Any) -> AuthUser | None:
    data = _row_dict(row)
    if not data:
        return None
    user_id = str(data["id"])
    return AuthUser(
        id=user_id,
        username=str(data["username"]),
        email=str(data["email"]) if data.get("email") else None,
        roles=_roles_for_user(conn, user_id),
    )


def _upsert_user(
    conn: sqlite3.Connection | PostgresStateConnection,
    *,
    username: str,
    password_hash: str | None,
    email: str | None,
    roles: tuple[str, ...],
) -> AuthUser:
    now = _now()
    existing = conn.execute(
        "SELECT id, username, email FROM auth_users WHERE username = ?",
        (username,),
    ).fetchone()
    if existing:
        user_id = str(_row_dict(existing)["id"])
        conn.execute(
            "UPDATE auth_users SET password_hash = ?, email = ?, active = ?, updated_at = ? WHERE id = ?",
            (password_hash, email, True, now, user_id),
        )
    else:
        user_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO auth_users (id, username, password_hash, email, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, password_hash, email, True, now, now),
        )
    conn.execute("DELETE FROM auth_user_roles WHERE user_id = ?", (user_id,))
    for role in roles:
        conn.execute(
            "INSERT INTO auth_user_roles (user_id, role) VALUES (?, ?)",
            (user_id, role),
        )
    conn.commit()
    _invalidate_session_cache()
    row = conn.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
    user = _user_from_row(conn, row)
    assert user is not None
    return user


def ensure_auth_users_seeded() -> None:
    """Seed admin and optional smoke users from env password hashes."""
    global _seeded
    with _lock:
        if _seeded:
            return
        with _get_conn() as conn:
            admin_hash = (os.environ.get("AUTH_PASSWORD_HASH") or "").strip()
            if admin_hash:
                _upsert_user(
                    conn,
                    username=default_admin_username(),
                    password_hash=admin_hash,
                    email=None,
                    roles=("owner", "admin"),
                )
            smoke_hash = (os.environ.get("AUTH_SMOKE_PASSWORD_HASH") or "").strip()
            if smoke_hash:
                _upsert_user(
                    conn,
                    username="smoke",
                    password_hash=smoke_hash,
                    email=None,
                    roles=("smoke", "viewer"),
                )
        _seeded = True


def get_user_by_username(username: str) -> AuthUser | None:
    ensure_auth_users_seeded()

    def _read() -> AuthUser | None:
        with _get_conn(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE username = ? AND active = ?",
                (username.strip(), True),
            ).fetchone()
            return _user_from_row(conn, row)

    return retry_read(_read)


def get_user_by_email(email: str) -> AuthUser | None:
    ensure_auth_users_seeded()

    def _read() -> AuthUser | None:
        with _get_conn(read_only=True) as conn:
            normalized = email.strip().lower()
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.email, r.role
                FROM (
                    SELECT id, username, email FROM auth_users
                    WHERE lower(email) = ? AND active = ? LIMIT 1
                ) u
                LEFT JOIN auth_user_roles r ON r.user_id = u.id
                ORDER BY r.role
                """,
                (normalized, True),
            ).fetchall()
            if not rows:
                return None
            data = _row_dict(rows[0])
            return AuthUser(
                id=str(data["id"]),
                username=str(data["username"]),
                email=str(data["email"]) if data.get("email") else None,
                roles=tuple(str(row["role"]) for row in rows if row["role"] is not None),
            )

    return retry_read(_read)


def get_or_create_cloudflare_user(email: str) -> AuthUser:
    """Map Cloudflare Access identity to a first-party user."""
    ensure_auth_users_seeded()
    normalized_email = email.strip().lower()
    existing = get_user_by_email(normalized_email)
    if existing:
        return existing
    username = normalized_email.split("@", 1)[0] or normalized_email
    base_username = username
    suffix = 0
    while get_user_by_username(username):
        suffix += 1
        username = f"{base_username}-{suffix}"
    default_roles = tuple(
        r.strip() for r in (os.environ.get("AUTH_CLOUDFLARE_DEFAULT_ROLES") or "admin,viewer").split(",") if r.strip()
    ) or ("admin", "viewer")
    with _get_conn() as conn:
        return _upsert_user(
            conn,
            username=username,
            password_hash=None,
            email=normalized_email,
            roles=default_roles,
        )


def verify_password(user: AuthUser, password: str) -> bool:
    ensure_auth_users_seeded()

    def _read():
        with _get_conn(read_only=True) as conn:
            row = conn.execute("SELECT password_hash FROM auth_users WHERE id = ?", (user.id,)).fetchone()
        return row

    row = retry_read(_read)
    if not row:
        return False
    stored = _row_dict(row).get("password_hash")
    if not stored:
        return False
    return bcrypt.checkpw(password.encode(), str(stored).encode())


def create_session(
    user: AuthUser,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> AuthSession:
    ensure_auth_users_seeded()
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(hours=_session_ttl_hours())
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (
                id, token_hash, user_id, csrf_token_hash, expires_at, revoked_at,
                created_at, user_agent, ip_address
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                session_id,
                _hash_secret(session_token),
                user.id,
                _hash_secret(csrf_token),
                expires_at.isoformat(),
                _now(),
                user_agent,
                ip_address,
            ),
        )
        conn.commit()
        return AuthSession(
            session_id=session_id,
            user=user,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )


def _lookup_validated_session(session_token: str, *, use_cache: bool = True) -> _ValidatedSession | None:
    if not session_token:
        return None
    ensure_auth_users_seeded()
    token_hash = _hash_secret(session_token)
    with _session_cache_lock:
        generation = _session_cache_generation
        cached = _session_cache.get(token_hash) if use_cache else None
        if cached is not None:
            if cached.session.expires_at > datetime.now(UTC):
                return cached
            _session_cache.pop(token_hash, None)

    def _read() -> _ValidatedSession | None:
        with _get_conn(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.user_id, s.csrf_token_hash, s.expires_at, s.revoked_at,
                       u.username, u.email, r.role
                FROM auth_sessions s
                JOIN auth_users u ON u.id = s.user_id
                LEFT JOIN auth_user_roles r ON r.user_id = u.id
                WHERE s.token_hash = ? AND u.active = ?
                ORDER BY r.role
                """,
                (token_hash, True),
            ).fetchall()
            if not rows:
                return None
            data = _row_dict(rows[0])
            if data.get("revoked_at"):
                return None
            expires_at = _parse_iso(str(data["expires_at"]))
            if expires_at <= datetime.now(UTC):
                return None
            user_id = str(data["user_id"])
            user = AuthUser(
                id=user_id,
                username=str(data["username"]),
                email=str(data["email"]) if data.get("email") else None,
                roles=tuple(str(row["role"]) for row in rows if row["role"] is not None),
            )
            return _ValidatedSession(
                session=AuthSession(
                    session_id=str(data["id"]),
                    user=user,
                    session_token=session_token,
                    csrf_token="",
                    expires_at=expires_at,
                ),
                csrf_token_hash=str(data["csrf_token_hash"]),
            )

    validated = retry_read(_read)
    with _session_cache_lock:
        if generation == _session_cache_generation:
            if validated is not None:
                _session_cache[token_hash] = validated
            else:
                _session_cache.pop(token_hash, None)
    return validated


def lookup_session(session_token: str, *, use_cache: bool = True) -> AuthSession | None:
    validated = _lookup_validated_session(session_token, use_cache=use_cache)
    return validated.session if validated is not None else None


def verify_csrf(session_token: str, csrf_token: str | None) -> bool:
    return validate_session_csrf(session_token, csrf_token) is not None


def validate_session_csrf(session_token: str, csrf_token: str | None) -> AuthSession | None:
    """Validate mutations against current state, returning identity for request reuse."""
    if not session_token or not csrf_token:
        return None
    validated = _lookup_validated_session(session_token, use_cache=False)
    if validated is None or not secrets.compare_digest(_hash_secret(csrf_token), validated.csrf_token_hash):
        return None
    return validated.session


def get_csrf_token_for_session(session_token: str) -> str | None:
    """Return a fresh CSRF token by rotating the stored hash (used on /me)."""
    session = refresh_session_csrf(session_token)
    return session.csrf_token if session is not None else None


def refresh_session_csrf(session_token: str) -> AuthSession | None:
    """Refresh CSRF and retrieve current identity in one statement, bypassing cache."""
    if not session_token:
        return None
    ensure_auth_users_seeded()
    csrf_token = secrets.token_urlsafe(32)
    roles_aggregate = "json_agg(role)" if use_postgres_state() else "json_group_array(role)"
    expiry_check = (
        "expires_at::timestamptz > ?::timestamptz" if use_postgres_state() else "julianday(expires_at) > julianday(?)"
    )
    with _get_conn() as conn:
        row = conn.execute(
            f"""
            UPDATE auth_sessions SET csrf_token_hash = ?
            WHERE token_hash = ? AND revoked_at IS NULL AND {expiry_check}
              AND EXISTS (SELECT 1 FROM auth_users WHERE id = auth_sessions.user_id AND active = ?)
            RETURNING id, user_id, expires_at,
                (SELECT username FROM auth_users WHERE id = auth_sessions.user_id) AS username,
                (SELECT email FROM auth_users WHERE id = auth_sessions.user_id) AS email,
                (SELECT {roles_aggregate} FROM auth_user_roles WHERE user_id = auth_sessions.user_id) AS roles_json
            """,
            (_hash_secret(csrf_token), _hash_secret(session_token), _now(), True),
        ).fetchone()
        conn.commit()
    _invalidate_session_cache(session_token)
    if row is None:
        return None
    data = _row_dict(row)
    roles = data.get("roles_json") or []
    if isinstance(roles, str):
        roles = json.loads(roles)
    return AuthSession(
        session_id=str(data["id"]),
        user=AuthUser(
            id=str(data["user_id"]),
            username=str(data["username"]),
            email=str(data["email"]) if data.get("email") else None,
            roles=tuple(sorted(roles)),
        ),
        session_token=session_token,
        csrf_token=csrf_token,
        expires_at=_parse_iso(str(data["expires_at"])),
    )


def revoke_session(session_token: str) -> None:
    if not session_token:
        return
    with _get_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_now(), _hash_secret(session_token)),
        )
        conn.commit()
    _invalidate_session_cache(session_token)


def user_has_role(user: AuthUser, role: str) -> bool:
    return role in user.roles or "admin" in user.roles or "owner" in user.roles
