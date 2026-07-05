FROM python:3.11-slim
WORKDIR /app

# Build context is repo root (laabu-ai-app/).
# sync_deploy.sh passes the repo root as the Docker build context so all
# paths below are relative to laabu-ai-app/.

COPY agents/knowledge-iq/enterpriseGPT/scheduler/requirements.txt ./scheduler/requirements.txt
RUN pip install --no-cache-dir -r scheduler/requirements.txt

# scheduler package
COPY agents/knowledge-iq/enterpriseGPT/scheduler/ ./scheduler/

# config.py — imported by webhook_server and job as top-level module
COPY agents/knowledge-iq/enterpriseGPT/config.py .

# tools/utils — used by config.py to read TOOLS_CONFIG_GCS_URI from GCS
COPY tools/__init__.py ./tools/__init__.py
COPY tools/utils/ ./tools/utils/

ENV PORT=8080
EXPOSE 8080

# Default CMD runs the webhook server (Cloud Run Service).
# The Cloud Run Job overrides this with: python -m scheduler.job
CMD ["python", "-m", "scheduler.webhook_server"]
