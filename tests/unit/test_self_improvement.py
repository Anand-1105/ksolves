"""tests/unit/test_self_improvement.py - Unit tests for the self-improvement module."""
from __future__ import annotations
import asyncio, json, tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from agent.self_improvement import analyse_audit_log, generate_learnings

def _make_record(ticket_id="T001", resolution="APPROVE", escalation_category=None, confidence_score=0.85, replan_attempts=None, checkpoint_events=None):
    return {"ticket_id": ticket_id, "customer_id": "C001", "resolution": resolution, "escalation_category": escalation_category, "confidence_score": confidence_score, "confidence_factors": {"data_completeness": 1.0, "reason_clarity": 0.9, "policy_consistency": 0.8}, "self_reflection_note": "All data present.", "replan_attempts": replan_attempts or [], "checkpoint_events": checkpoint_events or [], "tool_calls": [], "denial_reason": None, "processing_error": None}

class TestAnalyseAuditLog:
    def test_empty_records_returns_empty(self):
        assert analyse_audit_log([]) == {}

    def test_counts_resolutions_correctly(self):
        records = [_make_record(resolution="APPROVE"), _make_record(resolution="APPROVE"), _make_record(resolution="DENY"), _make_record(resolution="ESCALATE", escalation_category="missing_data")]
        r = analyse_audit_log(records)
        assert r["resolutions"]["APPROVE"] == 2
        assert r["resolutions"]["DENY"] == 1
        assert r["resolutions"]["ESCALATE"] == 1

    def test_counts_escalation_categories(self):
        records = [_make_record(resolution="ESCALATE", escalation_category="missing_data"), _make_record(resolution="ESCALATE", escalation_category="threat_detected"), _make_record(resolution="ESCALATE", escalation_category="missing_data")]
        r = analyse_audit_log(records)
        assert r["escalation_categories"]["missing_data"] == 2
        assert r["escalation_categories"]["threat_detected"] == 1

    def test_confidence_stats_computed(self):
        records = [_make_record(confidence_score=0.90), _make_record(confidence_score=0.72), _make_record(confidence_score=0.60)]
        r = analyse_audit_log(records)
        conf = r["confidence"]
        assert conf["avg"] == round((0.90 + 0.72 + 0.60) / 3, 3)
        assert conf["min"] == 0.60
        assert conf["max"] == 0.90
        assert conf["borderline_count"] == 1
        assert conf["low_confidence_count"] == 2

    def test_ambiguous_escalations_counted(self):
        records = [_make_record(resolution="ESCALATE", escalation_category="ambiguous_request"), _make_record(resolution="ESCALATE", escalation_category="ambiguous_request"), _make_record()]
        r = analyse_audit_log(records)
        assert r["ambiguous_escalations"] == 2
        assert len(r["ambiguous_ticket_ids"]) == 2

    def test_replanned_count(self):
        records = [_make_record(replan_attempts=[{"trigger": "test"}]), _make_record(replan_attempts=[]), _make_record(replan_attempts=[{"trigger": "test2"}])]
        r = analyse_audit_log(records)
        assert r["replanned_count"] == 2

    def test_hitl_triggered_count(self):
        records = [_make_record(checkpoint_events=[{"auto_approved": True}]), _make_record(checkpoint_events=[])]
        r = analyse_audit_log(records)
        assert r["hitl_triggered_count"] == 1

    def test_handles_none_confidence_scores(self):
        records = [_make_record(confidence_score=None), _make_record(confidence_score=0.85)]
        r = analyse_audit_log(records)
        assert r["confidence"]["avg"] == 0.85

    def test_total_tickets_correct(self):
        records = [_make_record() for _ in range(7)]
        r = analyse_audit_log(records)
        assert r["total_tickets"] == 7

    def test_avg_tool_chain_length(self):
        records = [_make_record() for _ in range(3)]
        records[0]["tool_calls"] = [{}] * 4
        records[1]["tool_calls"] = [{}] * 6
        records[2]["tool_calls"] = [{}] * 5
        r = analyse_audit_log(records)
        assert r["avg_tool_chain_length"] == 5.0


class TestGenerateLearnings:
    def test_returns_markdown_string(self):
        records = [_make_record() for _ in range(5)]
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as m:
            m.return_value = "LLM analysis here."
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "AGENT_LEARNINGS.md"
                result = asyncio.run(generate_learnings(records, output_path=out))
        assert isinstance(result, str)
        assert "# Agent Self-Improvement Report" in result

    def test_writes_file_to_disk(self):
        records = [_make_record() for _ in range(3)]
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as m:
            m.return_value = "Analysis."
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "AGENT_LEARNINGS.md"
                asyncio.run(generate_learnings(records, output_path=out))
                assert out.exists()
                assert len(out.read_text(encoding="utf-8")) > 100

    def test_empty_records_returns_message(self):
        result = asyncio.run(generate_learnings([]))
        assert "No audit records" in result

    def test_markdown_contains_run_statistics(self):
        records = [_make_record(resolution="APPROVE"), _make_record(resolution="DENY"), _make_record(resolution="ESCALATE", escalation_category="missing_data")]
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as m:
            m.return_value = "Analysis."
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "AGENT_LEARNINGS.md"
                result = asyncio.run(generate_learnings(records, output_path=out))
        assert "| Total tickets | 3 |" in result
        assert "| APPROVE | 1 |" in result

    def test_llm_failure_propagates(self):
        records = [_make_record()]
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as m:
            m.side_effect = Exception("LLM unavailable")
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "AGENT_LEARNINGS.md"
                with pytest.raises(Exception, match="LLM unavailable"):
                    asyncio.run(generate_learnings(records, output_path=out))

