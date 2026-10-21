"""Tests for auth user/session persistence."""

import bcrypt
import pytest

import api.auth_store as auth_store
from api.auth_store import (
    create_session,
    ensure_auth_users_seeded,
    get_user_by_username,
    lookup_session,
    reset_auth_store_for_tests,
    revoke_session,
    verify_csrf,
    verify_password,
)


class _Cursor:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RecordingConn:
    def __init__(self, *, existing_user=False):
        self.calls = []
        self.existing_user = existing_user

    def execute(self, sql, params=None):
        params = tuple(params or ())
        self.calls.append((sql, params))
        if sql == "SELECT 1":
            return _Cursor([{"?column?": 1}])
        if "SELECT id, username, email FROM auth_users" in sql and self.existing_user:
            return _Cursor([{"id": "user-1", "username": "admin", "email": None}])
        if "SELECT * FROM auth_users WHERE id" in sql:
            return _Cursor([{"id": "user-1", "username": "admin", "email": None}])
        if "SELECT role FROM auth_user_roles" in sql:
            return _Cursor([{"role": "admin"}])
        return _Cursor()

    def commit(self):
        pass

    def close(self):
        pass


def test_seed_admin_user_from_env(monkeypatch):
    reset_auth_store_for_tests()
    monkeypatch.setenv("AUTH_PASSWORD_HASH", bcrypt.hashpw(b"secret", bcrypt.gensalt(12)).decode())
    monkeypatch.setenv("AUTH_DEFAULT_USERNAME", "admin")
    ensure_auth_users_seeded()
    user = get_user_by_username("admin")
    assert user is not None
    assert verify_password(user, "secret")
    assert "admin" in user.roles


def test_opaque_session_lifecycle(monkeypatch):
    reset_auth_store_for_tests()
    monkeypatch.setenv("AUTH_PASSWORD_HASH", bcrypt.hashpw(b"secret", bcrypt.gensalt(12)).decode())
    ensure_auth_users_seeded()
    user = get_user_by_username("admin")
    assert user is not None
    session = create_session(user)
    loaded = lookup_session(session.session_token)
    assert loaded is not None
    assert loaded.user.username == "admin"
    assert verify_csrf(session.session_token, session.csrf_token)
    revoke_session(session.session_token)
    assert lookup_session(session.session_token) is None


def test_auth_user_active_uses_boolean_parameters_for_postgres():
    for existing_user in (False, True):
        conn = _RecordingConn(existing_user=existing_user)
        auth_store._upsert_user(
            conn,
            username="admin",
            password_hash="hash",
            email=None,
            roles=("admin",),
        )

        active_user_writes = [
            params
            for sql, params in conn.calls
            if "auth_users" in sql and ("INSERT INTO" in sql or "UPDATE auth_users" in sql)
        ]
        assert active_user_writes
        assert any(any(param is True for param in params) for params in active_user_writes)
        assert all(not any(type(param) is int and param == 1 for param in params) for params in active_user_writes)
        assert all("active = 1" not in sql for sql, _params in conn.calls)


def test_auth_user_active_read_filters_use_boolean_parameters(monkeypatch):
    reset_auth_store_for_tests()
    conn = _RecordingConn()
    monkeypatch.setattr(auth_store, "_conn", conn)
    monkeypatch.setattr(auth_store, "_seeded", True)

    get_user_by_username("admin")
    auth_store.get_user_by_email("admin@example.com")
    lookup_session("session-token")

    active_reads = [params for sql, params in conn.calls if "active = ?" in sql or "u.active = ?" in sql]
    assert len(active_reads) == 3
    assert all(any(param is True for param in params) for params in active_reads)
    assert all("active = 1" not in sql for sql, _params in conn.calls)


@pytest.fixture
def stored_session(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD_HASH", "")
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD_HASH", raising=False)
    ensure_auth_users_seeded()
    with auth_store._get_conn() as conn:
        user = auth_store._upsert_user(
            conn, username="member", password_hash=None, email="Member@Example.com", roles=("analyst", "viewer")
        )
    return create_session(user)


@pytest.fixture
def auth_statements():
    statements = []
    with auth_store._get_conn() as conn:
        conn.set_trace_callback(
            lambda sql: statements.append(sql) if sql.lstrip().upper().startswith(("SELECT", "UPDATE")) else None
        )
    yield statements
    conn.set_trace_callback(None)


def test_session_cache_miss_is_one_query_and_hit_is_zero(stored_session, auth_statements):
    loaded = lookup_session(stored_session.session_token)
    assert loaded is not None and loaded.user == stored_session.user
    assert len(auth_statements) == 1
    auth_statements.clear()
    assert lookup_session(stored_session.session_token) == loaded
    assert auth_statements == []


def test_user_without_roles_can_authenticate(stored_session, auth_statements):
    with auth_store._get_conn() as conn:
        conn.execute("DELETE FROM auth_user_roles WHERE user_id = ?", (stored_session.user.id,))
        conn.commit()
    loaded = lookup_session(stored_session.session_token)
    assert loaded is not None and loaded.user.roles == ()
    assert len(auth_statements) == 1


def test_session_cache_ttl_does_not_slide_on_hits(stored_session, monkeypatch):
    from cachetools import TTLCache

    now = [0.0]
    monkeypatch.setattr(auth_store, "_session_cache", TTLCache(maxsize=4096, ttl=30, timer=lambda: now[0]))
    assert lookup_session(stored_session.session_token) is not None
    with auth_store._get_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE id = ?", (auth_store._now(), stored_session.session_id)
        )
        conn.commit()
    now[0] = 29
    assert lookup_session(stored_session.session_token) is not None
    now[0] = 31
    assert lookup_session(stored_session.session_token) is None


def test_cached_session_cannot_outlive_session_expiry(stored_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    current = datetime.now(UTC)
    with auth_store._get_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?",
            ((current + timedelta(seconds=5)).isoformat(), stored_session.session_id),
        )
        conn.commit()
    assert lookup_session(stored_session.session_token) is not None

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return current + timedelta(seconds=6)

    monkeypatch.setattr(auth_store, "datetime", Later)
    assert lookup_session(stored_session.session_token) is None


@pytest.mark.parametrize("change", ["revoke", "deactivate", "roles"])
def test_fresh_validation_observes_changes_despite_cached_identity(stored_session, change):
    assert lookup_session(stored_session.session_token) is not None
    with auth_store._get_conn() as conn:
        if change == "revoke":
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE id = ?", (auth_store._now(), stored_session.session_id)
            )
        elif change == "deactivate":
            conn.execute("UPDATE auth_users SET active = ? WHERE id = ?", (False, stored_session.user.id))
        else:
            conn.execute("DELETE FROM auth_user_roles WHERE user_id = ?", (stored_session.user.id,))
        conn.commit()
    fresh = auth_store.validate_session_csrf(stored_session.session_token, stored_session.csrf_token)
    if change == "roles":
        assert fresh is not None and fresh.user.roles == ()
    else:
        assert fresh is None
        assert lookup_session(stored_session.session_token) is None


def test_logout_invalidates_local_cache_and_inflight_reads(stored_session, monkeypatch):
    original_retry = auth_store.retry_read

    def revoke_after_read(operation):
        result = original_retry(operation)
        revoke_session(stored_session.session_token)
        return result

    monkeypatch.setattr(auth_store, "retry_read", revoke_after_read)
    lookup_session(stored_session.session_token)
    monkeypatch.setattr(auth_store, "retry_read", original_retry)
    assert lookup_session(stored_session.session_token) is None


def test_invalid_sessions_are_not_cached(stored_session, auth_statements):
    assert lookup_session("unknown-session") is None
    assert lookup_session("unknown-session") is None
    assert len(auth_statements) == 2


@pytest.mark.parametrize("roles", [("analyst", "viewer"), ()])
def test_refresh_rotates_csrf_and_returns_current_identity_in_one_statement(stored_session, auth_statements, roles):
    if not roles:
        with auth_store._get_conn() as conn:
            conn.execute("DELETE FROM auth_user_roles WHERE user_id = ?", (stored_session.user.id,))
            conn.commit()
    refreshed = auth_store.refresh_session_csrf(stored_session.session_token)
    assert len(auth_statements) == 1
    assert refreshed is not None
    assert refreshed.user.username == stored_session.user.username
    assert refreshed.user.roles == roles
    assert refreshed.csrf_token != stored_session.csrf_token
    assert not verify_csrf(stored_session.session_token, stored_session.csrf_token)
    assert verify_csrf(stored_session.session_token, refreshed.csrf_token)


@pytest.mark.parametrize("change", ["revoked_at", "expires_at", "active"])
def test_refresh_cannot_revive_invalid_sessions(stored_session, change):
    assert lookup_session(stored_session.session_token) is not None
    with auth_store._get_conn() as conn:
        if change == "active":
            conn.execute("UPDATE auth_users SET active = ? WHERE id = ?", (False, stored_session.user.id))
        else:
            value = auth_store._now() if change == "revoked_at" else "2000-01-01T00:00:00Z"
            conn.execute(f"UPDATE auth_sessions SET {change} = ? WHERE id = ?", (value, stored_session.session_id))
        conn.commit()
    assert auth_store.refresh_session_csrf(stored_session.session_token) is None
    assert lookup_session(stored_session.session_token) is None


def test_csrf_rotation_on_another_instance_ignores_cached_hash(stored_session):
    assert lookup_session(stored_session.session_token) is not None
    with auth_store._get_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET csrf_token_hash = ? WHERE id = ?",
            (auth_store._hash_secret("rotated-on-another-instance"), stored_session.session_id),
        )
        conn.commit()
    assert not verify_csrf(stored_session.session_token, stored_session.csrf_token)
    assert verify_csrf(stored_session.session_token, "rotated-on-another-instance")


def test_cloudflare_email_and_roles_are_loaded_in_one_query(stored_session, auth_statements):
    assert auth_store.get_user_by_email("  MEMBER@example.COM  ") == stored_session.user
    assert len(auth_statements) == 1


def test_email_lookup_does_not_merge_roles_of_case_colliding_users(stored_session):
    with auth_store._get_conn() as conn:
        other = auth_store._upsert_user(
            conn, username="different-member", password_hash=None, email="member@example.com", roles=("owner",)
        )
    user = auth_store.get_user_by_email("MEMBER@example.com")
    expected = {stored_session.user.id: stored_session.user, other.id: other}
    assert user is not None and user == expected[user.id]


def test_local_user_role_changes_invalidate_sessions(stored_session):
    assert lookup_session(stored_session.session_token).user.roles == ("analyst", "viewer")
    with auth_store._get_conn() as conn:
        auth_store._upsert_user(
            conn, username="member", password_hash=None, email="Member@Example.com", roles=("viewer",)
        )
    assert lookup_session(stored_session.session_token).user.roles == ("viewer",)
