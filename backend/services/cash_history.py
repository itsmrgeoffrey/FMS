"""Portable, indexed access to same-person cash snapshots across all feeds."""
from sqlalchemy import or_, select
from backend.adapters.base import NormalizedTransaction
from backend.models import CashActivity, TransactionProcessing
from backend.services.analyzer import business_day


def activity(txn, processing_id):
    return CashActivity(processing_id=processing_id, account_id=txn.account_id,
        account_holder_id=txn.account_holder_id, conductor_id=txn.conductor_id,
        business_date=business_day(txn), currency=txn.currency, direction=txn.direction,
        timestamp=txn.timestamp)


def party_conditions(txn):
    conditions = [CashActivity.account_id == txn.account_id]
    if txn.account_holder_id:
        conditions.append(CashActivity.account_holder_id == txn.account_holder_id)
    if txn.conductor_id:
        conditions.append(CashActivity.conductor_id == txn.conductor_id)
    return or_(*conditions)


async def snapshots(db, txn):
    from backend.services.processing import deserialize
    rows = (await db.execute(select(TransactionProcessing).join(CashActivity,
        CashActivity.processing_id == TransactionProcessing.id).where(party_conditions(txn),
            CashActivity.business_date == business_day(txn), CashActivity.currency == txn.currency,
            CashActivity.direction == txn.direction, TransactionProcessing.state == "COMPLETED"))).scalars().all()
    result = []
    for row in rows:
        item = deserialize(row.payload)
        if row.assessment and row.assessment.get("business_date"):
            item.business_date = row.assessment["business_date"]
        result.append(item)
    return result


async def backfill(db):
    from datetime import datetime
    cursor = ""
    while True:
        rows = (await db.execute(select(TransactionProcessing).outerjoin(CashActivity,
            CashActivity.processing_id == TransactionProcessing.id).where(
                TransactionProcessing.id > cursor, TransactionProcessing.state == "COMPLETED",
                CashActivity.processing_id.is_(None)).order_by(TransactionProcessing.id).limit(200))).scalars().all()
        if not rows:
            return
        for row in rows:
            txn = NormalizedTransaction(**{**row.payload, "timestamp": datetime.fromisoformat(row.payload["timestamp"])})
            if txn.is_cash is True:
                index = activity(txn, row.id)
                if row.assessment and row.assessment.get("business_date"):
                    index.business_date = row.assessment["business_date"]
                db.add(index)
        cursor = rows[-1].id
        await db.commit()
