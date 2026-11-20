# EarShot

**Hear machine trouble before it becomes a breakdown.**

EarShot is a voice assistant for maintenance and quality workers. You talk to it on your phone, and it listens to the machine, compares it with that machine's healthy sound, says what is likely wrong, and then acts. It raises a work order, checks spares, takes the asset out of service, calls the right people in their own language and writes the shift report. Critical actions wait for a spoken "yes".

Built for **Build with Agora** (track: Voice AI at Work: Beyond the Call Center).

> 🚧 In progress. The full README (problem statement, Agora and Murf integration, agentic workflow, architecture diagram) comes with the final build phase.

## Layout

| Path | What | Deploys to |
|---|---|---|
| `backend/` | FastAPI: custom LLM endpoint for Agora, orchestrator, audio engine | Railway (Dockerfile) |
| `mcp_servers/enterprise/` | FastMCP server with mock enterprise systems | Railway (second service) |
| `web/` | Vite + React + TypeScript: website, phone app, dashboard | Vercel |

## Run locally

```bash
cp .env.example .env            # fill in keys
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8000
```

```bash
cd web && npm install && npm run dev   # http://localhost:5173
```

Health check: `GET http://localhost:8000/api/health` lists which integrations are configured (never values).
