# ShopWave Agent API

FastAPI backend for the ShopWave Support Resolution Agent.

## Setup

```bash
pip install -r requirements.txt
# Also install API-specific deps:
pip install fastapi uvicorn sse-starlette
```

## Run

From the `shopwave-agent/` directory:

```bash
uvicorn api.main:app --reload --port 8000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/tickets` | List all 20 tickets with current status |
| GET | `/api/tickets/{id}` | Single ticket + audit record |
| POST | `/api/tickets/{id}/resolve` | Run agent on one ticket (SSE stream) |
| POST | `/api/run-all` | Run all 20 tickets concurrently (SSE stream) |
| GET | `/api/audit-log` | Full `audit_log.json` |
| GET | `/api/learnings` | `AGENT_LEARNINGS.md` content |
| GET | `/api/tickets/{id}/debate` | Multi-agent debate transcript for a ticket |

## SSE Event Types

Events streamed during `/resolve` and `/run-all`:

| Type | Fields | Description |
|------|--------|-------------|
| `tool_call` | `ticket_id`, `tool_name`, `result`, `timestamp` | Tool executed |
| `decision` | `ticket_id`, `question`, `value` | Q1/Q2/Q3 gate evaluated |
| `confidence` | `ticket_id`, `score`, `factors` | Confidence score computed |
| `checkpoint` | `ticket_id`, `proposed_action`, `auto_approved`, `debate_transcript` | HITL checkpoint |
| `resolution` | `ticket_id`, `resolution`, `category`, `refund_id`, `case_id` | Final resolution |
| `reply` | `ticket_id`, `message` | Customer reply sent |
| `done` | `ticket_id` | Single ticket complete |
| `all_done` | `total` | All tickets complete |
| `error` | `ticket_id`, `message` | Processing error |

## CORS

Allowed origins are controlled by the `CORS_ORIGINS` environment variable (default: `http://localhost:3000`). Set it to a comma-separated list for multiple origins.

## Architecture

```
api/main.py     — FastAPI routes, SSE event generators, audit log persistence
api/runner.py   — SSETraceLogger, _process_one(), run_ticket_sse(), run_all_sse()
```

The runner bridges the LangGraph agent with SSE by replacing the file-based `TraceLogger` with an `SSETraceLogger` that puts events into an `asyncio.Queue`. The Next.js frontend consumes these events via the `/api/*` proxy in `next.config.js`.
