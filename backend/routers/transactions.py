from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.adapters.base import validate_identifier
from backend.auth import require_admin
from backend.config import ENVIRONMENT, bank_config
from backend.models import User
from backend.services.poller import get_adapter

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_admin)],
)


class TransactionPayload(BaseModel):
    direction: str = "OUTWARD"       # INWARD or OUTWARD
    account_id: str
    amount: float
    currency: str = "USD"
    beneficiary_account: str | None = None
    beneficiary_name: str | None = None
    sender_account: str | None = None
    sender_name: str | None = None
    channel: str = "MOBILE"
    narration: str | None = None
    reference: str | None = None


@router.post("")
async def inject_transaction(payload: TransactionPayload, _admin: User = Depends(require_admin)):
    if ENVIRONMENT.lower() != "development":
        raise HTTPException(status_code=404, detail="Demo transaction injection is disabled")

    adapter = get_adapter()

    if not await adapter.is_connected():
        raise HTTPException(status_code=503, detail="Bank DB not connected")

    table_key = "outward" if payload.direction == "OUTWARD" else "inward"
    tables = bank_config.get("tables", {})

    if table_key not in tables:
        raise HTTPException(status_code=400, detail=f"No '{table_key}' table configured")

    table_name = validate_identifier(tables[table_key]["table_name"], "table name")

    if payload.direction == "OUTWARD":
        sql = f"""
            INSERT INTO [{table_name}]
            (account_id, amount, currency, beneficiary_account, beneficiary_name,
             channel, reference, narration, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SUCCESS')
        """
        params = (
            payload.account_id, payload.amount, payload.currency,
            payload.beneficiary_account, payload.beneficiary_name,
            payload.channel, payload.reference, payload.narration,
        )
    else:
        sql = f"""
            INSERT INTO [{table_name}]
            (account_id, amount, currency, sender_account, sender_name,
             channel, reference, narration, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SUCCESS')
        """
        params = (
            payload.account_id, payload.amount, payload.currency,
            payload.sender_account, payload.sender_name,
            payload.channel, payload.reference, payload.narration,
        )

    # Route through the adapter so the write is serialized on the same lock as
    # the poller's reads - a bare adapter._conn.execute() on a separate thread
    # pool races the poller and trips "connection is busy".
    if not hasattr(adapter, "execute_write"):
        raise HTTPException(status_code=501, detail="Active adapter does not support writes")
    await adapter.execute_write(sql, params)

    return {"status": "submitted", "message": "Transaction written to DB. FMS will analyze shortly."}
