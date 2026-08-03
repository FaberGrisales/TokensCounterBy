import os
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
    """
    Yield token-usage metadata for each assistant message in a transcript
    file, plus the `name` of any tool it called (`tool_names`, e.g.
    "mcp__filesystem__read_file" or "Bash") - never the tool's arguments or
    result, and never any text/reasoning content.
    """
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

                tool_names = []
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name")
                            if isinstance(name, str):
                                tool_names.append(name)

                yield {
                    "timestamp": entry.get("timestamp"),
                    "cwd": entry.get("cwd"),
                    "model": model or "unknown",
                    "input_tokens": usage.get("input_tokens", 0) or 0,
                    "output_tokens": usage.get("output_tokens", 0) or 0,
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                    "cache_write_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
                    "tool_names": tool_names,
                }
    except (OSError, UnicodeDecodeError):
        return


def _parse_mcp_tool_name(name):
    """
    Splits a Claude Code MCP tool_use name ('mcp__<server>__<tool>') into
    (server, tool). Returns None for non-MCP tool names (e.g. "Bash", "Read").
    Server names can themselves contain underscores, so only the LAST "__"
    is treated as the server/tool separator.
    """
    if not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__"):]
    if "__" not in rest:
        return None
    server, tool = rest.rsplit("__", 1)
    return server, tool


def build_mcp_call_log(group, config_data):
    """
    Per-turn log of every local MCP tool_use call within one session (main +
    subagents), most recent first - the actual "what did this specific
    prompt/instruction consume" view, as opposed to a history-wide aggregate.
    Each row is one assistant turn that called at least one MCP tool, with
    which tool(s) it called and that turn's own token/cost.

    Honesty caveat this deliberately keeps visible in the UI (see
    tui.render_session_breakdown_view()): Claude bills per TURN (one
    assistant message), not per individual tool call, and a single turn can
    call more than one tool - including tools from more than one MCP server
    - alongside its own text/reasoning. So a row's tokens/cost describe the
    whole turn, not an isolated cost for just that one tool call. `tools`
    (the exact tool_use names in that turn) IS an exact count of what ran.
    """
    rows = []
    for path in [group["main"]] + group["subagents"]:
        is_subagent = path != group["main"]
        source = _read_subagent_meta(path).get("agentType", "Subagent") if is_subagent else "Main"

        for usage_line in _iter_usage_lines(path):
            mcp_tools = [n for n in (usage_line.get("tool_names") or []) if _parse_mcp_tool_name(n)]
            if not mcp_tools:
                continue

            model = usage_line["model"]
            cost = None
            if model in config_data:
                cost = calculate_call_cost(
                    model, usage_line["input_tokens"], usage_line["output_tokens"],
                    cached_read_tokens=usage_line["cache_read_tokens"], cached_write_tokens=usage_line["cache_write_tokens"]
                )

            rows.append({
                "timestamp": _parse_timestamp(usage_line["timestamp"]),
                "source": source,
                "tools": mcp_tools,
                "model": model,
                "input_tokens": usage_line["input_tokens"],
                "output_tokens": usage_line["output_tokens"],
                "cache_read_tokens": usage_line["cache_read_tokens"],
                "cache_write_tokens": usage_line["cache_write_tokens"],
                "cost": cost,
            })

    rows.sort(key=lambda r: r["timestamp"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def _safe_mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _parse_timestamp(ts):
    """Parse a transcript's ISO-8601 timestamp (e.g. '2026-01-01T00:00:00.000Z') into a UTC datetime, or None."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


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

    # Context window usage (mirrors what /context shows): the model bills
    # input_tokens + cache_read_tokens + cache_write_tokens as the full prompt
    # sent on the last turn, which is the best local proxy for how much of the
    # conversation-so-far occupies the context window right now.
    context_used_tokens = None
    context_window = None
    context_percent = None
    if last_request:
        context_used_tokens = last_request["input_tokens"] + last_request["cache_read_tokens"] + last_request["cache_write_tokens"]
        model_cfg = config_data.get(last_request["model"])
        if model_cfg and model_cfg.get("context_window"):
            context_window = model_cfg["context_window"]
            context_percent = min(100.0, (context_used_tokens / context_window) * 100)

    mtime = max([_safe_mtime(main_path)] + [_safe_mtime(p) for p in subagent_paths])

    return {
        "session_id": main_path.stem,
        "project": main_path.parent.name,
        "cwd": cwd,
        "models": sorted(by_model.keys()),
        "by_model": {model: dict(tokens) for model, tokens in by_model.items()},
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
        "context_used_tokens": context_used_tokens,
        "context_window": context_window,
        "context_percent": context_percent,
        "last_timestamp": last_timestamp,
        "mtime": mtime,
        "is_active": (now - mtime) <= ACTIVE_THRESHOLD_SECONDS
    }


def _read_subagent_meta(subagent_path):
    """
    Reads the sibling `<agent-id>.meta.json` Claude Code writes next to each
    subagent transcript (same directory, same stem, `.meta.json` extension).
    It holds only short task metadata - `agentType` (which subagent role was
    spawned, e.g. "Explore", "general-purpose") and `description` (a short
    one-line task label, the same text Claude Code's own transcript UI shows
    next to a Task tool call) - never the subagent's actual prompt/response
    content. Returns {} if the file is missing or malformed.
    """
    meta_path = subagent_path.with_suffix(".meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build_subagent_breakdown(group, config_data):
    """
    Per-subagent token/cost breakdown for one session group, so you can see
    exactly how much a single subagent invocation (a "Task" tool call, e.g.
    one Explore/general-purpose agent run) consumed, rather than only the
    session-wide total. Returns a list of dicts, most recently active first.
    """
    results = []
    for path in group["subagents"]:
        by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
        requests = 0
        last_timestamp = None

        for usage_line in _iter_usage_lines(path):
            model = usage_line["model"]
            by_model[model]["input"] += usage_line["input_tokens"]
            by_model[model]["output"] += usage_line["output_tokens"]
            by_model[model]["cache_read"] += usage_line["cache_read_tokens"]
            by_model[model]["cache_write"] += usage_line["cache_write_tokens"]
            requests += 1
            if usage_line["timestamp"] and (last_timestamp is None or usage_line["timestamp"] > last_timestamp):
                last_timestamp = usage_line["timestamp"]

        if requests == 0:
            continue

        cost = 0.0
        has_priced_model = False
        for model, tokens in by_model.items():
            if model not in config_data:
                continue
            has_priced_model = True
            cost += calculate_call_cost(
                model, tokens["input"], tokens["output"],
                cached_read_tokens=tokens["cache_read"], cached_write_tokens=tokens["cache_write"]
            )

        meta = _read_subagent_meta(path)

        results.append({
            "agent_id": path.stem,
            "agent_type": meta.get("agentType") or "unknown",
            "description": meta.get("description"),
            "models": sorted(by_model.keys()),
            "requests": requests,
            "input_tokens": sum(m["input"] for m in by_model.values()),
            "output_tokens": sum(m["output"] for m in by_model.values()),
            "cache_read_tokens": sum(m["cache_read"] for m in by_model.values()),
            "cache_write_tokens": sum(m["cache_write"] for m in by_model.values()),
            "cost": cost if has_priced_model else None,
            "last_timestamp": last_timestamp,
            "mtime": _safe_mtime(path),
        })

    results.sort(key=lambda a: a["mtime"], reverse=True)
    return results


def get_session_breakdown(session_id, config_data):
    """
    Finds the session group whose main transcript stem matches `session_id`
    and returns (session_summary, subagent_breakdown, mcp_call_log).
    session_summary is None if the session no longer exists (e.g. its
    transcript was removed between the picker list and this call).
    """
    for group in find_session_groups():
        if group["main"].stem == session_id:
            return (
                build_session_summary(group, config_data),
                build_subagent_breakdown(group, config_data),
                build_mcp_call_log(group, config_data),
            )
    return None, [], []


def watch_session_breakdown(session_id, config_data, refresh_seconds=3):
    """Render a live-updating per-subagent + per-MCP-call breakdown for one session until interrupted (Ctrl+C)."""
    from rich.live import Live
    from tokens_counter.tui import console, render_session_breakdown_view

    def snapshot():
        session_summary, subagents, mcp_calls = get_session_breakdown(session_id, config_data)
        return render_session_breakdown_view(session_id, session_summary, subagents, mcp_calls)

    with Live(snapshot(), console=console, refresh_per_second=4) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(snapshot())


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


def get_global_usage_summary(config_data):
    """
    Aggregates every local session into a snapshot modeled on Claude Code's
    own `/usage` command: a total cost and a "Usage by model" breakdown
    (per-model input/output/cache-read/cache-write tokens and cost), plus a
    per-project breakdown. Unlike `/usage` - which is scoped to the single
    session it's run from - this covers every local session found under
    ~/.claude/projects, since that's the "global" view this app can offer
    from local transcripts alone. It cannot reproduce `/usage`'s plan-limit
    percentage bars, which require a live call to Anthropic's usage endpoint.
    """
    sessions = get_all_sessions(config_data)

    global_by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    by_project = defaultdict(lambda: {"cost": 0.0, "has_priced_model": False, "requests": 0, "input": 0, "output": 0})
    total_requests = 0
    last_timestamp = None

    for s in sessions:
        for model, tokens in s["by_model"].items():
            bucket = global_by_model[model]
            bucket["input"] += tokens["input"]
            bucket["output"] += tokens["output"]
            bucket["cache_read"] += tokens["cache_read"]
            bucket["cache_write"] += tokens["cache_write"]

        project_label = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
        project = by_project[project_label]
        if s["cost"] is not None:
            project["cost"] += s["cost"]
            project["has_priced_model"] = True
        session_requests = s["main_requests"] + s["subagent_requests"]
        project["requests"] += session_requests
        project["input"] += s["input_tokens"]
        project["output"] += s["output_tokens"]

        total_requests += session_requests
        if s["last_timestamp"] and (last_timestamp is None or s["last_timestamp"] > last_timestamp):
            last_timestamp = s["last_timestamp"]

    usage_by_model = []
    total_cost = 0.0
    any_priced = False
    for model, tokens in global_by_model.items():
        cost = None
        if model in config_data:
            cost = calculate_call_cost(
                model, tokens["input"], tokens["output"],
                cached_read_tokens=tokens["cache_read"], cached_write_tokens=tokens["cache_write"]
            )
            total_cost += cost
            any_priced = True
        usage_by_model.append({"model": model, **tokens, "cost": cost})
    usage_by_model.sort(key=lambda m: (m["cost"] or 0), reverse=True)

    projects = [
        {
            "project": project,
            "cost": data["cost"] if data["has_priced_model"] else None,
            "requests": data["requests"],
            "input": data["input"],
            "output": data["output"]
        }
        for project, data in by_project.items()
    ]
    projects.sort(key=lambda p: (p["cost"] or 0), reverse=True)

    return {
        "session_count": len(sessions),
        "total_requests": total_requests,
        "total_cost": total_cost if any_priced else None,
        "usage_by_model": usage_by_model,
        "projects": projects,
        "last_timestamp": last_timestamp
    }


def get_rolling_window_usage(config_data, now=None):
    """
    Sums real local token/cost consumption across every local session (main +
    subagents) within rolling 5-hour and 7-day windows measured from `now`,
    and reports how much of each window's timespan is currently occupied by
    continuous real activity.

    This is deliberately NOT the same thing as Claude Code's actual quota-used
    percentage for its 5h/weekly seat-allowance windows: that's computed
    server-side against a per-tier budget that isn't publicly documented and
    isn't cached to disk anywhere this app can read (confirmed by inspecting
    ~/.claude.json, ~/.claude/.credentials.json, and ~/.claude/policy-limits.json
    - none of them hold a usage-consumed number or a reset timestamp).

    Two earlier versions of this function got the framing wrong:
    - The first tried to guess a window "start" from the last activity gap >=
      the window's duration, which collapsed to "just started" after any
      ordinary multi-hour break.
    - The second anchored to the MOST RECENT activity and counted down to
      when it would age out of the window. That's mathematically sound, but
      it means every new request during an active session pushes the
      countdown back out toward the full window duration - so while you're
      actively working, the countdown never visibly decreases. It also
      framed the number backwards from what "how much of my window have I
      used" should mean.

    This version instead finds the OLDEST activity that currently still
    falls inside the window (`window_start_at`) and reports how long it's
    been sitting there: `elapsed_seconds` = `now - window_start_at` (capped
    at the window's duration), expressed as `percent_used` of that duration.
    This grows the more continuously you keep using Claude Code (a real,
    non-fabricated fact from your own transcripts) instead of resetting
    every time you send a new message, and it naturally drops back down once
    that oldest request itself ages out with nothing newer to replace it. An
    empty window (no activity at all in range) reports None throughout
    rather than fabricating a value.
    """
    now = datetime.now(timezone.utc) if now is None else now
    windows = {
        "5h": {"cutoff": now - timedelta(hours=5), "duration": timedelta(hours=5)},
        "7d": {"cutoff": now - timedelta(days=7), "duration": timedelta(days=7)},
    }
    for w in windows.values():
        w.update({"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "requests": 0, "cost": 0.0, "any_priced": False, "window_start_at": None})

    for group in find_session_groups():
        for _, path in [(False, group["main"])] + [(True, p) for p in group["subagents"]]:
            for usage_line in _iter_usage_lines(path):
                ts = _parse_timestamp(usage_line["timestamp"])
                if ts is None:
                    continue

                model = usage_line["model"]
                cost = None
                if model in config_data:
                    cost = calculate_call_cost(
                        model, usage_line["input_tokens"], usage_line["output_tokens"],
                        cached_read_tokens=usage_line["cache_read_tokens"], cached_write_tokens=usage_line["cache_write_tokens"]
                    )

                for w in windows.values():
                    if ts < w["cutoff"] or ts > now:
                        continue
                    w["input"] += usage_line["input_tokens"]
                    w["output"] += usage_line["output_tokens"]
                    w["cache_read"] += usage_line["cache_read_tokens"]
                    w["cache_write"] += usage_line["cache_write_tokens"]
                    w["requests"] += 1
                    if cost is not None:
                        w["cost"] += cost
                        w["any_priced"] = True
                    if w["window_start_at"] is None or ts < w["window_start_at"]:
                        w["window_start_at"] = ts

    result = {}
    for key, w in windows.items():
        elapsed_seconds = percent_used = None
        if w["window_start_at"] is not None:
            duration_seconds = w["duration"].total_seconds()
            elapsed_seconds = min(duration_seconds, max(0.0, (now - w["window_start_at"]).total_seconds()))
            percent_used = min(100.0, (elapsed_seconds / duration_seconds) * 100)

        result[key] = {
            "input": w["input"],
            "output": w["output"],
            "cache_read": w["cache_read"],
            "cache_write": w["cache_write"],
            "requests": w["requests"],
            "cost": w["cost"] if w["any_priced"] else None,
            "window_start_at": w["window_start_at"],
            "elapsed_seconds": elapsed_seconds,
            "percent_used": percent_used
        }
    return result


def watch_sessions(config_data, refresh_seconds=3):
    """Render a live-updating view of all local sessions until interrupted (Ctrl+C)."""
    from rich.live import Live
    from tokens_counter.tui import console, render_session_monitor_view

    with Live(render_session_monitor_view(get_all_sessions(config_data)), console=console, refresh_per_second=4) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(render_session_monitor_view(get_all_sessions(config_data)))


def watch_global_usage(config_data, refresh_seconds=5):
    """
    Render a live-updating view of subscription status + global usage
    (Recent Consumption, Time-in-Window %, Usage by Model, By Project)
    until interrupted (Ctrl+C), so the Time-in-Window %/Time Elapsed counters
    visibly tick forward instead of requiring the user to exit and re-enter
    the menu option to see updated numbers.

    Keeping the live Group to just the numbers that actually change (plus
    capping long tables - see tui.MAX_TABLE_ROWS) matters: a Live renderable
    taller than the terminal either gets silently cropped (the default
    "ellipsis" overflow) or, if forced to vertical_overflow="visible", makes
    Live reprint the whole thing on every refresh instead of redrawing in
    place - which is what made "By Project" appear to scroll/duplicate
    endlessly in an earlier version of this function.
    """
    from rich.live import Live
    # Imported lazily (not at module load) to avoid a circular import, since
    # claude_config.py itself imports get_claude_config_dir from this module.
    from tokens_counter.claude_config import get_subscription_status
    from tokens_counter.tui import console, render_global_usage_live_view

    def snapshot():
        status = get_subscription_status()
        rolling_usage = get_rolling_window_usage(config_data)
        usage_data = get_global_usage_summary(config_data)
        return render_global_usage_live_view(status, rolling_usage, usage_data)

    with Live(snapshot(), console=console, refresh_per_second=1) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(snapshot())
