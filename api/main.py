"""
api/main.py — FastAPI backend for the ShopWave Support Resolution Agent.

Routes:
  GET  /api/health                    — health check
  GET  /api/tickets                   — list all 20 tickets with status
  GET  /api/tickets/{ticket_id}       — single ticket + audit record
  POST /api/tickets/{ticket_id}/resolve — run agent, SSE stream
  POST /api/run-all                   — run all 20 tickets, SSE stream
  GET  /api/audit-log                 — returns audit_log.json
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Path setup — add shopwave-agent/ root to sys.path
# ---------------------------------------------------------------------------

_API_DIR = Path(__file__).parent
_AGENT_ROOT = _API_DIR.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

# Load .env from the agent root so API keys are available
from dotenv import load_dotenv
load_dotenv(_AGENT_ROOT / ".env")

# Import runner — works whether uvicorn is run from shopwave-agent/ or api/
try:
    from api.runner import run_ticket_sse, run_all_sse
except ImportError:
    from runner import run_ticket_sse, run_all_sse  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = _AGENT_ROOT / "data"
_AUDIT_LOG_PATH = _AGENT_ROOT / "audit_log.json"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="ShopWave Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tickets() -> list[dict]:
    with open(_DATA_DIR / "tickets.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_audit_log() -> dict | None:
    if not _AUDIT_LOG_PATH.exists():
        return None
    with open(_AUDIT_LOG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _get_ticket_status(ticket_id: str, audit_log: dict | None) -> str:
    """Derive ticket status from audit log."""
    if audit_log is None:
        return "pending"
    for record in audit_log.get("ticket_audit", []):
        if record.get("ticket_id") == ticket_id:
            resolution = record.get("resolution")
            if resolution == "APPROVE":
                return "resolved"
            elif resolution == "DENY":
                return "denied"
            elif resolution == "ESCALATE":
                return "escalated"
            elif record.get("processing_error"):
                return "error"
    return "pending"


def _append_to_audit_log(audit_record: dict) -> None:
    """Append a single audit record to audit_log.json."""
    existing = _load_audit_log()
    if existing is None:
        existing = {
            "execution_metadata": {
                "run_id": f"run_{datetime.datetime.now(datetime.timezone.utc).isoformat()}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "total_tickets": 0,
                "tickets_processed": 0,
                "tickets_resolved": 0,
                "tickets_escalated": 0,
                "tickets_errored": 0,
                "execution_time_ms": 0,
            },
            "ticket_audit": [],
        }

    # Replace or append
    ticket_id = audit_record.get("ticket_id")
    records = existing.get("ticket_audit", [])
    replaced = False
    for i, r in enumerate(records):
        if r.get("ticket_id") == ticket_id:
            records[i] = audit_record
            replaced = True
            break
    if not replaced:
        records.append(audit_record)

    existing["ticket_audit"] = records

    # Update metadata counts
    meta = existing.get("execution_metadata", {})
    meta["tickets_processed"] = len(records)
    meta["tickets_resolved"] = sum(
        1 for r in records if r.get("resolution") in ("APPROVE", "DENY")
    )
    meta["tickets_escalated"] = sum(
        1 for r in records if r.get("resolution") == "ESCALATE"
    )
    meta["tickets_errored"] = sum(
        1 for r in records if r.get("processing_error")
    )
    existing["execution_metadata"] = meta

    with open(_AUDIT_LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Redirect root to API health — all routes are under /api/"""
    return RedirectResponse(url="/api/health")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tickets")
async def list_tickets() -> list[dict]:
    """Return all 20 tickets with their current status."""
    tickets = _load_tickets()
    audit_log = _load_audit_log()

    result = []
    for ticket in tickets:
        ticket_id = ticket.get("ticket_id", "")
        status = _get_ticket_status(ticket_id, audit_log)
        result.append({**ticket, "status": status})
    return result


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> dict:
    """Return a single ticket plus its audit record if resolved."""
    tickets = _load_tickets()
    ticket = next((t for t in tickets if t.get("ticket_id") == ticket_id), None)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    audit_log = _load_audit_log()
    status = _get_ticket_status(ticket_id, audit_log)

    audit_record = None
    if audit_log:
        for record in audit_log.get("ticket_audit", []):
            if record.get("ticket_id") == ticket_id:
                audit_record = record
                break

    return {
        **ticket,
        "status": status,
        "audit_record": audit_record,
    }


@app.post("/api/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: str):
    """Run the agent on one ticket and stream SSE events."""
    tickets = _load_tickets()
    ticket = next((t for t in tickets if t.get("ticket_id") == ticket_id), None)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator() -> AsyncGenerator[str, None]:
        # Start the agent in a background task
        agent_task = asyncio.create_task(run_ticket_sse(ticket, queue))

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "error", "ticket_id": ticket_id, "message": "timeout"})
                    break

                yield json.dumps(event, default=str)

                if event.get("type") == "done":
                    break
        finally:
            # Wait for agent task and persist audit record
            try:
                audit_record = await asyncio.wait_for(agent_task, timeout=5.0)
                if audit_record and isinstance(audit_record, dict):
                    _append_to_audit_log(audit_record)
            except Exception:
                pass

    return EventSourceResponse(event_generator())


@app.post("/api/run-all")
async def run_all():
    """Run all 20 tickets concurrently and stream SSE events."""
    tickets = _load_tickets()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator() -> AsyncGenerator[str, None]:
        agent_task = asyncio.create_task(run_all_sse(tickets, queue))

        done_count = 0
        total = len(tickets)

        try:
            while done_count < total:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "error", "message": "timeout"})
                    break

                yield json.dumps(event, default=str)

                if event.get("type") == "done":
                    done_count += 1

                if done_count >= total:
                    break
        finally:
            try:
                audit_records = await asyncio.wait_for(agent_task, timeout=10.0)
                if audit_records and isinstance(audit_records, list):
                    for record in audit_records:
                        if isinstance(record, dict):
                            _append_to_audit_log(record)
            except Exception:
                pass

        yield json.dumps({"type": "all_done", "total": total})

    return EventSourceResponse(event_generator())


@app.get("/api/audit-log")
async def get_audit_log() -> Any:
    """Return audit_log.json if it exists."""
    audit_log = _load_audit_log()
    if audit_log is None:
        return JSONResponse(content={"ticket_audit": [], "execution_metadata": {}})
    return audit_log


@app.get("/api/learnings")
async def get_learnings() -> Any:
    """Return AGENT_LEARNINGS.md content if it exists."""
    learnings_path = _AGENT_ROOT / "AGENT_LEARNINGS.md"
    if not learnings_path.exists():
        return JSONResponse(content={"content": None, "exists": False})
    content = learnings_path.read_text(encoding="utf-8")
    return {"content": content, "exists": True}


@app.post("/api/generate-learnings")
async def generate_learnings_endpoint() -> Any:
    """Run the self-improvement loop against the current audit log."""
    audit_log = _load_audit_log()
    if not audit_log:
        raise HTTPException(status_code=404, detail="No audit log found. Run all tickets first.")

    audit_records = audit_log.get("ticket_audit", [])
    if not audit_records:
        raise HTTPException(status_code=404, detail="Audit log is empty.")

    try:
        from agent.self_improvement import generate_learnings
        learnings_path = _AGENT_ROOT / "AGENT_LEARNINGS.md"
        content = await generate_learnings(audit_records, output_path=learnings_path)
        return {"content": content, "exists": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Self-improvement failed: {str(e)}")


@app.get("/api/tickets/{ticket_id}/debate")
async def get_debate(ticket_id: str) -> Any:
    """Return the debate transcript for a ticket if it exists in the audit log."""
    audit_log = _load_audit_log()
    if not audit_log:
        raise HTTPException(status_code=404, detail="No audit log found")
    for record in audit_log.get("ticket_audit", []):
        if record.get("ticket_id") == ticket_id:
            checkpoints = record.get("checkpoint_events") or []
            for cp in checkpoints:
                if cp.get("debate_transcript"):
                    return {
                        "ticket_id": ticket_id,
                        "debate_transcript": cp["debate_transcript"],
                        "judge_reasoning": cp.get("reasoning_summary", ""),
                        "final_resolution": record.get("resolution"),
                    }
            return JSONResponse(content={"ticket_id": ticket_id, "debate_transcript": None})
    raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
