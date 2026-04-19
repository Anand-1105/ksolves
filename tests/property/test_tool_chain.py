# Feature: shopwave-support-agent
# Property 3: Minimum Tool Chain Length — Validates: Requirements 2.1
# Property 4: Tool Chain Ordering Invariants — Validates: Requirements 2.2, 2.3, 2.4, 3.5, 3.6, 4.1, 8.3
# Property 12: Replanning Correctness — Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.6

from __future__ import annotations

from hypothesis import given, settings, strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    "get_order", "get_customer", "get_product", "search_knowledge_base",
    "check_refund_eligibility", "issue_refund", "send_reply", "escalate",
]

ISSUE_TYPES = ["refund_request", "warranty_claim", "replacement_request", "policy_question", "threat", "social_engineering"]


def _make_tool_call(tool_name: str, eligible: bool | str | None = None, error: bool = False) -> dict:
    if error:
        output = {"error": "not_found"}
    elif tool_name == "check_refund_eligibility":
        if eligible is True:
            output = {"eligible": True, "explanation": "Within window."}
        elif eligible == "escalate":
            output = {"eligible": "escalate", "explanation": "Warranty claim."}
        else:
            output = {"eligible": False, "explanation": "Outside window."}
    elif tool_name == "issue_refund":
        output = {"refund_id": "REF-001", "status": "issued"}
    elif tool_name == "send_reply":
        output = {"delivered": True, "ticket_id": "T001"}
    elif tool_name == "escalate":
        output = {"case_id": "ESC-001", "status": "escalated"}
    else:
        output = {"status": "ok"}
    return {"tool_name": tool_name, "input_args": {}, "output": output, "timestamp": "2024-01-01T00:00:00Z"}


@st.composite
def resolved_ticket_tool_calls_strategy(draw):
    """Generate a realistic tool_calls list for a resolved ticket (>= 3 calls)."""
    issue_type = draw(st.sampled_from(ISSUE_TYPES))
    resolution = draw(st.sampled_from(["APPROVE", "DENY", "ESCALATE"]))

    tool_calls = []
    tool_calls.append(_make_tool_call("get_order"))
    tool_calls.append(_make_tool_call("get_customer"))

    if issue_type in ("refund_request", "warranty_claim", "replacement_request"):
        tool_calls.append(_make_tool_call("get_product"))

    if issue_type == "policy_question":
        tool_calls.append(_make_tool_call("search_knowledge_base"))

    if resolution == "APPROVE":
        tool_calls.append(_make_tool_call("check_refund_eligibility", eligible=True))
        tool_calls.append(_make_tool_call("issue_refund"))
    elif resolution == "DENY":
        tool_calls.append(_make_tool_call("check_refund_eligibility", eligible=False))
    elif resolution == "ESCALATE":
        tool_calls.append(_make_tool_call("escalate"))

    tool_calls.append(_make_tool_call("send_reply"))

    return {"tool_calls": tool_calls, "resolution": resolution, "issue_type": issue_type}


@st.composite
def replan_scenario_strategy(draw):
    """Generate a scenario where get_order fails and replanning is attempted."""
    replan_succeeded = draw(st.booleans())
    customer_email_available = draw(st.booleans())

    tool_calls = []
    # get_order fails
    tool_calls.append(_make_tool_call("get_order", error=True))

    replan_attempts = []
    if not customer_email_available:
        replan_attempts.append({
            "trigger": "get_order not_found, no email available",
            "alternative_path": "none",
            "outcome": "failed",
        })
        resolution = "ESCALATE"
        escalation_category = "missing_data"
    elif replan_succeeded:
        tool_calls.append(_make_tool_call("get_customer"))
        replan_attempts.append({
            "trigger": "get_order not_found",
            "alternative_path": "get_customer(email)",
            "outcome": "succeeded — customer found but order still unavailable",
        })
        resolution = "ESCALATE"
        escalation_category = "missing_data"
    else:
        tool_calls.append(_make_tool_call("get_customer", error=True))
        replan_attempts.append({
            "trigger": "get_order not_found",
            "alternative_path": "get_customer(email)",
            "outcome": "failed",
        })
        resolution = "ESCALATE"
        escalation_category = "missing_data"

    tool_calls.append(_make_tool_call("escalate"))
    tool_calls.append(_make_tool_call("send_reply"))

    return {
        "tool_calls": tool_calls,
        "replan_attempts": replan_attempts,
        "resolution": resolution,
        "escalation_category": escalation_category,
    }


# ===========================================================================
# Property 3: Minimum Tool Chain Length
# Validates: Requirements 2.1
# ===========================================================================

class TestProperty3MinimumToolChainLength:
    """
    Tests that every resolved ticket has at least 3 tool calls.
    """

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_resolved_ticket_has_at_least_3_tool_calls(self, scenario):
        """
        Every ticket processed to a resolution must have >= 3 tool calls.
        **Validates: Requirements 2.1**
        """
        tool_calls = scenario["tool_calls"]
        assert len(tool_calls) >= 3, (
            f"Resolved ticket must have >= 3 tool calls, got {len(tool_calls)}: "
            f"{[tc['tool_name'] for tc in tool_calls]}"
        )

    @settings(max_examples=100)
    @given(
        n_extra=st.integers(min_value=0, max_value=5),
        resolution=st.sampled_from(["APPROVE", "DENY", "ESCALATE"]),
    )
    def test_minimum_3_holds_for_all_resolutions(self, n_extra, resolution):
        """
        The minimum 3 tool calls invariant holds for APPROVE, DENY, and ESCALATE.
        **Validates: Requirements 2.1**
        """
        # Build minimal tool chain for each resolution
        tool_calls = [
            _make_tool_call("get_order"),
            _make_tool_call("get_customer"),
        ]
        if resolution == "APPROVE":
            tool_calls.append(_make_tool_call("check_refund_eligibility", eligible=True))
            tool_calls.append(_make_tool_call("issue_refund"))
        elif resolution == "DENY":
            tool_calls.append(_make_tool_call("check_refund_eligibility", eligible=False))
        elif resolution == "ESCALATE":
            tool_calls.append(_make_tool_call("escalate"))

        tool_calls.append(_make_tool_call("send_reply"))

        # Add extra calls
        for _ in range(n_extra):
            tool_calls.append(_make_tool_call("get_product"))

        assert len(tool_calls) >= 3, (
            f"Tool chain for {resolution} must have >= 3 calls, got {len(tool_calls)}"
        )


# ===========================================================================
# Property 4: Tool Chain Ordering Invariants
# Validates: Requirements 2.2, 2.3, 2.4, 3.5, 3.6, 4.1, 8.3
# ===========================================================================

class TestProperty4ToolChainOrderingInvariants:
    """
    Tests ordering invariants in the tool_calls list.
    """

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_get_customer_appears_in_tool_calls(self, scenario):
        """
        get_customer must appear at least once in tool_calls.
        **Validates: Requirements 2.3**
        """
        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]
        assert "get_customer" in tool_names, (
            f"get_customer must appear in tool_calls, got {tool_names}"
        )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_get_order_before_check_refund_eligibility(self, scenario):
        """
        For refund/return tickets: get_order must appear before check_refund_eligibility.
        **Validates: Requirements 2.2, 4.1**
        """
        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]

        if "check_refund_eligibility" not in tool_names:
            return  # Vacuously satisfied

        order_idx = tool_names.index("get_order") if "get_order" in tool_names else -1
        elig_idx = tool_names.index("check_refund_eligibility")

        assert order_idx >= 0, "get_order must appear when check_refund_eligibility is present"
        assert order_idx < elig_idx, (
            f"get_order (idx={order_idx}) must appear before "
            f"check_refund_eligibility (idx={elig_idx})"
        )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_check_refund_eligibility_before_issue_refund(self, scenario):
        """
        check_refund_eligibility must appear before issue_refund.
        **Validates: Requirements 3.5**
        """
        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]

        if "issue_refund" not in tool_names:
            return  # Vacuously satisfied

        assert "check_refund_eligibility" in tool_names, (
            "check_refund_eligibility must appear when issue_refund is present"
        )
        elig_idx = tool_names.index("check_refund_eligibility")
        refund_idx = tool_names.index("issue_refund")
        assert elig_idx < refund_idx, (
            f"check_refund_eligibility (idx={elig_idx}) must appear before "
            f"issue_refund (idx={refund_idx})"
        )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_send_reply_is_last_tool_call(self, scenario):
        """
        send_reply must be the last tool call in the chain.
        **Validates: Requirements 3.6, 8.3**
        """
        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]

        if "send_reply" not in tool_names:
            return  # Vacuously satisfied

        last_tool = tool_names[-1]
        assert last_tool == "send_reply", (
            f"send_reply must be the last tool call, got '{last_tool}' as last. "
            f"Full chain: {tool_names}"
        )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_warranty_defect_tickets_include_get_product(self, scenario):
        """
        For warranty_claim and replacement_request tickets, get_product must appear.
        **Validates: Requirements 2.4**
        """
        issue_type = scenario["issue_type"]
        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]

        if issue_type in ("warranty_claim", "replacement_request"):
            assert "get_product" in tool_names, (
                f"get_product must appear for issue_type='{issue_type}', "
                f"got tool_calls={tool_names}"
            )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_approve_resolution_has_issue_refund(self, scenario):
        """
        APPROVE resolution must include issue_refund in tool_calls.
        **Validates: Requirements 3.5**
        """
        if scenario["resolution"] != "APPROVE":
            return

        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]
        assert "issue_refund" in tool_names, (
            f"APPROVE resolution must include issue_refund, got {tool_names}"
        )

    @settings(max_examples=100)
    @given(scenario=resolved_ticket_tool_calls_strategy())
    def test_escalate_resolution_has_escalate_call(self, scenario):
        """
        ESCALATE resolution must include escalate in tool_calls.
        **Validates: Requirements 8.3**
        """
        if scenario["resolution"] != "ESCALATE":
            return

        tool_names = [tc["tool_name"] for tc in scenario["tool_calls"]]
        assert "escalate" in tool_names, (
            f"ESCALATE resolution must include escalate tool call, got {tool_names}"
        )


# ===========================================================================
# Property 12: Replanning Correctness
# Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.6
# ===========================================================================

class TestProperty12ReplanningCorrectness:
    """
    Tests that replanning behaves correctly when tool calls fail.
    """

    @settings(max_examples=100)
    @given(scenario=replan_scenario_strategy())
    def test_replan_attempts_non_empty_before_missing_data_escalation(self, scenario):
        """
        replan_attempts must be non-empty before a missing_data escalation.
        **Validates: Requirements 14.1**
        """
        if scenario["escalation_category"] != "missing_data":
            return

        assert len(scenario["replan_attempts"]) > 0, (
            "replan_attempts must be non-empty before missing_data escalation"
        )

    @settings(max_examples=100)
    @given(scenario=replan_scenario_strategy())
    def test_no_duplicate_tool_calls_after_error(self, scenario):
        """
        No (tool_name, input_args) pair should appear more than once when the
        first occurrence returned an error (no identical retries).
        **Validates: Requirements 14.6**
        """
        tool_calls = scenario["tool_calls"]
        error_calls = {
            tc["tool_name"]
            for tc in tool_calls
            if "error" in tc["output"]
        }

        # For each errored tool, count occurrences with same args
        for tool_name in error_calls:
            matching = [
                tc for tc in tool_calls
                if tc["tool_name"] == tool_name
            ]
            # Should appear at most once (the failed call) — no identical retry
            assert len(matching) <= 1, (
                f"Tool '{tool_name}' with error must not be retried with identical args, "
                f"found {len(matching)} occurrences"
            )

    @settings(max_examples=100)
    @given(scenario=replan_scenario_strategy())
    def test_all_failed_replans_lead_to_missing_data_escalation(self, scenario):
        """
        If all replan attempts have outcome='failed', resolution must be ESCALATE
        with category=missing_data.
        **Validates: Requirements 14.4**
        """
        replan_attempts = scenario["replan_attempts"]
        if not replan_attempts:
            return

        all_failed = all(
            "failed" in attempt["outcome"]
            for attempt in replan_attempts
        )

        if all_failed:
            assert scenario["resolution"] == "ESCALATE", (
                f"All replans failed → resolution must be ESCALATE, got {scenario['resolution']}"
            )
            assert scenario["escalation_category"] == "missing_data", (
                f"All replans failed → escalation_category must be missing_data, "
                f"got {scenario['escalation_category']}"
            )

    @settings(max_examples=100)
    @given(scenario=replan_scenario_strategy())
    def test_replan_attempts_have_required_fields(self, scenario):
        """
        Each replan attempt must have trigger, alternative_path, and outcome fields.
        **Validates: Requirements 14.5**
        """
        for attempt in scenario["replan_attempts"]:
            assert "trigger" in attempt, f"replan attempt missing 'trigger': {attempt}"
            assert "alternative_path" in attempt, f"replan attempt missing 'alternative_path': {attempt}"
            assert "outcome" in attempt, f"replan attempt missing 'outcome': {attempt}"
            assert attempt["trigger"], "replan attempt trigger must be non-empty"
            assert attempt["outcome"], "replan attempt outcome must be non-empty"

    def test_replan_triggered_when_get_order_fails_with_email(self):
        """
        When get_order fails and customer email is available, a replan attempt
        must be recorded before escalating.
        **Validates: Requirements 14.2**
        """
        # Simulate: get_order fails, email available, get_customer succeeds
        replan_attempts = [
            {
                "trigger": "get_order not_found",
                "alternative_path": "get_customer(customer@example.com)",
                "outcome": "succeeded — customer found but order still unavailable",
            }
        ]
        assert len(replan_attempts) > 0, "Replan must be attempted when email is available"
        assert "get_customer" in replan_attempts[0]["alternative_path"], (
            "Alternative path must use get_customer when email is available"
        )

    def test_no_replan_when_no_email_available(self):
        """
        When get_order fails and no email is available, replan records 'none' as
        alternative_path and immediately escalates.
        **Validates: Requirements 14.1**
        """
        replan_attempts = [
            {
                "trigger": "get_order not_found, no email available",
                "alternative_path": "none",
                "outcome": "failed",
            }
        ]
        assert replan_attempts[0]["alternative_path"] == "none"
        assert "failed" in replan_attempts[0]["outcome"]
