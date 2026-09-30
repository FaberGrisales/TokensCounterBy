import os
import json
import math
import shutil
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tokens_counter.config import load_budget
from tokens_counter.pricing import PriceBook, learn_rates

# Claude Code stores one JSONL transcript per session under
# <config_dir>/projects/<project>/<session-id>.jsonl, plus (when the session
# spawns subagents/workflows) nested transcripts under a same-named directory:
# <config_dir>/projects/<project>/<session-id>/subagents/**/*.jsonl
# This on-disk layout is an internal implementation detail of Claude Code
# (not a stable public API) so parsing failures are handled gracefully
# instead of raising - a format change should degrade to "no data", not crash.
ACTIVE_THRESHOLD_SECONDS = 300

# How long a session must have been idle before it's offered as a cleanup
# candidate in main.py's Option 5. Deliberately much longer than
# ACTIVE_THRESHOLD_SECONDS (which just distinguishes "LIVE" from "idle" in
# the live monitor) - this one gates real, irreversible file deletion, so it
# defaults to a week of true inactivity rather than a few idle minutes.
CLEANUP_INACTIVE_THRESHOLD_SECONDS = 7 * 24 * 60 * 60


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
    try:
        project_dirs = [p for p in projects_dir.iterdir() if p.is_dir()]
    except OSError:
        return []

    groups = []

    for project_dir in project_dirs:
        # scandir, not iterdir + is_file: DirEntry types come from readdir,
        # while Path.is_file() is one stat per entry - ~12ms each on a slow
        # (network/virtualized) filesystem.
        try:
            with os.scandir(project_dir) as it:
                entries = list(it)
        except OSError:
            continue
        dir_names = {e.name for e in entries if e.is_dir()}
        for entry in entries:
            if not (entry.is_file() and entry.name.endswith(".jsonl")):
                continue
            main = project_dir / entry.name
            subagent_files = []
            if main.stem in dir_names:
                try:
                    subagent_files = sorted((project_dir / main.stem).rglob("*.jsonl"))
                except OSError:
                    subagent_files = []
            groups.append({"main": main, "subagents": subagent_files})

    return groups


# path -> ((st_mtime_ns, st_size), [usage dicts]). Live views re-read every
# transcript every few seconds; a stat per file is ~100x cheaper than a
# re-parse (165MB of transcripts on a slow mounted drive: ~6s to parse, ~0.3s
# to stat), and only files that actually changed get parsed again.
# Callers only read the cached dicts - never mutate them.
_USAGE_CACHE = {}

# While a _scan() is running: path -> os.stat_result, so each file is stat'ed
# once per scan instead of once per helper that looks at it. None otherwise,
# so a file changed between two scans is always seen fresh.
_SCAN_STATS = None


def _stat(path):
    stats = _SCAN_STATS
    key = str(path)
    if stats is not None and key in stats:
        return stats[key]
    st = os.stat(path)
    if stats is not None:
        stats[key] = st
    return st


@contextmanager
def _scan(groups):
    """
    Parse every transcript in `groups` concurrently before a serial pass.

    The work is I/O-bound: on a slow filesystem each stat and read waits on
    the disk, and 8 threads read the same 93MB in 1.4s instead of 5.9s.
    The serial code afterwards then only hits _USAGE_CACHE / _SCAN_STATS.
    """
    global _SCAN_STATS
    owner = _SCAN_STATS is None
    if owner:
        _SCAN_STATS = {}
    try:
        paths = [p for g in groups for p in [g["main"], *g["subagents"]]]
        if len(paths) > 1:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(_cached_file, paths))
        yield
    finally:
        if owner:
            _SCAN_STATS = None


def _cached_file(path):
    """(usage lines, cost-state records) for one transcript, memoized on (mtime, size)."""
    try:
        st = _stat(path)
    except OSError:
        return [], []
    key = (st.st_mtime_ns, st.st_size)
    cached = _USAGE_CACHE.get(str(path))
    if cached is None or cached[0] != key:
        cached = (key, *_parse_file(path))
        _USAGE_CACHE[str(path)] = cached
    return cached[1], cached[2]


def _iter_usage_lines(path):
    """
    Token-usage metadata for each assistant message in a transcript file,
    plus the `name` of any tool it called (`tool_names`, e.g.
    "mcp__filesystem__read_file" or "Bash") - never the tool's arguments or
    result, and never any text/reasoning content.
    """
    return iter(_cached_file(path)[0])


def _iter_cost_states(path):
    """Claude Code's own `cost-state` records in a transcript (numbers only)."""
    return iter(_cached_file(path)[1])


def _usage_number(usage, key):
    """A token count: a finite, non-negative number, else 0."""
    value = usage.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value if math.isfinite(value) and value >= 0 else 0


def _parse_file(path):
    """
    One pass over a transcript: deduplicated usage lines, and cost-state records.

    Claude Code writes ONE assistant message as SEVERAL lines - one per
    content block (thinking, text, each tool_use) - and every one of them
    repeats the message's `usage`. Summing lines counted real usage ~2.4x on
    the developer's machine (4,734 lines for 2,001 messages). Lines sharing
    a `(message.id, requestId)` are therefore merged into one: token counts
    take the largest value seen (a later line of a streamed message carries
    the final output count, never a smaller one), and tool names are
    unioned, since each line holds different blocks. Lines without an id
    can't be matched and are kept as-is.

    `cost-state` records keep only numeric fields (see _cost_state_numbers).
    """
    lines = []
    by_key = {}
    cost_states = []
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
                if not isinstance(entry, dict):
                    continue

                if entry.get("type") == "cost-state":
                    record = _cost_state_numbers(entry)
                    if record:
                        cost_states.append(record)
                    continue

                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                model = message.get("model")
                if not isinstance(model, str):
                    model = None
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

                cache_creation = usage.get("cache_creation")
                cache_creation = cache_creation if isinstance(cache_creation, dict) else {}
                server_tools = usage.get("server_tool_use")
                server_tools = server_tools if isinstance(server_tools, dict) else {}

                # Only well-formed ids form a key - anything else can't be
                # matched reliably, and a list or dict isn't even hashable.
                message_id = message.get("id")
                request_id = entry.get("requestId")
                message_key = None
                if isinstance(message_id, str) and message_id and isinstance(request_id, (str, type(None))):
                    message_key = (message_id, request_id)

                timestamp = entry.get("timestamp")
                parsed = {
                    "timestamp": timestamp if isinstance(timestamp, str) else None,
                    "cwd": entry.get("cwd"),
                    "model": model or "unknown",
                    "input_tokens": _usage_number(usage, "input_tokens"),
                    "output_tokens": _usage_number(usage, "output_tokens"),
                    "cache_read_tokens": _usage_number(usage, "cache_read_input_tokens"),
                    "cache_write_tokens": _usage_number(usage, "cache_creation_input_tokens"),
                    # The part of cache_write written with a 1-hour TTL, billed
                    # at 2x input rather than the 5-minute 1.25x.
                    "cache_write_1h_tokens": _usage_number(cache_creation, "ephemeral_1h_input_tokens"),
                    "web_search_requests": _usage_number(server_tools, "web_search_requests"),
                    "tool_names": tool_names,
                    "message_key": message_key,
                }

                previous = by_key.get(message_key) if message_key else None
                if previous is None:
                    if message_key:
                        by_key[message_key] = parsed
                    lines.append(parsed)
                    continue
                for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                              "cache_write_1h_tokens", "web_search_requests"):
                    previous[field] = max(previous[field], parsed[field])
                previous["tool_names"] = previous["tool_names"] + [
                    n for n in tool_names if n not in previous["tool_names"]]
                if not previous["cwd"]:
                    previous["cwd"] = parsed["cwd"]
    except (OSError, UnicodeDecodeError):
        pass
    return lines, cost_states


_COST_STATE_FIELDS = ("inputTokens", "outputTokens", "cacheReadInputTokens",
                      "cacheCreationInputTokens", "webSearchRequests", "costUSD")


def _cost_state_numbers(entry):
    """
    A `cost-state` record reduced to its per-model numbers. The record also
    carries durations and line counts; only what pricing needs is kept.
    """
    model_usage = entry.get("modelUsage")
    if not isinstance(model_usage, dict):
        return None
    kept = {}
    for model, usage in model_usage.items():
        if isinstance(model, str) and isinstance(usage, dict):
            kept[model] = {k: usage.get(k) for k in _COST_STATE_FIELDS}
    if not kept:
        return None
    return {"modelUsage": kept, "hasUnknownModelCost": bool(entry.get("hasUnknownModelCost"))}


def _group_paths(group):
    return [group["main"], *group["subagents"]]


def build_price_book(config_data, groups=None):
    """
    A PriceBook over `config_data` plus rates learned from the cost-state
    records in `groups`' transcripts (already parsed if inside a _scan()).
    """
    records = [r for g in (groups or []) for p in _group_paths(g) for r in _iter_cost_states(p)]
    return PriceBook(config_data, learn_rates(records))


def _ownership_order(group):
    """
    Sort key deciding which session owns a message found in several files:
    the one whose transcript starts earliest. A resumed session copies the
    earlier messages WITH their original timestamps, so the two files often
    start at the same instant; the least recently modified file (the
    original, which stopped growing when it was resumed) breaks the tie,
    then the path, so the owner never depends on directory listing order.
    """
    stamps = [line["timestamp"] for p in _group_paths(group) for line in _iter_usage_lines(p) if line["timestamp"]]
    return (min(stamps) if stamps else "~", _safe_mtime(group["main"]), str(group["main"]))


def _dedupe_across(groups):
    """
    {path: usage lines} with each message kept in only ONE file.

    A resumed or forked session starts its transcript with a copy of the
    earlier conversation, message ids included - 296 messages on the
    developer's machine appeared in two sessions' files. They were billed
    once, so they're counted once: the session whose transcript starts
    earliest keeps them, and later copies are dropped.
    """
    seen = set()
    owned = {}
    for group in sorted(groups, key=_ownership_order):
        for path in _group_paths(group):
            kept = []
            for line in _iter_usage_lines(path):
                key = line.get("message_key")
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                kept.append(line)
            owned[str(path)] = kept
    return owned


def _lines_for(path, lines_by_path):
    if lines_by_path is not None and str(path) in lines_by_path:
        return iter(lines_by_path[str(path)])
    return _iter_usage_lines(path)


def _new_bucket():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cache_write_1h": 0, "web_search": 0}


def _add_to_bucket(bucket, usage_line):
    bucket["input"] += usage_line["input_tokens"]
    bucket["output"] += usage_line["output_tokens"]
    bucket["cache_read"] += usage_line["cache_read_tokens"]
    bucket["cache_write"] += usage_line["cache_write_tokens"]
    bucket["cache_write_1h"] += usage_line.get("cache_write_1h_tokens", 0)
    bucket["web_search"] += usage_line.get("web_search_requests", 0)


def _line_bucket(usage_line):
    bucket = _new_bucket()
    _add_to_bucket(bucket, usage_line)
    return bucket


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


def build_mcp_call_log(group, config_data, book=None, lines_by_path=None):
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
    book = book or build_price_book(config_data, [group])
    rows = []
    for path in [group["main"]] + group["subagents"]:
        is_subagent = path != group["main"]
        source = _read_subagent_meta(path).get("agentType", "Subagent") if is_subagent else "Main"

        for usage_line in _lines_for(path, lines_by_path):
            mcp_tools = [n for n in (usage_line.get("tool_names") or []) if _parse_mcp_tool_name(n)]
            if not mcp_tools:
                continue

            model = usage_line["model"]
            cost = book.cost(model, _line_bucket(usage_line))

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
                "cost_estimated": book.is_estimated(model),
            })

    rows.sort(key=lambda r: r["timestamp"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def _safe_mtime(path):
    try:
        return _stat(path).st_mtime
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


def build_session_summary(group, config_data, now=None, book=None, lines_by_path=None):
    """
    Aggregate one session (main transcript + its subagents) into a display-ready summary dict.

    `book` prices the models (built from `config_data` alone when omitted);
    `lines_by_path` is _dedupe_across()'s output, so a resumed session
    doesn't re-count the conversation it copied from an earlier one.
    """
    main_path = group["main"]
    subagent_paths = group["subagents"]
    now = time.time() if now is None else now

    book = book or build_price_book(config_data, [group])
    by_model = defaultdict(_new_bucket)
    main_requests = 0
    subagent_requests = 0
    cwd = None
    last_timestamp = None
    last_request = None

    for is_subagent, path in [(False, main_path)] + [(True, p) for p in subagent_paths]:
        for usage_line in _lines_for(path, lines_by_path):
            model = usage_line["model"]
            _add_to_bucket(by_model[model], usage_line)

            if is_subagent:
                subagent_requests += 1
            else:
                main_requests += 1

            if usage_line["cwd"]:
                cwd = usage_line["cwd"]
            if usage_line["timestamp"] and (last_timestamp is None or usage_line["timestamp"] > last_timestamp):
                last_timestamp = usage_line["timestamp"]
                last_request = {"model": model, **{k: usage_line.get(k, 0) for k in (
                    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                    "cache_write_1h_tokens", "web_search_requests")}}

    total_requests = main_requests + subagent_requests
    if total_requests == 0:
        return None

    total_input = sum(m["input"] for m in by_model.values())
    total_output = sum(m["output"] for m in by_model.values())
    total_cache_read = sum(m["cache_read"] for m in by_model.values())
    total_cache_write = sum(m["cache_write"] for m in by_model.values())

    priced_cost = 0.0
    has_priced_model = False
    pricing = {}
    for model, tokens in by_model.items():
        cost = book.cost(model, tokens)
        pricing[model] = book.source(model)
        if cost is None:
            continue
        has_priced_model = True
        priced_cost += cost

    last_request_cost = None
    if last_request:
        last_request_cost = book.cost(last_request["model"], _line_bucket(last_request))

    # Context window usage (mirrors what /context shows): the model bills
    # input_tokens + cache_read_tokens + cache_write_tokens as the full prompt
    # sent on the last turn, which is the best local proxy for how much of the
    # conversation-so-far occupies the context window right now.
    context_used_tokens = None
    context_window = None
    context_percent = None
    if last_request:
        context_used_tokens = last_request["input_tokens"] + last_request["cache_read_tokens"] + last_request["cache_write_tokens"]
        model_cfg = book.get(last_request["model"])
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
        # model -> "configured" / "alias" / "learned" / "estimated", or None
        # when unpriced. An estimated rate is borrowed from a sibling model,
        # so a cost that includes one is shown with a "~".
        "pricing": pricing,
        "cost_estimated": any(src == "estimated" for src in pricing.values()),
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


def build_subagent_breakdown(group, config_data, book=None, lines_by_path=None):
    """
    Per-subagent token/cost breakdown for one session group, so you can see
    exactly how much a single subagent invocation (a "Task" tool call, e.g.
    one Explore/general-purpose agent run) consumed, rather than only the
    session-wide total. Returns a list of dicts, most recently active first.
    """
    book = book or build_price_book(config_data, [group])
    results = []
    for path in group["subagents"]:
        by_model = defaultdict(_new_bucket)
        requests = 0
        last_timestamp = None

        for usage_line in _lines_for(path, lines_by_path):
            _add_to_bucket(by_model[usage_line["model"]], usage_line)
            requests += 1
            if usage_line["timestamp"] and (last_timestamp is None or usage_line["timestamp"] > last_timestamp):
                last_timestamp = usage_line["timestamp"]

        if requests == 0:
            continue

        cost = 0.0
        has_priced_model = False
        for model, tokens in by_model.items():
            model_cost = book.cost(model, tokens)
            if model_cost is None:
                continue
            has_priced_model = True
            cost += model_cost

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
            "cost_estimated": any(book.is_estimated(m) for m in by_model),
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
    groups = find_session_groups()
    with _scan(groups):
        # Rates learned from every session's cost records, so a model is
        # priced the same here as in Options 1 and 2.
        book = build_price_book(config_data, groups)
        owned = _dedupe_across(groups)
        for group in groups:
            if group["main"].stem == session_id:
                return (
                    _summarize(group, config_data, now=None, book=book, owned=owned),
                    build_subagent_breakdown(group, config_data, book=book, lines_by_path=owned),
                    build_mcp_call_log(group, config_data, book=book, lines_by_path=owned),
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


def _summarize(group, config_data, now, book, owned):
    """
    build_session_summary() over the lines this session OWNS (see
    _dedupe_across), falling back to a zero-usage summary for a session whose
    every message is a copy from another one - a resumed session nothing new
    was sent in. Dropping it would hide a real transcript file from Option 1
    and, worse, from Option 5's cleanup list.
    """
    summary = build_session_summary(group, config_data, now=now, book=book, lines_by_path=owned)
    if summary is not None:
        return summary
    summary = build_session_summary(group, config_data, now=now, book=book)
    if summary is None:
        return None
    summary.update({
        "by_model": {}, "main_requests": 0, "subagent_requests": 0,
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost": None, "pricing": {}, "cost_estimated": False,
        "copied_only": True,
    })
    return summary


def get_all_sessions(config_data, now=None):
    """Return a summary per local Claude Code session, most recently active first."""
    return _all_sessions_with_book(config_data, now)[0]


def _all_sessions_with_book(config_data, now=None):
    """get_all_sessions() plus the PriceBook it priced them with."""
    now = time.time() if now is None else now
    summaries = []
    groups = find_session_groups()
    with _scan(groups):
        book = build_price_book(config_data, groups)
        owned = _dedupe_across(groups)
        for group in groups:
            summary = _summarize(group, config_data, now, book, owned)
            if summary:
                summaries.append(summary)
    summaries.sort(key=lambda s: s["mtime"], reverse=True)
    return summaries, book


def get_cleanup_candidates(config_data, now=None, threshold_seconds=CLEANUP_INACTIVE_THRESHOLD_SECONDS):
    """
    Returns sessions that have been inactive for at least `threshold_seconds`
    (default CLEANUP_INACTIVE_THRESHOLD_SECONDS, 7 days), most-inactive
    first, for main.py's Option 5 cleanup picker. Each candidate is a normal
    build_session_summary() dict plus `age_seconds` and the actual
    `main_path`/`subagent_paths` delete_session() needs to remove it - kept
    on the same dict so the picker never has to re-look-up a session by ID
    between listing it and deleting it.
    """
    now = time.time() if now is None else now
    candidates = []
    groups = find_session_groups()
    with _scan(groups):
        book = build_price_book(config_data, groups)
        owned = _dedupe_across(groups)
        summaries = [(group, _summarize(group, config_data, now, book, owned)) for group in groups]
    for group, summary in summaries:
        if summary is None:
            continue
        age_seconds = now - summary["mtime"]
        if age_seconds < threshold_seconds:
            continue
        candidates.append({
            **summary,
            "age_seconds": age_seconds,
            "main_path": group["main"],
            "subagent_paths": group["subagents"],
        })
    candidates.sort(key=lambda c: c["mtime"])
    return candidates


def delete_session(candidate):
    """
    Permanently deletes one session's main transcript file and its
    `<session-id>/subagents/` directory (if any) from disk. This is real,
    irreversible deletion of Claude Code's own local history files - not
    reversible by this app, and not something Claude Code itself exposes a
    command for. Only ever call this after explicit user confirmation.
    Returns (success: bool, error_message: str or None).
    """
    main_path = candidate["main_path"]
    session_dir = main_path.parent / main_path.stem
    try:
        if main_path.exists():
            main_path.unlink()
        if session_dir.is_dir():
            shutil.rmtree(session_dir)
        return True, None
    except OSError as e:
        return False, str(e)


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
    sessions, book = _all_sessions_with_book(config_data)

    global_by_model = defaultdict(_new_bucket)
    by_project = defaultdict(lambda: {"cost": 0.0, "has_priced_model": False, "requests": 0, "input": 0, "output": 0})
    total_requests = 0
    last_timestamp = None

    for s in sessions:
        for model, tokens in s["by_model"].items():
            bucket = global_by_model[model]
            for field, value in tokens.items():
                bucket[field] = bucket.get(field, 0) + value

        project_label = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
        project = by_project[project_label]
        if s["cost"] is not None:
            project["cost"] += s["cost"]
            project["has_priced_model"] = True
            project["cost_estimated"] = project.get("cost_estimated", False) or s.get("cost_estimated", False)
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
    any_estimated = False
    for model, tokens in global_by_model.items():
        cost = book.cost(model, tokens)
        if cost is not None:
            total_cost += cost
            any_priced = True
        pricing = book.get(model)
        source = pricing["pricing_source"] if pricing else None
        any_estimated = any_estimated or source == "estimated"
        usage_by_model.append({
            "model": model, **tokens, "cost": cost,
            "pricing_source": source,
            "based_on": pricing.get("based_on") if pricing else None,
        })
    usage_by_model.sort(key=lambda m: (m["cost"] or 0), reverse=True)

    projects = [
        {
            "project": project,
            "cost": data["cost"] if data["has_priced_model"] else None,
            "cost_estimated": data.get("cost_estimated", False),
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
        "total_cost_estimated": any_estimated,
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
        w.update({"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "requests": 0, "cost": 0.0,
                  "any_priced": False, "cost_estimated": False, "window_start_at": None})

    groups = find_session_groups()
    with _scan(groups):
        book = build_price_book(config_data, groups)
        owned = _dedupe_across(groups)
        lines = [line for group in groups for path in _group_paths(group)
                 for line in owned.get(str(path), ())]
    for usage_line in lines:
        ts = _parse_timestamp(usage_line["timestamp"])
        if ts is None:
            continue

        model = usage_line["model"]
        cost = book.cost(model, _line_bucket(usage_line))
        estimated = book.is_estimated(model)

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
                w["cost_estimated"] = w["cost_estimated"] or estimated
            if w["window_start_at"] is None or ts < w["window_start_at"]:
                w["window_start_at"] = ts

    result = {}
    for key, w in windows.items():
        elapsed_seconds = percent_used = None
        window_end_at = remaining_seconds = None
        if w["window_start_at"] is not None:
            duration_seconds = w["duration"].total_seconds()
            elapsed_seconds = min(duration_seconds, max(0.0, (now - w["window_start_at"]).total_seconds()))
            percent_used = min(100.0, (elapsed_seconds / duration_seconds) * 100)

            # When the oldest request still inside the window ages out of it.
            # This is an exact, computable moment - window_start_at is a real
            # timestamp from a transcript and the duration is fixed - unlike a
            # plan-quota reset time, which is server-side and unknowable here.
            # It is NOT "when your limit resets": after this instant the
            # window simply re-anchors to whatever request is then oldest, so
            # the end time jumps forward rather than the counter zeroing.
            window_end_at = w["window_start_at"] + w["duration"]
            remaining_seconds = max(0.0, (window_end_at - now).total_seconds())

        result[key] = {
            "input": w["input"],
            "output": w["output"],
            "cache_read": w["cache_read"],
            "cache_write": w["cache_write"],
            "requests": w["requests"],
            "cost": w["cost"] if w["any_priced"] else None,
            "cost_estimated": w["cost_estimated"],
            "window_start_at": w["window_start_at"],
            "window_end_at": window_end_at,
            "remaining_seconds": remaining_seconds,
            "elapsed_seconds": elapsed_seconds,
            "percent_used": percent_used
        }
    return result


def apply_budgets(rolling_usage, budget):
    """
    Annotate each rolling window with usage against the user's own budget.

    This is the ONLY honest percentage-of-consumption this app can show. The
    plan-quota percentage `/usage` displays is computed server-side against an
    undocumented per-tier allowance that is not cached to disk anywhere
    readable (see get_rolling_window_usage), so the denominator here has to
    come from the user. Windows with no budget set get None throughout rather
    than a guessed limit - an invented denominator produces a believable,
    wrong number, which is worse than no number.

    Adds per window: `total_tokens` (always, budget or not),
    `budget_tokens`/`budget_tokens_percent` and
    `budget_cost`/`budget_cost_percent`. Percentages are NOT clamped at 100 -
    going over your own budget is exactly what you'd want to see.
    """
    budget = budget or {}
    for key, window in rolling_usage.items():
        total_tokens = (
            window.get("input", 0) + window.get("output", 0)
            + window.get("cache_read", 0) + window.get("cache_write", 0)
        )
        window["total_tokens"] = total_tokens

        limits = budget.get(key) or {}
        token_limit = limits.get("tokens")
        cost_limit = limits.get("cost_usd")

        window["budget_tokens"] = token_limit
        window["budget_tokens_percent"] = (
            (total_tokens / token_limit) * 100 if token_limit else None
        )

        cost = window.get("cost")
        window["budget_cost"] = cost_limit
        window["budget_cost_percent"] = (
            (cost / cost_limit) * 100 if cost_limit and cost is not None else None
        )
    return rolling_usage


def get_live_sessions(config_data, now=None):
    """
    Claude Code sessions plus OpenCode's, most recently active first - for
    the live views (Option 1, floating window). The rest of the app (Session
    Breakdown, Cleanup, usage windows) stays Claude Code only: OpenCode
    sessions have no transcript files to break down or delete.
    """
    from tokens_counter.opencode_sessions import get_opencode_sessions
    sessions = get_all_sessions(config_data, now=now) + get_opencode_sessions(now=now)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def watch_sessions(config_data, refresh_seconds=2):
    """Render a live-updating view of all local sessions until interrupted (Ctrl+C)."""
    from rich.live import Live
    from tokens_counter.tui import console, render_session_monitor_view

    with Live(render_session_monitor_view(get_live_sessions(config_data)), console=console, refresh_per_second=4) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(render_session_monitor_view(get_live_sessions(config_data)))


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
    from tokens_counter.claude_config import get_subscription_status, get_best_plan_limits
    from tokens_counter.tui import console, render_global_usage_live_view

    def snapshot():
        status = get_subscription_status()
        # Re-read the budget each tick (not once outside the loop) so editing
        # budget_config.json shows up within one refresh instead of needing
        # the app restarted.
        rolling_usage = apply_budgets(get_rolling_window_usage(config_data), load_budget())
        usage_data = get_global_usage_summary(config_data)
        # Re-read each tick too: the status line rewrites its cache whenever a
        # Claude Code session renders, and Desktop samples every ~15 minutes.
        plan_limits = get_best_plan_limits()
        from tokens_counter.opencode_sessions import get_opencode_usage
        return render_global_usage_live_view(status, rolling_usage, usage_data, plan_limits,
                                             opencode_usage=get_opencode_usage())

    with Live(snapshot(), console=console, refresh_per_second=1) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(snapshot())
