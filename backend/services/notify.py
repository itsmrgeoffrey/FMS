"""Outbound notification dispatch (email, webhooks, callbacks).

Two problems this exists to solve:

**1. Pool isolation.** Notifications were dispatched with
``loop.run_in_executor(None, ...)``, which uses asyncio's *default* executor —
the same pool that serves OFAC list refreshes and LDAP authentication. The
default pool has a small fixed size, so a mail or webhook endpoint that accepts
connections and never replies could occupy every worker and take directory
logins down with it. Notifications now run on their own bounded pool: a stuck
mail server degrades notifications only.

**2. Silent failures.** The previous pattern discarded the returned future, so
an exception inside the worker was never retrieved and never logged — an OFAC
sanctions hit could fail to notify anyone with no trace. :func:`submit` attaches
a done-callback that logs whatever the worker raised.

Delivery is still best-effort by design: a notification failure must never fail
the ingestion request or stall the poller, because the case is already durably
recorded before any notification is attempted. What changes is that failures are
now *visible* rather than silent.
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_MAX_WORKERS = int(os.getenv("FMS_NOTIFY_WORKERS", "4"))
_pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="fms-notify")


def _log_result(label: str):
    def _done(fut) -> None:
        try:
            fut.result()
        except Exception as e:
            # Never re-raise: this runs on the event loop's callback path.
            log.error("Notification %r failed: %s", label, e, exc_info=True)
    return _done


def submit(fn, *args, label: str | None = None) -> None:
    """Run a blocking notification callable off the event loop.

    Failures are logged, never raised. Safe to call from a coroutine; falls back
    to a direct pool submission if no event loop is running (e.g. from a worker
    thread or a script).
    """
    name = label or getattr(fn, "__name__", repr(fn))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        fut = _pool.submit(fn, *args)
        fut.add_done_callback(_log_result(name))
        return
    fut = loop.run_in_executor(_pool, fn, *args)
    fut.add_done_callback(_log_result(name))


def shutdown(wait: bool = False) -> None:
    """Stop accepting notifications; used on application shutdown."""
    _pool.shutdown(wait=wait, cancel_futures=not wait)
