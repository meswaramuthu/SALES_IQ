"""
pytest configuration for enterpriseGPT evaluation.

ADK 1.34.3 requires agent_module to end with ".agent" (e.g. "enterpriseGPT.agent").
For that to work, sys.path must expose the parent of the enterpriseGPT package.

Paths injected:
  - knowledge-iq/          → makes `enterpriseGPT` importable as a package
  - enterpriseGPT/         → makes `config`, `prompts`, `scheduler` importable
  - new_folder_structure/  → makes `tools` importable

Run from repo root with:

    PYTHONPATH=new_folder_structure/agents/knowledge-iq:\
              new_folder_structure/agents/knowledge-iq/enterpriseGPT:\
              new_folder_structure \
      pytest new_folder_structure/agents/knowledge-iq/enterpriseGPT/evaluation/ -v
"""

import pathlib
import sys

# .../enterpriseGPT/evaluation/conftest.py
EVAL_DIR            = pathlib.Path(__file__).parent.resolve()
ENTERPRISE_GPT_ROOT = EVAL_DIR.parent                        # .../enterpriseGPT/
KNOWLEDGE_IQ_ROOT   = ENTERPRISE_GPT_ROOT.parent             # .../knowledge-iq/
NEW_FOLDER_ROOT     = KNOWLEDGE_IQ_ROOT.parent.parent        # .../new_folder_structure/

for path in [str(KNOWLEDGE_IQ_ROOT), str(ENTERPRISE_GPT_ROOT), str(NEW_FOLDER_ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)
