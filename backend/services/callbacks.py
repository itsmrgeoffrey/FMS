"""Outbound result delivery — FMS posts verdicts back to the institution.

Completes the zero-DB-access integration loop:
  institution -> POST /ingest/transactions -> engine verdict (synchronous)
  FMS -> POST institution callback_url     -> flagged-case events + later
                                              analyst dispositions

Every delivery is signed with HMAC-SHA256 over the raw body using the shared
callback secret (header: X-FMS-Signature, hex). The receiver recomputes the
HMAC to verify authenticity and integrity. Deliveries are best-effort with
retries; failures are logged and never block case processing.
"""
import hashlib
import hmac
import json
import logging
import time

from backend.config import bank_config

log = logging.getLogger(__name__)

_RETRIES = 3
_BACKOFF_SECONDS = 2


def _config() -> tuple[str, str]:
    integ = bank_config.get("integrations", {}) or {}
    return (integ.get("callback_url", "") or "").strip(), (integ.get("callback_secret", "") or "").strip()


def is_configured() -> bool:
    return bool(_config()[0])


def post_event(event_type: str, payload: dict) -> None:
    """Deliver one event to the institution's callback URL. Blocking — run in
    an executor. event_type: case.flagged | case.disposition"""
    url, secret = _config()
    if not url:
        return
    body = json.dumps(
        {"event": event_type, "sent_at": int(time.time()), "data": payload},
        separators=(",", ":"), default=str,
    ).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "FMS-Callback/1.0"}
    if secret:
        headers["X-FMS-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    import httpx
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = httpx.post(url, content=body, headers=headers, timeout=10)
            if resp.status_code < 300:
                log.info(f"Callback delivered: {event_type} -> {url} ({resp.status_code})")
                return
            log.warning(f"Callback attempt {attempt} got HTTP {resp.status_code} from {url}")
        except Exception as e:
            log.warning(f"Callback attempt {attempt} failed: {e}")
        if attempt < _RETRIES:
            time.sleep(_BACKOFF_SECONDS * attempt)
    log.error(f"Callback delivery FAILED after {_RETRIES} attempts: {event_type} -> {url}")


def case_payload(case) -> dict:
    """The fields an institution needs to act on a verdict."""
    return {
        "case_id": case.id,
        "external_id": case.source_txn_id if case.source_table == "api" else None,
        "account_id": case.account_id,
        "amount": case.amount,
        "currency": case.currency,
        "direction": case.direction,
        "status": case.status,
        "risk_score": case.risk_score,
        "confidence": case.confidence,
        "fraud_type": case.fraud_type,
        "sanctions_hit": case.sanctions_hit,
        "ctr_required": case.ctr_required,
        "sar_recommended": case.sar_recommended,
        "reasons": case.reasons,
    }
