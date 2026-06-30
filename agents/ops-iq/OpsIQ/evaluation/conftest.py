"""
pytest configuration for OpsIQ evaluation.

ADK 1.34.3 requires agent_module to end with ".agent" (e.g. "OpsIQ.agent").
For that to work, sys.path must expose the parent of the OpsIQ package.

Paths injected:
  - ops-iq/          → makes `OpsIQ` importable as a package
  - OpsIQ/           → makes `config`, `prompts`, `callbacks` importable
  - laabu-ai-app/    → makes `tools` importable

Run from repo root with:

    PYTHONPATH=agents/ops-iq:agents/ops-iq/OpsIQ:. \
      pytest agents/ops-iq/OpsIQ/evaluation/ -v
"""

import pathlib
import sys

# .../OpsIQ/evaluation/conftest.py
EVAL_DIR    = pathlib.Path(__file__).parent.resolve()
OPS_IQ_ROOT = EVAL_DIR.parent                        # .../OpsIQ/
OPS_DIR     = OPS_IQ_ROOT.parent                     # .../ops-iq/
REPO_ROOT   = OPS_DIR.parent.parent                  # .../laabu-ai-app/

for path in [str(OPS_DIR), str(OPS_IQ_ROOT), str(REPO_ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)
