# ShopWave Support Resolution Agent

An autonomous AI agent that processes 20 customer support tickets end-to-end using a LangGraph state machine. The agent chains multiple tool calls per ticket, evaluates business rules, and produces APPROVE / DENY / ESCALATE resolutions with a full audit trail and LLM-generated customer replies.

---

## Demo

[![ShopWave Agent Demo](https://img.youtube.com/vi/4I0njRMqHII/0.jpg)](https://youtu.be/4I0njRMqHII)

▶ [Watch the full demo on YouTube](https://youtu.be/4I0njRMqHII)

---

## Quick Start (Single Command)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API keys
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (get free key at console.groq.com)

# 3. Run the agent against all 20 tickets
python main.py
```

Output: `audit_log.json` and `trace_log.jsonl` in the project root.

---

## Run with UI (Fullstack App)

```bash
# Terminal 1 — FastAPI backend
pip install fastapi uvicorn sse-starlette
python -m uvicorn api.main:app --reload --port 8000

# Terminal 2 — Next.js frontend
cd web
npm install
npm run dev
```

Open `http://localhost:3000`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph (Python) |
| Primary LLM | Groq — `llama-3.3-70b-versatile` |
| Fallback LLM | Anthropic — `claude-3-5-haiku-20241022` |
| Backend API | FastAPI + SSE streaming |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Concurrency | `asyncio.gather()` — all 20 tickets in parallel |
| State management | LangGraph `TicketState` TypedDict |

---

## Features

- **Concurrent processing** — all 20 tickets processed simultaneously via `asyncio.gather()`
- **Tool chaining** — minimum 3 tool calls per ticket (lookup → analyse → act)
- **Q1/Q2/Q3 decision framework** — structured reasoning for every resolution
- **Self-reflection & confidence scoring** — uncertain decisions auto-escalate below 0.75 threshold
- **Retry with replanning** — exponential backoff on transient failures, alternative lookup paths
- **Human-in-the-loop checkpointing** — pauses on high-stakes actions (refunds > $200, fraud)
- **Cross-ticket session memory** — detects fraud patterns across the run
- **LLM-generated replies** — Groq writes personalised customer emails; Anthropic as fallback
- **Structured observability** — real-time trace events written to `trace_log.jsonl`

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
GROQ_API_KEY=gsk_...          # Primary LLM — free at console.groq.com
ANTHROPIC_API_KEY=sk-ant-...  # Fallback LLM — console.anthropic.com
```

**Never commit `.env` to git.** It is listed in `.gitignore`.

---

## Project Structure

```
shopwave-agent/
├── main.py                    # CLI entry point — run all 20 tickets
├── agent/
│   ├── graph.py               # LangGraph state machine (15 nodes)
│   ├── tools.py               # 8 mock tool functions with realistic failures
│   ├── state.py               # TicketState TypedDict + enums
│   ├── decisions.py           # Business rule evaluators (Q1/Q2/Q3)
│   ├── llm_client.py          # Groq primary + Anthropic fallback
│   └── session_memory.py      # Cross-ticket fraud detection
├── api/
│   ├── main.py                # FastAPI routes + SSE streaming
│   └── runner.py              # SSETraceLogger + agent runner
├── web/                       # Next.js frontend
├── data/
│   ├── tickets.json           # 20 mock support tickets
│   ├── customers.json         # 10 customers (VIP/Premium/Standard)
│   ├── orders.json            # 20 orders with purchase dates
│   ├── products.json          # 8 products with return windows + warranties
│   └── knowledge-base.md      # ShopWave policy document
├── utils/
│   ├── logger.py              # TraceLogger (async-safe JSONL writer)
│   └── validators.py          # Output contract validators
├── tests/                     # 244 tests (unit + property + smoke + integration)
├── audit_log.json             # Generated output — all 20 tickets
├── trace_log.jsonl            # Real-time trace events
├── architecture.png           # 1-page architecture diagram
├── ARCHITECTURE.md            # Architecture documentation
├── FAILURE_MODES.md           # 5 failure scenarios with handling
└── HOW_IT_WORKS.md            # Complete technical walkthrough
```

---

## Tools Implemented

| Tool | Type | Description |
|---|---|---|
| `get_order(order_id)` | READ | Order details, status, timestamps |
| `get_customer(email)` | READ | Customer profile, tier, history |
| `get_product(product_id)` | READ | Product metadata, category, warranty |
| `search_knowledge_base(query)` | READ | Policy & FAQ semantic search |
| `check_refund_eligibility(order_id)` | WRITE | Returns eligibility + reason. May throw errors. |
| `issue_refund(order_id, amount)` | WRITE | IRREVERSIBLE — checks eligibility first |
| `send_reply(ticket_id, message)` | WRITE | Sends response to the customer |
| `escalate(ticket_id, summary, priority)` | WRITE | Routes to human with full context |

---

## Output Files

### `audit_log.json`
One record per ticket containing:
- All tool calls with inputs and outputs (ordered)
- Q1/Q2/Q3 boolean reasoning flags
- Confidence score (0.0–1.0) with factor breakdown
- LLM self-reflection note
- Final resolution (APPROVE/DENY/ESCALATE)
- Refund ID, case ID, or denial reason

### `trace_log.jsonl`
Newline-delimited JSON — one event per line, written in real time as the agent processes tickets. Events: `ticket_ingested`, `tool_call_before/after`, `decision_evaluated`, `confidence_computed`, `checkpoint_emitted`, `resolution_final`, and more.

---

## Running Tests

```bash
pytest tests/ --hypothesis-seed=0 --ignore=tests/integration -q
# 493 passed
```
