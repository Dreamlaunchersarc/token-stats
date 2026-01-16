#!/usr/bin/env python3
"""Shared pricing utilities for Claude Token Stats."""

import json
from pathlib import Path

STATS_DIR = Path.home() / ".claude" / "stats"
PRICING_FILE = STATS_DIR / "pricing.json"

# Default API pricing per million tokens (as of 2025)
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
DEFAULT_PRICING = {
    "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
}

# Fallback pricing by model family (used when specific model not found)
# Uses conservative estimates - cache pricing follows standard multipliers (0.1x read, 1.25x write)
FAMILY_PRICING = {
    "opus": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "sonnet": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "haiku": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
}


def get_family_pricing(model: str) -> dict:
    """Get fallback pricing based on model family (opus/sonnet/haiku)."""
    model_lower = model.lower()
    if "opus" in model_lower:
        return FAMILY_PRICING["opus"]
    elif "haiku" in model_lower:
        return FAMILY_PRICING["haiku"]
    return FAMILY_PRICING["sonnet"]


def load_pricing() -> dict:
    """Load pricing from user config file merged with defaults."""
    pricing = DEFAULT_PRICING.copy()

    # Load user overrides (highest priority)
    if PRICING_FILE.exists():
        try:
            with open(PRICING_FILE, "r") as f:
                custom = json.load(f)
                pricing.update(custom)
        except (json.JSONDecodeError, FileNotFoundError, PermissionError):
            pass

    return pricing


def get_model_pricing(model: str, pricing: dict) -> dict:
    """Get pricing for a model. Falls back to family pricing for unknown models."""
    # Direct match
    if model in pricing:
        return pricing[model]

    # Partial match (model ID contains known key or vice versa)
    for key in pricing:
        if key in model or model in key:
            return pricing[key]

    # Fallback to family-based pricing for unknown models
    return get_family_pricing(model)


def calculate_cost(tokens: dict, model: str, pricing: dict) -> float:
    """Calculate cost in dollars for given token counts and model."""
    mp = get_model_pricing(model, pricing)
    cost = 0.0
    cost += (tokens.get("input_tokens", 0) / 1_000_000) * mp.get("input", 0)
    cost += (tokens.get("output_tokens", 0) / 1_000_000) * mp.get("output", 0)
    cost += (tokens.get("cache_read_tokens", 0) / 1_000_000) * mp.get("cache_read", 0)
    cost += (tokens.get("cache_creation_tokens", 0) / 1_000_000) * mp.get("cache_write", 0)
    return cost
