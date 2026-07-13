"""Dual control (maker-checker) — the security property under test:

With two or more active admins, no sensitive change applies until a DIFFERENT
admin approves it. With fewer, changes apply immediately (bootstrap mode).
Runs against an in-memory SQLite database; audit writes are stubbed out.
"""
import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from backend.auth import hash_password
from backend.database import Base
from backend.models import PendingApproval, User
from backend.services import dual_control


# ─── Harness ─────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _add_admin(db, username: str, active: bool = True) -> User:
    user = User(username=username, email=f"{username}@bank.test",
                password_hash=hash_password("fixture-pass-A1"),
                role="admin", is_active=active)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _stub_audit(monkeypatch):
    """Audit writes use the app's real session factory; stub them in unit tests."""
    async def _noop(*args, **kwargs):
        return None
    from backend.routers import audit
    monkeypatch.setattr(audit, "record", _noop)


@pytest.fixture(autouse=True)
def _test_executor():
    """A trackable executor registered for a synthetic action."""
    calls: list[dict] = []

    async def _exec(db, payload, actor, request):
        calls.append({"payload": payload, "actor": actor})
        return {"done": True}

    dual_control.EXECUTORS["TEST_ACTION"] = _exec
    yield calls
    dual_control.EXECUTORS.pop("TEST_ACTION", None)


# ─── dual_control_active ─────────────────────────────────────────────────────

def test_dual_control_inactive_with_one_admin(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            await _add_admin(db, "alice")
            assert not await dual_control.dual_control_active(db)
    run(scenario())


def test_dual_control_active_with_two_admins(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            await _add_admin(db, "alice")
            await _add_admin(db, "bob")
            assert await dual_control.dual_control_active(db)
    run(scenario())


def test_disabled_admin_does_not_count(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            await _add_admin(db, "alice")
            await _add_admin(db, "bob", active=False)
            assert not await dual_control.dual_control_active(db)
    run(scenario())


# ─── submit_or_execute ───────────────────────────────────────────────────────

def test_single_admin_executes_immediately(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            result = await dual_control.submit_or_execute(
                db, None, alice, "TEST_ACTION", {"x": 1}, "test change")
            assert result["pending"] is False
            assert result["done"] is True
            assert len(_test_executor) == 1
            assert _test_executor[0]["actor"] == "alice"
    run(scenario())


def test_two_admins_queues_instead_of_executing(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            await _add_admin(db, "bob")
            result = await dual_control.submit_or_execute(
                db, None, alice, "TEST_ACTION", {"x": 1}, "test change", target="t")
            assert result["pending"] is True
            assert _test_executor == []          # NOT executed
            approval = (await db.execute(select(PendingApproval))).scalar_one()
            assert approval.status == "pending"
            assert approval.requested_by == "alice"
            assert json.loads(approval.payload) == {"x": 1}
    run(scenario())


def test_approval_executes_and_records_checker(_test_executor):
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            bob = await _add_admin(db, "bob")
            await dual_control.submit_or_execute(
                db, None, alice, "TEST_ACTION", {"x": 2}, "test change")
            approval = (await db.execute(select(PendingApproval))).scalar_one()

            result = await dual_control.execute_approval(db, None, bob, approval)
            assert result["done"] is True
            assert _test_executor[0]["actor"] == "bob"   # executed under the checker
            assert approval.status == "approved"
            assert approval.decided_by == "bob"
    run(scenario())


# ─── User-management executors (auth_routes) ────────────────────────────────

def test_create_user_executor_creates_account():
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            await _add_admin(db, "alice")
            from backend.routers.auth_routes import _exec_create_user
            result = await _exec_create_user(
                db, {"email": "carol@bank.test", "full_name": "Carol", "role": "analyst"},
                "alice", None)
            assert result["username"] == "carol@bank.test"
            assert result["role"] == "analyst"
            assert result["temp_password"]        # no SMTP in tests → shown once
            carol = (await db.execute(
                select(User).where(User.username == "carol@bank.test"))).scalar_one()
            assert carol.is_active
    run(scenario())


def test_cannot_disable_last_active_admin():
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            from backend.routers.auth_routes import _exec_toggle_active
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as e:
                await _exec_toggle_active(db, {"user_id": alice.id}, "alice", None)
            assert e.value.status_code == 400
    run(scenario())


def test_cannot_demote_last_active_admin():
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            from backend.routers.auth_routes import _exec_set_role
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as e:
                await _exec_set_role(db, {"user_id": alice.id, "role": "viewer"}, "alice", None)
            assert e.value.status_code == 400
    run(scenario())


def test_demote_allowed_when_second_admin_exists():
    async def scenario():
        _, S = await _make_db()
        async with S() as db:
            alice = await _add_admin(db, "alice")
            await _add_admin(db, "bob")
            from backend.routers.auth_routes import _exec_set_role
            result = await _exec_set_role(db, {"user_id": alice.id, "role": "viewer"}, "bob", None)
            assert result["role"] == "viewer"
    run(scenario())
