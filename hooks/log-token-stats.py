#!/usr/bin/env python3
"""
Claude Code PostToolUse hook to log token usage statistics.
Reads session transcript, extracts token counts per model, and saves to daily JSON file.

Token field mapping (API -> Storage -> Display):
- input_tokens        -> input_tokens          -> Input
- output_tokens       -> output_tokens         -> Output
- cache_read_input_tokens    -> cache_read_tokens     -> Cache Read
- cache_creation_input_tokens -> cache_creation_tokens -> Cache Write
"""

import json
import sys
from datetime import datetime
from pathlib import Path

STATS_DIR = Path.home() / ".claude" / "stats"
DEBUG_LOG = STATS_DIR / "debug.log"
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
        except (json.JSONDecodeError, IOError):
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


def debug_log(msg: str):
    """Write debug message to log file."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def parse_transcript(transcript_path: str) -> dict:
    """Parse transcript JSONL and extract token usage per model.

    For each request_id, tracks the maximum value seen for each token type
    independently to handle streaming responses correctly.
    """
    request_usage = {}

    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "assistant":
                        message = entry.get("message", {})
                        usage = message.get("usage", {})
                        request_id = entry.get("requestId")
                        model = message.get("model", "unknown")

                        # Validate we have the required fields
                        if not usage or not request_id:
                            continue

                        # Extract token counts with validation
                        input_tokens = usage.get("input_tokens", 0) or 0
                        output_tokens = usage.get("output_tokens", 0) or 0
                        cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0
                        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0

                        if request_id not in request_usage:
                            # First time seeing this request
                            request_usage[request_id] = {
                                "model": model,
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "cache_read_tokens": cache_read_tokens,
                                "cache_creation_tokens": cache_creation_tokens,
                            }
                        else:
                            # Update each token type to max seen value independently
                            existing = request_usage[request_id]
                            existing["input_tokens"] = max(existing["input_tokens"], input_tokens)
                            existing["output_tokens"] = max(existing["output_tokens"], output_tokens)
                            existing["cache_read_tokens"] = max(existing["cache_read_tokens"], cache_read_tokens)
                            existing["cache_creation_tokens"] = max(existing["cache_creation_tokens"], cache_creation_tokens)
                            # Update model if we get a more specific one
                            if model != "unknown":
                                existing["model"] = model
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return {"by_model": {}, "totals": {}}

    pricing = load_pricing()

    by_model = {}
    for req_data in request_usage.values():
        model = req_data["model"]
        if model not in by_model:
            by_model[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "request_count": 0,
            }
        by_model[model]["input_tokens"] += req_data["input_tokens"]
        by_model[model]["output_tokens"] += req_data["output_tokens"]
        by_model[model]["cache_read_tokens"] += req_data["cache_read_tokens"]
        by_model[model]["cache_creation_tokens"] += req_data["cache_creation_tokens"]
        by_model[model]["request_count"] += 1

    # Calculate cost per model
    for model, stats in by_model.items():
        stats["cost"] = calculate_cost(stats, model, pricing)

    totals = {
        "input_tokens": sum(m["input_tokens"] for m in by_model.values()),
        "output_tokens": sum(m["output_tokens"] for m in by_model.values()),
        "cache_read_tokens": sum(m["cache_read_tokens"] for m in by_model.values()),
        "cache_creation_tokens": sum(m["cache_creation_tokens"] for m in by_model.values()),
        "request_count": len(request_usage),
        "cost": sum(m["cost"] for m in by_model.values()),
    }
    totals["total_tokens"] = (
        totals["input_tokens"] + totals["output_tokens"] +
        totals["cache_read_tokens"] + totals["cache_creation_tokens"]
    )

    return {"by_model": by_model, "totals": totals}


def load_daily_stats(stats_file: Path) -> dict:
    """Load existing daily stats or create new structure."""
    if stats_file.exists():
        try:
            with open(stats_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sessions": [],
        "daily_totals": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
            "session_count": 0,
            "cost": 0.0,
        },
        "by_model": {}
    }


def recalculate_daily_totals(daily_stats: dict) -> None:
    """Recalculate daily totals from all sessions."""
    totals = daily_stats["daily_totals"]
    totals["input_tokens"] = 0
    totals["output_tokens"] = 0
    totals["cache_read_tokens"] = 0
    totals["cache_creation_tokens"] = 0
    totals["total_tokens"] = 0
    totals["request_count"] = 0
    totals["cost"] = 0.0

    daily_stats["by_model"] = {}

    for session in daily_stats["sessions"]:
        totals["input_tokens"] += session.get("input_tokens", 0)
        totals["output_tokens"] += session.get("output_tokens", 0)
        totals["cache_read_tokens"] += session.get("cache_read_tokens", 0)
        totals["cache_creation_tokens"] += session.get("cache_creation_tokens", 0)
        totals["total_tokens"] += session.get("total_tokens", 0)
        totals["request_count"] += session.get("request_count", 0)
        totals["cost"] += session.get("cost", 0.0)

        for model, model_stats in session.get("by_model", {}).items():
            if model not in daily_stats["by_model"]:
                daily_stats["by_model"][model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "request_count": 0,
                    "cost": 0.0,
                }
            for key in ["input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "request_count", "cost"]:
                daily_stats["by_model"][model][key] += model_stats.get(key, 0)

    totals["session_count"] = len(daily_stats["sessions"])


def save_stats(stats_file: Path, stats: dict):
    """Save stats to file with pretty formatting."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    transcript_path = hook_input.get("transcript_path")
    session_id = hook_input.get("session_id", "unknown")
    cwd = hook_input.get("cwd", "")

    if not transcript_path:
        sys.exit(0)

    parsed = parse_transcript(transcript_path)
    session_tokens = parsed["totals"]
    by_model = parsed["by_model"]

    if session_tokens.get("total_tokens", 0) == 0:
        sys.exit(0)

    today = datetime.now().strftime("%Y-%m-%d")
    stats_file = STATS_DIR / f"{today}.json"

    daily_stats = load_daily_stats(stats_file)

    session_entry = {
        "session_id": session_id,
        "date": today,  # Track which date this session entry belongs to
        "last_updated": datetime.now().isoformat(),
        "project": cwd,
        "by_model": by_model,
        **session_tokens
    }

    session_index = next(
        (i for i, s in enumerate(daily_stats["sessions"]) if s["session_id"] == session_id),
        None
    )

    if session_index is not None:
        session_entry["started"] = daily_stats["sessions"][session_index].get("started", session_entry["last_updated"])
        daily_stats["sessions"][session_index] = session_entry
    else:
        session_entry["started"] = session_entry["last_updated"]
        daily_stats["sessions"].append(session_entry)

    recalculate_daily_totals(daily_stats)
    save_stats(stats_file, daily_stats)

    sys.exit(0)


if __name__ == "__main__":
    main()
