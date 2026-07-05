"""GCS-backed sync state store.

The state file is a JSON object at SYNC_STATE_GCS_URI. It persists, per connector:
  last_sync_utc       : ISO-8601 timestamp of the last completed sync run
  delta_token         : Opaque incremental-query token (Graph deltaLink or GitHub HEAD SHA)
  drive_delta_tokens  : Per-drive delta tokens { drive_id -> deltaLink } (SharePoint)
  files               : { source_unique_key -> FileRecord }

FileRecord maps a source document to the Vertex AI RAG file resource name so we
can delete the correct RAG entry when the source document is removed or replaced.

Concurrency note: the store uses last-writer-wins. Running the cron job and the
webhook service simultaneously may cause one update to overwrite the other. For
most deployments this is acceptable — at worst a file is re-indexed on the next
scheduled run. Use Firestore if you need strict consistency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FileRecord:
    name: str
    last_modified: str       # ISO-8601 UTC
    rag_file_name: str       # projects/.../ragCorpora/.../ragFiles/...
    etag: str = ""           # eTag (SharePoint) or blob SHA (GitHub) for change detection


@dataclass
class ConnectorState:
    last_sync_utc: str = ""
    delta_token: str = ""                    # generic single-token connectors (GitHub HEAD SHA)
    drive_delta_tokens: dict[str, str] = field(default_factory=dict)   # SharePoint per-drive
    files: dict[str, FileRecord] = field(default_factory=dict)


@dataclass
class SyncState:
    connectors: dict[str, ConnectorState] = field(default_factory=dict)

    def connector(self, name: str) -> ConnectorState:
        if name not in self.connectors:
            self.connectors[name] = ConnectorState()
        return self.connectors[name]


class StateStore:
    """Loads and saves the full SyncState as a single JSON blob in GCS."""

    def __init__(self, gcs_uri: str) -> None:
        self._uri = gcs_uri

    def load(self) -> SyncState:
        try:
            from tools.utils.gcs_utils import read_gcs_text

            raw = json.loads(read_gcs_text(self._uri))
            state = SyncState()
            for name, data in raw.get("connectors", {}).items():
                files = {
                    k: FileRecord(**v) for k, v in data.get("files", {}).items()
                }
                state.connectors[name] = ConnectorState(
                    last_sync_utc=data.get("last_sync_utc", ""),
                    delta_token=data.get("delta_token", ""),
                    drive_delta_tokens=data.get("drive_delta_tokens", {}),
                    files=files,
                )
            logger.info(
                "Loaded sync state from %s (%d connector(s))",
                self._uri,
                len(state.connectors),
            )
            return state
        except Exception as exc:
            logger.warning(
                "Could not load sync state from %s (%s) — starting fresh.", self._uri, exc
            )
            return SyncState()

    def save(self, state: SyncState) -> None:
        try:
            from tools.utils.gcs_utils import write_gcs_text

            raw: dict = {"connectors": {}}
            for name, cs in state.connectors.items():
                raw["connectors"][name] = {
                    "last_sync_utc": cs.last_sync_utc,
                    "delta_token": cs.delta_token,
                    "drive_delta_tokens": cs.drive_delta_tokens,
                    "files": {k: asdict(v) for k, v in cs.files.items()},
                }
            write_gcs_text(self._uri, json.dumps(raw, indent=2), "application/json")
            logger.info("Saved sync state to %s", self._uri)
        except Exception as exc:
            logger.error("Failed to save sync state to %s: %s", self._uri, exc)
            raise
