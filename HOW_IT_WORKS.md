# How ShopWave Support Resolution Agent Works

A complete technical walkthrough — every component, every call, every decision.

---

## The Big Picture

You have 20 customer support tickets. Instead of routing them to humans, an AI agent processes each one autonomously. It looks up data, evaluates business rules, scores its own confidence, and either approves a refund, denies a request, or escalates to a human — then writes a personalised reply to the customer.

Everything is logged. Every tool call, every reasoning step, every LLM output.

---

## System Components

```
shopwave-agent/
├── agent/          ← The AI agent (LangGraph state machine)
├── api/            ← FastAPI backend (serves the frontend)
├── web/            ← Next.js frontend (the UI)
├── data/           ← Mock data (tickets, customers, orders, products, KB)
├── utils/          ← Logging, validation
├── main.py         ← CLI entry point (run all 20 tickets from terminal)
├── audit_log.json  ← Generated output after each run
└── trace_log.jsonl ← Real-time trace events (one JSON per line)
```

---

## Part 1: The Agent (`agent/`)

### What it is

A **LangGraph state machine** — a directed graph where each node is an async Python function. The agent processes one ticket at a time by passing a `TicketState` object through the graph. Each node reads from the state, does work, and returns a partial update.

### The 15 nodes (in order)

```
ingest_ticket
    ↓
analyze_sentiment (detect emotion, churn risk, urgency)
    ↓
check_session_memory
    ↓ (no prior fraud)
lookup_data  ──→ replan_lookup (if tool fails)
    ↓
evaluate_q1  ──→ escalate_node (if Q1 = false)
    ↓
evaluate_q2
    ↓
evaluate_q3
    ↓
confidence_gate ──→ hitl_checkpoint (if high-stakes)
    ↓
approve_node / deny_node / escalate_node
    ↓
send_reply_node
    ↓
write_audit
```

### Node-by-node breakdown

**`ingest_ticket`**
Loads the ticket fields into state. Emits a `ticket_ingested` trace event.

**`analyze_sentiment`**
Analyses the customer's emotional state using LLM-based sentiment detection with rule-based fallback. Detects:
- **Primary emotion**: angry, frustrated, confused, desperate, calm, sarcastic, neutral
- **Churn risk**: high, medium, low (based on emotion + churn signals like "cancel my account")
- **Urgency**: critical, high, medium, low
- **Recommended tone**: determines how `send_reply_node` will phrase its response

The result enriches the entire downstream pipeline — confidence scoring adjusts based on emotion, HITL thresholds adapt, and the customer reply is tone-matched.

**`check_session_memory`**
Queries the in-memory `SessionMemory` store for prior records of this customer. If a previous ticket from the same customer was flagged as `threat_detected` or `social_engineering`, the current ticket is immediately routed to escalation — no further processing needed.

**`lookup_data`**
Executes the tool chain:
1. `get_customer(email)` — fetches customer profile, tier (VIP/premium/standard), and any pre-approved exceptions
2. `get_order(order_id)` — fetches order details, purchase date, amount, status
3. `get_product(product_id)` — fetches product metadata, return window (15–60 days), warranty period (0–24 months)
4. `search_knowledge_base(query)` — for threat/social_engineering/ambiguous tickets, searches the ShopWave policy KB

Each tool call is wrapped with `with_retry()` — exponential backoff on transient failures (timeouts, malformed responses). Permanent failures (not_found) are not retried.

If `get_order` fails and no order ID was provided (e.g. T020), the node routes to `replan_lookup`.

**`replan_lookup`**
Alternative lookup path when the primary tool chain fails. Tries `get_customer(email)` as a fallback to locate the customer even without an order ID. Records each attempt in `replan_attempts`. If all paths are exhausted, escalates with `missing_data`.

**`evaluate_q1`**
Checks: are both `order` and `customer` present in state without error keys?
- True → continue
- False → escalate with `missing_data`

**`evaluate_q2`**
Evaluates policy compliance using `decisions.py`. Checks in order:
1. Threat language (sue, lawyer, legal action, chargeback...) → `threat_detected`
2. Social engineering patterns (on behalf of, authorized representative, bypass...) → `social_engineering`
3. Ambiguous issue type → `ambiguous_request`
4. Missing order data → `missing_data`
5. Replacement request → `replacement_needed`
6. Warranty claim → calls `check_refund_eligibility`, routes to `warranty_claim` if within warranty
7. Refund request → calls `check_refund_eligibility`, returns eligible/ineligible/escalate

**`evaluate_q3`**
Computes a **confidence score** (0.0–1.0) from three weighted factors:
- `data_completeness` (weight 0.4): how much of the expected data was retrieved
- `reason_clarity` (weight 0.3): heuristic based on description length and issue type
- `policy_consistency` (weight 0.3): how clearly the policy applies; reduced by prior denials; zeroed by prior fraud flags

**This is where the LLM is called for the first time.** After computing the numeric score, the agent calls `chat_completion()` to generate a human-readable self-reflection note explaining *why* it made the decision it did. This note appears in the audit log.

If score < 0.75 → auto-escalate with `ambiguous_request`.

**`confidence_gate`**
Routes based on score and proposed resolution:
- Low confidence → escalate
- High-stakes action (refund > $200 or fraud escalation) → `hitl_checkpoint`
- Otherwise → approve / deny / escalate

**`hitl_checkpoint`**
Human-in-the-loop pause point. In demo mode, auto-approves and records `auto_approved: true`. In production, the graph would pause here (LangGraph `interrupt_before`) and wait for a human to review before proceeding.

**`approve_node`**
Calls `check_refund_eligibility(order_id)` to confirm eligibility, then calls `issue_refund(order_id, amount)`. If eligibility returns `"escalate"` (within warranty), routes to escalation instead.

**`deny_node`**
Sets `resolution = DENY` with the denial reason from `evaluate_q2`.

**`escalate_node`**
Calls `escalate(ticket_id, summary, priority)`. Priority is derived from escalation category:
- `threat_detected` / `social_engineering` → `urgent`
- `warranty_claim` / `replacement_needed` → `medium`
- `missing_data` / `ambiguous_request` → `low`

**`send_reply_node`**
**This is where the LLM is called for the second time.** Builds a context prompt with the ticket description, customer name, resolution, and relevant details. The prompt is **enriched with sentiment context** — tone guidance (e.g. "lead with a sincere apology" for angry customers), churn risk alerts, and the detected emotion. Falls back to a template if the LLM is unavailable.

**`write_audit`**
Builds the full audit record from state, appends it to the shared results list, writes a `SessionRecord` to `SessionMemory`, and emits `resolution_final` and `session_memory_write` trace events.

---

## Part 2: The LLM Client (`agent/llm_client.py`)

### Two providers, one interface

```python
await chat_completion(messages, system, max_tokens, temperature)
```

**Primary: Groq** (`llama-3.3-70b-versatile` via `console.groq.com`)
Fast, free tier available, `gsk_` API key.

**Fallback: Anthropic** (`claude-3-5-haiku-20241022`)
If Groq fails for any reason (rate limit, error, unavailable), the same call is automatically retried with Anthropic. If both fail, `LLMUnavailableError` is raised and the node falls back to a rule-based template.

### Where exactly the LLM is called

| Location | Purpose | Prompt content |
|---|---|---|
| `evaluate_q3_node` in `graph.py` | Self-reflection note | Ticket description, Q1/Q2 results, confidence factors, escalation category |
| `send_reply_node` in `graph.py` | Customer reply email | Customer name, resolution, order ID, denial reason or refund details, **sentiment context** |
| `analyze_sentiment_node` in `graph.py` | Sentiment analysis | Ticket description, issue type, customer tier |

The LLM is **not** used for routing decisions. All APPROVE/DENY/ESCALATE decisions are deterministic rule-based logic. The LLM only generates natural language output.

---

## Part 3: The Tools (`agent/tools.py`)

All 8 tools are mock functions that read from local JSON files. They never make real API calls.

### Realistic failure simulation

Every tool has a 5% chance of returning a transient error (timeout or malformed response). This is intentional — the spec requires tools that "fail realistically." The `with_retry()` wrapper handles these with exponential backoff.

### Tool contracts

| Tool | Input | Output |
|---|---|---|
| `get_order(order_id)` | Order ID string | Order record or `{"error": "not_found"}` |
| `get_customer(email)` | Email or customer ID | Customer record with tier, VIP exceptions |
| `get_product(product_id)` | Product ID string | Product with return_window_days, warranty_months |
| `search_knowledge_base(query)` | Query string | Relevant policy sections from `knowledge-base.md` |
| `check_refund_eligibility(order_id)` | Order ID only | `{eligible: true/false/"escalate", reason: "..."}` |
| `issue_refund(order_id, amount)` | Order ID + amount | `{refund_id: "REF-...", status: "issued"}` |
| `send_reply(ticket_id, message)` | Ticket ID + message | `{delivered: true, timestamp: "..."}` |
| `escalate(ticket_id, summary, priority)` | Ticket ID + summary + priority | `{case_id: "ESC-...", status: "escalated"}` |

`check_refund_eligibility` contains the core business logic:
- Computes days since purchase
- Applies VIP extended return window (90 days for Alice and Emma) instead of product default
- Returns `eligible: true` if within window
- Returns `eligible: "escalate"` if outside window but within warranty
- Returns `eligible: false` if outside both

---

## Part 4: Session Memory (`agent/session_memory.py`)

An in-process dictionary protected by `asyncio.Lock`. Persists for the lifetime of one run (cleared between runs).

**Write:** After each ticket resolves, a `SessionRecord` is written keyed by `customer_id`.

**Read:** At the start of each ticket (`check_session_memory` node), prior records for the same customer are loaded. If any prior record has `threat_detected` or `social_engineering`, the current ticket is immediately escalated with the same category — no tool calls needed.

**Why this matters:** T011 (Bob's social engineering attempt) and T010 (threat) are from different customers, but if the same customer had two tickets in one run, the second would be auto-escalated based on the first.

---

## Part 5: Observability (`utils/logger.py` + `trace_log.jsonl`)

Every step emits a structured trace event to `trace_log.jsonl` (newline-delimited JSON). Events are written immediately, protected by `asyncio.Lock` to prevent interleaved output from concurrent coroutines.

### Event types

| Event | When |
|---|---|
| `ticket_ingested` | Ticket enters the graph |
| `tool_call_before` | Before each tool call |
| `tool_call_after` | After each tool call (with result) |
| `decision_evaluated` | Q1, Q2, Q3 evaluated |
| `confidence_computed` | Confidence score calculated |
| `checkpoint_emitted` | HITL checkpoint triggered |
| `replan_triggered` | Alternative lookup path started |
| `replan_outcome` | Replan attempt result |
| `session_memory_read` | Prior records queried |
| `session_memory_write` | Resolution written to memory |
| `resolution_final` | Final resolution determined |

---

## Part 6: The FastAPI Backend (`api/`)

### What it does

Wraps the agent in an HTTP API so the frontend can trigger runs and receive real-time updates.

### Routes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/health` | Returns `{"status": "ok"}` |
| `GET` | `/api/tickets` | Returns all 20 tickets with current status (pending/resolved/denied/escalated) |
| `GET` | `/api/tickets/{id}` | Returns single ticket + audit record if already resolved |
| `POST` | `/api/tickets/{id}/resolve` | Runs agent on one ticket, **streams SSE events** |
| `POST` | `/api/run-all` | Runs all 20 tickets concurrently, **streams SSE events** |
| `GET` | `/api/audit-log` | Returns `audit_log.json` |

### How SSE streaming works

Instead of the file-based `TraceLogger`, the API uses `SSETraceLogger` — a drop-in replacement that puts events into an `asyncio.Queue` instead of writing to a file.

```
Frontend                    FastAPI                     Agent Graph
   |                           |                            |
   |-- POST /resolve --------> |                            |
   |                           |-- create asyncio.Queue --> |
   |                           |-- start agent task ------> |
   |                           |                            |-- tool_call_after → queue.put()
   |<-- data: {"type":"tool_call"...} -------------------- |
   |                           |                            |-- decision_evaluated → queue.put()
   |<-- data: {"type":"decision"...} --------------------- |
   |                           |                            |-- confidence_computed → queue.put()
   |<-- data: {"type":"confidence"...} ------------------- |
   |                           |                            |-- resolution → queue.put()
   |<-- data: {"type":"resolution"...} ------------------- |
   |<-- data: {"type":"reply"...} ------------------------ |
   |<-- data: {"type":"done"...} ------------------------- |
   |                           |-- append to audit_log.json|
```

The `event_generator()` function reads from the queue and yields each event as an SSE `data:` line. The frontend consumes this with `fetch` + `ReadableStream`.

---

## Part 7: The Next.js Frontend (`web/`)

### Pages

**`/` (Dashboard)**
Split layout. Left sidebar shows all 20 tickets with tier dots (gold=VIP, silver=premium, grey=standard) and status badges. Clicking a ticket shows it in the main area. If already resolved, shows the audit detail. If not, shows a "Resolve ticket" button that starts the SSE stream.

**`/run` (Run All)**
4×5 grid of ticket cards. Hitting "Run All 20" calls `POST /api/run-all` and opens an SSE stream. Cards transition from idle → pulsing indigo border (processing) → colored resolved state. Live stats bar shows counts and elapsed time.

**`/audit` (Audit Log)**
Sortable, filterable table of all resolved tickets. Columns: ticket ID, customer, issue type, resolution, confidence score, tool call count, timestamp.

**`/tickets/[id]` (Ticket Detail)**
Full audit record: tool call timeline (collapsible input/output), Q1/Q2/Q3 gates, animated confidence bars, agent self-reflection note, customer reply.

### How the frontend consumes SSE

```typescript
// api.ts
const response = await fetch(`/api/tickets/${ticketId}/resolve`, { method: "POST" });
const reader = response.body!.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split("\n");
  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const event = JSON.parse(line.slice(6));
      onEvent(event);  // updates Zustand store → re-renders AgentStream component
    }
  }
}
```

### State management (Zustand)

```typescript
{
  tickets: Ticket[],                          // all 20 tickets with status
  selectedTicketId: string | null,            // which ticket is selected in sidebar
  auditRecords: Record<string, AuditRecord>,  // resolved ticket audit data
  processingTickets: Set<string>,             // which tickets are currently running
  streamEvents: Record<string, SSEEvent[]>,   // live events per ticket
}
```

---

## Part 8: Concurrency

All 20 tickets are processed simultaneously using `asyncio.gather()`. Each ticket gets its own LangGraph thread (via `config={"configurable": {"thread_id": ticket_id}}`). The `SessionMemory` and `SSETraceLogger` are shared across all coroutines and protected by `asyncio.Lock`.

Expected time: ~20–30 seconds for all 20 tickets (limited by Groq API rate limits, not compute).

---

## Part 9: Data Flow End-to-End

```
data/tickets.json
    ↓ loaded by main.py or api/main.py
    ↓
asyncio.gather(20 coroutines)
    ↓ each coroutine:
    ↓
initial_state(ticket) → TicketState TypedDict
    ↓
graph.ainvoke(state)
    ↓
[15 nodes execute in sequence]
    ↓
    ├── get_customer(email)     → data/customers.json
    ├── get_order(order_id)     → data/orders.json
    ├── get_product(product_id) → data/products.json
    ├── search_knowledge_base() → data/knowledge-base.md
    ├── check_refund_eligibility() → business logic (no external call)
    ├── issue_refund()          → mock (no external call)
    ├── send_reply()            → mock (no external call)
    └── escalate()              → mock (no external call)
    ↓
LLM call 1: Groq → self-reflection note
LLM call 2: Groq → customer reply email
    ↓
write_audit_node
    ↓
audit_log.json (appended)
trace_log.jsonl (appended in real time)
SessionMemory (in-process, cleared between runs)
```

---

## Part 10: Running the App

### CLI (no UI)
```bash
cd shopwave-agent
python main.py
# Processes all 20 tickets, writes audit_log.json and trace_log.jsonl
```

### With UI
```bash
# Terminal 1 — FastAPI backend
cd shopwave-agent
python -m uvicorn api.main:app --reload --port 8000

# Terminal 2 — Next.js frontend
cd shopwave-agent/web
npm run dev
# Open http://localhost:3000
```

### Environment variables (`.env`)
```
ANTHROPIC_API_KEY=sk-ant-...   # fallback LLM (needs credits)
GROQ_API_KEY=gsk_...           # primary LLM (free tier available)
```

---

## Key Design Decisions

**Why rule-based decisions + LLM for language only?**
Deterministic routing means the agent is auditable and predictable. The LLM is used where it adds value — natural language generation — not where rules are clearer and faster.

**Why LangGraph?**
Explicit state machine means every transition is visible, testable, and inspectable. The graph can be paused (HITL), replayed, and debugged. No hidden reasoning loops.

**Why SSE instead of WebSockets?**
SSE is unidirectional (server → client), simpler to implement, and perfectly suited for streaming agent events. No need for bidirectional communication here.

**Why Groq as primary?**
Free tier, fast inference (llama-3.3-70b), no credits needed. Anthropic is the fallback for when Groq is unavailable or rate-limited.

**Why 5% tool failure rate?**
The hackathon spec explicitly says "build mocks that fail realistically." The retry logic with exponential backoff demonstrates production-grade error handling.
