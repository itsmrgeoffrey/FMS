"""Transactional notification outbox; deliveries are at-least-once."""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from backend.config import settings
from backend.database import SessionLocal
from backend.models import NotificationDelivery
from backend.services import callbacks, emailer, notify

log = logging.getLogger(__name__)


def enqueue(db, event, payload):
    channels = ["callback"] if callbacks.is_configured() else []
    if event == "case.flagged":
        if emailer.is_configured():
            channels.append("email")
        if settings.alert_webhook_url:
            channels.append("webhook")
    for channel in channels:
        db.add(NotificationDelivery(event=event, channel=channel, payload=payload))


def _send(row):
    payload = {**row.payload, "delivery_id": row.id}
    if row.channel == "callback":
        if not callbacks.is_configured():
            raise RuntimeError("Callback configuration unavailable")
        callbacks.post_event(row.event, payload)
    elif row.channel == "email":
        if not emailer.is_configured():
            raise RuntimeError("Email configuration unavailable")
        emailer.send_fraud_alert(payload)
    else:
        if not settings.alert_webhook_url:
            raise RuntimeError("Webhook configuration unavailable")
        emailer.send_webhook_alert(payload)


async def deliver_pending():
    async with SessionLocal() as db:
        rows = (await db.execute(select(NotificationDelivery).where(
            NotificationDelivery.delivered == False,
            NotificationDelivery.next_attempt_at <= datetime.utcnow()).limit(20))).scalars().all()
        for row in rows:
            row.attempts += 1
            try:
                await asyncio.get_running_loop().run_in_executor(notify._pool, _send, row)
                row.delivered, row.error = True, None
            except Exception as exc:
                row.error = type(exc).__name__
                row.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(3600, 2 ** min(row.attempts, 12)))
                log.warning("Notification %s failed on attempt %s", row.id, row.attempts)
            await db.commit()


async def recovery_loop():
    from backend.services.processing import retry_pending
    while True:
        try:
            await retry_pending()
            await deliver_pending()
        except Exception:
            log.exception("Recovery cycle failed")
        await asyncio.sleep(5)
