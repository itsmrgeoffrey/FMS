"""Seed a self-contained DEMO instance — test users + sample cases — for display.

This is the "test for display" half of test-vs-prod separation:

    DEMO  (this script): SQLite app DB, API-push mode, seeded users + sample
          cases. No real database, no real credentials, safe to show anyone.
    PROD  (real deploy): FMS_APP_DB_URL -> your server DB, real bank_config.yaml,
          FMS_ALLOW_SIGNUP=false + FMS_SETUP_TOKEN, real users. Never seeded.

Run it against a throwaway SQLite file so demo data never touches production:

    # Windows (Git Bash)
    FMS_APP_DB_URL= FMS_DB_PATH=fms_demo.db python scripts/seed_demo.py

Then start the backend with the same env and log in with the printed credentials.
Idempotent: re-running tops up any missing demo users and (re)seeds sample cases.
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # project root importable

from backend.auth import hash_password
from backend.database import DATABASE_URL, SessionLocal, init_db
from backend.models import AuditLog, CaseAction, FraudCase, User
from sqlalchemy import delete, select

DEMO_USERS = [
    ("admin@fms.demo",   "DemoAdmin!2026",   "Dana Okafor (Demo Admin)",    "admin"),
    ("analyst@fms.demo", "DemoAnalyst!2026", "Alex Rivera (Demo Analyst)",  "analyst"),
    ("viewer@fms.demo",  "DemoViewer!2026",  "Val Chen (Demo Viewer)",      "viewer"),
]

now = datetime.utcnow()


def _case(days_ago, hours, **kw):
    ts = now - timedelta(days=days_ago, hours=hours)
    base = dict(
        source_table="api", account_id="ACC-100200", amount=1000.0, direction="OUTWARD",
        timestamp=ts, counterparty_account="CP-0001", counterparty_name="Acme Supplies",
        channel="WIRE", currency="USD", reference=None, risk_score=10,
        ctr_required=False, ctr_reason=None, sar_recommended=False, sar_reason=None,
        sanctions_hit=False, sanctions_detail=None, confidence="LOW", fraud_type=None,
        reasons=["No specific fraud signals were detected for this transaction."],
        ai_summary=None, status="CLEAN", created_at=ts, updated_at=ts,
    )
    base.update(kw)
    base["source_txn_id"] = kw.get("source_txn_id") or f"DEMO-{days_ago:02d}{hours:02d}-{int(base['amount'])}"
    return FraudCase(**base)


DEMO_CASES = [
    # A clean, routine transfer
    lambda: _case(9, 2, amount=2400, counterparty_name="Office Depot"),
    # High-value + CTR
    lambda: _case(7, 5, amount=42000, counterparty_name="Global Machinery Ltd", risk_score=58,
                  ctr_required=True, ctr_reason="Single transaction of USD 42,000.00 exceeds CTR threshold",
                  confidence="HIGH", fraud_type="large outward transfer", status="OPEN",
                  reasons=["This transfer of USD 42,000.00 is significantly above the USD 10,000 high-value threshold."]),
    # Invoice fraud — new vendor, big jump
    lambda: _case(5, 3, amount=60000, counterparty_name="Swift Payment Services Ltd", counterparty_account="CP-9931",
                  risk_score=67, ctr_required=True, ctr_reason="Single transaction exceeds CTR threshold",
                  sar_recommended=True, sar_reason="Suspicious activity meets the USD 5,000 SAR threshold",
                  confidence="HIGH", fraud_type="invoice fraud", status="OPEN",
                  reasons=["This USD 60,000.00 transfer is far outside this account's typical USD 21,000 payment.",
                           "Swift Payment Services Ltd has never received a payment from this account before."]),
    # Multi-source smurfing (inward)
    lambda: _case(3, 1, amount=3200, direction="INWARD", account_id="ACC-556677", counterparty_name="Sender D",
                  risk_score=72, sar_recommended=True, sar_reason="Multi-source smurfing pattern — reportable regardless of amount",
                  confidence="HIGH", fraud_type="multi-source smurfing", status="OPEN",
                  reasons=["4 different accounts deposited into this account in the last 48h; combined inflow USD 12,600.00 — a smurfing pattern."]),
    # OFAC sanctions match
    lambda: _case(2, 6, amount=8200, counterparty_name="Redline Shipping Co", counterparty_account="CP-4412",
                  risk_score=26, sanctions_hit=True,
                  sanctions_detail="Counterparty 'Redline Shipping Co' matches OFAC SDN entry 'REDLINE SHIPPING CO' (program: IRAN, 100% match)",
                  confidence="HIGH", fraud_type="sanctions match", status="OPEN",
                  reasons=["OFAC SANCTIONS MATCH — counterparty matches the SDN list. Block or reject and report to OFAC."]),
    # Account takeover — critical
    lambda: _case(2, 2, amount=95000, account_id="ACC-778899", counterparty_name="International Trade Solutions",
                  counterparty_account="CP-7788", channel="MOBILE", risk_score=84,
                  ctr_required=True, ctr_reason="Single transaction exceeds CTR threshold",
                  sar_recommended=True, sar_reason="Suspicious high-value activity meets the SAR threshold",
                  confidence="HIGH", fraud_type="account takeover", status="OPEN",
                  reasons=["USD 95,000.00 via MOBILE at 02:00 to a never-seen beneficiary — consistent with account takeover."]),
    # A confirmed fraud (feeds the KPIs)
    lambda: _case(6, 8, amount=15000, account_id="ACC-334455", counterparty_name="Ghost Vendor LLC",
                  risk_score=70, confidence="HIGH", fraud_type="invoice fraud", status="CONFIRMED_FRAUD",
                  sar_recommended=True, sar_reason="Confirmed suspicious activity",
                  reasons=["Large payment to an unrecognized vendor; confirmed fraudulent after review."]),
    # A dismissed false positive (feeds the false-positive rate)
    lambda: _case(4, 4, amount=9500, counterparty_name="Payroll Batch", reference="Monthly PAYROLL run",
                  risk_score=32, confidence="MEDIUM", fraud_type="near-threshold pattern", status="DISMISSED",
                  reasons=["Amount just below the reporting threshold — reviewed and cleared as a scheduled payroll run."]),
    # A couple more clean ones for volume
    lambda: _case(8, 1, amount=1800, counterparty_name="City Utilities"),
    lambda: _case(1, 3, amount=5400, counterparty_name="Northwind Traders"),
]


async def main():
    print(f"Seeding demo data into: {DATABASE_URL}")
    if "sqlite" not in DATABASE_URL:
        print("\n  ⚠  This is NOT a SQLite database. Demo data is meant for a throwaway SQLite file.")
        print("     Re-run with:  FMS_APP_DB_URL= FMS_DB_PATH=fms_demo.db python scripts/seed_demo.py\n")
        return

    await init_db()

    async with SessionLocal() as db:
        # Users (idempotent)
        created_users = []
        for email, password, full_name, role in DEMO_USERS:
            existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if existing:
                continue
            db.add(User(username=email, email=email, full_name=full_name,
                        password_hash=hash_password(password), role=role,
                        is_active=True, last_login_at=None))
            created_users.append((email, password, role))
        await db.commit()

        # Sample cases — clear prior demo cases, then reseed (idempotent, deterministic).
        await db.execute(delete(CaseAction))
        await db.execute(delete(FraudCase).where(FraudCase.source_txn_id.like("DEMO-%")))
        await db.commit()
        cases = [factory() for factory in DEMO_CASES]
        db.add_all(cases)
        await db.commit()

        # A little case-action + audit history so the Audit Trail and analytics have content.
        for c in cases:
            await db.refresh(c)
        by_type = {c.fraud_type: c for c in cases}
        actions = []
        if "invoice fraud" in by_type:
            actions.append(CaseAction(case_id=by_type["invoice fraud"].id, action="REVIEW",
                                      actor="analyst@fms.demo", note="Contacting the account holder to verify the vendor."))
        confirmed = next((c for c in cases if c.status == "CONFIRMED_FRAUD"), None)
        if confirmed:
            actions.append(CaseAction(case_id=confirmed.id, action="CONFIRMED",
                                      actor="admin@fms.demo", note="Verified fraudulent with the customer."))
        dismissed = next((c for c in cases if c.status == "DISMISSED"), None)
        if dismissed:
            actions.append(CaseAction(case_id=dismissed.id, action="DISMISSED",
                                      actor="analyst@fms.demo", note="Legitimate scheduled payroll — false positive."))
        db.add_all(actions)
        db.add_all([
            AuditLog(username="admin@fms.demo", action="LOGIN", ip="127.0.0.1", created_at=now - timedelta(hours=3)),
            AuditLog(username="analyst@fms.demo", action="LOGIN", ip="127.0.0.1", created_at=now - timedelta(hours=2)),
            AuditLog(username="admin@fms.demo", action="SETTINGS_UPDATED", detail="institution", ip="127.0.0.1", created_at=now - timedelta(hours=1)),
            AuditLog(username="attacker@evil.test", action="LOGIN_FAILED", ip="203.0.113.7", created_at=now - timedelta(minutes=20)),
            AuditLog(username="attacker@evil.test", action="LOGIN_FAILED", ip="203.0.113.7", created_at=now - timedelta(minutes=19)),
        ])
        await db.commit()

    print(f"  seeded {len(DEMO_CASES)} sample cases + activity")
    print("\nDemo login credentials:")
    for email, password, _fn, role in DEMO_USERS:
        print(f"  {role:<8} {email:<20} {password}")
    print("\nStart the backend/frontend with the SAME env and sign in:")
    print("  FMS_APP_DB_URL= FMS_DB_PATH=fms_demo.db python -m uvicorn backend.main:app --port 8002")


if __name__ == "__main__":
    asyncio.run(main())
