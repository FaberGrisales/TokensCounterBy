"""
OpenCode sessions (the open-source coding agent) in the same shape as
session_monitor.build_session_summary(), so the Live Session Monitor and the
floating window can list them next to Claude Code's.

OpenCode keeps everything in one SQLite database,
`<XDG_DATA_HOME or ~/.local/share>/opencode/opencode.db` - the same path on
Windows, macOS and Linux. Each assistant row of its `message` table carries a
JSON `data` blob with `providerID`, `modelID`, `time`, `path.cwd`, `cost` (in
USD, computed by OpenCode itself from its models catalog - 0 for free and
local models) and `tokens` {input, output, reasoning, cache {read, write}}.
Sessions with a `parent_id` are subagent runs and are folded into their root
session, the way Claude Code's subagent transcripts are.

What this deliberately does NOT do:
- touch `auth.json` or the account/credential tables (live API keys/tokens);
- read message text - `part` holds the content and is never queried, and the
  `message` blobs are only read for the usage fields above;
- write anything: the database is opened read-only (`mode=ro`). If that
  fails - e.g. a WAL file left behind with no shared-memory file, which a
  read-only connection can't recover - the three files are copied to a temp
  dir and the copy is read instead, never the original.
- price anything itself: models_config.json is Claude-only; OpenCode's own
  `cost` is the only number shown. No context-window % either.

The format is OpenCode's internal schema, not an API, so every failure
degrades to "no OpenCode sessions" rather than raising.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

ACTIVE_THRESHOLD_SECONDS = 300

# (db mtime/size, wal mtime/size) -> parsed sessions; the widget refreshes
# every few seconds and the database rarely changes between refreshes.
_cache = {"key": None, "sessions": []}


def opencode_db_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "opencode", "opencode.db")


def _file_key(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_rows(db_path):
    """(sessions, assistant message blobs) from the database, read-only."""
    def query(path):
        con = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            sessions = con.execute(
                "select id, parent_id, directory, time_updated from session").fetchall()
            messages = con.execute("select session_id, data from message").fetchall()
            return sessions, messages
        finally:
            con.close()

    try:
        return query(db_path)
    except sqlite3.Error:
        pass
    tmp = tempfile.mkdtemp(prefix="tokenscounter-opencode-")
    try:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                shutil.copy2(db_path + suffix, os.path.join(tmp, "opencode.db" + suffix))
        return query(os.path.join(tmp, "opencode.db"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _summarize(session_rows, message_rows, now):
    parent = {sid: pid for sid, pid, _dir, _upd in session_rows}
    directory = {sid: d for sid, _pid, d, _upd in session_rows}
    updated = {sid: u for sid, _pid, _d, u in session_rows}

    def root_of(sid):
        seen = set()
        while parent.get(sid) and sid not in seen:
            seen.add(sid)
            sid = parent[sid]
        return sid

    roots = {}
    for sid, _pid, _d, _u in session_rows:
        root = root_of(sid)
        entry = roots.setdefault(root, {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0,
            "requests": 0, "children": set(), "models": [], "last": None, "last_time": 0,
            "cwd": directory.get(root), "updated": _number(updated.get(root)),
        })
        if sid != root:
            entry["children"].add(sid)
        entry["updated"] = max(entry["updated"], _number(updated.get(sid)))

    for sid, blob in message_rows:
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("role") != "assistant":
            continue
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        root = root_of(sid)
        entry = roots.get(root)
        if entry is None:
            continue
        # Reasoning tokens are billed as output, so count them there.
        out = _number(tokens.get("output")) + _number(tokens.get("reasoning"))
        entry["input"] += _number(tokens.get("input"))
        entry["output"] += out
        entry["cache_read"] += _number(cache.get("read"))
        entry["cache_write"] += _number(cache.get("write"))
        entry["cost"] += _number(data.get("cost"))
        entry["requests"] += 1
        model = "/".join(p for p in (data.get("providerID"), data.get("modelID"))
                         if isinstance(p, str) and p)
        if model and model not in entry["models"]:
            entry["models"].append(model)
        when = data.get("time") if isinstance(data.get("time"), dict) else {}
        stamp = _number(when.get("completed")) or _number(when.get("created"))
        if stamp >= entry["last_time"]:
            entry["last_time"] = stamp
            entry["last"] = {"input_tokens": _number(tokens.get("input")),
                             "output_tokens": out, "cost": _number(data.get("cost"))}
        path = data.get("path") if isinstance(data.get("path"), dict) else {}
        if not entry["cwd"] and isinstance(path.get("cwd"), str):
            entry["cwd"] = path["cwd"]

    summaries = []
    for root, e in roots.items():
        if not e["requests"]:
            continue
        mtime = max(e["updated"], e["last_time"]) / 1000.0
        cwd = e["cwd"]
        summaries.append({
            "session_id": root,
            "project": cwd.replace("\\", "/").rstrip("/").split("/")[-1] if cwd else "opencode",
            "cwd": cwd,
            "origin": "opencode",
            "models": e["models"],
            "main_requests": e["requests"],
            "subagent_count": len(e["children"]),
            "subagent_requests": 0,
            "input_tokens": e["input"],
            "output_tokens": e["output"],
            "cache_read_tokens": e["cache_read"],
            "cache_write_tokens": e["cache_write"],
            # OpenCode's own figure; 0.0 means it reported no charge (free or
            # local model), which is shown as such rather than as unpriced.
            "cost": round(e["cost"], 6),
            "last_request": e["last"],
            "last_request_cost": e["last"]["cost"] if e["last"] else None,
            "context_percent": None,
            "mtime": mtime,
            "is_active": (now - mtime) <= ACTIVE_THRESHOLD_SECONDS,
        })
    summaries.sort(key=lambda s: s["mtime"], reverse=True)
    return summaries


def get_opencode_sessions(db_path=None, now=None):
    """OpenCode sessions, most recently active first; [] when there are none."""
    db_path = db_path or opencode_db_path()
    now = time.time() if now is None else now
    if not os.path.isfile(db_path):
        return []
    key = (db_path, _file_key(db_path), _file_key(db_path + "-wal"))
    if _cache["key"] != key:
        try:
            session_rows, message_rows = _read_rows(db_path)
            parsed = _summarize(session_rows, message_rows, now)
        except Exception:
            return []
        _cache.update(key=key, sessions=parsed)
    # Activity depends on the clock, not just the file, so refresh it.
    return [{**s, "is_active": (now - s["mtime"]) <= ACTIVE_THRESHOLD_SECONDS}
            for s in _cache["sessions"]]
