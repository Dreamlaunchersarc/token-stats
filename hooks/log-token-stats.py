#!/usr/bin/env python3
"""
Claude Code PostToolUse hook to log token usage statistics.
Reads session transcript, extracts token counts per model, and saves to daily JSON file.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

STATS_DIR = Path.home() / ".claude" / "stats"
DEBUG_LOG = STATS_DIR / "debug.log"


def debug_log(msg: str):
    """Write debug message to log file."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def parse_transcript(transcript_path: str) -> dict:
    """Parse transcript JSONL and extract token usage per model."""
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

                        if usage and request_id:
                            output_tokens = usage.get("output_tokens", 0)
                            if request_id not in request_usage or output_tokens > request_usage[request_id].get("output_tokens", 0):
                                request_usage[request_id] = {
                                    "model": model,
                                    "input_tokens": usage.get("input_tokens", 0),
                                    "output_tokens": output_tokens,
                                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                                }
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return {"by_model": {}, "totals": {}}

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

    totals = {
        "input_tokens": sum(m["input_tokens"] for m in by_model.values()),
        "output_tokens": sum(m["output_tokens"] for m in by_model.values()),
        "cache_read_tokens": sum(m["cache_read_tokens"] for m in by_model.values()),
        "cache_creation_tokens": sum(m["cache_creation_tokens"] for m in by_model.values()),
        "request_count": len(request_usage),
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

    daily_stats["by_model"] = {}

    for session in daily_stats["sessions"]:
        totals["input_tokens"] += session.get("input_tokens", 0)
        totals["output_tokens"] += session.get("output_tokens", 0)
        totals["cache_read_tokens"] += session.get("cache_read_tokens", 0)
        totals["cache_creation_tokens"] += session.get("cache_creation_tokens", 0)
        totals["total_tokens"] += session.get("total_tokens", 0)
        totals["request_count"] += session.get("request_count", 0)

        for model, model_stats in session.get("by_model", {}).items():
            if model not in daily_stats["by_model"]:
                daily_stats["by_model"][model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "request_count": 0,
                }
            for key in ["input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "request_count"]:
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
