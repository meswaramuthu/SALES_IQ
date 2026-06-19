.PHONY: install dev run web lint format test setup-corpus \
        deploy-full deploy-agent-only delete-all delete-agent \
        deploy upload-config upload-prompt

install:
	uv sync

dev:
	uv sync --group dev

run:
	uv run adk run knowledge_iq

web:
	uv run adk web

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest eval/ -v

# Create (or retrieve) the RAG corpus and optionally seed it.
# Override NAME to set the corpus display name.
# Example: make setup-corpus NAME="Engineering Docs" SEED_GCS=gs://my-bucket/docs/
NAME ?= "Knowledge IQ Corpus"
SEED_GCS ?=
SEED_URL ?=
setup-corpus:
	uv run python scripts/setup_corpus.py \
		--name $(NAME) \
		$(if $(SEED_GCS),--seed-gcs $(SEED_GCS),) \
		$(if $(SEED_URL),--seed-url $(SEED_URL),)

# ── One-go deploy / teardown ─────────────────────────────────────────────────
# Full deploy: infrastructure + corpus + config upload + agent engine + Gemini Enterprise
deploy-full:
	uv run python deployment/deploy_full.py

# Skip Gemini Enterprise (Agent Engine only)
deploy-agent-only:
	uv run python deployment/deploy_full.py --skip-gemini-enterprise

# Complete teardown: agent engine + corpus + GCS config objects
delete-all:
	uv run python deployment/deploy_full.py --delete --delete-corpus --delete-gcs-config

# Delete agent engine only (keep corpus and GCS config)
delete-agent:
	uv run python deployment/deploy_full.py --delete

# ── Individual steps ─────────────────────────────────────────────────────────
deploy:
	uv run python deployment/deploy.py

upload-config:
	uv run python scripts/upload_config.py config/tools_config.json

upload-prompt:
	uv run python scripts/upload_prompt.py config/prompt.txt

# Validate and configure a data connector, then upload updated config to GCS.
# CONNECTOR: sharepoint | github | jira | confluence | gmail | gdrive | hubspot | apollo
# ARGS: connector-specific flags, e.g. --tenant-id X --client-id Y --client-secret Z
# Examples:
#   make setup-connector CONNECTOR=github ARGS="--token env:GITHUB_TOKEN --default-org my-org"
#   make setup-connector CONNECTOR=sharepoint ARGS="--tenant-id X --client-id Y --client-secret Z"
#   make setup-connector CONNECTOR=github ARGS="--token env:GITHUB_TOKEN --dry-run"
CONNECTOR ?=
ARGS ?=
setup-connector:
	uv run python scripts/setup_connector.py $(CONNECTOR) $(ARGS)
