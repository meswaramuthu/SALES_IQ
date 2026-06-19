"""Jira tool — Atlassian Cloud REST API v3 via atlassian-python-api.

Required credentials (set in tools_config.json or env vars):
  url        : https://your-org.atlassian.net
  username   : your-admin@your-org.com
  api_token  : Atlassian API token (create at id.atlassian.com → Security)

In tools_config.json, reference secrets as:  "api_token": "env:JIRA_API_TOKEN"
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


def get_tools() -> list[Callable]:
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
            comments_data = jira.get_issue_comments(issue_key)
            comments = [
                {
                    "author": c["author"]["displayName"],
                    "body": c["body"],
                    "created": c["created"],
                }
                for c in comments_data.get("comments", [])
            ]
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

    return [search_jira, get_jira_issue]
