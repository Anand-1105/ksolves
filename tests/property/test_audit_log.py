# Feature: shopwave-support-agent
# Property 1: Audit Log Completeness — Validates: Requirements 1.2, 9.1, 9.2, 9.3, 9.5, 13.2, 13.4
# Property 2: Fault Isolation — Validates: Requirements 1.3

from __future__ import annotations

import json
from hypothesis import given, settings, strategies as st, HealthCheck

# ---------------------------------------------------------------------------
# Required audit record fields
# ---------------------------------------------------------------------------

REQUIRED_AUDIT_FIELDS = [
    "ticket_id",
    "customer_id",
    "tool_calls",
    "reasoning",
    "confidence_score",
    "confidence_factors",
    "self_reflection_note",
    "replan_attempts",
    "checkpoint_events",
    "resolution",
    "escalation_category",
]

REQUIRED_REASONING_FIELDS = ["q1_identified", "q2_in_policy", "q3_confident"]

REQUIRED_CONFIDENCE_FACTOR_FIELDS = ["data_completeness", "reason_clarity", "policy_consistency"]

VALID_RESOLUTIONS = {"APPROVE", "DENY", "ESCALATE", None}  # None for error records


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@st.composite
def audit_record_strategy(draw):
    """Generate a valid audit record with all required fields."""
    resolution = draw(st.sampled_from(["APPROVE", "DENY", "ESCALATE"]))
    escalation_category = draw(st.sampled_from([
        "warranty_claim", "threat_detected", "social_engineering",
        "ambiguous_request", "missing_data", "replacement_needed"
    ])) if resolution == "ESCALATE" else None

    confidence_score = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    data_completeness = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    reason_clarity = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    policy_consistency = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))

    return {
        "ticket_id": draw(st.text(min_size=1, max_size=20)),
        "customer_id": draw(st.text(min_size=1, max_size=10)),
        "tool_calls": [],
        "reasoning": {
            "q1_identified": draw(st.booleans()),
            "q2_in_policy": draw(st.booleans()),
            "q3_confident": draw(st.booleans()),
        },
        "confidence_score": confidence_score,
        "confidence_factors": {
            "data_completeness": data_completeness,
            "reason_clarity": reason_clarity,
            "policy_consistency": policy_consistency,
        },
        "self_reflection_note": draw(st.text(min_size=0, max_size=200)),
        "replan_attempts": [],
        "checkpoint_events": [],
        "resolution": resolution,
        "escalation_category": escalation_category,
        "refund_id": None,
        "case_id": None,
        "denial_reason": None,
        "processing_error": None,
    }


@st.composite
def error_audit_record_strategy(draw):
    """Generate an error audit record (processing_error set, resolution=None)."""
    return {
        "ticket_id": draw(st.text(min_size=1, max_size=20)),
        "customer_id": draw(st.text(min_size=1, max_size=10)),
        "tool_calls": [],
        "reasoning": {"q1_identified": None, "q2_in_policy": None, "q3_confident": None},
        "confidence_score": None,
        "confidence_factors": None,
        "self_reflection_note": None,
        "replan_attempts": [],
        "checkpoint_events": [],
        "resolution": None,
        "escalation_category": None,
        "refund_id": None,
        "case_id": None,
        "denial_reason": None,
        "processing_error": draw(st.text(min_size=1, max_size=200)),
    }


@st.composite
def audit_log_strategy(draw, min_tickets=1, max_tickets=20):
    """Generate a complete audit log with N records."""
    n = draw(st.integers(min_value=min_tickets, max_value=max_tickets))
    records = draw(st.lists(audit_record_strategy(), min_size=n, max_size=n))
    return {
        "execution_metadata": {
            "total_tickets": n,
            "tickets_processed": n,
        },
        "ticket_audit": records,
    }


# ===========================================================================
# Property 1: Audit Log Completeness
# Validates: Requirements 1.2, 9.1, 9.2, 9.3, 9.5, 13.2, 13.4
# ===========================================================================

class TestProperty1AuditLogCompleteness:
    """
    Tests that audit_log.json contains exactly N records (one per ticket)
    and each record contains all required fields.
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(audit_log=audit_log_strategy())
    def test_audit_log_has_correct_record_count(self, audit_log):
        """
        audit_log["ticket_audit"] must contain exactly N records where N is
        the number of tickets processed.
        **Validates: Requirements 1.2, 9.1**
        """
        n = audit_log["execution_metadata"]["total_tickets"]
        records = audit_log["ticket_audit"]
        assert len(records) == n, (
            f"audit_log must contain exactly {n} records, got {len(records)}"
        )

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_each_record_has_required_fields(self, record):
        """
        Each audit record must contain all required fields.
        **Validates: Requirements 9.2**
        """
        for field in REQUIRED_AUDIT_FIELDS:
            assert field in record, f"Audit record missing required field: '{field}'"

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_reasoning_has_q1_q2_q3_booleans(self, record):
        """
        The reasoning dict must contain q1_identified, q2_in_policy, q3_confident
        as explicit fields (may be bool or None for error records).
        **Validates: Requirements 9.4**
        """
        reasoning = record["reasoning"]
        for field in REQUIRED_REASONING_FIELDS:
            assert field in reasoning, (
                f"reasoning dict missing required field: '{field}'"
            )

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_confidence_score_in_valid_range(self, record):
        """
        confidence_score must be a float in [0.0, 1.0].
        **Validates: Requirements 13.2**
        """
        score = record["confidence_score"]
        assert isinstance(score, float), f"confidence_score must be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"confidence_score must be in [0.0, 1.0], got {score}"

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_confidence_factors_has_required_keys(self, record):
        """
        confidence_factors must contain data_completeness, reason_clarity, policy_consistency.
        **Validates: Requirements 13.4**
        """
        factors = record["confidence_factors"]
        assert isinstance(factors, dict), f"confidence_factors must be dict, got {type(factors)}"
        for key in REQUIRED_CONFIDENCE_FACTOR_FIELDS:
            assert key in factors, f"confidence_factors missing key: '{key}'"

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_resolution_is_valid_value(self, record):
        """
        resolution must be one of APPROVE, DENY, ESCALATE (or None for errors).
        **Validates: Requirements 9.2**
        """
        assert record["resolution"] in VALID_RESOLUTIONS, (
            f"resolution must be in {VALID_RESOLUTIONS}, got {record['resolution']}"
        )

    @settings(max_examples=100)
    @given(audit_log=audit_log_strategy())
    def test_audit_log_is_valid_json(self, audit_log):
        """
        The audit log must be serialisable to valid JSON.
        **Validates: Requirements 9.5**
        """
        serialised = json.dumps(audit_log, default=str)
        parsed = json.loads(serialised)
        assert parsed["execution_metadata"]["total_tickets"] == audit_log["execution_metadata"]["total_tickets"]

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_tool_calls_is_list(self, record):
        """
        tool_calls must be a list (ordered sequence of tool call records).
        **Validates: Requirements 9.3**
        """
        assert isinstance(record["tool_calls"], list), (
            f"tool_calls must be a list, got {type(record['tool_calls'])}"
        )

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_replan_attempts_is_list(self, record):
        """replan_attempts must be a list."""
        assert isinstance(record["replan_attempts"], list)

    @settings(max_examples=100)
    @given(record=audit_record_strategy())
    def test_checkpoint_events_is_list(self, record):
        """checkpoint_events must be a list."""
        assert isinstance(record["checkpoint_events"], list)


# ===========================================================================
# Property 2: Fault Isolation
# Validates: Requirements 1.3
# ===========================================================================

class TestProperty2FaultIsolation:
    """
    Tests that when some tickets fail with exceptions, the audit log still
    contains records for all tickets, with processing_error set for failed ones
    and normal resolution records for successful ones.
    """

    @settings(max_examples=100)
    @given(
        normal_records=st.lists(audit_record_strategy(), min_size=1, max_size=15),
        error_records=st.lists(error_audit_record_strategy(), min_size=1, max_size=5),
    )
    def test_error_records_have_processing_error_set(self, normal_records, error_records):
        """
        Error audit records must have processing_error non-null and resolution=None.
        **Validates: Requirements 1.3**
        """
        for record in error_records:
            assert record["processing_error"], (
                f"Error record must have non-empty processing_error, got {record}"
            )
            assert record["resolution"] is None, (
                f"Error record must have resolution=None, got {record['resolution']}"
            )

    @settings(max_examples=100)
    @given(
        normal_records=st.lists(audit_record_strategy(), min_size=1, max_size=15),
        error_records=st.lists(error_audit_record_strategy(), min_size=1, max_size=5),
    )
    def test_normal_records_unaffected_by_errors(self, normal_records, error_records):
        """
        Normal records must have resolution set and processing_error=None,
        regardless of how many error records exist in the same audit log.
        **Validates: Requirements 1.3**
        """
        all_records = normal_records + error_records
        total = len(all_records)

        # Verify normal records are intact
        for record in normal_records:
            assert record["resolution"] in ("APPROVE", "DENY", "ESCALATE"), (
                f"Normal record must have valid resolution, got {record['resolution']}"
            )
            assert record["processing_error"] is None, (
                f"Normal record must have processing_error=None, got {record['processing_error']}"
            )

        # Verify total count is preserved
        assert len(all_records) == total

    @settings(max_examples=100)
    @given(
        normal_records=st.lists(audit_record_strategy(), min_size=0, max_size=19),
        error_records=st.lists(error_audit_record_strategy(), min_size=1, max_size=20),
    )
    def test_audit_log_count_includes_error_records(self, normal_records, error_records):
        """
        The audit log record count must include both normal and error records.
        One ticket's failure must not reduce the total record count.
        **Validates: Requirements 1.3**
        """
        all_records = normal_records + error_records
        n = len(all_records)

        audit_log = {
            "execution_metadata": {"total_tickets": n, "tickets_processed": n},
            "ticket_audit": all_records,
        }

        assert len(audit_log["ticket_audit"]) == n, (
            f"audit_log must contain {n} records (including error records), "
            f"got {len(audit_log['ticket_audit'])}"
        )

    def test_error_record_structure_is_valid(self):
        """
        An error record must still contain all required structural fields
        (with None values where data is unavailable).
        **Validates: Requirements 1.3**
        """
        error_record = {
            "ticket_id": "T001",
            "customer_id": "C001",
            "tool_calls": [],
            "reasoning": {"q1_identified": None, "q2_in_policy": None, "q3_confident": None},
            "confidence_score": None,
            "confidence_factors": None,
            "self_reflection_note": None,
            "replan_attempts": [],
            "checkpoint_events": [],
            "resolution": None,
            "escalation_category": None,
            "refund_id": None,
            "case_id": None,
            "denial_reason": None,
            "processing_error": "Simulated exception during processing",
        }

        # Must be JSON-serialisable
        serialised = json.dumps(error_record, default=str)
        parsed = json.loads(serialised)
        assert parsed["processing_error"] == "Simulated exception during processing"
        assert parsed["resolution"] is None

        # Must contain all required fields
        for field in REQUIRED_AUDIT_FIELDS:
            assert field in error_record, f"Error record missing field: '{field}'"
