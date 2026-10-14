"""Cash routing, explicit party linkage, and independently approved exemptions."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from backend.models import CashActivity, CtrExemption, PendingApproval, User
from backend.routers import ctr_exemptions as E
from backend.routers.insights import _replay
from backend.services import analyzer as A, cash_history, processing as P, dual_control
from test_processing import store, txn, NOW  # noqa: F401


def exemption(**changes):
    return {"id": "exemption-1", "subject_id": "PERSON", "account_ids": ["A", "B"],
        "status": "ACTIVE", "approved_by": "checker", "exemption_type": "NONLISTED_BUSINESS",
        "effective_from": "2026-01-01", "expires_on": "2026-12-31", "review_due": "2026-12-31", **changes}


def test_six_routing_scenarios(store):
    cash = A.evaluate(txn(amount="12000", direction="INWARD"), [])
    assert cash["ctr"].required and cash["risk"].score >= 0
    wire = A.evaluate(txn(amount="50000", is_cash=False), [])
    assert not wire["ctr"].required and wire["risk"].score > 0
    first = txn(id="branch-one", amount="6000", account_holder_id="PERSON", branch_id="NORTH")
    second = replace(first, id="branch-two", account_id="B", branch_id="SOUTH", timestamp=NOW + timedelta(hours=1))
    split = A.evaluate(second, [first])
    assert split["ctr"].required and split["ctr"].trigger == "SAME_DAY_AGGREGATE"
    assert "cross_branch_structuring" in split["risk"].components
    assert split["profile"].transaction_count == 0
    assert split["sar_recommended"]
    small_history = [txn(id=f"small-{i}", amount="100", is_cash=False, timestamp=NOW - timedelta(days=i + 2)) for i in range(4)]
    unusual = A.evaluate(txn(amount="4000", is_cash=False), small_history)
    assert not unusual["ctr"].required and unusual["is_fraudulent"]
    assert not unusual["sar_recommended"]  # Suspicion below $5k can alert without a mandatory SAR claim.
    routine_history = [replace(item, amount="100000") for item in small_history]
    routine = A.evaluate(txn(amount="100000", is_cash=False), routine_history)
    assert routine["risk"].level == "LOW" and not routine["is_fraudulent"]
    assert not routine["ctr"].required and not routine["sar_recommended"]
    exempt = txn(amount="15000", account_holder_id="PERSON", acting_as_agent=False)
    regular = A.evaluate(exempt, [])
    assessed = A.evaluate(exempt, [], [exemption()])
    assert not assessed["ctr"].required and assessed["ctr"].trigger == "EXEMPT"
    assert assessed["risk"] == regular["risk"]
    assert assessed["sar_recommended"] == regular["sar_recommended"]


@pytest.mark.parametrize("changes", [
    {"account_holder_id": "OTHER"}, {"account_id": "UNCOVERED"},
    {"acting_as_agent": None}, {"acting_as_agent": True},
])
def test_exemption_never_applies_outside_transaction_scope(changes):
    item = txn(amount="15000", account_holder_id="PERSON", acting_as_agent=False)
    assert A.evaluate(replace(item, **changes), [], [exemption()])["ctr"].required


@pytest.mark.parametrize("changes", [
    {"status": "REVOKED"}, {"approved_by": None}, {"effective_from": "2026-11-01"},
    {"expires_on": "2026-10-05"}, {"review_due": "2026-10-05"},
])
def test_invalid_exemption_does_not_suppress_ctr(changes):
    item = txn(amount="15000", account_holder_id="PERSON", acting_as_agent=False)
    assert A.evaluate(item, [], [exemption(**changes)])["ctr"].required


def test_payroll_only_covers_payroll_withdrawals():
    item = txn(amount="15000", account_holder_id="PERSON", acting_as_agent=False, cash_purpose="PAYROLL")
    records = [exemption(exemption_type="PAYROLL_CUSTOMER")]
    assert not A.evaluate(item, [], records)["ctr"].required
    assert A.evaluate(replace(item, direction="INWARD"), [], records)["ctr"].required
    assert A.evaluate(replace(item, cash_purpose="OTHER"), [], records)["ctr"].required


def test_cash_groups_do_not_union_unrelated_people_or_guess_names():
    current = txn(id="current", amount="4000", account_id="A", account_holder_id="H1", conductor_id="C1")
    owner_link = replace(current, id="owner", account_id="B", conductor_id="C2")
    conductor_link = replace(current, id="conductor", account_id="C", account_holder_id="H2")
    result = A.evaluate(current, [owner_link, conductor_link])
    assert not result["ctr"].required  # H1=8k, C1=8k, not one invented 12k person.
    unrelated = replace(current, id="unrelated", account_id="D", account_holder_id="H3", conductor_id="C3", amount="20000")
    assert not A.evaluate(current, [unrelated])["ctr"].required
    assert not A.evaluate(replace(current, account_holder_id=None, conductor_id=None), [unrelated])["ctr"].required


@pytest.mark.parametrize("changes", [
    {"direction": "INWARD"}, {"currency": "EUR"},
    {"business_date": "2026-10-05"}, {"is_cash": False},
    {"timestamp": NOW + timedelta(hours=1)},
])
def test_cash_totals_exclude_other_direction_day_currency_and_future(changes):
    current = txn(account_holder_id="PERSON", amount="6000")
    previous = replace(current, id="previous", account_id="B", **changes)
    assert not A.evaluate(current, [previous])["ctr"].required


def test_cash_boundary_dedup_and_replay():
    first = txn(id="one", account_holder_id="PERSON", amount="5000", branch_id="NORTH")
    second = replace(first, id="two", account_id="B", branch_id="SOUTH", timestamp=NOW + timedelta(minutes=1))
    assert not A.evaluate(second, [first, first])["ctr"].required
    second = replace(second, amount="5000.01")
    replay = _replay([first, second])
    assert replay["ctr_required"] == 1
    assert replay["verdicts"][1] == A.evaluate(second, [first])


def test_aggregation_preserves_excluded_exemption_evidence():
    first = txn(id="exempt", account_holder_id="PERSON", amount="15000", acting_as_agent=False)
    current = replace(first, id="not-exempt", account_id="B", amount="6000", acting_as_agent=True)
    result = A.evaluate(current, [first], [exemption()])
    assert not result["ctr"].required
    holder = next(group for group in result["ctr"].details["groups"] if group["basis"] == "account_holder")
    assert holder["gross_total"] == "21000" and holder["reportable_total"] == "6000"
    exempt_item = next(item for item in holder["transactions"] if item["transaction_id"] == "exempt")
    assert not exempt_item["reportable"]
    assert exempt_item["exemption_id"] == "exemption-1" and exempt_item["approved_by"] == "checker"


def test_concurrent_cross_account_sources_and_backfill(store):
    async def run():
        items = [txn(id=f"cash-{i}", account_id=f"A{i}", source_table=f"feed-{i}",
            account_holder_id="PERSON", branch_id=f"BR{i}", amount="6000") for i in range(2)]
        results = await asyncio.gather(*(P.process(item) for item in items))
        assert sum(result["ctr_required"] for result in results) == 1
        assert sum(result["structuring_alert"] for result in results) == 1
        assert (await P.process(items[0]))["duplicate"]
        async with store() as db:
            assert (await db.scalar(select(func.count()).select_from(CashActivity))) == 2
            await db.execute(delete(CashActivity)); await db.commit()
            await cash_history.backfill(db)
            await cash_history.backfill(db)
            assert (await db.scalar(select(func.count()).select_from(CashActivity))) == 2
        late = await P.process(replace(items[0], id="late", account_id="LATE", timestamp=NOW - timedelta(minutes=1)))
        assert late["assessment"]["late_arrival"]
        assert late["assessment"]["regulatory_status"] == "MANUAL_REVIEW"
        assert not late["ctr_required"]
    asyncio.run(run())


def proposal():
    today = datetime.now(timezone.utc).date()
    return E.ExemptionIn(subject_id="PERSON", subject_name="Example business", exemption_type="NONLISTED_BUSINESS",
        account_ids=["A", "B"], effective_from=today - timedelta(days=20), expires_on=today + timedelta(days=90),
        reviewed_on=today - timedelta(days=20), review_due=today + timedelta(days=90),
        eligibility_basis="Institution verified the applicable eligibility requirements.",
        evidence_reference="KYC-123", designation_reference="DOEP-123", eligibility_verified=True)


def test_exemption_requires_evidence_and_valid_dates():
    values = proposal().model_dump()
    for changes in ({"eligibility_verified": False}, {"designation_reference": None}, {"account_ids": [" "]},
                    {"review_due": values["reviewed_on"] + timedelta(days=366)}):
        with pytest.raises(ValidationError):
            E.ExemptionIn.model_validate({**values, **changes})


def test_exemption_approval_processing_revocation_and_immutable_history(store, monkeypatch):
    async def noop(*args, **kwargs):
        pass
    from backend.routers import audit
    monkeypatch.setattr(audit, "record", noop)
    async def run():
        maker = User(username="maker", password_hash="unused", role="admin", is_active=True)
        checker = User(username="checker", password_hash="unused", role="admin", is_active=True)
        async with store() as db:
            db.add(maker); await db.commit()
            pending = await E.propose(proposal(), None, db, maker)
            assert pending["pending"]  # Even the only admin cannot bypass approval.
            assert not await db.scalar(select(CtrExemption.id))
            approval = await db.get(PendingApproval, pending["approval_id"])
            with pytest.raises(HTTPException) as exc:
                await dual_control.execute_approval(db, None, maker, approval)
            assert exc.value.status_code == 403
            db.add(checker); await db.commit()
            checker.role = "approver"; await db.commit()
            with pytest.raises(HTTPException):
                await dual_control.execute_approval(db, None, checker, approval)
            checker.role = "admin"; await db.commit()
            active = await dual_control.execute_approval(db, None, checker, approval)
            assert active["status"] == "ACTIVE"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        item = txn(id="exempt-cash", account_holder_id="PERSON", amount="15000", acting_as_agent=False, timestamp=now)
        result = await P.process(item)
        assert not result["ctr_required"]
        assert result["assessment"]["ctr_assessment"]["exemption"]["approved_by"] == "checker"
        assert result["risk_score"] > 0  # Risk assessment remains active.
        async with store() as db:
            pending = await E.revoke(active["id"], E.RevocationIn(reason="Eligibility ceased"), None, db, maker)
            approval = await db.get(PendingApproval, pending["approval_id"])
            await dual_control.execute_approval(db, None, checker, approval)
        assert (await P.process(replace(item, id="after-revocation")))["ctr_required"]
        unchanged = await P.process(item)
        assert unchanged["duplicate"] and not unchanged["ctr_required"]
        assert unchanged["assessment"] == result["assessment"]
    asyncio.run(run())


@pytest.mark.parametrize("role", ["analyst", "approver", "viewer"])
def test_exemption_endpoints_are_admin_only(store, role):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from backend.auth import require_user
    from backend.database import get_db
    app = FastAPI()
    app.include_router(E.router)
    app.dependency_overrides[require_user] = lambda: User(username=role, role=role, is_active=True)
    async def db_override():
        async with store() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/ctr-exemptions")).status_code == 403
            assert (await client.post("/ctr-exemptions", json=proposal().model_dump(mode="json"))).status_code == 403
            assert (await client.post("/ctr-exemptions/test/revoke", json={"reason": "Test reason"})).status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("module,name", [
    ("mysql", "MySQLAdapter"), ("mssql", "MSSQLAdapter"),
    ("postgres", "PostgresAdapter"), ("oracle", "OracleAdapter"),
])
def test_source_mapping_preserves_exemption_scope(module, name):
    from importlib import import_module
    adapter_type = getattr(import_module(f"backend.adapters.{module}"), name)
    fields = {"id": "i", "account_id": "a", "amount": "v", "timestamp": "t", "is_cash": "cash",
        "account_holder_id": "holder", "acting_as_agent": "agent", "cash_purpose": "purpose"}
    adapter = adapter_type({}, {"outward": {"table_name": "entries", "columns": fields}})
    result = adapter._row_to_txn({"i": "1", "a": "A", "v": "15000", "t": NOW,
        "cash": True, "holder": "PERSON", "agent": False, "purpose": "PAYROLL"}, "outward")
    assert result.is_cash is True and result.acting_as_agent is False
    assert result.account_holder_id == "PERSON" and result.cash_purpose == "PAYROLL"
