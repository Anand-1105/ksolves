"""
agent/learned_config.py — Persistent Learning Configuration

Manages a JSON config file that the agent reads on startup and writes
after each self-improvement cycle. This closes the learning loop:
  1. Agent processes tickets
  2. Self-improvement analyses decisions
  3. Learnings are written to learned_config.json
  4. Next run reads and applies the learned thresholds/rules

Config is stored in data/learned_config.json alongside the mock data.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).parent.parent / "data" / "learned_config.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "generation": 0,
    "last_updated": None,

    # Confidence threshold — auto-escalate below this
    "confidence_threshold": 0.75,

    # Sentiment-driven adjustments
    "sentiment_rules": {
        # Lower HITL threshold for angry VIP customers (approve faster)
        "angry_vip_hitl_amount_threshold": 150.0,
        # Boost confidence for calm customers with complete data
        "calm_confidence_boost": 0.05,
        # Auto-escalate desperate customers with high churn risk
        "desperate_high_churn_auto_escalate": True,
        # Reduce confidence for frustrated repeat customers
        "frustrated_repeat_confidence_penalty": 0.05,
    },

    # Learned keyword additions (from self-improvement analysis)
    "additional_threat_keywords": [],
    "additional_social_engineering_keywords": [],

    # Per-run statistics (rolling window for trend detection)
    "run_history": [],
}


def load_config() -> dict:
    """
    Load learned configuration from disk. Returns default config if
    the file doesn't exist or is corrupted.
    """
    if not _CONFIG_PATH.exists():
        return dict(_DEFAULT_CONFIG)

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            config = json.load(fh)
        # Validate it's a dict with expected structure
        if not isinstance(config, dict):
            return dict(_DEFAULT_CONFIG)
        # Merge with defaults so new keys are always present
        merged = dict(_DEFAULT_CONFIG)
        merged.update(config)
        # Ensure nested dicts are merged properly
        if "sentiment_rules" in config:
            merged_rules = dict(_DEFAULT_CONFIG["sentiment_rules"])
            merged_rules.update(config["sentiment_rules"])
            merged["sentiment_rules"] = merged_rules
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Write learned configuration to disk atomically (temp file + rename)."""
    import tempfile
    config["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Write to a temp file in the same directory, then rename atomically
    tmp_path = _CONFIG_PATH.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, default=str)
        tmp_path.replace(_CONFIG_PATH)  # atomic on POSIX; best-effort on Windows
    except Exception:
        # Clean up temp file on failure
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def get_confidence_threshold(config: dict | None = None) -> float:
    """Get the current confidence threshold (default 0.75)."""
    if config is None:
        config = load_config()
    return float(config.get("confidence_threshold", 0.75))


def get_sentiment_rules(config: dict | None = None) -> dict:
    """Get sentiment-driven adjustment rules."""
    if config is None:
        config = load_config()
    return config.get("sentiment_rules", _DEFAULT_CONFIG["sentiment_rules"])


def get_additional_keywords(config: dict | None = None) -> tuple[list[str], list[str]]:
    """Get learned threat and social engineering keywords."""
    if config is None:
        config = load_config()
    return (
        config.get("additional_threat_keywords", []),
        config.get("additional_social_engineering_keywords", []),
    )


def record_run_stats(config: dict, stats: dict) -> dict:
    """
    Append run statistics to the rolling history.
    Keeps only the last 10 runs to prevent unbounded growth.
    """
    history = list(config.get("run_history", []))
    stats["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    history.append(stats)
    config["run_history"] = history[-10:]  # Keep last 10
    config["generation"] = config.get("generation", 0) + 1
    return config
