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

## Voice path (Phase 2)

```
Phone browser ⇄ Agora RTC channel ⇄ Agora Conversational AI agent
                                      ├─ ASR: Agora ARES (en-IN / hi-IN / ta-IN)
                                      ├─ LLM: our /v1/chat/completions (OpenAI format, SSE) → Gemini
                                      └─ TTS: Murf Falcon (Agora built-in "murf" vendor)
Browser ⇠ RTM ⇠ live transcripts, agent speaking state, latency metrics (agora-agent-client-toolkit)
```

- **Agora integration:** the backend uses Agora's official Python SDK (`agora-agents`) to start, stop and speak through agents. REST calls are signed with the App ID and Certificate, so no Customer ID or Secret is needed. Browser tokens (RTC and RTM) come from the same SDK. The agent runs with interruption on (`start_of_speech`), a 120 s idle timeout and the RTM data channel turned on.
- **Murf integration:** Murf Falcon is a built-in Agora TTS vendor (`vendor: "murf"`, `model` from `MURF_MODEL`, default `falcon-2.1`), so no TTS adapter is needed. The agent's voice is picked from Murf's own voice list (`GET /v1/speech/voices`) for the session's locale and cached. You can pin one with `MURF_AGENT_VOICE`.
- **Custom LLM:** Agora calls `${PUBLIC_BACKEND_URL}/v1/chat/completions?session=<channel>` with our secret as a Bearer key. EarShot keeps the conversation history per channel and streams back only the spoken text.

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

Agora's cloud must reach your backend over HTTPS. In dev, run a tunnel and set `PUBLIC_BACKEND_URL` to its URL:

```bash
cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
```

## Deploy

- **Backend → Railway:** new service from this repo with root directory `backend/` (it builds `backend/Dockerfile`). Set the variables from `.env.example`. `PUBLIC_BACKEND_URL` is the Railway domain, and `CORS_ORIGINS` must include your Vercel domain. Also set `AGENT_LLM_KEY`.
- **Web → Vercel:** new project with root directory `web/`, and set `VITE_BACKEND_URL` to the Railway domain.
