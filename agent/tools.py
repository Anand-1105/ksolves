"""
agent/tools.py — Mock tool functions for the ShopWave Support Resolution Agent.

Tool signatures match the official hackathon spec:
  READ:  get_order(order_id), get_customer(email), get_product(product_id),
         search_knowledge_base(query)
  WRITE: check_refund_eligibility(order_id), issue_refund(order_id, amount),
         send_reply(ticket_id, message), escalate(ticket_id, summary, priority)

Mocks fail realistically: random timeouts, malformed data, partial responses.
All tools are wrapped with @safe_tool_call — they never raise unhandled exceptions.
Retry logic with exponential backoff is applied to transient failures.
"""

from __future__ import annotations

import asyncio
import datetime
import functools
import json
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_json(filename: str) -> list:
    with open(_DATA_DIR / filename, "r", encoding="utf-8") as fh:
        return json.load(fh)


_ORDERS: dict[str, dict] = {r["order_id"]: r for r in _load_json("orders.json")}
_CUSTOMERS: dict[str, dict] = {r["customer_id"]: r for r in _load_json("customers.json")}
_PRODUCTS: dict[str, dict] = {r["product_id"]: r for r in _load_json("products.json")}
_CUSTOMERS_BY_EMAIL: dict[str, dict] = {
    r["email"].lower(): r for r in _CUSTOMERS.values()
}

# Load knowledge base from file
_KB_PATH = _DATA_DIR / "knowledge-base.md"
_KB_TEXT: str = _KB_PATH.read_text(encoding="utf-8") if _KB_PATH.exists() else ""

# ---------------------------------------------------------------------------
# Realistic failure simulation
# ---------------------------------------------------------------------------

# Failure rate for transient simulation. Set TOOL_FAILURE_RATE=0 in tests to disable.
import os as _os
_FAILURE_RATE: float = float(_os.environ.get("TOOL_FAILURE_RATE", "0.05"))


def _maybe_fail_transiently(tool_name: str) -> dict | None:
    """
    Simulate realistic transient failures: timeouts and malformed responses.
    Returns an error dict if a failure is simulated, None otherwise.
    """
    if random.random() < _FAILURE_RATE:
        failure_type = random.choice(["timeout", "malformed"])
        if failure_type == "timeout":
            return {"error": "timeout", "tool": tool_name, "message": f"{tool_name} timed out after 5s"}
        else:
            return {"error": "malformed_response", "tool": tool_name, "message": "Received partial/malformed data"}
    return None


# ---------------------------------------------------------------------------
# safe_tool_call decorator
# ---------------------------------------------------------------------------

def safe_tool_call(func):
    """Catch any unhandled exception and return a structured error dict."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> dict:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return {"error": "tool_exception", "tool": func.__name__, "message": str(e)}
    return wrapper


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

async def with_retry(tool_fn, *args, max_retries: int = 2, base_delay: float = 0.1, **kwargs) -> dict:
    """
    Call tool_fn with exponential backoff retry on transient errors.
    Retries on: timeout, malformed_response, tool_exception.
    Does NOT retry on: not_found (permanent failure).
    """
    last_result = None
    for attempt in range(max_retries + 1):
        result = tool_fn(*args, **kwargs)
        error_type = result.get("error", "")

        # Permanent failures — don't retry
        if error_type == "not_found":
            return result

        # Transient failures — retry with backoff
        if error_type in ("timeout", "malformed_response", "tool_exception"):
            last_result = result
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.05)
                await asyncio.sleep(delay)
                continue

        # Success or non-retryable error
        return result

    return last_result or {"error": "max_retries_exceeded", "message": "All retry attempts failed"}


# ---------------------------------------------------------------------------
# READ / LOOKUP tools
# ---------------------------------------------------------------------------

@safe_tool_call
def get_order(order_id: str) -> dict:
    """Fetch order details, status, timestamps. May return transient errors."""
    if not order_id:
        return {"error": "not_found", "order_id": order_id}

    failure = _maybe_fail_transiently("get_order")
    if failure:
        return failure

    record = _ORDERS.get(str(order_id))
    if record is None:
        return {"error": "not_found", "order_id": order_id}
    return dict(record)


@safe_tool_call
def get_customer(email: str) -> dict:
    """
    Fetch customer profile, tier, history by email address.
    Also accepts customer_id for internal lookups.
    """
    if not email:
        return {"error": "not_found", "email": email}

    failure = _maybe_fail_transiently("get_customer")
    if failure:
        return failure

    # Try email lookup first (primary per spec)
    record = _CUSTOMERS_BY_EMAIL.get(str(email).lower())
    if record is not None:
        return dict(record)

    # Fall back to customer_id (for internal graph use)
    record = _CUSTOMERS.get(str(email))
    if record is not None:
        return dict(record)

    return {"error": "not_found", "email": email}


@safe_tool_call
def get_product(product_id: str) -> dict:
    """Fetch product metadata, category, warranty."""
    if not product_id:
        return {"error": "not_found", "product_id": product_id}

    failure = _maybe_fail_transiently("get_product")
    if failure:
        return failure

    record = _PRODUCTS.get(str(product_id))
    if record is None:
        return {"error": "not_found", "product_id": product_id}
    return dict(record)


@safe_tool_call
def search_knowledge_base(query: str) -> dict:
    """
    Policy & FAQ semantic search against the ShopWave knowledge base.
    Returns relevant policy sections based on keyword matching.
    """
    if not query or not _KB_TEXT:
        return {"result": None, "message": "no_result"}

    failure = _maybe_fail_transiently("search_knowledge_base")
    if failure:
        return failure

    query_lower = query.lower()

    # Section-based matching against the real knowledge base
    sections = {
        "return": ["return policy", "return window", "non-returnable", "damaged", "wrong item"],
        "refund": ["refund policy", "refund eligibility", "partial refund", "refund exception"],
        "warranty": ["warranty policy", "warranty claim", "warranty period"],
        "cancellation": ["cancellation policy", "cancel order"],
        "exchange": ["exchange policy"],
        "tier": ["customer tier", "vip", "premium", "standard"],
        "escalation": ["escalation guidelines", "escalate"],
        "faq": ["common faq", "how long", "can i return"],
        "tone": ["tone", "communication"],
    }

    matched_sections = []
    for keyword, section_keywords in sections.items():
        if any(kw in query_lower for kw in section_keywords) or keyword in query_lower:
            matched_sections.append(keyword)

    if not matched_sections:
        # Return general policy overview
        return {
            "result": _KB_TEXT[:500] + "...",
            "source": "shopwave_knowledge_base",
            "note": "General policy overview — refine query for specific sections",
        }

    # Extract relevant sections from the KB text
    lines = _KB_TEXT.split("\n")
    relevant_lines = []
    capture = False
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in matched_sections):
            capture = True
        if capture:
            relevant_lines.append(line)
            if len(relevant_lines) > 30:
                break

    result_text = "\n".join(relevant_lines) if relevant_lines else _KB_TEXT[:800]
    return {
        "result": result_text,
        "source": "shopwave_knowledge_base",
        "matched_topics": matched_sections,
    }


# ---------------------------------------------------------------------------
# WRITE / ACT tools
# ---------------------------------------------------------------------------

@safe_tool_call
def check_refund_eligibility(order_id: str) -> dict:
    """
    Returns eligibility + reason. May throw errors (per spec).
    Checks return window, warranty period, and VIP exceptions.
    """
    if not order_id:
        return {"error": "not_found", "order_id": order_id}

    failure = _maybe_fail_transiently("check_refund_eligibility")
    if failure:
        return failure

    order = _ORDERS.get(str(order_id))
    if order is None:
        return {"error": "not_found", "order_id": order_id}

    product = _PRODUCTS.get(order.get("product_id", ""), {})
    customer = _CUSTOMERS.get(order.get("customer_id", ""), {})

    purchase_date = datetime.date.fromisoformat(order["purchase_date"])
    today = datetime.date.today()
    days_since = (today - purchase_date).days

    # Effective return window (VIP override)
    return_window_days: int = product.get("return_window_days", 30)
    if customer.get("tier") == "vip":
        extended = customer.get("vip_exceptions", {}).get("extended_return_window_days")
        if extended:
            return_window_days = extended

    if days_since <= return_window_days:
        return {
            "eligible": True,
            "reason": f"Within {return_window_days}-day return window ({days_since} days since purchase).",
            "return_window_days": return_window_days,
            "days_since_purchase": days_since,
        }

    # Check warranty
    warranty_months: int = product.get("warranty_months", 0)
    if warranty_months > 0:
        months_since = (today.year - purchase_date.year) * 12 + (today.month - purchase_date.month)
        if months_since <= warranty_months:
            return {
                "eligible": "escalate",
                "reason": (
                    f"Outside {return_window_days}-day return window ({days_since} days) "
                    f"but within {warranty_months}-month warranty ({months_since} months). "
                    f"Escalate as warranty claim."
                ),
                "warranty_months": warranty_months,
                "months_since_purchase": months_since,
            }

    return {
        "eligible": False,
        "reason": (
            f"Outside {return_window_days}-day return window ({days_since} days since purchase) "
            f"and outside {warranty_months}-month warranty. Not eligible for refund."
        ),
        "return_window_days": return_window_days,
        "days_since_purchase": days_since,
    }


@safe_tool_call
def issue_refund(order_id: str, amount: float) -> dict:
    """
    IRREVERSIBLE — must check eligibility first.
    Issues a refund and returns a confirmation with refund_id.
    """
    today = datetime.date.today()
    refund_id = f"REF-{today.isoformat()}-{order_id}"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": amount,
        "status": "issued",
        "timestamp": timestamp,
        "note": "Refund processed. Customer should see funds in 5-7 business days.",
    }


@safe_tool_call
def send_reply(ticket_id: str, message: str) -> dict:
    """Sends response to the customer. Returns delivery confirmation."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "delivered": True,
        "ticket_id": ticket_id,
        "timestamp": timestamp,
        "message_preview": message[:150] if message else "",
    }


@safe_tool_call
def escalate(ticket_id: str, summary: str, priority: str) -> dict:
    """
    Routes to human with full context.
    priority: low | medium | high | urgent
    """
    today = datetime.date.today()
    case_id = f"ESC-{today.isoformat()}-{ticket_id}"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    valid_priorities = {"low", "medium", "high", "urgent"}
    if priority not in valid_priorities:
        priority = "medium"

    return {
        "case_id": case_id,
        "ticket_id": ticket_id,
        "summary": summary,
        "priority": priority,
        "status": "escalated",
        "timestamp": timestamp,
        "assigned_to": "specialist_team",
    }
