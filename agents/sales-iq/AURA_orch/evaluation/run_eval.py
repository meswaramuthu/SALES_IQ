"""
enterpriseGPT — ADK Agent Evaluation Runner

Uses AgentEvaluator.evaluate() from google-adk[eval] to run all .test.json
eval cases against the live agent (Gemini 2.5 Flash + all tools).

ADK reads evaluation thresholds from test_cases/test_config.json automatically
(same directory as the .test.json files).

Run from the repo root:

    REPO_ROOT=/path/to/stratova-gcp
    KIQ=$REPO_ROOT/new_folder_structure/agents/knowledge-iq
    AGENT=$KIQ/enterpriseGPT
    NFS=$REPO_ROOT/new_folder_structure

    source $REPO_ROOT/agents/knowledge-iq/.env

    PYTHONPATH="$KIQ:$AGENT:$NFS" \\
      $REPO_ROOT/agents/knowledge-iq/.venv/bin/pytest \\
      $AGENT/evaluation/run_eval.py -v

Run a single suite:

    ... pytest $AGENT/evaluation/run_eval.py::test_rag_eval -v

Requirements:
    uv add "google-adk[eval]" pytest pytest-asyncio  (in agents/knowledge-iq/)

Env vars required (from agents/knowledge-iq/.env):
    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI=1
    TOOLS_CONFIG_GCS_URI, PROMPT_GCS_URI, RAG_CORPUS
"""

import pathlib
import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

# ─── Paths ───────────────────────────────────────────────────────────────────

THIS_DIR = pathlib.Path(__file__).parent
TEST_CASES_DIR = THIS_DIR / "test_cases"

# ADK 1.34.3 requires module_name.endswith(".agent") or module to have
# an attribute named "agent".  "enterpriseGPT.agent" satisfies the former.
# PYTHONPATH must include new_folder_structure/agents/knowledge-iq/ so that
# the enterpriseGPT package is importable as a top-level package.
AGENT_MODULE = "enterpriseGPT.agent"


# ─── Helper ──────────────────────────────────────────────────────────────────

def _eval_file(name: str) -> str:
    """Return absolute path to a test case file."""
    return str(TEST_CASES_DIR / name)


# ─── Eval suites ─────────────────────────────────────────────────────────────
# ADK automatically reads test_cases/test_config.json for thresholds:
#   tool_trajectory_avg_score = 1.0
#   response_match_score      = 0.1

@pytest.mark.asyncio
async def test_rag_eval():
    """RAG knowledge base: search, list, delete."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("rag.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="GitHub test cases need explicit owner/repo paths in user prompts — skipped until test data is updated")
@pytest.mark.asyncio
async def test_github_eval():
    """GitHub: repos, commits, PRs, issues, code search, file content."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("github.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="Jira and Confluence disabled in tools_config.json — enable them first")
@pytest.mark.asyncio
async def test_atlassian_eval():
    """Atlassian: Jira JQL search, issue detail, Confluence search and fetch."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("atlassian.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_sharepoint_eval():
    """Microsoft SharePoint: list sites, drives, file search, list items."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("sharepoint.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="Gemini Enterprise connector returns 400 (engine config mismatch) and Gmail is disabled — skipped until connectors are reconfigured")
@pytest.mark.asyncio
async def test_google_eval():
    """Google tools: Gmail search, Gemini Enterprise connector search."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("google.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="A2A request text is reformulated by the agent and is unpredictable — exact arg matching fails. Enable when ADK supports partial/wildcard arg matching.")
@pytest.mark.asyncio
async def test_a2a_eval():
    """A2A routing: CRM Agent (HubSpot), Enrichment Agent."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("a2a.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="Multi-tool cases include gemini_connectors which returns 400 — skipped until connector is fixed")
@pytest.mark.asyncio
async def test_multi_tool_eval():
    """Cross-source queries combining two or more tools in a single turn."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("multi_tool.test.json"),
        num_runs=1,
    )


@pytest.mark.skip(reason="Full suite includes disabled-connector test files — run individual suites (test_rag_eval, test_sharepoint_eval) instead")
@pytest.mark.asyncio
async def test_full_eval_suite():
    """Run all eval cases in test_cases/ in a single pass."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=str(TEST_CASES_DIR),
        num_runs=1,
    )
