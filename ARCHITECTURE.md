# ShopWave Support Resolution Agent — Architecture

## Component Overview

```
main.py
  └── asyncio.gather() → 20 concurrent process_ticket() coroutines
        └── agent/graph.py (LangGraph StateGraph)
              ├── agent/state.py      (TicketState TypedDict)
              ├── agent/tools.py      (8 mock tool functions)
              ├── agent/decisions.py  (business rule evaluators)
              └── agent/session_memory.py (cross-ticket memory)
        └── utils/logger.py (TraceLogger → trace_log.jsonl)
  └── writes audit_log.json
```

## LangGraph State Machine — 15 Nodes

The agent is implemented as a directed graph where each node is an async function that receives the current `TicketState` and returns a partial state update.

| Node | Responsibility |
|---|---|
| `ingest_ticket` | Load ticket fields, emit `ticket_ingested` trace event |
| `analyze_sentiment` | LLM-based emotion/churn/urgency detection with rule-based fallback |
| `check_session_memory` | Query SessionMemory for prior fraud flags; short-circuit to escalate if found |
| `lookup_data` | Execute tool chain: `get_order` → `get_customer` → `get_product` → `search_knowledge_base` |
| `replan_lookup` | On tool failure, attempt alternative path (e.g. email → customer → order) |
| `evaluate_q1` | Q1: Can order and customer be identified? |
| `evaluate_q2` | Q2: Is the request within ShopWave policy? |
| `evaluate_q3` | Q3: Compute confidence score (0.0–1.0), adjusted by sentiment |
| `confidence_gate` | Route based on confidence and proposed resolution |
| `hitl_checkpoint` | Emit HITL checkpoint for high-stakes actions; auto-approve in demo mode |
| `approve_node` | Call `check_refund_eligibility` then `issue_refund` |
| `deny_node` | Set resolution to DENY |
| `escalate_node` | Call `escalate` tool, record case_id |
| `send_reply_node` | Build and send sentiment-adapted customer-facing reply |
| `write_audit` | Build audit record (incl. sentiment), write to results, update SessionMemory |

### Graph Flow

```
ingest_ticket
  → analyze_sentiment (detect emotion, churn risk, urgency)
  → check_session_memory
      → [prior fraud] → escalate_node
      → [no fraud]    → lookup_data
          → [tool error] → replan_lookup
              → [replan ok]       → evaluate_q1
              → [replan failed]   → escalate_node
          → [success]    → evaluate_q1
              → [Q1=false] → escalate_node (missing_data)
              → [Q1=true]  → evaluate_q2
                  → evaluate_q3
                      → confidence_gate
                          → [low confidence]  → escalate_node (ambiguous_request)
                          → [high-stakes]     → hitl_checkpoint
                              → approve_node / escalate_node
                          → [APPROVE]         → approve_node
                          → [DENY]            → deny_node
                          → [ESCALATE]        → escalate_node
  → send_reply_node → write_audit → END
```

## Five Advanced Agentic Capabilities

### 1. Self-Reflection & Confidence Scoring (`agent/decisions.py`)

After completing the tool chain and Q1/Q2 evaluation, `compute_confidence_score()` computes a weighted score:

- **data_completeness** (weight 0.4): fraction of expected data fields retrieved
- **reason_clarity** (weight 0.3): heuristic based on description length and issue type
- **policy_consistency** (weight 0.3): how clearly policy applies; reduced by prior denials; zeroed by prior fraud flags

Score < 0.75 → auto-escalate with `ambiguous_request`. Score and factors are recorded in the audit log.

### 2. Retry with Replanning (`agent/graph.py` — `replan_lookup_node`)

When `get_order` returns a not-found error:
1. Check `failed_tool_calls` to avoid identical retries
2. If customer email is available, call `get_customer(email)` as alternative
3. Record the attempt in `replan_attempts` with trigger, path, and outcome
4. If all paths exhausted → escalate with `missing_data`

### 3. Human-in-the-Loop Checkpointing (`agent/graph.py` — `hitl_checkpoint_node`)

High-stakes threshold:
- Refund amount > $200.00 (APPROVE path)
- Escalation category in `{threat_detected, social_engineering}` (ESCALATE path)

Uses LangGraph's `interrupt_before=["hitl_checkpoint"]` at compile time. In demo mode, all checkpoints are auto-approved with `auto_approved: true` recorded in the audit log.

### 4. Cross-Ticket Session Memory (`agent/session_memory.py`)

A single `SessionMemory` instance is shared across all 20 concurrent ticket coroutines. Protected by `asyncio.Lock` for thread safety.

- **Read phase** (`check_session_memory` node): query prior records for the customer before processing
- **Write phase** (`write_audit` node): write resolution + fraud flags after processing
- Prior `threat_detected` or `social_engineering` → immediately escalate current ticket with same category

### 5. Structured Observability (`utils/logger.py`)

`TraceLogger` writes one JSON object per line to `trace_log.jsonl` immediately on each event. Protected by `asyncio.Lock` to prevent interleaved output from concurrent coroutines.

Trace points: `ticket_ingested`, `tool_call_before/after`, `decision_evaluated` (Q1/Q2/Q3), `confidence_computed`, `checkpoint_emitted`, `replan_triggered/outcome`, `session_memory_read/write`, `resolution_final`.

## Data Flow

```
data/tickets.json
  → main.py loads 20 tickets
  → asyncio.gather() spawns 20 coroutines
  → each coroutine: initial_state(ticket) → graph.ainvoke()
      → nodes read from data/*.json via agent/tools.py
      → nodes write to TicketState (immutable updates)
      → write_audit_node appends to shared results list
      → write_audit_node writes to SessionMemory
      → TraceLogger writes to trace_log.jsonl (real-time)
  → main.py aggregates results → audit_log.json
```

## Concurrency Model

- `asyncio.gather(..., return_exceptions=True)` — all 20 tickets run concurrently
- Per-ticket exceptions are caught and recorded as error audit records
- `SessionMemory` and `TraceLogger` use `asyncio.Lock` for safe concurrent access
- `audit_log.json` is written once after all coroutines complete (no concurrent writes)
- Each ticket gets its own LangGraph thread via `config={"configurable": {"thread_id": ticket_id}}`
