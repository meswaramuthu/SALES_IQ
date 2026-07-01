.PHONY: install dev run web lint format test \
        deploy-full deploy-agent-only delete-all delete-agent \
        deploy upload-config upload-prompt

install:
	uv sync

dev:
	uv sync --group dev

run:
	uv run adk run aura

web:
	uv run adk web

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest evaluation/ -v

# ── One-go deploy / teardown ─────────────────────────────────────────────────
# Full deploy: infrastructure + config upload + agent engine
deploy-full:
	uv run python deploy/deploy_full.py

# Skip Gemini Enterprise (Agent Engine only)
deploy-agent-only:
	uv run python deploy/deploy_full.py --skip-gemini-enterprise

# Complete teardown: agent engine + GCS config objects
delete-all:
	uv run python deploy/deploy_full.py --delete --delete-gcs-config

# Delete agent engine only (keep GCS config)
delete-agent:
	uv run python deploy/deploy_full.py --delete

# ── Individual steps ─────────────────────────────────────────────────────────
deploy:
	uv run python deploy/deploy.py

upload-config:
	uv run python deploy/scripts/upload_config.py AURA_orch/tools_config.json

upload-prompt:
	uv run python deploy/scripts/upload_prompt.py AURA_orch/prompt.md
