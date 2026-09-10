from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import os
import re

# Bank-database timeouts, shared by every adapter so they cannot drift apart.
#
# Both are needed and they are not the same thing: a CONNECT timeout bounds
# session establishment, a QUERY timeout bounds each statement afterwards. An
# adapter with only the first still wedges permanently when a bank database
# accepts the connection and then stops responding mid-query — which is the
# common failure, not a refused connection. Read-only monitoring queries should
# fail fast and retry on the next poll cycle rather than hold a shared
# connection open indefinitely.
CONNECT_TIMEOUT_SECONDS = int(os.getenv("FMS_BANK_CONNECT_TIMEOUT", "10"))
QUERY_TIMEOUT_SECONDS = int(os.getenv("FMS_BANK_QUERY_TIMEOUT", "30"))

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str | None, label: str = "identifier") -> str:
    """Validate table/column identifiers before interpolating them into SQL."""
    if not value or not _IDENTIFIER_RE.fullmatch(str(value)):
        raise ValueError(f"Invalid SQL {label}: {value!r}")
    return str(value)



@dataclass
class NormalizedTransaction:
    id: str
    account_id: str
    amount: float
    direction: str          # INWARD / OUTWARD
    timestamp: datetime
    counterparty_account: str | None
    counterparty_name: str | None
    channel: str | None
    currency: str
    reference: str | None
    status: str | None
    source_table: str       # which config table key this came from
    batch_id: str | None = None   # optional — set when bank table has a batch/payment-run ID column


class BaseAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def is_connected(self) -> bool: ...

    @abstractmethod
    async def fetch_new_transactions(
        self, table_key: str, since_id: str | None, limit: int = 100
    ) -> list[NormalizedTransaction]: ...

    @abstractmethod
    async def fetch_account_history(
        self, account_id: str, table_keys: list[str], history_days: int = 90
    ) -> list[NormalizedTransaction]: ...
