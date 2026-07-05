FROM python:3.11-slim
WORKDIR /app

COPY scheduler/requirements.txt ./scheduler/requirements.txt
RUN pip install --no-cache-dir -r scheduler/requirements.txt

COPY scheduler/ ./scheduler/

ENV PORT=8080
EXPOSE 8080

# Default CMD runs the webhook server (Cloud Run Service).
# The Cloud Run Job overrides this with: python -m scheduler.job
CMD ["python", "-m", "scheduler.webhook_server"]
