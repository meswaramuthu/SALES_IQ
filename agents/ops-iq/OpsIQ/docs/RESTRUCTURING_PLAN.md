# OpsIQ — Restructuring / Migration Plan

## Overview

This document tracks the migration of OpsIQ from the original `new_folder_structure/` layout to the current `laabu-ai-app/` monorepo structure, and records structural decisions for future reference.

---

## Status: Complete

The migration has been completed. OpsIQ is now fully operating from the `laabu-ai-app/` monorepo layout.

---

## Changes Made

### 1. Path References Updated

All deployment scripts and the scheduler Dockerfile were updated from stale `new_folder_structure/` paths to the current repo-root-relative paths.

| File | Change |
|---|---|
| `deploy/deploy.py` | `_repo_root = Path(__file__).parents[4]` (was `new_folder_structure/`) |
| `deploy/deploy_full.py` | `_REPO_ROOT = _AGENT_ROOT.parents[2]` (removed `_SHARED_SRC`) |
| `scheduler/Dockerfile` | `COPY agents/ops-iq/OpsIQ/` (was `new_folder_structure/agents/...`) |
| `docs/README.md` | All `new_folder_structure/` → `laabu-ai-app/` |

### 2. `stratova_shared` Package Removed

The `stratova_shared` package was originally planned as a shared library at `agents/shared/`. That directory does not exist in the current monorepo — shared utilities were absorbed into `tools/` instead.

Removed references:
- `deploy/deploy.py`: removed hard import of `stratova_shared.session_service`
- `deploy/deploy_full.py`: removed `_SHARED_SRC` copy + removed `stratova_shared` from `extra_packages`
- `callbacks.py`: rewritten to write usage events directly to Firestore via `google.cloud.firestore`

### 3. Tool Registry Created

`tools/ops_iq_registry.py` was created to aggregate all 5 OpsIQ tool modules. The `agent.py` import `from tools.ops_iq_registry import get_all_tools` now resolves correctly.

### 4. Evaluation Infrastructure Added

Missing evaluation files were created to match the knowledge-iq pattern:
- `evaluation/conftest.py` — pytest sys.path setup
- `evaluation/run_eval.py` — ADK AgentEvaluator runner
- `evaluation/test_config.json` — ADK evaluation thresholds
- `evaluation/test_cases/ops_iq.test.json` — expanded to 20 test cases

### 5. Makefile Bug Fixed

`deploy-agent-only` target was using `--skip-scheduler` (non-existent flag). Corrected to `--skip-infrastructure`.

---

## Directory Structure (current)

```
laabu-ai-app/
├── agents/
│   ├── knowledge-iq/enterpriseGPT/    ← Knowledge IQ agent
│   └── ops-iq/OpsIQ/                  ← Ops IQ agent (this repo)
├── tools/
│   ├── google/                         ← Gmail, GDrive, quota, metrics
│   ├── vertex/                         ← Vertex AI resource inventory
│   ├── firestore/                      ← Per-user usage tracking
│   ├── alerting/                       ← Threshold alerting + email
│   ├── ops_iq_registry.py              ← OpsIQ tool aggregator (NEW)
│   ├── registry.py                     ← Knowledge IQ tool aggregator
│   └── utils/                          ← gcs_utils, date_time
└── deployment/                         ← Central infra scripts
```

---

## Python Path Convention

All agents use `pyproject.toml` with:
```toml
[tool.pytest.ini_options]
pythonpath = [".", "../../.."]
```

This means:
- `.` = the agent root (`OpsIQ/`) — makes `config`, `prompts`, `callbacks` importable
- `../../..` = the repo root (`laabu-ai-app/`) — makes `tools` importable

When running scripts directly (outside pytest), set:
```bash
PYTHONPATH="$(pwd):$(pwd)/../../.."
```

---

## Future Considerations

1. **Shared package** — if cross-agent utilities grow, consider creating `agents/shared/` with a proper `pyproject.toml` and re-introducing it as a local editable dependency.
2. **Multi-region** — currently hardcoded to `us-central1`. Add `GOOGLE_CLOUD_LOCATION` parameterisation to deployment scripts.
3. **Firestore indexes** — production will need a composite index on `(timestamp_utc ASC, agent_name ASC)` in the `ops_iq_usage` collection.
4. **Agent Engine autoscaling** — currently using default managed runtime. Monitor cold-start latency and consider `min_replica_count=1` for production.
