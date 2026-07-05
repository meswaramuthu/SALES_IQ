"""GitHub sync connector — compare API for efficient incremental file sync.

Delta strategy:
  State stores the HEAD commit SHA of the last successful sync per repo
  (in ConnectorState.delta_token for single-repo setups, or as a per-repo
  entry in ConnectorState.files with key "meta:{owner}/{repo}:head_sha").

  First run  : walk the full Git tree for the default branch
  Later runs : use repo.compare(last_sha, head_sha) to get only changed files

File filtering:
  Only files whose extension is in SYNC_GITHUB_FILE_EXTS (env) are indexed.
  Files larger than 1 MB are skipped (GitHub API limit is ~100 MB but RAG
  quality degrades for very large code files).

Webhook support:
  Validates the X-Hub-Signature-256 HMAC header using SYNC_GITHUB_WEBHOOK_SECRET.
  On a valid push event, the webhook server triggers an immediate delta sync for
  the affected repository.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from scheduler.connectors.base import BaseConnector, SyncResult
from scheduler.ingestion import RAG_SUPPORTED_EXTS, delete_from_rag, upload_to_rag
from scheduler.state import ConnectorState, FileRecord

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB
_META_KEY_PREFIX = "meta:"          # state key prefix for per-repo HEAD SHA entries

# Path segments that indicate generated / vendored content — never worth indexing
_SKIP_DIRS = frozenset({
    "node_modules", ".git", "dist", "build", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", ".tox", "vendor", "third_party",
    "bower_components", "target", "out", ".gradle", ".mvn",
    "coverage", ".nyc_output", ".cache",
})


def _in_skip_dir(path: str) -> bool:
    return any(part in _SKIP_DIRS for part in path.split("/"))


class GitHubConnector(BaseConnector):
    NAME = "github"

    def __init__(
        self,
        token: str,
        repos: list[str],           # ["owner/repo", ...]
        file_exts: frozenset[str],
        webhook_secret: str = "",
    ) -> None:
        self._token = token
        self._repos = repos
        self._file_exts = file_exts or RAG_SUPPORTED_EXTS
        self._webhook_secret = webhook_secret

    # ------------------------------------------------------------------
    # Public sync entry point
    # ------------------------------------------------------------------

    def sync(self, cs: ConnectorState, corpus: str) -> SyncResult:
        from github import Auth, Github, GithubException

        result = SyncResult(connector=self.NAME)
        gh = Github(auth=Auth.Token(self._token))

        for repo_full_name in self._repos:
            try:
                repo = gh.get_repo(repo_full_name)
                self._sync_repo(repo, cs, corpus, result)
            except GithubException as exc:
                msg = f"repo {repo_full_name}: {exc.data.get('message', exc)}"
                logger.error("GitHub — %s", msg)
                result.errors.append(msg)
            except Exception as exc:
                msg = f"repo {repo_full_name}: {exc}"
                logger.error("GitHub — %s", msg)
                result.errors.append(msg)

        cs.last_sync_utc = datetime.now(timezone.utc).isoformat()
        gh.close()
        return result

    # ------------------------------------------------------------------
    # Per-repo sync
    # ------------------------------------------------------------------

    def _head_sha_key(self, repo_name: str) -> str:
        return f"{_META_KEY_PREFIX}{repo_name}:head_sha"

    def _sync_repo(self, repo, cs: ConnectorState, corpus: str, result: SyncResult) -> None:
        repo_name = repo.full_name

        try:
            head_sha = repo.get_branch(repo.default_branch).commit.sha
        except Exception as exc:
            result.errors.append(f"get_head {repo_name}: {exc}")
            return

        meta_key = self._head_sha_key(repo_name)
        last_sha_record = cs.files.get(meta_key)
        last_sha = last_sha_record.etag if last_sha_record else ""

        if last_sha == head_sha:
            logger.debug("GitHub %s: no new commits since %s", repo_name, head_sha[:8])
            return

        if not last_sha:
            logger.info("GitHub %s: first run — full tree crawl at %s", repo_name, head_sha[:8])
            self._full_sync(repo, head_sha, cs, corpus, result)
        else:
            logger.info(
                "GitHub %s: delta sync %s..%s",
                repo_name,
                last_sha[:8],
                head_sha[:8],
            )
            self._delta_sync(repo, last_sha, head_sha, cs, corpus, result)

        # Persist HEAD SHA so the next run only processes newer commits
        cs.files[meta_key] = FileRecord(
            name=f"{repo_name}:head_sha",
            last_modified=datetime.now(timezone.utc).isoformat(),
            rag_file_name="",  # metadata record, not a RAG file
            etag=head_sha,
        )

    # ------------------------------------------------------------------
    # Full tree crawl (first run)
    # ------------------------------------------------------------------

    def _full_sync(self, repo, sha: str, cs: ConnectorState, corpus: str, result: SyncResult) -> None:
        try:
            tree = repo.get_git_tree(sha, recursive=True)
        except Exception as exc:
            result.errors.append(f"get_tree {repo.full_name}: {exc}")
            return

        for item in tree.tree:
            if item.type != "blob":
                continue
            if _in_skip_dir(item.path):
                continue
            _, ext = os.path.splitext(item.path)
            if ext.lower() not in self._file_exts:
                result.skipped += 1
                continue
            self._upsert_file(repo, item.path, item.sha, cs, corpus, result)

    # ------------------------------------------------------------------
    # Compare-based delta sync (subsequent runs)
    # ------------------------------------------------------------------

    def _delta_sync(
        self,
        repo,
        base_sha: str,
        head_sha: str,
        cs: ConnectorState,
        corpus: str,
        result: SyncResult,
    ) -> None:
        try:
            comparison = repo.compare(base_sha, head_sha)
        except Exception as exc:
            result.errors.append(f"compare {repo.full_name}: {exc}")
            return

        for file in comparison.files:
            if _in_skip_dir(file.filename):
                result.skipped += 1
                continue
            _, ext = os.path.splitext(file.filename)
            if ext.lower() not in self._file_exts:
                result.skipped += 1
                continue

            if file.status == "removed":
                state_key = f"{repo.full_name}/{file.filename}"
                record = cs.files.get(state_key)
                if record and record.rag_file_name:
                    if delete_from_rag(record.rag_file_name):
                        del cs.files[state_key]
                        result.deleted += 1
            else:
                # added, modified, renamed, copied
                blob_sha = file.sha or ""
                self._upsert_file(repo, file.filename, blob_sha, cs, corpus, result)

    # ------------------------------------------------------------------
    # Single file upsert
    # ------------------------------------------------------------------

    def _upsert_file(
        self,
        repo,
        path: str,
        blob_sha: str,
        cs: ConnectorState,
        corpus: str,
        result: SyncResult,
    ) -> None:
        state_key = f"{repo.full_name}/{path}"
        existing = cs.files.get(state_key)

        # Skip if already indexed at this exact blob SHA
        if existing and existing.etag == blob_sha and existing.rag_file_name:
            return

        try:
            file_obj = repo.get_contents(path)
            if isinstance(file_obj, list):
                return  # path resolved to a directory

            if file_obj.size > _MAX_FILE_BYTES:
                logger.warning(
                    "Skipping %s/%s — too large (%d bytes)", repo.full_name, path, file_obj.size
                )
                result.skipped += 1
                return

            # GitHub API returns base64-encoded content
            content = base64.b64decode(file_obj.content)
        except Exception as exc:
            result.errors.append(f"fetch {path}: {exc}")
            return

        # Remove stale RAG entry before uploading the new version
        if existing and existing.rag_file_name:
            delete_from_rag(existing.rag_file_name)

        filename = os.path.basename(path)
        display_name = f"github/{repo.full_name}/{path}"
        description = (
            f"GitHub: {repo.html_url}/blob/{repo.default_branch}/{path}"
        )
        _, ext = os.path.splitext(path)

        rag_name = upload_to_rag(
            content=content,
            filename=filename,
            display_name=display_name,
            corpus_name=corpus,
            description=description,
            source_metadata={
                "source": "github",
                "repo": repo.full_name,
                "file_ext": ext.lower().lstrip("."),
                "last_modified": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
        )
        if rag_name:
            cs.files[state_key] = FileRecord(
                name=path,
                last_modified=datetime.now(timezone.utc).isoformat(),
                rag_file_name=rag_name,
                etag=blob_sha,
            )
            result.upserted += 1
        else:
            result.errors.append(f"rag_upload_failed: {path}")

    # ------------------------------------------------------------------
    # Webhook helpers
    # ------------------------------------------------------------------

    def validate_webhook(
        self, headers: dict, body: bytes, query_params: dict
    ) -> tuple[bool, str]:
        if not self._webhook_secret:
            return True, ""  # no secret configured — accept all (not recommended in prod)

        sig_header = headers.get("x-hub-signature-256", "")
        if not sig_header.startswith("sha256="):
            return False, ""

        expected = "sha256=" + hmac.new(
            self._webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig_header, expected), ""

    def get_push_event_repo(self, body: bytes) -> str:
        """Return the full_name of the repo from a GitHub push event payload."""
        try:
            return json.loads(body).get("repository", {}).get("full_name", "")
        except Exception:
            return ""

    def get_push_event_head_sha(self, body: bytes) -> str:
        """Return the after (new HEAD) SHA from a GitHub push event payload."""
        try:
            return json.loads(body).get("after", "")
        except Exception:
            return ""
