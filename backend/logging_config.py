"""Central logging configuration for FMS.

Application logs are emitted throughout the backend via the standard ``logging``
module. This wires them to a consistent format, an environment-controlled level,
and — in production — a rotating file on disk so operational history survives a
process restart (console-only logging is lost the moment the process dies).

Everything is controlled by environment variables (set per-environment in the
env file selected by ``FMS_ENV_FILE``), so no code change is needed to switch
between a chatty console for the demo and persistent, rotated files for prod:

    FMS_LOG_LEVEL         DEBUG | INFO | WARNING | ERROR       (default INFO)
    FMS_LOG_FILE          path to a log file; empty = stdout only    (default "")
    FMS_LOG_MAX_BYTES     rotate after this many bytes          (default 10_000_000)
    FMS_LOG_BACKUP_COUNT  number of rotated files to keep       (default 5)

Every log line also carries the ingest request id (see the ingest tracing
middleware in ``backend/main.py``) when one is in scope, so a single pushed
transaction can be followed end-to-end through the logs. Lines emitted outside a
request show ``-``.
"""
import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Set for the duration of an /ingest request so every record emitted while
# handling it is tagged with the same id. "-" when no request is in scope.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s"

_configured = False


class RequestIdFilter(logging.Filter):
    """Inject the current ingest request id onto every record so the formatter
    can print it. Attached to every handler, so records from any logger (ours or
    uvicorn's) are covered."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def setup_logging() -> None:
    """Configure the root logger. Idempotent — safe to call once at startup."""
    global _configured
    if _configured:
        return

    level_name = os.getenv("FMS_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)
    id_filter = RequestIdFilter()

    handlers: list[logging.Handler] = []

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(id_filter)
    handlers.append(console)

    log_file = os.getenv("FMS_LOG_FILE", "").strip()
    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path,
                maxBytes=_int_env("FMS_LOG_MAX_BYTES", 10_000_000),
                backupCount=_int_env("FMS_LOG_BACKUP_COUNT", 5),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(id_filter)
            handlers.append(file_handler)
        except OSError as e:
            # Never let a bad log path stop the app from starting — fall back to
            # console only and say so.
            logging.getLogger(__name__).warning(
                "Could not open log file %s (%s) — logging to console only", log_file, e
            )
            log_file = ""

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any pre-existing handlers (e.g. a prior basicConfig) so our format
    # and filters are the ones that apply.
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)

    # uvicorn installs its own handlers on these loggers; route them through the
    # root handlers instead so access/error logs share our format and file.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _configured = True
    logging.getLogger(__name__).info(
        "Logging configured: level=%s, file=%s", level_name, log_file or "(console only)"
    )
