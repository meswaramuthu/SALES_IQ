"""GitHub tool — full repository intelligence via PyGithub.

Token requirements (set GITHUB_TOKEN in Vertex Agent Engine env vars):
  - repo       : read access to private repos
  - read:org   : list org repos and search across org

In tools_config.json reference the token as:  "token": "env:GITHUB_TOKEN"

Tools exported:
  DISCOVERY
    list_github_repos          - list all repos in the configured org
    get_github_repository      - repo metadata, branches, topics, last activity

  COMMITS
    list_github_commits        - list commits with branch/author/date filters
    get_github_commit          - full commit: message, author, stats, every file changed with patch

  PULL REQUESTS
    list_github_pull_requests  - list PRs by state (open/closed/all)
    get_github_pull_request    - full PR: description, files changed (+patch), reviews, merge status

  ISSUES
    search_github_issues       - search issues AND PRs via GitHub search syntax
    get_github_issue           - full issue body + all comment thread

  CODE
    search_github_code         - full-text code search with content snippet
    get_github_file_content    - read any file at any branch/tag/SHA
"""
from __future__ import annotations

import base64
import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_MAX_PATCH_CHARS = 3_000  # per-file patch preview cap


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gh(token: str):
    from github import Auth, Github
    return Github(auth=Auth.Token(token))


def _token(cfg: dict) -> str:
    return cfg.get("token", "")


def _default_repo(cfg: dict) -> str:
    return cfg.get("default_repo", "")


def _org(cfg: dict) -> str:
    return cfg.get("default_org", "")


def _resolve_repo(cfg: dict, repo_arg: str) -> str:
    """Return repo arg if set, else default_repo from config."""
    return repo_arg or _default_repo(cfg)


def _fmt_file(f) -> dict:
    """Serialise a GitHub file-change object into a clean dict."""
    return {
        "filename": f.filename,
        "status": f.status,           # added | modified | removed | renamed
        "additions": f.additions,
        "deletions": f.deletions,
        "changes": f.changes,
        "patch": (f.patch or "")[:_MAX_PATCH_CHARS],  # actual diff lines
    }


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def get_tools() -> list[Callable]:

    # ── DISCOVERY ────────────────────────────────────────────────────────────

    def list_github_repos(max_results: int = 20) -> dict:
        """List all repositories in the configured GitHub organisation.

        Use this to discover which repos exist before drilling into commits or PRs.

        Args:
            max_results: Maximum repos to return (default 20).

        Returns:
            dict with list of repos (full_name, description, default_branch,
            language, is_empty, size_kb, updated_at).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh  = _gh(_token(cfg.config))
            org = _org(cfg.config)
            if not org:
                return {"status": "error", "message": "default_org is not set in GitHub config."}
            repos = [
                {
                    "full_name": r.full_name,
                    "description": r.description or "",
                    "default_branch": r.default_branch,
                    "language": r.language or "",
                    "is_empty": r.size == 0,
                    "size_kb": r.size,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                }
                for r in list(gh.get_organization(org).get_repos())[:max_results]
            ]
            return {"repos": repos, "count": len(repos), "org": org}
        except Exception as exc:
            logger.error("list_github_repos error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_github_repository(repo: str = "") -> dict:
        """Get detailed metadata for a GitHub repository.

        Returns description, branches, topics, language breakdown,
        and recent activity. Use this before searching commits or PRs
        to confirm branch names and repo state.

        Args:
            repo: Repository in 'owner/name' format. Uses default_repo from
                  config if not specified.

        Returns:
            dict with repo metadata, branch list, and open issue/PR counts.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}
            r = gh.get_repo(repo)
            branches = [b.name for b in list(r.get_branches())[:20]]
            return {
                "full_name": r.full_name,
                "description": r.description or "",
                "default_branch": r.default_branch,
                "language": r.language or "",
                "topics": r.get_topics(),
                "branches": branches,
                "open_issues": r.open_issues_count,
                "stars": r.stargazers_count,
                "size_kb": r.size,
                "is_empty": r.size == 0,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                "clone_url": r.clone_url,
            }
        except Exception as exc:
            logger.error("get_github_repository error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── COMMITS ──────────────────────────────────────────────────────────────

    def list_github_commits(
        repo: str = "",
        branch: str = "",
        author: str = "",
        since: str = "",
        until: str = "",
        path: str = "",
        max_results: int = 20,
    ) -> dict:
        """List commits in a repository with optional filters.

        Use this to audit recent changes, trace who touched what, or find
        commits in a date range. Each result shows files affected.

        Args:
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            branch: Branch or tag name (e.g. 'main', 'dev'). Defaults to repo's
                    default branch.
            author: Filter by GitHub login or email (e.g. 'abdulkadir').
            since: ISO 8601 start date (e.g. '2025-01-01' or '2025-01-01T00:00:00Z').
            until: ISO 8601 end date (e.g. '2025-12-31').
            path: Only commits that touched this file/directory (e.g. 'src/auth/').
            max_results: Maximum commits to return (default 20).

        Returns:
            dict with list of commits (sha, author, date, message, files_changed,
            additions, deletions).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            from datetime import datetime, timezone

            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r      = gh.get_repo(repo)
            kwargs: dict = {}
            if branch:
                kwargs["sha"] = branch
            if author:
                kwargs["author"] = author
            if since:
                kwargs["since"] = datetime.fromisoformat(since.rstrip("Z")).replace(tzinfo=timezone.utc)
            if until:
                kwargs["until"] = datetime.fromisoformat(until.rstrip("Z")).replace(tzinfo=timezone.utc)
            if path:
                kwargs["path"] = path

            commits = []
            for c in list(r.get_commits(**kwargs))[:max_results]:
                commits.append({
                    "sha": c.sha,
                    "sha_short": c.sha[:8],
                    "author_name": c.commit.author.name,
                    "author_login": c.author.login if c.author else "",
                    "date": c.commit.author.date.isoformat(),
                    "message": c.commit.message.strip(),
                    "additions": c.stats.additions,
                    "deletions": c.stats.deletions,
                    "total_changes": c.stats.total,
                    "files_changed": [f.filename for f in c.files],
                    "url": c.html_url,
                })
            return {"commits": commits, "count": len(commits), "repo": repo}
        except Exception as exc:
            logger.error("list_github_commits error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_github_commit(sha: str, repo: str = "") -> dict:
        """Get full details of a single commit including every file changed with diff.

        Use this after list_github_commits to inspect exactly what changed in a
        specific commit — the actual diff lines (patch) are included per file.

        Args:
            sha: Full or short commit SHA (e.g. '2df060f1' or full 40-char SHA).
            repo: Repository 'owner/name'. Uses default_repo if not specified.

        Returns:
            dict with commit metadata, stats, and a list of changed files each
            with filename, status (added/modified/removed), additions, deletions,
            and patch (diff lines, capped at 3000 chars per file).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r = gh.get_repo(repo)
            c = r.get_commit(sha)
            return {
                "sha": c.sha,
                "sha_short": c.sha[:8],
                "author_name": c.commit.author.name,
                "author_email": c.commit.author.email,
                "author_login": c.author.login if c.author else "",
                "committer_name": c.commit.committer.name,
                "date": c.commit.author.date.isoformat(),
                "message": c.commit.message.strip(),
                "parents": [p.sha[:8] for p in c.parents],
                "stats": {
                    "additions": c.stats.additions,
                    "deletions": c.stats.deletions,
                    "total": c.stats.total,
                },
                "files": [_fmt_file(f) for f in c.files],
                "url": c.html_url,
            }
        except Exception as exc:
            logger.error("get_github_commit error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── PULL REQUESTS ─────────────────────────────────────────────────────────

    def list_github_pull_requests(
        repo: str = "",
        state: str = "open",
        base: str = "",
        max_results: int = 20,
    ) -> dict:
        """List pull requests in a repository.

        Use this to see what's in review, recently merged, or pending.

        Args:
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            state: 'open', 'closed', or 'all' (default 'open').
            base: Filter by target branch (e.g. 'main', 'dev').
            max_results: Maximum PRs to return (default 20).

        Returns:
            dict with list of PRs (number, title, state, author, branches,
            additions, deletions, review status, URL).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r = gh.get_repo(repo)
            kwargs: dict = {"state": state}
            if base:
                kwargs["base"] = base

            prs = []
            for pr in list(r.get_pulls(**kwargs))[:max_results]:
                prs.append({
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "author": pr.user.login,
                    "base_branch": pr.base.ref,
                    "head_branch": pr.head.ref,
                    "draft": pr.draft,
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "changed_files": pr.changed_files,
                    "created_at": pr.created_at.isoformat(),
                    "updated_at": pr.updated_at.isoformat(),
                    "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    "url": pr.html_url,
                })
            return {"pull_requests": prs, "count": len(prs), "repo": repo}
        except Exception as exc:
            logger.error("list_github_pull_requests error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_github_pull_request(pr_number: int, repo: str = "") -> dict:
        """Get full details of a pull request including files changed and reviews.

        Use this to understand exactly what a PR changes, who reviewed it,
        and whether it is mergeable. Includes per-file diff patches.

        Args:
            pr_number: Pull request number.
            repo: Repository 'owner/name'. Uses default_repo if not specified.

        Returns:
            dict with PR metadata, description, list of changed files (with patch),
            reviews (approvals/changes-requested), and merge status.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r  = gh.get_repo(repo)
            pr = r.get_pull(pr_number)

            files   = [_fmt_file(f) for f in pr.get_files()]
            reviews = [
                {
                    "reviewer": rv.user.login,
                    "state": rv.state,           # APPROVED | CHANGES_REQUESTED | COMMENTED
                    "submitted_at": rv.submitted_at.isoformat() if rv.submitted_at else "",
                    "body": rv.body or "",
                }
                for rv in pr.get_reviews()
            ]
            comments = [
                {
                    "author": c.user.login,
                    "body": c.body,
                    "created_at": c.created_at.isoformat(),
                }
                for c in pr.get_issue_comments()
            ]
            return {
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "author": pr.user.login,
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref,
                "draft": pr.draft,
                "body": pr.body or "",
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files_count": pr.changed_files,
                "mergeable": pr.mergeable,
                "merged": pr.merged,
                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                "merged_by": pr.merged_by.login if pr.merged_by else None,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "url": pr.html_url,
                "files": files,
                "reviews": reviews,
                "comments": comments,
            }
        except Exception as exc:
            logger.error("get_github_pull_request error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── ISSUES ───────────────────────────────────────────────────────────────

    def search_github_issues(
        query: str,
        repo: str = "",
        state: str = "all",
        max_results: int = 10,
    ) -> dict:
        """Search GitHub issues and pull requests using GitHub search syntax.

        Use this to find bugs, feature requests, and PRs by keyword, label,
        assignee, or any GitHub search qualifier.

        Args:
            query: Search query. Supports GitHub qualifiers, e.g.:
                   'authentication error label:bug'
                   'type:pr is:merged base:main'
                   'assignee:abdulkadir is:open'
            repo: Restrict to 'owner/name'. Uses default_repo or default_org if blank.
            state: 'open', 'closed', or 'all' (default 'all').
            max_results: Maximum results (default 10).

        Returns:
            dict with list of issues/PRs (number, title, state, URL, labels, preview).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh  = _gh(_token(cfg.config))
            q   = query
            tgt = repo or _default_repo(cfg.config)
            if tgt:
                q += f" repo:{tgt}"
            elif _org(cfg.config):
                q += f" org:{_org(cfg.config)}"
            if state != "all":
                q += f" state:{state}"

            items = []
            for issue in gh.search_issues(q)[:max_results]:
                items.append({
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "is_pr": issue.pull_request is not None,
                    "repo": issue.repository.full_name,
                    "author": issue.user.login,
                    "labels": [lbl.name for lbl in issue.labels],
                    "created_at": issue.created_at.isoformat(),
                    "url": issue.html_url,
                    "body_preview": (issue.body or "")[:400],
                })
            return {"issues": items, "count": len(items)}
        except Exception as exc:
            logger.error("search_github_issues error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_github_issue(repo: str, issue_number: int) -> dict:
        """Get the full body and comment thread of a GitHub issue.

        Use this after search_github_issues to read a specific issue in full.
        For pull requests, use get_github_pull_request instead (which includes
        file diffs and reviews).

        Args:
            repo: Repository 'owner/name'.
            issue_number: Issue number.

        Returns:
            dict with title, body, state, labels, assignees, and all comments.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh    = _gh(_token(cfg.config))
            issue = gh.get_repo(repo).get_issue(issue_number)
            comments = [
                {
                    "author": c.user.login,
                    "body": c.body,
                    "created_at": c.created_at.isoformat(),
                }
                for c in issue.get_comments()
            ]
            return {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "is_pr": issue.pull_request is not None,
                "author": issue.user.login,
                "assignees": [a.login for a in issue.assignees],
                "labels": [lbl.name for lbl in issue.labels],
                "body": issue.body or "",
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "url": issue.html_url,
                "comments": comments,
            }
        except Exception as exc:
            logger.error("get_github_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CODE ─────────────────────────────────────────────────────────────────

    def search_github_code(query: str, repo: str = "", max_results: int = 10) -> dict:
        """Search code across GitHub repositories with content snippets.

        Use this to find where a function, variable, pattern, or string lives
        in the codebase.

        Args:
            query: Code search query (e.g. 'def authenticate', 'SECRET_KEY',
                   'TODO FIXME extension:py').
            repo: Restrict to 'owner/name'. Uses default_repo or default_org if blank.
            max_results: Maximum files (default 10).

        Returns:
            dict with list of matching files (name, path, repo, URL, content snippet).
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh  = _gh(_token(cfg.config))
            q   = query
            tgt = repo or _default_repo(cfg.config)
            if tgt:
                q += f" repo:{tgt}"
            elif _org(cfg.config):
                q += f" org:{_org(cfg.config)}"

            items = []
            for item in gh.search_code(q)[:max_results]:
                # Fetch a short content snippet
                snippet = ""
                try:
                    raw = item.repository.get_contents(item.path)
                    text = base64.b64decode(raw.content).decode("utf-8", errors="replace")
                    snippet = text[:600]
                except Exception:
                    pass
                items.append({
                    "name": item.name,
                    "path": item.path,
                    "repo": item.repository.full_name,
                    "url": item.html_url,
                    "sha": item.sha,
                    "content_snippet": snippet,
                })
            return {"files": items, "count": len(items)}
        except Exception as exc:
            logger.error("search_github_code error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_github_file_content(file_path: str, repo: str = "", ref: str = "") -> dict:
        """Read the content of any file in a GitHub repository.

        Use this to inspect source code, configuration, documentation, or any
        other file. Specify a branch or commit SHA to read a historical version.

        Args:
            file_path: Path to the file in the repo (e.g. 'src/auth/login.py',
                       'README.md', 'package.json').
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            ref: Branch name, tag, or commit SHA. Uses repo default branch if blank.

        Returns:
            dict with file path, ref, encoding, size, and decoded text content.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r       = gh.get_repo(repo)
            kwargs  = {"path": file_path}
            if ref:
                kwargs["ref"] = ref
            content = r.get_contents(**kwargs)

            if isinstance(content, list):
                # It's a directory
                return {
                    "type": "directory",
                    "path": file_path,
                    "entries": [c.name for c in content],
                }

            text = base64.b64decode(content.content).decode("utf-8", errors="replace")
            return {
                "path": content.path,
                "ref": ref or r.default_branch,
                "size_bytes": content.size,
                "sha": content.sha,
                "content": text,
                "url": content.html_url,
            }
        except Exception as exc:
            logger.error("get_github_file_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Discovery
        list_github_repos,
        get_github_repository,
        # Commits
        list_github_commits,
        get_github_commit,
        # Pull requests
        list_github_pull_requests,
        get_github_pull_request,
        # Issues
        search_github_issues,
        get_github_issue,
        # Code
        search_github_code,
        get_github_file_content,
    ]
