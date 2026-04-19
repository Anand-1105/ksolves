# Feature: shopwave-support-agent, Property 10: Tool Contract Compliance
# Validates: Requirements 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8

import pytest
from hypothesis import given, settings, strategies as st

from agent.tools import (
    check_refund_eligibility,
    escalate,
    get_customer,
    get_order,
    get_product,
    issue_refund,
    search_knowledge_base,
    send_reply,
)

# ---------------------------------------------------------------------------
# Known IDs (sampled from actual data)
# ---------------------------------------------------------------------------

_KNOWN_ORDER_IDS = [f"O{str(i).zfill(3)}" for i in range(1, 21)]  # O001–O020
_KNOWN_CUSTOMER_IDS = [f"C{str(i).zfill(3)}" for i in range(1, 11)]  # C001–C010
_KNOWN_CUSTOMER_EMAILS = [
    "alice.johnson@example.com",
    "emma.williams@example.com",
    "carol.martinez@example.com",
    "grace.thompson@example.com",
    "irene.garcia@example.com",
    "bob.anderson@example.com",
    "dave.robinson@example.com",
    "frank.lewis@example.com",
    "henry.walker@example.com",
    "jane.harris@example.com",
]
_KNOWN_PRODUCT_IDS = [f"P{str(i).zfill(3)}" for i in range(1, 9)]  # P001–P008

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

arbitrary_text = st.text(min_size=0, max_size=50)

amount_strategy = st.floats(
    min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False
)


@st.composite
def tool_id_strategy(draw, known_ids):
    """Generate either a known ID (sampled from actual data) or an arbitrary text string."""
    use_known = draw(st.booleans())
    if use_known and known_ids:
        return draw(st.sampled_from(known_ids))
    return draw(arbitrary_text)


# ---------------------------------------------------------------------------
# Property 10a: All tools return a dict and never raise
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    order_id=tool_id_strategy(known_ids=_KNOWN_ORDER_IDS),
    customer_id=tool_id_strategy(
        known_ids=_KNOWN_CUSTOMER_IDS + _KNOWN_CUSTOMER_EMAILS
    ),
    product_id=tool_id_strategy(known_ids=_KNOWN_PRODUCT_IDS),
    query=arbitrary_text,
    reason=arbitrary_text,
    amount=amount_strategy,
    ticket_id=arbitrary_text,
    message=arbitrary_text,
    category=arbitrary_text,
)
def test_all_tools_return_dict_never_raise(
    order_id,
    customer_id,
    product_id,
    query,
    reason,
    amount,
    ticket_id,
    message,
    category,
):
    """All 8 tools always return a dict and never raise an exception for any input."""
    # Validates: Requirements 11.5, 12.1–12.8
    assert isinstance(get_order(order_id), dict)
    assert isinstance(get_customer(customer_id), dict)
    assert isinstance(get_product(product_id), dict)
    assert isinstance(search_knowledge_base(query), dict)
    assert isinstance(check_refund_eligibility(order_id), dict)
    assert isinstance(issue_refund(order_id, amount), dict)
    assert isinstance(send_reply(ticket_id, message), dict)
    assert isinstance(escalate(ticket_id, reason, category), dict)


# ---------------------------------------------------------------------------
# Property 10b: Lookup tools — known IDs return matching records
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(order_id=st.sampled_from(_KNOWN_ORDER_IDS))
def test_get_order_known_id_returns_record(order_id):
    """get_order returns the matching record for known IDs."""
    # Validates: Requirement 12.1
    result = get_order(order_id)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("order_id") == order_id


@settings(max_examples=100)
@given(customer_id=st.sampled_from(_KNOWN_CUSTOMER_IDS))
def test_get_customer_known_id_returns_record(customer_id):
    """get_customer returns the matching record for known customer IDs."""
    # Validates: Requirement 12.2
    result = get_customer(customer_id)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("customer_id") == customer_id


@settings(max_examples=100)
@given(email=st.sampled_from(_KNOWN_CUSTOMER_EMAILS))
def test_get_customer_known_email_returns_record(email):
    """get_customer returns the matching record for known email addresses."""
    # Validates: Requirement 12.2
    result = get_customer(email)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("email", "").lower() == email.lower()


@settings(max_examples=100)
@given(product_id=st.sampled_from(_KNOWN_PRODUCT_IDS))
def test_get_product_known_id_returns_record(product_id):
    """get_product returns the matching record for known product IDs."""
    # Validates: Requirement 12.3
    result = get_product(product_id)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("product_id") == product_id


# ---------------------------------------------------------------------------
# Property 10c: Lookup tools — unknown IDs return structured not-found error
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    order_id=st.text(min_size=1, max_size=50).filter(
        lambda x: x not in _KNOWN_ORDER_IDS
    )
)
def test_get_order_unknown_id_returns_not_found(order_id):
    """get_order returns {"error": "not_found", ...} for unknown IDs."""
    # Validates: Requirements 11.5, 12.1
    result = get_order(order_id)
    assert isinstance(result, dict)
    assert result.get("error") == "not_found"
    assert "order_id" in result


@settings(max_examples=100)
@given(
    identifier=st.text(min_size=1, max_size=50).filter(
        lambda x: x not in _KNOWN_CUSTOMER_IDS
        and x.lower() not in [e.lower() for e in _KNOWN_CUSTOMER_EMAILS]
    )
)
def test_get_customer_unknown_id_returns_not_found(identifier):
    """get_customer returns {"error": "not_found", ...} for unknown identifiers."""
    # Validates: Requirements 11.5, 12.2
    result = get_customer(identifier)
    assert isinstance(result, dict)
    assert result.get("error") == "not_found"


@settings(max_examples=100)
@given(
    product_id=st.text(min_size=1, max_size=50).filter(
        lambda x: x not in _KNOWN_PRODUCT_IDS
    )
)
def test_get_product_unknown_id_returns_not_found(product_id):
    """get_product returns {"error": "not_found", ...} for unknown product IDs."""
    # Validates: Requirements 11.5, 12.3
    result = get_product(product_id)
    assert isinstance(result, dict)
    assert result.get("error") == "not_found"
    assert "product_id" in result


# ---------------------------------------------------------------------------
# Property 10d: check_refund_eligibility contract
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    order_id=tool_id_strategy(known_ids=_KNOWN_ORDER_IDS),
    reason=arbitrary_text,
)
def test_check_refund_eligibility_contract(order_id, reason):
    """
    check_refund_eligibility always returns a dict with "eligible" key
    (bool or "escalate") and "reason" (str) — or an error dict.
    """
    # Validates: Requirement 12.5
    result = check_refund_eligibility(order_id)
    assert isinstance(result, dict)

    if "error" in result:
        assert isinstance(result["error"], str)
    else:
        assert "eligible" in result
        eligible = result["eligible"]
        assert isinstance(eligible, bool) or eligible == "escalate", (
            f"eligible must be bool or 'escalate', got {eligible!r}"
        )
        assert "reason" in result
        assert isinstance(result["reason"], str)


@settings(max_examples=100)
@given(
    order_id=st.sampled_from(_KNOWN_ORDER_IDS),
    reason=arbitrary_text,
)
def test_check_refund_eligibility_known_order_has_explanation(order_id, reason):
    """For known order IDs, check_refund_eligibility always returns eligible + reason."""
    # Validates: Requirement 12.5
    result = check_refund_eligibility(order_id)
    assert isinstance(result, dict)
    assert "error" not in result
    assert "eligible" in result
    eligible = result["eligible"]
    assert isinstance(eligible, bool) or eligible == "escalate"
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


# ---------------------------------------------------------------------------
# Property 10e: issue_refund contract
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    order_id=tool_id_strategy(known_ids=_KNOWN_ORDER_IDS),
    amount=amount_strategy,
)
def test_issue_refund_returns_non_empty_refund_id(order_id, amount):
    """issue_refund always returns a dict with a non-empty "refund_id" string."""
    # Validates: Requirement 12.6
    result = issue_refund(order_id, amount)
    assert isinstance(result, dict)
    assert "refund_id" in result
    assert isinstance(result["refund_id"], str)
    assert len(result["refund_id"]) > 0


# ---------------------------------------------------------------------------
# Property 10f: send_reply contract
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ticket_id=arbitrary_text,
    message=arbitrary_text,
)
def test_send_reply_returns_delivered_true_and_matching_ticket_id(ticket_id, message):
    """send_reply always returns a dict with "delivered": True and matching "ticket_id"."""
    # Validates: Requirement 12.7
    result = send_reply(ticket_id, message)
    assert isinstance(result, dict)
    assert result.get("delivered") is True
    assert result.get("ticket_id") == ticket_id


# ---------------------------------------------------------------------------
# Property 10g: escalate contract
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ticket_id=arbitrary_text,
    reason=arbitrary_text,
    category=arbitrary_text,
)
def test_escalate_returns_non_empty_case_id(ticket_id, reason, category):
    """escalate always returns a dict with a non-empty "case_id" string."""
    # Validates: Requirement 12.8
    result = escalate(ticket_id, reason, category)
    assert isinstance(result, dict)
    assert "case_id" in result
    assert isinstance(result["case_id"], str)
    assert len(result["case_id"]) > 0


# ---------------------------------------------------------------------------
# Property 10h: search_knowledge_base contract
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(query=arbitrary_text)
def test_search_knowledge_base_returns_result_key(query):
    """search_knowledge_base always returns a dict with a "result" key."""
    # Validates: Requirement 12.4
    result = search_knowledge_base(query)
    assert isinstance(result, dict)
    assert "result" in result
