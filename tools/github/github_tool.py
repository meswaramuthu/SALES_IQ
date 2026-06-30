"""GitHub tool — full repository intelligence via PyGithub.

Token requirements (set GITHUB_TOKEN in Vertex Agent Engine env vars):
  - repo       : read AND write access to private repos
  - read:org   : list org repos and search across org
  - delete_repo: required only for delete_github_repository

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
    create_github_pull_request - open a new pull request
    merge_github_pull_request  - merge a pull request

  ISSUES
    search_github_issues       - search issues AND PRs via GitHub search syntax
    get_github_issue           - full issue body + all comment thread
    create_github_issue        - create a new issue
    update_github_issue        - update title, body, state, labels, assignees
    add_github_comment         - post a comment on an issue or PR

  CODE / FILES
    search_github_code         - full-text code search with content snippet
    get_github_file_content    - read any file at any branch/tag/SHA
    create_or_update_github_file - create or update a file in a repo
    delete_github_file         - delete a file from a repo

  BRANCHES
    create_github_branch       - create a new branch from an existing ref
    delete_github_branch       - delete a branch
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
                    "state": rv.state,
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

    def create_github_pull_request(
        title: str,
        head: str,
        base: str,
        body: str = "",
        repo: str = "",
        draft: bool = False,
    ) -> dict:
        """Create a new pull request in a GitHub repository.

        Args:
            title: PR title.
            head: Branch name with the changes to merge (e.g. 'feature/auth-fix').
            base: Target branch to merge into (e.g. 'main', 'dev').
            body: PR description (markdown supported). Optional.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            draft: Create as a draft PR (default False).

        Returns:
            dict with PR number, title, URL, and state.
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
            pr = r.create_pull(title=title, body=body, head=head, base=base, draft=draft)
            return {
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "url": pr.html_url,
                "head": head,
                "base": base,
                "draft": draft,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_github_pull_request error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def merge_github_pull_request(
        pr_number: int,
        repo: str = "",
        merge_method: str = "merge",
        commit_title: str = "",
        commit_message: str = "",
    ) -> dict:
        """Merge a pull request.

        Args:
            pr_number: Pull request number to merge.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            merge_method: Merge strategy — 'merge' (default), 'squash', or 'rebase'.
            commit_title: Custom merge commit title. Leave blank to use GitHub default.
            commit_message: Custom merge commit message. Leave blank to use GitHub default.

        Returns:
            dict with merge SHA and status confirming the merge.
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
            kwargs: dict = {"merge_method": merge_method}
            if commit_title:
                kwargs["commit_title"] = commit_title
            if commit_message:
                kwargs["commit_message"] = commit_message

            result = pr.merge(**kwargs)
            return {
                "pr_number": pr_number,
                "merged": result.merged,
                "sha": result.sha,
                "message": result.message,
                "status": "merged" if result.merged else "not_merged",
            }
        except Exception as exc:
            logger.error("merge_github_pull_request error: %s", exc)
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

    def create_github_issue(
        title: str,
        body: str = "",
        repo: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict:
        """Create a new GitHub issue.

        Args:
            title: Issue title.
            body: Issue description (markdown supported). Optional.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            labels: List of label names to apply (e.g. ['bug', 'priority:high']).
            assignees: List of GitHub usernames to assign (e.g. ['alice', 'bob']).

        Returns:
            dict with issue number, title, URL, and state.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            from github import GithubObject

            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r = gh.get_repo(repo)
            issue = r.create_issue(
                title=title,
                body=body or GithubObject.NotSet,
                labels=labels or GithubObject.NotSet,
                assignees=assignees or GithubObject.NotSet,
            )
            return {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "url": issue.html_url,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_github_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_github_issue(
        issue_number: int,
        repo: str = "",
        title: str = "",
        body: str = "",
        state: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict:
        """Update an existing GitHub issue.

        Only the fields you supply are changed; omitted fields stay as-is.

        Args:
            issue_number: Issue number to update.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            title: New title. Leave blank to keep existing.
            body: New description. Leave blank to keep existing.
            state: 'open' or 'closed'. Leave blank to keep existing.
            labels: New label list (replaces all existing labels).
            assignees: New assignee list (replaces all existing assignees).

        Returns:
            dict with updated issue number, title, state, and URL.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            from github import GithubObject

            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            issue = gh.get_repo(repo).get_issue(issue_number)
            kwargs: dict = {}
            if title:
                kwargs["title"] = title
            if body:
                kwargs["body"] = body
            if state in ("open", "closed"):
                kwargs["state"] = state
            if labels is not None:
                kwargs["labels"] = labels
            if assignees is not None:
                kwargs["assignees"] = assignees
            if not kwargs:
                return {"status": "error", "message": "No fields to update were provided."}

            issue.edit(**kwargs)
            return {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "url": issue.html_url,
                "status": "updated",
            }
        except Exception as exc:
            logger.error("update_github_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_github_comment(repo: str, issue_number: int, body: str) -> dict:
        """Post a comment on a GitHub issue or pull request.

        Args:
            repo: Repository 'owner/name'.
            issue_number: Issue or PR number to comment on.
            body: Comment text (markdown supported).

        Returns:
            dict with comment id, author, created_at, and URL.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh      = _gh(_token(cfg.config))
            issue   = gh.get_repo(repo).get_issue(issue_number)
            comment = issue.create_comment(body)
            return {
                "comment_id": comment.id,
                "author": comment.user.login,
                "created_at": comment.created_at.isoformat(),
                "url": comment.html_url,
                "status": "commented",
            }
        except Exception as exc:
            logger.error("add_github_comment error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CODE / FILES ──────────────────────────────────────────────────────────

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

    def create_or_update_github_file(
        file_path: str,
        content: str,
        commit_message: str,
        repo: str = "",
        branch: str = "",
    ) -> dict:
        """Create a new file or update an existing file in a GitHub repository.

        If the file already exists the current SHA is fetched automatically
        so you do not need to supply it.

        Args:
            file_path: Path where the file should be created/updated
                       (e.g. 'docs/runbook.md', 'src/config.py').
            content: Full file content as a plain text string (UTF-8).
            commit_message: Commit message for this change.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            branch: Branch to commit to. Uses repo default branch if blank.

        Returns:
            dict with file path, commit SHA, and URL.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r   = gh.get_repo(repo)
            ref = branch or r.default_branch

            try:
                existing = r.get_contents(file_path, ref=ref)
                result = r.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=existing.sha,
                    branch=ref,
                )
                action = "updated"
            except Exception:
                result = r.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch=ref,
                )
                action = "created"

            commit = result.get("commit")
            file_obj = result.get("content")
            return {
                "path": file_path,
                "branch": ref,
                "commit_sha": commit.sha if commit else "",
                "commit_message": commit_message,
                "url": file_obj.html_url if file_obj else "",
                "status": action,
            }
        except Exception as exc:
            logger.error("create_or_update_github_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_github_file(
        file_path: str,
        commit_message: str,
        repo: str = "",
        branch: str = "",
    ) -> dict:
        """Delete a file from a GitHub repository.

        Args:
            file_path: Path to the file to delete (e.g. 'docs/old-runbook.md').
            commit_message: Commit message for this deletion.
            repo: Repository 'owner/name'. Uses default_repo if not specified.
            branch: Branch to delete from. Uses repo default branch if blank.

        Returns:
            dict with commit SHA confirming the deletion.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r   = gh.get_repo(repo)
            ref = branch or r.default_branch
            existing = r.get_contents(file_path, ref=ref)
            result = r.delete_file(
                path=file_path,
                message=commit_message,
                sha=existing.sha,
                branch=ref,
            )
            commit = result.get("commit")
            return {
                "path": file_path,
                "branch": ref,
                "commit_sha": commit.sha if commit else "",
                "status": "deleted",
            }
        except Exception as exc:
            logger.error("delete_github_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── BRANCHES ──────────────────────────────────────────────────────────────

    def create_github_branch(
        branch_name: str,
        from_ref: str = "",
        repo: str = "",
    ) -> dict:
        """Create a new branch in a GitHub repository.

        Args:
            branch_name: Name for the new branch (e.g. 'feature/new-login',
                         'fix/auth-timeout').
            from_ref: Branch, tag, or commit SHA to branch from. Uses the
                      repo's default branch if blank.
            repo: Repository 'owner/name'. Uses default_repo if not specified.

        Returns:
            dict with new branch name, source SHA, and URL.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r      = gh.get_repo(repo)
            source = from_ref or r.default_branch
            sha    = r.get_branch(source).commit.sha
            r.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
            return {
                "branch": branch_name,
                "from_ref": source,
                "sha": sha,
                "url": f"{r.html_url}/tree/{branch_name}",
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_github_branch error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_github_branch(branch_name: str, repo: str = "") -> dict:
        """Delete a branch from a GitHub repository.

        The branch must not be the default branch. Use this to clean up
        feature branches after a PR is merged.

        Args:
            branch_name: Branch to delete.
            repo: Repository 'owner/name'. Uses default_repo if not specified.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("github")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "GitHub tool is currently disabled."}
        try:
            gh   = _gh(_token(cfg.config))
            repo = _resolve_repo(cfg.config, repo)
            if not repo:
                return {"status": "error", "message": "No repo specified and default_repo is not configured."}

            r   = gh.get_repo(repo)
            ref = r.get_git_ref(f"heads/{branch_name}")
            ref.delete()
            return {"branch": branch_name, "repo": repo, "status": "deleted"}
        except Exception as exc:
            logger.error("delete_github_branch error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Discovery
        list_github_repos,
        get_github_repository,
        # Commits
        list_github_commits,
        get_github_commit,
        # Pull Requests
        list_github_pull_requests,
        get_github_pull_request,
        create_github_pull_request,
        merge_github_pull_request,
        # Issues
        search_github_issues,
        get_github_issue,
        create_github_issue,
        update_github_issue,
        add_github_comment,
        # Code / Files
        search_github_code,
        get_github_file_content,
        create_or_update_github_file,
        delete_github_file,
        # Branches
        create_github_branch,
        delete_github_branch,
    ]
