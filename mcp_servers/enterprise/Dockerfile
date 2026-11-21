FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py jira_sync.py data.json ./
# Listens on $PORT (Railway) or 8101, path /mcp. Keep it on a private network: it has no auth.
CMD ["python", "server.py"]
