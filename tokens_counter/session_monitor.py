import os
import json
import time
from collections import defaultdict
from pathlib import Path

from tokens_counter.config import calculate_call_cost

# Claude Code stores one JSONL transcript per session under
# <config_dir>/projects/<project>/<session-id>.jsonl, plus (when the session
# spawns subagents/workflows) nested transcripts under a same-named directory:
# <config_dir>/projects/<project>/<session-id>/subagents/**/*.jsonl
# This on-disk layout is an internal implementation detail of Claude Code
# (not a stable public API) so parsing failures are handled gracefully
# instead of raising - a format change should degrade to "no data", not crash.
ACTIVE_THRESHOLD_SECONDS = 300


def get_claude_config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")))


def find_session_groups():
    """
    Find every local Claude Code session, grouping each top-level transcript
    with any subagent/workflow transcripts nested under its own directory.
    Returns a list of {"main": Path, "subagents": [Path, ...]}.
    """
    projects_dir = get_claude_config_dir() / "projects"
    if not projects_dir.is_dir():
        return []

    groups = []
    try:
        project_dirs = [p for p in projects_dir.iterdir() if p.is_dir()]
    except OSError:
        return []

    for project_dir in project_dirs:
        try:
            entries = list(project_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not (entry.is_file() and entry.suffix == ".jsonl"):
                continue
            session_dir = project_dir / entry.stem
            subagent_files = []
            if session_dir.is_dir():
                try:
                    subagent_files = sorted(session_dir.rglob("*.jsonl"))
                except OSError:
                    subagent_files = []
            groups.append({"main": entry, "subagents": subagent_files})

    return groups


def _iter_usage_lines(path):
    """Yield token-usage metadata for each assistant message in a transcript file. Never reads message text/content."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue

                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                model = message.get("model")
                if model == "<synthetic>":
                    # Internal zero-usage placeholder (e.g. a cancelled/tool-only
                    # turn), not a real billable request - skip it entirely so it
                    # doesn't inflate request counts or clutter the model list.
                    continue

                yield {
                    "timestamp": entry.get("timestamp"),
                    "cwd": entry.get("cwd"),
                    "model": model or "unknown",
                    "input_tokens": usage.get("input_tokens", 0) or 0,
                    "output_tokens": usage.get("output_tokens", 0) or 0,
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                    "cache_write_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
                }
    except (OSError, UnicodeDecodeError):
        return


def _safe_mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def build_session_summary(group, config_data, now=None):
    """Aggregate one session (main transcript + its subagents) into a display-ready summary dict."""
    main_path = group["main"]
    subagent_paths = group["subagents"]
    now = time.time() if now is None else now

    by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    main_requests = 0
    subagent_requests = 0
    cwd = None
    last_timestamp = None
    last_request = None

    for is_subagent, path in [(False, main_path)] + [(True, p) for p in subagent_paths]:
        for usage_line in _iter_usage_lines(path):
            model = usage_line["model"]
            by_model[model]["input"] += usage_line["input_tokens"]
            by_model[model]["output"] += usage_line["output_tokens"]
            by_model[model]["cache_read"] += usage_line["cache_read_tokens"]
            by_model[model]["cache_write"] += usage_line["cache_write_tokens"]

            if is_subagent:
                subagent_requests += 1
            else:
                main_requests += 1

            if usage_line["cwd"]:
                cwd = usage_line["cwd"]
            if usage_line["timestamp"] and (last_timestamp is None or usage_line["timestamp"] > last_timestamp):
                last_timestamp = usage_line["timestamp"]
                last_request = {"model": model, **{k: usage_line[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")}}

    total_requests = main_requests + subagent_requests
    if total_requests == 0:
        return None

    total_input = sum(m["input"] for m in by_model.values())
    total_output = sum(m["output"] for m in by_model.values())
    total_cache_read = sum(m["cache_read"] for m in by_model.values())
    total_cache_write = sum(m["cache_write"] for m in by_model.values())

    priced_cost = 0.0
    has_priced_model = False
    for model, tokens in by_model.items():
        if model not in config_data:
            continue
        has_priced_model = True
        priced_cost += calculate_call_cost(
            model, tokens["input"], tokens["output"],
            cached_read_tokens=tokens["cache_read"], cached_write_tokens=tokens["cache_write"]
        )

    last_request_cost = None
    if last_request and last_request["model"] in config_data:
        last_request_cost = calculate_call_cost(
            last_request["model"], last_request["input_tokens"], last_request["output_tokens"],
            cached_read_tokens=last_request["cache_read_tokens"], cached_write_tokens=last_request["cache_write_tokens"]
        )

    mtime = max([_safe_mtime(main_path)] + [_safe_mtime(p) for p in subagent_paths])

    return {
        "session_id": main_path.stem,
        "project": main_path.parent.name,
        "cwd": cwd,
        "models": sorted(by_model.keys()),
        "main_requests": main_requests,
        "subagent_requests": subagent_requests,
        "subagent_count": len(subagent_paths),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "cost": priced_cost if has_priced_model else None,
        "last_request": last_request,
        "last_request_cost": last_request_cost,
        "last_timestamp": last_timestamp,
        "mtime": mtime,
        "is_active": (now - mtime) <= ACTIVE_THRESHOLD_SECONDS
    }


def get_all_sessions(config_data, now=None):
    """Return a summary per local Claude Code session, most recently active first."""
    now = time.time() if now is None else now
    summaries = []
    for group in find_session_groups():
        summary = build_session_summary(group, config_data, now=now)
        if summary:
            summaries.append(summary)
    summaries.sort(key=lambda s: s["mtime"], reverse=True)
    return summaries


def watch_sessions(config_data, refresh_seconds=3):
    """Render a live-updating view of all local sessions until interrupted (Ctrl+C)."""
    from rich.live import Live
    from tokens_counter.tui import console, render_session_monitor_view

    with Live(render_session_monitor_view(get_all_sessions(config_data)), console=console, refresh_per_second=4) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(render_session_monitor_view(get_all_sessions(config_data)))
