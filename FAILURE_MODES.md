# ShopWave Support Resolution Agent — Failure Mode Analysis

## Failure Mode 1: Tool Not Found (Order/Customer/Product Missing)

**Trigger:** `get_order`, `get_customer`, or `get_product` returns `{"error": "not_found", ...}`.

**How it's handled:**
1. `lookup_data_node` detects the error key in the result
2. Adds the call to `failed_tool_calls` to prevent identical retries
3. Routes to `replan_lookup_node`
4. `replan_lookup_node` attempts an alternative path (e.g. `get_customer` by email)
5. If the alternative succeeds, processing continues normally
6. If all alternatives are exhausted, escalates with `escalation_category: missing_data`

**Audit log entry:**
```json
{
  "resolution": "ESCALATE",
  "escalation_category": "missing_data",
  "replan_attempts": [
    {
      "trigger": "get_order not_found",
      "alternative_path": "get_customer(email@example.com)",
      "outcome": "failed"
    }
  ],
  "processing_error": null
}
```

---

## Failure Mode 2: All Replans Exhausted

**Trigger:** `get_order` fails, `get_customer` by email also fails, no further alternatives exist.

**How it's handled:**
1. `replan_lookup_node` records each failed attempt in `replan_attempts`
2. After all paths are tried, sets `resolution=ESCALATE`, `escalation_category=missing_data`
3. Routes to `escalate_node` → `send_reply_node` → `write_audit`
4. Customer receives an escalation acknowledgment email

**Audit log entry:**
```json
{
  "resolution": "ESCALATE",
  "escalation_category": "missing_data",
  "replan_attempts": [
    {"trigger": "get_order not_found", "alternative_path": "get_customer(email)", "outcome": "failed"}
  ]
}
```

---

## Failure Mode 3: Confidence Below Threshold

**Trigger:** `compute_confidence_score()` returns a score < 0.75.

**Common causes:**
- Missing product data (data_completeness = 0.7)
- Vague or very short customer description (reason_clarity = 0.3–0.5)
- Prior denial on record for the same customer (policy_consistency reduced by 0.1)
- Prior fraud flag for the same customer (policy_consistency = 0.0)

**How it's handled:**
1. `evaluate_q3_node` sets `q3_confident = False`
2. `confidence_gate_node` routes to `escalate_node` with `escalation_category: ambiguous_request`
3. The self_reflection_note explains which factors lowered the score

**Audit log entry:**
```json
{
  "resolution": "ESCALATE",
  "escalation_category": "ambiguous_request",
  "confidence_score": 0.62,
  "confidence_factors": {
    "data_completeness": 0.7,
    "reason_clarity": 0.5,
    "policy_consistency": 0.8
  },
  "self_reflection_note": "Order and customer data present; product data missing. Customer description is brief but present. Confidence score: 0.62."
}
```

---

## Failure Mode 4: HITL Checkpoint Triggered

**Trigger:** `is_high_stakes()` returns True — refund > $200 or threat/social_engineering escalation.

**How it's handled:**
1. `confidence_gate_node` routes to `hitl_checkpoint_node` instead of directly to `approve_node`/`escalate_node`
2. `hitl_checkpoint_node` emits a checkpoint event with the proposed action and reasoning summary
3. In demo/automated mode: auto-approves immediately, records `auto_approved: true`
4. In production mode: graph pauses at `interrupt_before=["hitl_checkpoint"]` awaiting human input
5. After approval, routes to the appropriate action node

**Audit log entry:**
```json
{
  "checkpoint_events": [
    {
      "ticket_id": "T001",
      "proposed_action": "APPROVE",
      "amount_or_category": 450.00,
      "reasoning_summary": "All data present. Refund clearly within policy. Confidence: 0.91.",
      "auto_approved": true,
      "timestamp": "2024-01-01T10:00:00Z"
    }
  ]
}
```

---

## Failure Mode 5: Per-Ticket Exception Isolation

**Trigger:** An unhandled exception occurs inside a LangGraph node (e.g. unexpected data format, import error, network timeout).

**How it's handled:**
1. Each node is wrapped in `try/except Exception`
2. On exception: sets `processing_error = str(e)` and `next_node = "write_audit"`
3. Routes directly to `write_audit_node`, bypassing remaining processing
4. `write_audit_node` records the partial state with the error
5. `main.py` uses `asyncio.gather(..., return_exceptions=True)` — top-level exceptions are also caught
6. All other tickets continue processing unaffected

**Audit log entry:**
```json
{
  "ticket_id": "T007",
  "resolution": null,
  "processing_error": "KeyError: 'product_id' — unexpected data format in order record",
  "tool_calls": [...],
  "reasoning": {"q1_identified": null, "q2_in_policy": null, "q3_confident": null}
}
```

**Key guarantee:** One ticket's failure never prevents other tickets from being processed and recorded. The audit log always contains exactly N records for N input tickets.
