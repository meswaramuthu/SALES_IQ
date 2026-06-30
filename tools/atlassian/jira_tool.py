"""Jira tool — Atlassian Cloud REST API v3 via atlassian-python-api.

Required credentials (set in tools_config.json or env vars):
  url        : https://your-org.atlassian.net
  username   : your-admin@your-org.com
  api_token  : Atlassian API token (create at id.atlassian.com → Security)

In tools_config.json, reference secrets as:  "api_token": "env:JIRA_API_TOKEN"

Tools exported:
  READ
    search_jira              - search issues with JQL
    get_jira_issue           - get full issue with comments
    get_jira_transitions     - list available workflow transitions for an issue

  CREATE
    create_jira_issue        - create a new issue/ticket/bug/story
    add_jira_comment         - post a comment on an issue

  UPDATE
    update_jira_issue        - update fields (summary, description, priority, labels)
    transition_jira_issue    - move issue to a different status/workflow state
    assign_jira_issue        - assign issue to a user by account ID

  DELETE
    delete_jira_issue        - permanently delete an issue
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _jira(cfg: dict):
    from atlassian import Jira

    return Jira(
        url=cfg.get("url", ""),
        username=cfg.get("username", ""),
        password=cfg.get("api_token", ""),
        cloud=True,
    )


def _to_adf(text: str) -> dict:
    """Wrap plain text in Atlassian Document Format for Jira Cloud v3."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def search_jira(jql: str, max_results: int = 10) -> dict:
        """Search Jira tickets using JQL (Jira Query Language).

        Use this tool to find bugs, tasks, stories, and epics in Jira.

        Args:
            jql: JQL query string. Examples:
                 'project = PROJ AND status = "In Progress"'
                 'text ~ "payment timeout" ORDER BY created DESC'
                 'assignee = currentUser() AND sprint in openSprints()'
            max_results: Maximum number of issues to return (default 10).

        Returns:
            dict with a list of Jira issues (key, summary, status, assignee, URL).
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            result = jira.jql(
                jql,
                limit=max_results,
                fields=["summary", "status", "assignee", "priority", "labels", "description"],
            )
            issues = [
                {
                    "key": i["key"],
                    "summary": i["fields"]["summary"],
                    "status": i["fields"]["status"]["name"],
                    "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned"),
                    "priority": (i["fields"].get("priority") or {}).get("name", ""),
                    "labels": i["fields"].get("labels", []),
                    "url": f"{cfg.config.get('url', '')}/browse/{i['key']}",
                }
                for i in result.get("issues", [])
            ]
            return {"issues": issues, "total": result.get("total", 0), "count": len(issues)}
        except Exception as exc:
            logger.error("Jira search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_jira_issue(issue_key: str) -> dict:
        """Get the full details of a Jira issue including description and comments.

        Use this after search_jira to read the complete content of a ticket.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').

        Returns:
            dict with summary, description, status, assignee, priority, and comments.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            issue = jira.get_issue(issue_key)
            fields = issue["fields"]
            comments_data = jira.issue_get_comments(issue_key)
            comments = []
            for c in comments_data.get("comments", []):
                body = c["body"]
                if isinstance(body, dict):
                    # ADF format — extract plain text
                    body = " ".join(
                        t.get("text", "")
                        for para in body.get("content", [])
                        for t in para.get("content", [])
                        if t.get("type") == "text"
                    )
                comments.append({
                    "author": c["author"]["displayName"],
                    "body": body,
                    "created": c["created"],
                })
            return {
                "key": issue_key,
                "summary": fields["summary"],
                "status": fields["status"]["name"],
                "description": fields.get("description", ""),
                "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "labels": fields.get("labels", []),
                "comments": comments,
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
            }
        except Exception as exc:
            logger.error("Jira get_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_jira_transitions(issue_key: str) -> dict:
        """Get available workflow transitions for a Jira issue.

        Use this before transition_jira_issue to see which status changes
        are allowed from the issue's current state.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').

        Returns:
            dict with list of transitions (id, name, to_status).
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            data = jira.get_issue_transitions(issue_key)
            # atlassian-python-api returns a plain list (not a dict)
            raw = data if isinstance(data, list) else data.get("transitions", [])
            transitions = []
            for t in raw:
                to = t.get("to", "")
                transitions.append({
                    "id": t["id"],
                    "name": t["name"],
                    # 'to' may be a plain string or a dict {'name': ...}
                    "to_status": to if isinstance(to, str) else to.get("name", ""),
                })
            return {"transitions": transitions, "issue_key": issue_key}
        except Exception as exc:
            logger.error("Jira get_transitions error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_jira_issue(
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str = "",
        priority: str = "",
        assignee: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new Jira issue (ticket, bug, story, task, epic).

        Args:
            project_key: Jira project key (e.g. 'ENG', 'OPS', 'PROD').
            summary: Issue title/summary.
            issue_type: Issue type name — 'Bug', 'Task', 'Story', 'Epic',
                        'Sub-task', or any custom type in your project.
                        Default 'Task'.
            description: Plain-text description of the issue. Optional.
            priority: Priority name — 'Highest', 'High', 'Medium', 'Low', 'Lowest'.
                      Leave blank to use the project default.
            assignee: Display name, email fragment, or Atlassian account ID of the
                      assignee. The name is resolved to an account ID automatically —
                      no need to look it up manually. Leave blank to leave unassigned.
                      If multiple users match the name, the tool returns the options
                      for the user to choose from.
            labels: List of label strings to apply (e.g. ['backend', 'urgent']).

        Returns:
            dict with created issue key, id, summary, and URL.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            fields: dict = {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
            if description:
                fields["description"] = description
            if priority:
                fields["priority"] = {"name": priority}
            if assignee:
                aid = assignee.strip()
                if ":" not in aid and len(aid) < 32:
                    results = jira.user_find_by_user_string(query=aid, start=0, limit=5)
                    active = [u for u in results if u.get("active") and u.get("accountType") == "atlassian"]
                    if not active:
                        return {"status": "error", "message": f"No active Jira user found matching '{aid}'. Use find_jira_user to search."}
                    if len(active) > 1:
                        opts = [
                            {"account_id": u["accountId"], "display_name": u.get("displayName", ""), "email": u.get("emailAddress", "")}
                            for u in active
                        ]
                        return {
                            "status": "needs_clarification",
                            "message": f"Multiple users match '{aid}'. Please ask the user to pick one:",
                            "options": opts,
                        }
                    aid = active[0]["accountId"]
                fields["assignee"] = {"accountId": aid}
            if labels:
                fields["labels"] = labels

            result = jira.create_issue(fields=fields)
            issue_key = result.get("key", "")
            return {
                "key": issue_key,
                "id": result.get("id", ""),
                "summary": summary,
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                "status": "created",
            }
        except Exception as exc:
            logger.error("Jira create_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_jira_comment(issue_key: str, body: str) -> dict:
        """Add a comment to a Jira issue.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').
            body: Comment text to post.

        Returns:
            dict with comment id, author, created timestamp, and URL.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            result = jira.issue_add_comment(issue_key, body)
            return {
                "id": result.get("id", ""),
                "author": result.get("author", {}).get("displayName", ""),
                "created": result.get("created", ""),
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                "status": "commented",
            }
        except Exception as exc:
            logger.error("Jira add_comment error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_jira_issue(
        issue_key: str,
        summary: str = "",
        description: str = "",
        priority: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        """Update fields of an existing Jira issue.

        Only the fields you supply are changed; omitted fields stay as-is.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').
            summary: New title/summary. Leave blank to keep existing.
            description: New description text. Leave blank to keep existing.
            priority: New priority — 'Highest', 'High', 'Medium', 'Low', 'Lowest'.
            labels: New label list (replaces existing labels entirely).
                    Pass empty list [] to remove all labels.

        Returns:
            dict with issue key and URL confirming the update.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            fields: dict = {}
            if summary:
                fields["summary"] = summary
            if description:
                fields["description"] = description
            if priority:
                fields["priority"] = {"name": priority}
            if labels is not None:
                fields["labels"] = labels
            if not fields:
                return {"status": "error", "message": "No fields to update were provided."}

            jira.update_issue_field(issue_key, fields=fields)
            return {
                "key": issue_key,
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                "status": "updated",
                "updated_fields": list(fields.keys()),
            }
        except Exception as exc:
            logger.error("Jira update_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def transition_jira_issue(issue_key: str, status_name: str) -> dict:
        """Transition a Jira issue to a different workflow status.

        Use get_jira_transitions first to see the available status names
        for the issue's current state.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').
            status_name: Target status name (e.g. 'In Progress', 'Done',
                         'Code Review', 'Closed', 'Reopened').

        Returns:
            dict with issue key and new status confirming the transition.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            jira.set_issue_status(issue_key, status_name)
            return {
                "key": issue_key,
                "new_status": status_name,
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                "status": "transitioned",
            }
        except Exception as exc:
            logger.error("Jira transition error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def find_jira_user(query: str) -> dict:
        """Search for a Jira user by name or email.

        Use this to resolve a person's name to their Atlassian account ID
        before assigning an issue. You can also pass the result directly to
        assign_jira_issue — it accepts display names as well as account IDs.

        Args:
            query: Name or email fragment to search (e.g. 'abdul', 'john.doe').

        Returns:
            dict with a list of matching users (account_id, display_name, email).
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            results = jira.user_find_by_user_string(query=query, start=0, limit=10)
            users = [
                {
                    "account_id": u["accountId"],
                    "display_name": u.get("displayName", ""),
                    "email": u.get("emailAddress", ""),
                    "active": u.get("active", True),
                }
                for u in results
                if u.get("accountType") == "atlassian"
            ]
            return {"users": users, "count": len(users)}
        except Exception as exc:
            logger.error("Jira find_user error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def assign_jira_issue(issue_key: str, assignee: str) -> dict:
        """Assign a Jira issue to a user.

        Accepts either a display name (e.g. 'Abdul', 'John Doe') or an
        Atlassian account ID. When a name is given, it is automatically
        resolved to the matching account ID — no need to look it up first.
        Pass 'unassigned' or leave blank to remove the current assignee.

        Args:
            issue_key: Jira issue key (e.g. 'PROJ-123').
            assignee: User display name, email fragment, or Atlassian account ID.
                      Pass 'unassigned' or empty string to remove the assignee.

        Returns:
            dict confirming the assignment with resolved display name.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)

            if not assignee or assignee.strip().lower() == "unassigned":
                jira.assign_issue(issue_key, None)
                return {
                    "key": issue_key,
                    "assignee": "unassigned",
                    "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                    "status": "assigned",
                }

            # If it looks like an account ID (contains ':' or is long hex), use directly.
            # Otherwise search by name/email.
            aid = assignee.strip()
            display_name = aid
            if ":" not in aid and len(aid) < 32:
                results = jira.user_find_by_user_string(query=aid, start=0, limit=5)
                active = [u for u in results if u.get("active") and u.get("accountType") == "atlassian"]
                if not active:
                    return {
                        "status": "error",
                        "message": f"No active Jira user found matching '{aid}'. Use find_jira_user to search.",
                    }
                if len(active) > 1:
                    matches = [u.get("displayName", "") for u in active]
                    return {
                        "status": "error",
                        "message": f"Multiple users match '{aid}': {matches}. Be more specific or use find_jira_user.",
                    }
                aid = active[0]["accountId"]
                display_name = active[0].get("displayName", aid)

            jira.assign_issue(issue_key, aid)
            return {
                "key": issue_key,
                "assignee": display_name,
                "assignee_account_id": aid,
                "url": f"{cfg.config.get('url', '')}/browse/{issue_key}",
                "status": "assigned",
            }
        except Exception as exc:
            logger.error("Jira assign_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_jira_issue(issue_key: str) -> dict:
        """Permanently delete a Jira issue.

        WARNING: This action is irreversible. The issue and all its comments,
        attachments, and history will be permanently removed.

        Args:
            issue_key: Jira issue key to delete (e.g. 'PROJ-123').

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("jira")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Jira tool is currently disabled."}
        try:
            jira = _jira(cfg.config)
            jira.delete_issue(issue_key)
            return {"key": issue_key, "status": "deleted"}
        except Exception as exc:
            logger.error("Jira delete_issue error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_jira,
        get_jira_issue,
        get_jira_transitions,
        find_jira_user,
        # Create
        create_jira_issue,
        add_jira_comment,
        # Update
        update_jira_issue,
        transition_jira_issue,
        assign_jira_issue,
        # Delete
        delete_jira_issue,
    ]
