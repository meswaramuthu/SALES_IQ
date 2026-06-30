.PHONY: install dev run web lint format test \
        deploy-full deploy-agent-only delete-all delete-agent \
        deploy upload-config upload-prompt eod-summary check

install:
	uv sync

dev:
	uv sync --group dev

run:
	uv run adk run ops_iq

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

# ── Scheduled checks (local testing) ─────────────────────────────────────────
check:
	PYTHONPATH="$(shell pwd):$(shell pwd)/../../.." uv run python scheduler/run_scheduled_check.py

eod-summary:
	PYTHONPATH="$(shell pwd):$(shell pwd)/../../.." uv run python scheduler/run_scheduled_check.py --eod-summary

user-report:
	PYTHONPATH="$(shell pwd):$(shell pwd)/../../.." uv run python scheduler/run_scheduled_check.py --user-report

agent-report:
	PYTHONPATH="$(shell pwd):$(shell pwd)/../../.." uv run python scheduler/run_scheduled_check.py --agent-report

# ── One-go deploy / teardown ─────────────────────────────────────────────────
deploy-full:
	uv run python deploy/deploy_full.py

deploy-agent-only:
	uv run python deploy/deploy_full.py --skip-infrastructure

delete-all:
	uv run python deploy/deploy_full.py --delete

delete-agent:
	uv run python deploy/deploy_full.py --delete

# ── Individual steps ─────────────────────────────────────────────────────────
deploy:
	uv run python deploy/deploy.py

upload-config:
	uv run python deploy/scripts/upload_config.py config/tools_config.json

upload-prompt:
	uv run python deploy/scripts/upload_prompt.py config/prompt.txt
