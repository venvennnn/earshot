#!/usr/bin/env bash
# Start the MCP enterprise server, the backend and the web app for local development. Ctrl+C stops all three.
# Prerequisites: backend/.venv with requirements installed, web/node_modules, and .env filled in.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=backend/.venv/bin/python
[ -x "$PY" ] || { echo "Create the venv first: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }

trap 'kill 0' EXIT
(cd mcp_servers/enterprise && "../../$PY" server.py) &
(cd backend && .venv/bin/uvicorn main:app --reload --port 8000) &
(cd web && npm run dev) &
echo "MCP :8101 · backend :8000 · web http://localhost:5173 (Ctrl+C to stop)"
wait
