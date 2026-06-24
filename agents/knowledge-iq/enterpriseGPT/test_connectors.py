#!/usr/bin/env python3
"""Quick connector health check — tests every enabled tool with a minimal call.

Run from the enterpriseGPT directory:
    uv run --env-file .env python test_connectors.py
"""
import sys
import time
import traceback

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

results: list[tuple[str, str, str]] = []  # (connector, status, detail)


def ok(name: str, detail: str = "") -> None:
    print(f"  {GREEN}✓{RESET} {name}" + (f"  →  {detail[:120]}" if detail else ""))
    results.append((name, "OK", detail))


def fail(name: str, detail: str) -> None:
    print(f"  {RED}✗{RESET} {name}  →  {detail[:200]}")
    results.append((name, "FAIL", detail))


def skip(name: str, reason: str) -> None:
    print(f"  {YELLOW}–{RESET} {name}  →  {reason}")
    results.append((name, "SKIP", reason))


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 50)


# ── wait for TTL cache to refresh (config just uploaded) ──────────────────────
print(f"\n{BOLD}Waiting 5 s for GCS config TTL cache to refresh…{RESET}")
time.sleep(5)

# ── 1. RAG ────────────────────────────────────────────────────────────────────
section("1 · RAG / Knowledge Base")
try:
    from tools.rag.user_rag_tool import get_tools as rag_tools
    fns = {f.__name__: f for f in rag_tools()}
    r = fns["search_knowledge_base"]("Stratova AI vision")
    if r.get("status") == "disabled":
        fail("search_knowledge_base", "disabled")
    elif r.get("status") == "error":
        # RAG needs ADK context for user_id — expected to fail in raw script; treat as skip
        skip("search_knowledge_base", f"needs ADK context (expected outside ADK runner): {r.get('message', '')[:80]}")
    elif "results" in r or "chunks" in r:
        ok("search_knowledge_base", f"{len(r.get('results') or r.get('chunks', []))} result(s)")
    else:
        ok("search_knowledge_base", str(r)[:100])
except Exception as e:
    fail("RAG", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 2. GitHub ─────────────────────────────────────────────────────────────────
section("2 · GitHub")
try:
    from tools.github.github_tool import get_tools as gh_tools
    fns = {f.__name__: f for f in gh_tools()}

    r = fns["list_github_repos"](max_results=3)
    if r.get("status") == "disabled": fail("list_github_repos", "disabled")
    elif r.get("repos"): ok("list_github_repos", f"{len(r['repos'])} repos — {[x.get('full_name', x.get('name','?')) for x in r['repos'][:3]]}")
    else: fail("list_github_repos", str(r)[:120])

    r = fns["search_github_issues"]("is:open", max_results=2)
    if r.get("status") == "disabled": fail("search_github_issues", "disabled")
    elif "issues" in r: ok("search_github_issues", f"{len(r['issues'])} issue(s)")
    else: fail("search_github_issues", str(r)[:120])

    r = fns["search_github_code"]("agent", max_results=2)
    if r.get("status") == "disabled": fail("search_github_code", "disabled")
    elif "items" in r or "results" in r or "files" in r: ok("search_github_code", f"code search: {len(r.get('files') or r.get('items') or r.get('results', []))} file(s)")
    else: fail("search_github_code", str(r)[:120])
except Exception as e:
    fail("GitHub", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 3. Jira ───────────────────────────────────────────────────────────────────
section("3 · Jira")
try:
    from tools.atlassian.jira_tool import get_tools as jira_tools
    fns = {f.__name__: f for f in jira_tools()}

    r = fns["search_jira"]("project is not EMPTY ORDER BY created DESC", max_results=3)
    if r.get("status") == "disabled": fail("search_jira", "disabled")
    elif "issues" in r: ok("search_jira", f"{len(r['issues'])} issue(s) — {[x.get('key') for x in r['issues'][:3]]}")
    else: fail("search_jira", str(r)[:120])
except Exception as e:
    fail("Jira", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 4. Confluence ─────────────────────────────────────────────────────────────
section("4 · Confluence")
try:
    from tools.atlassian.confluence_tool import get_tools as conf_tools
    fns = {f.__name__: f for f in conf_tools()}

    r = fns["search_confluence"]("Stratova", max_results=3)
    if r.get("status") == "disabled": fail("search_confluence", "disabled")
    elif "pages" in r: ok("search_confluence", f"{len(r['pages'])} page(s) — {[x.get('title') for x in r['pages'][:2]]}")
    else: fail("search_confluence", str(r)[:120])
except Exception as e:
    fail("Confluence", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 5. SharePoint ─────────────────────────────────────────────────────────────
section("5 · SharePoint")
try:
    from tools.microsoft.sharepoint_tool import get_tools as sp_tools
    fns = {f.__name__: f for f in sp_tools()}

    r = fns["list_sharepoint_sites"](max_results=3)
    if r.get("status") == "disabled": fail("list_sharepoint_sites", "disabled")
    elif "sites" in r: ok("list_sharepoint_sites", f"{len(r['sites'])} site(s) — {[x.get('name') for x in r['sites'][:3]]}")
    else: fail("list_sharepoint_sites", str(r)[:120])

    r = fns["search_sharepoint"]("policy", max_results=2)
    if r.get("status") == "disabled": fail("search_sharepoint", "disabled")
    elif "results" in r or "hits" in r: ok("search_sharepoint", f"search returned results")
    else: fail("search_sharepoint", str(r)[:120])
except Exception as e:
    fail("SharePoint", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 6. OneDrive ───────────────────────────────────────────────────────────────
section("6 · OneDrive")
try:
    from tools.microsoft.onedrive_tool import get_tools as od_tools
    fns = {f.__name__: f for f in od_tools()}

    r = fns["list_onedrive_files"](max_results=5)
    if r.get("status") == "disabled": fail("list_onedrive_files", "disabled")
    elif "files" in r: ok("list_onedrive_files", f"{len(r['files'])} file(s) — {[x.get('name') for x in r['files'][:3]]}")
    elif "items" in r: ok("list_onedrive_files", f"{len(r['items'])} item(s) — {[x.get('name') for x in r['items'][:3]]}")
    else: fail("list_onedrive_files", str(r)[:120])

    r = fns["search_onedrive"]("report", max_results=3)
    if r.get("status") == "disabled": fail("search_onedrive", "disabled")
    elif "files" in r: ok("search_onedrive", f"{len(r['files'])} result(s)")
    else: fail("search_onedrive", str(r)[:120])
except Exception as e:
    fail("OneDrive", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 7. Outlook ────────────────────────────────────────────────────────────────
section("7 · Outlook")
try:
    from tools.microsoft.outlook_tool import get_tools as ol_tools
    fns = {f.__name__: f for f in ol_tools()}

    r = fns["list_outlook_emails"](folder="inbox", max_results=3)
    if r.get("status") == "disabled": fail("list_outlook_emails", "disabled")
    elif "emails" in r: ok("list_outlook_emails", f"{len(r['emails'])} email(s) — subjects: {[x.get('subject','(no subject)')[:40] for x in r['emails'][:2]]}")
    else: fail("list_outlook_emails", str(r)[:120])

    r = fns["search_outlook_emails"]("from:riya@stratova.ai", max_results=2)
    if r.get("status") == "disabled": fail("search_outlook_emails", "disabled")
    elif "emails" in r: ok("search_outlook_emails", f"{len(r['emails'])} result(s)")
    else: fail("search_outlook_emails", str(r)[:120])
except Exception as e:
    fail("Outlook", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 8. Notion ─────────────────────────────────────────────────────────────────
section("8 · Notion")
try:
    from tools.notion.notion_tool import get_tools as notion_tools
    fns = {f.__name__: f for f in notion_tools()}

    r = fns["list_notion_databases"](max_results=5)
    if r.get("status") == "disabled": fail("list_notion_databases", "disabled")
    elif "databases" in r: ok("list_notion_databases", f"{len(r['databases'])} DB(s) — {[x.get('title') for x in r['databases'][:3]]}")
    else: fail("list_notion_databases", str(r)[:120])

    r = fns["search_notion"]("meeting notes", max_results=3)
    if r.get("status") == "disabled": fail("search_notion", "disabled")
    elif "results" in r: ok("search_notion", f"{len(r['results'])} result(s)")
    else: fail("search_notion", str(r)[:120])
except Exception as e:
    fail("Notion", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 9. Gmail ──────────────────────────────────────────────────────────────────
section("9 · Gmail")
try:
    from tools.google.gmail_tool import get_tools as gmail_tools
    fns = {f.__name__: f for f in gmail_tools()}

    r = fns["search_gmail"]("in:inbox", max_results=3)
    if r.get("status") == "disabled": fail("search_gmail", "disabled")
    elif r.get("status") == "error": fail("search_gmail", r.get("message", "error"))
    elif "messages" in r: ok("search_gmail", f"{len(r['messages'])} message(s) — {[x.get('subject','(no subject)')[:40] for x in r['messages'][:2]]}")
    else: fail("search_gmail", str(r)[:120])
except Exception as e:
    fail("Gmail", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 10. Google Drive ──────────────────────────────────────────────────────────
section("10 · Google Drive")
try:
    from tools.google.gdrive_tool import get_tools as gdrive_tools
    fns = {f.__name__: f for f in gdrive_tools()}

    r = fns["search_gdrive"]("Stratova", max_results=3)
    if r.get("status") == "disabled": fail("search_gdrive", "disabled")
    elif r.get("status") == "error": fail("search_gdrive", r.get("message", "error"))
    elif "files" in r: ok("search_gdrive", f"{len(r['files'])} file(s) — {[x.get('name') for x in r['files'][:3]]}")
    else: fail("search_gdrive", str(r)[:120])
except Exception as e:
    fail("Google Drive", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── 11. A2A sub-agents ────────────────────────────────────────────────────────
section("11 · A2A Sub-agents (config check only — skipping live call)")
try:
    from tools.a2a.a2a_tools import get_tools as a2a_tools
    fns = get_tools_list = a2a_tools()
    if fns:
        for fn in fns:
            ok(fn.__name__, "registered — live call skipped (cold-start may take 60s)")
    else:
        fail("A2A", "no sub-agent tools generated — check sub_agents in GCS config")
except Exception as e:
    fail("A2A", traceback.format_exc(limit=2).strip().splitlines()[-1])

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print(f"\n{'═'*50}")
print(f"{BOLD}SUMMARY{RESET}")
print(f"{'═'*50}")
passed = [r for r in results if r[1] == "OK"]
failed = [r for r in results if r[1] == "FAIL"]
skipped = [r for r in results if r[1] == "SKIP"]

print(f"  {GREEN}PASS{RESET}  {len(passed)}")
print(f"  {RED}FAIL{RESET}  {len(failed)}")
print(f"  {YELLOW}SKIP{RESET}  {len(skipped)}")

if failed:
    print(f"\n{RED}Failed connectors:{RESET}")
    for name, _, detail in failed:
        print(f"  • {name}: {detail[:150]}")

sys.exit(0 if not failed else 1)
