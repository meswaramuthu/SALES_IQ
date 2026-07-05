# Build context must be the repo root (laabu-ai-app/):
#   gcloud builds submit --tag=... agents/ops-iq/OpsIQ/scheduler/
#   OR: docker build -f agents/ops-iq/OpsIQ/scheduler/Dockerfile -t ops-iq-checker .
#
# Cloud Run Jobs pass all env vars at runtime via --set-env-vars.
# GCP auth uses Workload Identity of the attached service account.

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# agent source (OpsIQ package)
COPY agents/ops-iq/OpsIQ/ ./OpsIQ/

# shared tools
COPY tools/ ./tools/

# Install agent deps (shared already installed above)
RUN uv pip install --system --no-cache \
    google-cloud-aiplatform[agent_engines]>=1.148.1 \
    google-adk==1.34.3 \
    google-cloud-monitoring>=2.22.0 \
    google-cloud-quotas>=0.1.5 \
    google-cloud-firestore>=2.19.0 \
    google-cloud-storage>=2.0 \
    google-auth>=2.36.0 \
    pydantic>=2.0 \
    python-dotenv>=1.0.0 \
    requests>=2.32.3

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/OpsIQ

ENTRYPOINT ["python", "OpsIQ/scheduler/run_scheduled_check.py"]
