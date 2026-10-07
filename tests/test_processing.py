"""Regression coverage for the ingestion boundary, money, recovery and delivery."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.adapters.base import NormalizedTransaction
from backend.database import Base
from backend.models import FraudCase, TransactionProcessing, NotificationDelivery, IngestedTransaction, User, RevokedSession
from backend.services import analyzer as A, processing as P, delivery as D, sanctions, callbacks
from backend.auth import create_token, authenticate_token, hash_password

NOW = datetime(2026, 10, 6, 12)


def txn(**kwargs):
    values = dict(id="t1", account_id="A", amount="6000", direction="OUTWARD", timestamp=NOW,
        counterparty_account="B", counterparty_name="Vendor", account_holder_name="Customer",
        channel="WIRE", currency="USD", reference=None, status=None, source_table="api", is_cash=True)
    return NormalizedTransaction(**{**values, **kwargs})


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(create())
    monkeypatch.setattr(P, "SessionLocal", factory)
    monkeypatch.setattr(D, "SessionLocal", factory)
    monkeypatch.setattr(P, "_locks", [asyncio.Lock() for _ in range(256)])
    monkeypatch.setattr(sanctions, "screen", lambda name: None)
    monkeypatch.setattr(sanctions, "has_full_list", lambda: True)
    monkeypatch.setattr(sanctions, "status", lambda: {"state": "ok", "ok": True, "list_age_hours": 1})
    monkeypatch.setattr(callbacks, "is_configured", lambda: True)
    monkeypatch.setattr(A.settings, "ai_summaries", "off")
    monkeypatch.setattr(A.settings, "business_timezone", "UTC")
    yield factory
    asyncio.run(engine.dispose())


def test_cash_boundary_and_no_ctr_for_wire():
    assert not A.evaluate(txn(amount="10000"), [])["ctr"].required
    assert A.evaluate(txn(amount="10000.01"), [])["ctr"].required
    assert not A.evaluate(txn(amount="20000", is_cash=False), [])["ctr"].required
    assert A.evaluate(txn(is_cash=None), [])["ctr"].trigger == "MANUAL_REVIEW"


@pytest.fixture
def configuration_store(store, monkeypatch):
    from backend.services import installation, rule_governance
    before, original_profile = A.snapshot_rules(), installation.profile()
    monkeypatch.setattr(rule_governance, "_change_lock", asyncio.Lock())
    yield store
    A.restore_rules(before)
    installation.activate(original_profile)


def test_rule_changes_require_reason_revision_and_initial_ack(configuration_store):
    from backend.services import rule_governance as G
    from backend.models import RuleChange, AuditLog
    async def run():
        before = A.snapshot_rules()
        rules = {"ctr_thresholds": {"KES": 250000}}
        async with configuration_store() as db:
            for reason, version, ack, status in [
                ("", G.revision(), True, 422), ("Review", "stale", True, 409),
                ("Review", G.revision(), False, 422),
            ]:
                with pytest.raises(HTTPException) as exc:
                    await G.apply_change(db, rules, reason, version, "operator", ack)
                assert exc.value.status_code == status
                assert A.snapshot_rules() == before
            version = G.revision()
            result = await G.apply_change(db, rules, "Initial KES calibration", version, "operator", True)
            assert result["saved"] and G.revision() != version
            assert A.snapshot_rules()["ctr_thresholds"]["KES"] == 250000
            row = (await db.execute(select(RuleChange))).scalar_one()
            assert row.rationale == "Initial KES calibration"
            assert row.backtest["initial_configuration"] and row.backtest["replayed"] == 0
            assert row.backtest["base_revision"] == version
            assert "institution_type" in row.backtest["operating_profile"]
            assert (await db.execute(select(AuditLog.action))).scalar_one() == "RULES_UPDATED"
            A.restore_rules(before)
            await G.restore_latest(db)
            assert A.snapshot_rules() == row.new_values
    asyncio.run(run())


def test_configuration_write_failure_keeps_live_values(configuration_store, monkeypatch):
    from backend.services import rule_governance as G, installation as I
    async def run():
        before, profile = A.snapshot_rules(), I.profile()
        async with configuration_store() as db:
            async def failed_commit():
                raise RuntimeError("Database unavailable")
            monkeypatch.setattr(db, "commit", failed_commit)
            with pytest.raises(RuntimeError, match="Database unavailable"):
                await G.apply_change(db, {"ctr_thresholds": {"KES": 200000}}, "Calibration", G.revision(), "operator", True)
            assert A.snapshot_rules() == before
            await db.rollback()
            with pytest.raises(RuntimeError, match="Database unavailable"):
                await G.apply_profile(db, {**profile, "regulatory_jurisdiction": "NG"}, "Local scope", G.revision(), "operator")
            assert I.profile() == profile
    asyncio.run(run())


def test_profile_persists_and_invalidates_rule_proposals(configuration_store):
    from backend.services import rule_governance as G, installation as I
    async def run():
        original, old_revision = I.profile(), G.revision()
        async with configuration_store() as db:
            changed = {"regulatory_jurisdiction": "NG", "institution_type": "fintech", "business_timezone": "Africa/Lagos"}
            await G.apply_profile(db, changed, "Confirm institution scope", old_revision, "operator")
            assert I.profile() == changed and G.revision() != old_revision
            assert (await I.inspect(db))["reporting_scope"].startswith("Manual")
            with pytest.raises(HTTPException) as exc:
                await G.apply_change(db, {"rolling_window_days": 7}, "Review", old_revision, "operator", True)
            assert exc.value.status_code == 409
            I.activate(original)
            await G.restore_latest(db)
            assert I.profile() == changed
            analysis = await A.analyze(txn(), [])
            assert analysis.assessed_rules["operating_profile"] == changed
            assert analysis.regulatory_review
    asyncio.run(run())


def test_rule_change_stores_server_replay_not_client_evidence(configuration_store):
    from backend.routers.settings import _exec_settings_update
    from backend.services import rule_governance as G
    from backend.models import RuleChange
    async def run():
        await P.process(txn(id="replay-current", timestamp=datetime.utcnow(), is_cash=False))
        async with configuration_store() as db:
            old_usd = A.snapshot_rules()["ctr_thresholds"]["USD"]
            result = await _exec_settings_update(db, {
                "rules": {"ctr_thresholds": {"USD": old_usd + 1000}},
                "rules_rationale": "Observed volume review", "rules_base_version": G.revision(),
                "rules_backtest": {"replayed": 987654321},
            }, "operator", None)
            assert result["saved"]
            row = (await db.execute(select(RuleChange))).scalar_one()
            assert row.backtest["replayed"] == 1
            assert row.backtest["storage_version"] == 1
            assert not row.backtest["initial_configuration"]
            # Behavioural tuning cannot move the fixed cash-reporting boundary.
            assert A.evaluate(txn(amount="10000.01"), [])["ctr"].required
    asyncio.run(run())


def test_configuration_routes_and_second_person_approval(configuration_store, monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from backend.database import get_db
    from backend.models import PendingApproval
    from backend.routers import settings as routes, insights, approvals, audit
    from backend.services import rule_governance as G, installation as I
    app = FastAPI()
    for router in (routes.router, insights.router, approvals.router):
        app.include_router(router)
    async def sessions():
        async with configuration_store() as db:
            yield db
    async def no_audit(*args, **kwargs):
        pass
    app.dependency_overrides[get_db] = sessions
    monkeypatch.setattr(audit, "record", no_audit)
    async def run():
        async with configuration_store() as db:
            users = [User(username=name, password_hash="unused", role=role) for name, role in
                     [("maker", "admin"), ("checker", "admin"), ("viewer", "analyst")]]
            db.add_all(users)
            await db.commit()
            headers = [{"Authorization": f"Bearer {create_token(user)}"} for user in users]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/settings/installation")).status_code == 401
            assert (await client.get("/settings/installation", headers=headers[2])).status_code == 403
            info = await client.get("/settings/installation", headers=headers[0])
            assert info.status_code == 200, info.text
            assert next(c for c in info.json()["checks"] if c["key"] == "operations")["state"] == "unverified"
            assert next(c for c in info.json()["checks"] if c["key"] == "admins")["state"] == "configured"
            invalid = {"operating_profile": {**I.profile(), "business_timezone": "Invalid/Timezone"}, "profile_rationale": "Scope", "configuration_revision": G.revision()}
            assert (await client.put("/settings", json=invalid, headers=headers[0])).status_code == 422
            payload = {"rules": {"ctr_thresholds": {"KES": 250000}}, "rules_rationale": "Initial calibration", "rules_base_version": G.revision(), "rules_allow_empty_history": True}
            assert (await client.put("/settings", json={**payload, "rules_rationale": " "}, headers=headers[0])).status_code == 422
            assert (await client.put("/settings", json={**payload, "rules": {"typo": 1}}, headers=headers[0])).status_code == 422
            assert (await client.put("/settings", json=payload, headers=headers[2])).status_code == 403
            before = A.snapshot_rules()
            queued = await client.put("/settings", json=payload, headers=headers[0])
            assert queued.status_code == 200 and queued.json()["pending"], queued.text
            assert A.snapshot_rules() == before
            queued2 = await client.put("/settings", json={**payload, "rules": {"ctr_thresholds": {"KES": 350000}}}, headers=headers[0])
            first = queued.json()["approval_id"]
            assert (await client.post(f"/approvals/{first}/approve", headers=headers[0])).status_code == 403
            approved = await client.post(f"/approvals/{first}/approve", headers=headers[1])
            assert approved.status_code == 200, approved.text
            assert A.snapshot_rules()["ctr_thresholds"]["KES"] == 250000
            second = queued2.json()["approval_id"]
            assert (await client.post(f"/approvals/{second}/approve", headers=headers[1])).status_code == 409
            async with configuration_store() as db:
                assert (await db.get(PendingApproval, second)).status == "pending"
    asyncio.run(run())


@pytest.mark.parametrize("rules", [
    {"ctr_thresholds": {"USD": 20000, "EUR": -1}},
    {"rolling_window_days": 0}, {"rolling_window_days": 1.5},
    {"smurfing_window_hours": float("inf")}, {"structuring_band_ratio": 1},
    {"rolling_window_days": True}, {"ctr_thresholds": {"USD": True}}, {"unknown_rule": 1},
])
def test_invalid_rules_do_not_partially_change_engine(rules):
    before = A.snapshot_rules()
    with pytest.raises(ValueError):
        A.apply_rule_overrides(rules)
    assert A.snapshot_rules() == before


@pytest.mark.parametrize("value", [
    {"business_timezone": "Invalid/Zone"}, {"institution_type": "unsupported"},
    {"regulatory_jurisdiction": "USA"}, {"unexpected": True},
])
def test_invalid_operating_profile_is_rejected(value):
    from pydantic import ValidationError
    from backend.services.installation import OperatingProfile, profile
    with pytest.raises(ValidationError):
        OperatingProfile(**{**profile(), **value})


def test_unavailable_and_stale_screening_require_review(store, monkeypatch):
    async def run():
        monkeypatch.setattr(sanctions, "status", lambda: {"ok": False})
        unavailable = await P.process(txn(id="unavailable", amount=10, is_cash=False))
        assert unavailable["assessment"]["screening_status"] == "UNAVAILABLE"
        assert unavailable["review_status"] == "OPEN"
        monkeypatch.setattr(sanctions, "status", lambda: {"ok": True, "list_age_hours": 1000})
        stale = await P.process(txn(id="stale", amount=10, is_cash=False))
        assert stale["assessment"]["screening_status"] == "STALE"
        assert stale["review_status"] == "OPEN"
    asyncio.run(run())


def test_api_routing_pagination_assessments_and_logout(store, monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from backend.database import get_db
    from backend.routers import ingest, cases, stats, auth_routes, insights, audit
    app = FastAPI()
    for router in (ingest.router, cases.router, stats.router, auth_routes.router, insights.router):
        app.include_router(router)
    async def sessions():
        async with store() as db:
            yield db
    async def no_audit(*args, **kwargs):
        pass
    app.dependency_overrides[get_db] = sessions
    monkeypatch.setattr(audit, "record", no_audit)
    monkeypatch.setattr(ingest.settings, "fms_ingest_api_key", "test-key")
    async def run():
        async with store() as db:
            user = User(username="admin", password_hash=hash_password("Test!123456"), role="admin")
            db.add(user)
            await db.commit()
            token = create_token(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                headers={"Authorization": f"Bearer {token}"}) as client:
            body = dict(external_id="api-1", account_id="ACCOUNT-ONE", amount="10000.01",
                direction="INWARD", currency="USD", channel="ANY-CHANNEL", is_cash=True,
                account_holder_name="Customer", counterparty_name="Vendor")
            pushed = await client.post("/ingest/transactions", json=body, headers={"X-API-Key": "test-key"})
            assert pushed.status_code == 200, pushed.text
            assert pushed.json()["ctr_required"]
            duplicate = await client.post("/ingest/simulate", json=body)
            assert duplicate.json()["duplicate"]
            assert duplicate.json()["case_id"] == pushed.json()["case_id"]
            conflict = await client.post("/ingest/simulate", json={**body, "account_id": "OTHER"})
            assert conflict.status_code == 409
            second = await client.post("/ingest/simulate", json={**body, "external_id": "api-2",
                "account_id": "ACCOUNT-TWO", "is_cash": False, "amount": "10"})
            assert second.status_code == 200 and not second.json()["ctr_required"]
            detail = await client.get(f"/cases/{second.json()['case_id']}")
            assert detail.status_code == 200 and detail.json()["account_id"] == "ACCOUNT-TWO"
            assert detail.json()["assessment"]["cash_classification"] is False
            assert datetime.fromisoformat(detail.json()["timestamp"]).tzinfo == timezone.utc
            assert datetime.fromisoformat(detail.json()["created_at"]).tzinfo == timezone.utc
            for amount in ("NaN", "-1", "0", "1.1234567"):
                response = await client.post("/ingest/simulate", json={**body, "amount": amount})
                assert response.status_code == 422
            review = await client.get("/cases?review_required=true&sort=risk&limit=1")
            assert review.status_code == 200 and review.json()["total"] == 1
            case_id = pushed.json()["case_id"]
            assert (await client.post(f"/cases/{case_id}/actions", json={"action": "ESCALATED"})).status_code == 422
            escalated = await client.post(f"/cases/{case_id}/actions", json={"action": "ESCALATED", "note": "Verify filing applicability"})
            assert escalated.status_code == 200, escalated.text
            assert escalated.json()["ctr_required"]
            assert (await client.get("/stats")).json()["pending_review"] == 1
            async with store() as db:
                original = await db.get(FraudCase, case_id)
                legacy = FraudCase(**{k: getattr(original, k) for k in
                    ("account_id", "amount", "direction", "timestamp", "currency")},
                    source_table="legacy", source_txn_id="old", status="CLEAN", ctr_required=True,
                    risk_score=99, confidence="LOW", created_at=datetime(2020, 1, 1))
                db.add(legacy)
                await db.commit()
            review = (await client.get("/cases?review_required=true&sort=risk&limit=1")).json()
            assert review["total"] == 2 and review["items"][0]["source_table"] == "legacy"
            assert review["items"][0]["assessment"]["version"] == "legacy"
            assert len((await client.get("/cases?review_required=true&limit=1&page=2")).json()["items"]) == 1
            # Queue filters apply before pagination and search treats LIKE tokens literally.
            filtered = (await client.get("/cases", params={"review_required": "true", "search": "account-one", "flag": "ctr", "limit": 1})).json()
            assert filtered["total"] == 2 and len(filtered["items"]) == 1
            assert (await client.get("/cases", params={"search": "ACCOUNT-TWO"})).json()["total"] == 1
            assert (await client.get("/cases", params={"search": "legacy", "min_risk": 76})).json()["total"] == 1
            assert (await client.get("/cases", params={"status": "ESCALATED", "flag": "ctr"})).json()["total"] == 1
            for term in ("%", "_", "not-present"):
                assert (await client.get("/cases", params={"search": term})).json()["total"] == 0
            for params in ({"flag": "invalid"}, {"min_risk": 101}, {"min_risk": -1}, {"search": "x" * 201}):
                assert (await client.get("/cases", params=params)).status_code == 422
            overview = (await client.get("/stats/dashboard")).json()
            legacy_attention = next(item for item in overview["attention"] if item["id"] == legacy.id)
            assert legacy_attention["ctr_required"] and legacy_attention["status"] == "CLEAN"
            assert legacy_attention["assessment"]["version"] == "legacy"
            assert legacy_attention["source_table"] == "legacy"
            replay = await client.post("/rules/backtest", json={"proposed": {}})
            assert replay.status_code == 200 and replay.json()["current"]["ctr_required"] == 1
            assert (await client.post("/auth/logout")).status_code == 200
            assert (await client.get("/cases")).status_code == 401
    asyncio.run(run())


def test_broadcast_rechecks_authorization_before_sending():
    from backend.services.broadcaster import ConnectionManager
    class Socket:
        def __init__(self):
            self.closed, self.sent = False, []
        async def accept(self):
            pass
        async def close(self, code):
            self.closed = True
        async def send_text(self, payload):
            self.sent.append(payload)
    async def run():
        manager, ws = ConnectionManager(), Socket()
        async def denied():
            return False
        await manager.connect(ws, denied)
        await manager.broadcast({"private": "case data"})
        assert ws.closed and not ws.sent and not manager._connections
    asyncio.run(run())


def test_poller_retries_without_advancing_and_uses_shared_processor(store, monkeypatch):
    from backend.services import poller
    checkpoint = []
    async def load(table):
        return "1"
    async def save(table, identifier):
        checkpoint.append(identifier)
    class Adapter:
        async def fetch_new_transactions(self, table, since):
            return [txn(id="2", source_table="bank_table", account_id="POLLED-A"),
                    txn(id="3", source_table="bank_table", account_id="POLLED-B")]
        async def fetch_account_history(self, account, tables, days):
            return []
    original = A.analyze
    async def unavailable(*args):
        raise RuntimeError("temporary analysis failure")
    monkeypatch.setattr(poller, "_load_checkpoint", load)
    monkeypatch.setattr(poller, "_save_checkpoint", save)
    async def run():
        monkeypatch.setattr(A, "analyze", unavailable)
        with pytest.raises(RuntimeError):
            await poller._process_table(Adapter(), "bank_table", 90)
        assert checkpoint == []
        monkeypatch.setattr(A, "analyze", original)
        await poller._process_table(Adapter(), "bank_table", 90)
        assert checkpoint == ["2", "3"]
        async with store() as db:
            cases = (await db.execute(select(FraudCase))).scalars().all()
            assert {c.account_id for c in cases} == {"POLLED-A", "POLLED-B"}
            assert all(c.assessment["screening_status"] == "NO_MATCH" for c in cases)
            records = (await db.execute(select(TransactionProcessing))).scalars().all()
            assert len(records) == 2 and all(r.state == "COMPLETED" for r in records)
    asyncio.run(run())


def test_history_excludes_foreign_currency_future_and_other_accounts():
    t = txn(amount="100")
    history = [replace(t, id="ngn", currency="NGN", amount="15000"),
               replace(t, id="future", timestamp=NOW + timedelta(seconds=1), amount="9900"),
               replace(t, id="other", account_id="Z", amount="20000")]
    score = A.evaluate(t, history)
    assert score["risk"].rolling_5d_total == Decimal("100")
    assert score["profile"].transaction_count == 0
    assert not score["ctr"].required


def test_decimal_aggregation_and_timezone_business_day(monkeypatch):
    t = txn(amount="0.01")
    h = replace(t, id="h", amount="10000", timestamp=NOW - timedelta(seconds=1))
    assert A._rolling_window(t, [h])[0] == Decimal("10000.01")
    assert A.evaluate(t, [h])["ctr"].required
    monkeypatch.setattr(A.settings, "business_timezone", "America/New_York")
    t = txn(timestamp=datetime(2026, 10, 6, 1, tzinfo=timezone.utc), amount=6000)
    h = replace(t, id="h", timestamp=datetime(2026, 10, 5, 23, tzinfo=timezone.utc))
    assert A.evaluate(t, [h])["ctr"].required


def test_reporting_not_changed_by_behavioral_tuning():
    snap = A.snapshot_rules()
    try:
        A.apply_rule_overrides({"ctr_thresholds": {"USD": 50000}, "sar_ratio": 0.9})
        assert A.evaluate(txn(amount=11000), [])["ctr"].required
        assert not A.evaluate(txn(amount=9000), [])["ctr"].required
    finally:
        A.restore_rules(snap)


def test_simultaneous_requests_have_complete_history_and_stable_duplicates(store):
    async def run():
        a, b = await asyncio.gather(P.process(txn(id="a")), P.process(txn(id="b")))
        assert sum(v["ctr_required"] for v in (a, b)) == 1
        duplicate = await P.process(txn(id="a"))
        assert duplicate["duplicate"] and duplicate["case_id"] == a["case_id"]
        with pytest.raises(HTTPException) as exc:
            await P.process(txn(id="a", account_id="other"))
        assert exc.value.status_code == 409
        async with store() as db:
            assert (await db.execute(select(func.count()).select_from(FraudCase))).scalar_one() == 2
    asyncio.run(run())


def test_analysis_failure_is_durable_and_retry_resumes(store, monkeypatch):
    analyze = A.analyze
    async def fail(*args):
        raise RuntimeError("temporary failure")
    async def run():
        monkeypatch.setattr(A, "analyze", fail)
        with pytest.raises(RuntimeError):
            await P.process(txn())
        async with store() as db:
            row = (await db.execute(select(TransactionProcessing))).scalar_one()
            assert row.state == "FAILED" and row.case_id is None
        monkeypatch.setattr(A, "analyze", analyze)
        result = await P.process(txn())
        assert result["processing_status"] == "COMPLETED"
        async with store() as db:
            assert (await db.execute(select(func.count()).select_from(FraudCase))).scalar_one() == 1
    asyncio.run(run())


def test_legacy_orphan_resumes_and_conflicting_payload_is_rejected(store):
    async def run():
        async with store() as db:
            db.add(IngestedTransaction(external_id="t1", account_id="A", amount=6000, direction="OUTWARD",
                timestamp=NOW, counterparty_account="B", counterparty_name="Vendor", account_holder_name="Customer",
                channel="WIRE", currency="USD"))
            await db.commit()
        with pytest.raises(HTTPException):
            await P.process(txn(amount=10))
        assert (await P.process(txn()))["case_id"]
    asyncio.run(run())


def test_ctr_only_is_open_and_notifications_survive_failures(store, monkeypatch):
    async def run():
        history = [txn(id=f"h{i}", amount=20000, timestamp=NOW - timedelta(days=30-i)) for i in range(5)]
        result = await P.process(txn(amount=20000), history)
        assert result["assessment"]["detection_status"] == "NO_FRAUD_SIGNAL"
        assert result["review_status"] == "OPEN" and result["ctr_required"]
        def fail(row):
            raise RuntimeError("remote unavailable")
        monkeypatch.setattr(D, "_send", fail)
        await D.deliver_pending()
        async with store() as db:
            row = (await db.execute(select(NotificationDelivery))).scalar_one()
            assert not row.delivered and row.attempts == 1 and row.error
            row.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            await db.commit()
        monkeypatch.setattr(D, "_send", lambda row: None)
        await D.deliver_pending()
        async with store() as db:
            row = (await db.execute(select(NotificationDelivery))).scalar_one()
            assert row.delivered and row.attempts == 2
    asyncio.run(run())


def test_polled_and_api_transactions_use_identical_screening(store):
    async def run():
        api = await P.process(txn(account_id="api-account", is_cash=False))
        poll = await P.process(txn(account_id="db-account", source_table="outward", is_cash=False))
        for field in ("risk_score", "ctr_required", "sar_recommended", "assessment"):
            assert api[field] == poll[field]
    asyncio.run(run())


def test_password_changes_and_disable_revoke_existing_sessions(store):
    async def run():
        async with store() as db:
            user = User(username="test", role="admin", password_hash=hash_password("password123"), is_active=True)
            db.add(user)
            await db.commit()
            token = create_token(user)
            assert await authenticate_token(token, db)
            user.password_hash = hash_password("newpassword123")
            await db.commit()
            assert await authenticate_token(token, db) is None
            token = create_token(user)
            user.is_active = False
            await db.commit()
            assert await authenticate_token(token, db) is None
    asyncio.run(run())
