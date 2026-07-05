"""Abstract base connector and SyncResult.

Every data-source connector inherits BaseConnector and implements two methods:
  sync()             — incremental delta sync, mutates ConnectorState in-place
  validate_webhook() — validate an inbound webhook request (default: accept all)

Adding a new source:
  1. Create sync/connectors/mysource.py and subclass BaseConnector
  2. Set NAME = "mysource"
  3. Implement sync() using whatever delta mechanism the source provides
  4. Register in sync/job.py _build_connectors() and sync/webhook_server.py routes
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SyncResult:
    connector: str
    upserted: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "OK" if not self.errors else f"{len(self.errors)} error(s)"
        return (
            f"[{self.connector}] upserted={self.upserted} deleted={self.deleted} "
            f"skipped={self.skipped} status={status}"
        )


class BaseConnector(ABC):
    NAME: str = ""

    @abstractmethod
    def sync(self, cs, corpus: str) -> SyncResult:
        """Run incremental sync against cs (ConnectorState). Mutates cs in-place."""
        ...

    def validate_webhook(
        self, headers: dict, body: bytes, query_params: dict
    ) -> tuple[bool, str]:
        """Validate an inbound webhook request.

        Returns (is_valid, echo_body).
        echo_body is non-empty only for subscription-validation handshakes (e.g. Graph API).
        """
        return True, ""
