"""
OpsIQ — ADK Agent Evaluation Runner

Uses AgentEvaluator.evaluate() from google-adk[eval] to run all .test.json
eval cases against the live agent (Gemini 2.5 Flash + all tools).

ADK reads evaluation thresholds from test_cases/test_config.json automatically
(same directory as the .test.json files).

Run from the repo root:

    REPO_ROOT=/path/to/laabu-ai-app
    OPS=$REPO_ROOT/agents/ops-iq
    AGENT=$OPS/OpsIQ

    source $AGENT/.env

    PYTHONPATH="$OPS:$AGENT:$REPO_ROOT" \\
      $AGENT/.venv/bin/pytest \\
      $AGENT/evaluation/run_eval.py -v

Run a single suite:

    ... pytest $AGENT/evaluation/run_eval.py::test_quota_eval -v

Requirements:
    uv add "google-adk[eval]" pytest pytest-asyncio  (in agents/ops-iq/OpsIQ/)

Env vars required (from agents/ops-iq/OpsIQ/.env):
    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI=1
    TOOLS_CONFIG_GCS_URI, PROMPT_GCS_URI
"""

import pathlib
import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

# ─── Paths ───────────────────────────────────────────────────────────────────

THIS_DIR = pathlib.Path(__file__).parent
TEST_CASES_DIR = THIS_DIR / "test_cases"

# ADK 1.34.3 requires module_name.endswith(".agent") or module to have
# an attribute named "agent".  "OpsIQ.agent" satisfies the former.
# PYTHONPATH must include agents/ops-iq/ so that OpsIQ is importable as
# a top-level package.
AGENT_MODULE = "OpsIQ.agent"


# ─── Helper ──────────────────────────────────────────────────────────────────

def _eval_file(name: str) -> str:
    """Return absolute path to a test case file."""
    return str(TEST_CASES_DIR / name)


# ─── Eval suites ─────────────────────────────────────────────────────────────
# ADK automatically reads test_cases/test_config.json for thresholds:
#   tool_trajectory_avg_score = 1.0
#   response_match_score      = 0.0

@pytest.mark.asyncio
async def test_quota_eval():
    """Quota monitoring: list quotas, preferences, and headroom summary."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=_eval_file("ops_iq.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_full_eval_suite():
    """Run all eval cases in test_cases/ in a single pass."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=str(TEST_CASES_DIR),
        num_runs=1,
    )
