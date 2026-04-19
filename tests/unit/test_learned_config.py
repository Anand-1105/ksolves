"""
tests/unit/test_learned_config.py — Unit tests for the Persistent Learning module.

Tests config loading, saving, threshold management, and run history.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from agent.learned_config import (
    load_config,
    save_config,
    get_confidence_threshold,
    get_sentiment_rules,
    get_additional_keywords,
    record_run_stats,
    _DEFAULT_CONFIG,
)


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_defaults_when_no_file(self):
        with patch("agent.learned_config._CONFIG_PATH") as mock_path:
            mock_path.exists.return_value = False
            config = load_config()
        assert config["confidence_threshold"] == 0.75
        assert config["generation"] == 0

    def test_loads_from_valid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"confidence_threshold": 0.72, "generation": 3}, f)
            path = f.name
        try:
            with patch("agent.learned_config._CONFIG_PATH") as mock_path:
                mock_path.exists.return_value = True
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = lambda s: open(path, "r")
                    mock_open.return_value.__exit__ = lambda s, *a: None
                    # Use direct file read instead
                    pass
            # Simpler approach: test with actual temp file
            import agent.learned_config as lc
            original = lc._CONFIG_PATH
            lc._CONFIG_PATH = type(original)(path)
            try:
                config = load_config()
                assert config["confidence_threshold"] == 0.72
                assert config["generation"] == 3
            finally:
                lc._CONFIG_PATH = original
        finally:
            os.unlink(path)

    def test_returns_defaults_for_corrupted_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{{")
            path = f.name
        try:
            import agent.learned_config as lc
            original = lc._CONFIG_PATH
            lc._CONFIG_PATH = type(original)(path)
            try:
                config = load_config()
                assert config["confidence_threshold"] == 0.75
            finally:
                lc._CONFIG_PATH = original
        finally:
            os.unlink(path)

    def test_merges_with_defaults(self):
        """New keys from defaults are present even if file doesn't have them."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"confidence_threshold": 0.80}, f)
            path = f.name
        try:
            import agent.learned_config as lc
            original = lc._CONFIG_PATH
            lc._CONFIG_PATH = type(original)(path)
            try:
                config = load_config()
                assert config["confidence_threshold"] == 0.80
                assert "sentiment_rules" in config
                assert "version" in config
            finally:
                lc._CONFIG_PATH = original
        finally:
            os.unlink(path)


class TestSaveConfig:
    """Tests for save_config()."""

    def test_writes_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            import agent.learned_config as lc
            original = lc._CONFIG_PATH
            lc._CONFIG_PATH = type(original)(path)
            try:
                config = {"confidence_threshold": 0.72, "generation": 5}
                save_config(config)
                with open(path, "r") as f:
                    saved = json.load(f)
                assert saved["confidence_threshold"] == 0.72
                assert saved["generation"] == 5
                assert "last_updated" in saved
            finally:
                lc._CONFIG_PATH = original
        finally:
            os.unlink(path)


class TestGetters:
    """Tests for config getter functions."""

    def test_get_confidence_threshold_default(self):
        assert get_confidence_threshold({}) == 0.75

    def test_get_confidence_threshold_custom(self):
        assert get_confidence_threshold({"confidence_threshold": 0.80}) == 0.80

    def test_get_sentiment_rules_default(self):
        rules = get_sentiment_rules({})
        assert "angry_vip_hitl_amount_threshold" in rules

    def test_get_sentiment_rules_custom(self):
        custom = {"sentiment_rules": {"angry_vip_hitl_amount_threshold": 100.0}}
        rules = get_sentiment_rules(custom)
        assert rules["angry_vip_hitl_amount_threshold"] == 100.0

    def test_get_additional_keywords_empty(self):
        threat, se = get_additional_keywords({})
        assert threat == []
        assert se == []

    def test_get_additional_keywords_populated(self):
        config = {
            "additional_threat_keywords": ["extort"],
            "additional_social_engineering_keywords": ["pretend"],
        }
        threat, se = get_additional_keywords(config)
        assert "extort" in threat
        assert "pretend" in se


class TestRecordRunStats:
    """Tests for run history recording."""

    def test_appends_to_history(self):
        config = {"run_history": [], "generation": 0}
        stats = {"total_tickets": 20, "avg_confidence": 0.85}
        config = record_run_stats(config, stats)
        assert len(config["run_history"]) == 1
        assert config["generation"] == 1
        assert config["run_history"][0]["total_tickets"] == 20

    def test_limits_to_10_runs(self):
        config = {"run_history": [{"run": i} for i in range(10)], "generation": 10}
        stats = {"total_tickets": 20}
        config = record_run_stats(config, stats)
        assert len(config["run_history"]) == 10
        assert config["run_history"][-1]["total_tickets"] == 20
        assert config["generation"] == 11

    def test_adds_timestamp(self):
        config = {"run_history": [], "generation": 0}
        config = record_run_stats(config, {"test": True})
        assert "timestamp" in config["run_history"][0]

    def test_increments_generation(self):
        config = {"run_history": [], "generation": 5}
        config = record_run_stats(config, {})
        assert config["generation"] == 6
