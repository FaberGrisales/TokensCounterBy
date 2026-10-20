"""
OpenCode sessions (the open-source coding agent) in the same shape as
session_monitor.build_session_summary(), so the Live Session Monitor and the
floating window can list them next to Claude Code's, plus a per-model usage
summary for the Global Usage view.

OpenCode keeps everything in one SQLite database,
`<XDG_DATA_HOME or ~/.local/share>/opencode/opencode.db` - the same path on
Windows, macOS and Linux. Each assistant row of its `message` table carries a
JSON `data` blob with `providerID`, `modelID`, `time`, `path.cwd`, `cost` (in
USD, computed by OpenCode itself from its models catalog - 0 for free and
local models) and `tokens` {input, output, reasoning, cache {read, write}}.
Sessions with a `parent_id` are subagent runs and are folded into their root
session, the way Claude Code's subagent transcripts are.

Context window %: the size of each model's window comes from the catalog
OpenCode itself caches (`<XDG_CACHE_HOME or ~/.cache>/opencode/models.json`,
models.dev data: provider -> models -> limit.context), overridden by any
`provider.<id>.models.<id>.limit.context` in the user's opencode.json(c) -
the usual way to declare a local (Ollama) model's window. How much of it is
in use is the root session's latest reply, counted the way OpenCode's own
session header counts it: input + output + reasoning + cache read + cache
write. A model in neither place has no known window and gets no %.

What this deliberately does NOT do:
- touch `auth.json` or the account/credential tables (live API keys/tokens);
- read message text - `part` holds the content and is never queried, and the
  `message` blobs are only read for the usage fields above;
- OpenCode 2.x moved sessions to `session_v2` and messages to
  `session_message` (one row per user/assistant/idle/... record, in `seq`
  order); both layouts are read, the 2.x one reshaped into the 1.x form.
- write anything itself: the database is opened read-only (`mode=ro`). If that
  fails - e.g. a WAL file left behind with no shared-memory file, which a
  read-only connection can't recover - the three files are copied to a temp
  dir and the copy is read instead, never the original.
  Deleting a session (Option 5) goes through OpenCode's own
  `opencode session delete <id>` command, never a write to its database.
- read message text, with ONE exception: read_opencode_conversation() reads
  the `part` table's text parts of a single session, only when the user asks
  to preview that session in Option 5's cleanup picker.
- price anything itself: models_config.json is Claude-only; OpenCode's own
  `cost` is the only number shown.

The format is OpenCode's internal schema, not an API, so every failure
degrades to "no OpenCode sessions" rather than raising.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

ACTIVE_THRESHOLD_SECONDS = 300

# Parsed results keyed on the files they came from; the widget refreshes
# every few seconds and these rarely change between refreshes.
_cache = {"key": None, "sessions": [], "usage": None}
_windows_cache = {"key": None, "windows": {}}


def _home():
    return os.path.expanduser("~")


def opencode_db_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(_home(), ".local", "share")
    return os.path.join(base, "opencode", "opencode.db")


def opencode_catalog_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(_home(), ".cache")
    return os.path.join(base, "opencode", "models.json")


def opencode_config_paths():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(_home(), ".config")
    folder = os.path.join(base, "opencode")
    return [os.path.join(folder, "opencode.json"), os.path.join(folder, "opencode.jsonc")]


def _file_key(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


# --- context windows ---------------------------------------------------------

def _load_jsonc(path):
    """JSON, tolerating the whole-line `//` comments opencode.jsonc allows."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        return None


def _windows_from(providers):
    """{(provider, model): context} from a models.dev-shaped provider map."""
    windows = {}
    if not isinstance(providers, dict):
        return windows
    for provider_id, provider in providers.items():
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(models, dict):
            continue
        for model_id, model in models.items():
            limit = model.get("limit") if isinstance(model, dict) else None
            context = limit.get("context") if isinstance(limit, dict) else None
            if isinstance(context, (int, float)) and not isinstance(context, bool) and context > 0:
                windows[(provider_id, model_id)] = context
    return windows


def context_windows(catalog_path=None, config_paths=None):
    """(provider, model) -> context window in tokens; user config wins."""
    catalog_path = catalog_path or opencode_catalog_path()
    config_paths = config_paths or opencode_config_paths()
    key = (catalog_path, _file_key(catalog_path),
           tuple((p, _file_key(p)) for p in config_paths))
    if _windows_cache["key"] == key:
        return _windows_cache["windows"]
    windows = {}
    catalog = _load_jsonc(catalog_path)
    windows.update(_windows_from(catalog))
    for path in config_paths:
        config = _load_jsonc(path)
        if isinstance(config, dict):
            windows.update(_windows_from(config.get("provider")))
    _windows_cache.update(key=key, windows=windows)
    return windows


def context_window_for(windows, provider, model):
    """Exact id first, then without a routing suffix (`gpt-oss-120b:exacto`)."""
    if not provider or not model:
        return None
    return windows.get((provider, model)) or windows.get((provider, model.split(":")[0]))


# --- database ----------------------------------------------------------------

def _query_ro(db_path, query):
    """Runs query(connection) on the database read-only, falling back to a temp copy."""
    def run(path):
        con = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            return query(con)
        finally:
            con.close()

    try:
        return run(db_path)
    except sqlite3.Error:
        pass
    tmp = tempfile.mkdtemp(prefix="tokenscounter-opencode-")
    try:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                shutil.copy2(db_path + suffix, os.path.join(tmp, "opencode.db" + suffix))
        return run(os.path.join(tmp, "opencode.db"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def _v2_reply(blob):
    """
    An OpenCode 2.x `session_message` assistant record, reshaped into the 1.x
    `message.data` fields _replies() reads. 2.x keeps the same `cost`,
    `tokens` and `time`, but nests the model as {"id", "providerID"} and has
    no per-message `path` (the session's directory stands in for it).
    """
    try:
        data = json.loads(blob)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    return json.dumps({"role": "assistant", "providerID": model.get("providerID"),
                       "modelID": model.get("id"), "cost": data.get("cost"),
                       "time": data.get("time"), "tokens": data.get("tokens")})


def _read_rows(db_path):
    """
    (sessions, message blobs) from the database, read-only. OpenCode 1.x
    keeps them in `session`/`message`; 2.x (checked with 2.0.16) moved to
    `session_v2`/`session_message`, whose rows are reshaped to the 1.x form.
    """
    def query(con):
        tables = _tables(con)
        if "session" not in tables and "session_v2" in tables:
            sessions = con.execute(
                "select id, parent_id, directory, time_updated from session_v2").fetchall()
            messages = [(sid, reply) for sid, blob in con.execute(
                "select session_id, data from session_message where type = 'assistant'")
                for reply in [_v2_reply(blob)] if reply]
            return sessions, messages
        sessions = con.execute(
            "select id, parent_id, directory, time_updated from session").fetchall()
        messages = con.execute("select session_id, data from message").fetchall()
        return sessions, messages

    return _query_ro(db_path, query)


def _replies(message_rows):
    """Usage fields of every assistant message, as plain dicts."""
    for sid, blob in message_rows:
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("role") != "assistant":
            continue
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        when = data.get("time") if isinstance(data.get("time"), dict) else {}
        path = data.get("path") if isinstance(data.get("path"), dict) else {}
        provider = data.get("providerID") if isinstance(data.get("providerID"), str) else ""
        model = data.get("modelID") if isinstance(data.get("modelID"), str) else ""
        yield {
            "session_id": sid,
            "provider": provider,
            "model_id": model,
            "model": "/".join(p for p in (provider, model) if p),
            "input": _number(tokens.get("input")),
            # Reasoning tokens are billed as output, so count them there.
            "output": _number(tokens.get("output")) + _number(tokens.get("reasoning")),
            "cache_read": _number(cache.get("read")),
            "cache_write": _number(cache.get("write")),
            "cost": _number(data.get("cost")),
            "time": _number(when.get("completed")) or _number(when.get("created")),
            "cwd": path.get("cwd") if isinstance(path.get("cwd"), str) else None,
        }


def _summarize(session_rows, message_rows, windows, now):
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
            "requests": 0, "children": set(), "models": [], "last": None, "last_main": None,
            "cwd": directory.get(root), "updated": _number(updated.get(root)),
        })
        if sid != root:
            entry["children"].add(sid)
        entry["updated"] = max(entry["updated"], _number(updated.get(sid)))

    by_model = {}
    for r in _replies(message_rows):
        root = root_of(r["session_id"])
        entry = roots.get(root)
        if entry is None:
            continue
        for field in ("input", "output", "cache_read", "cache_write", "cost"):
            entry[field] += r[field]
        entry["requests"] += 1
        if r["model"] and r["model"] not in entry["models"]:
            entry["models"].append(r["model"])
        if entry["last"] is None or r["time"] >= entry["last"]["time"]:
            entry["last"] = r
        # The context in use is the main conversation's, not a subagent's -
        # and from a reply that actually ran: a failed call records 0 tokens,
        # which would read as an empty context.
        used = r["input"] + r["output"] + r["cache_read"] + r["cache_write"]
        if r["session_id"] == root and used and (entry["last_main"] is None
                                                 or r["time"] >= entry["last_main"]["time"]):
            entry["last_main"] = r
        if not entry["cwd"] and r["cwd"]:
            entry["cwd"] = r["cwd"]

        m = by_model.setdefault(r["model"] or "unknown", {
            "model": r["model"] or "unknown", "requests": 0, "input": 0, "output": 0,
            "cache_read": 0, "cache_write": 0, "cost": 0.0})
        m["requests"] += 1
        for field in ("input", "output", "cache_read", "cache_write", "cost"):
            m[field] += r[field]

    summaries = []
    for root, e in roots.items():
        last, main = e["last"], e["last_main"]
        mtime = max(e["updated"], last["time"] if last else 0) / 1000.0
        context_used = context_window = context_percent = None
        if main:
            context_used = (main["input"] + main["output"] + main["cache_read"]
                            + main["cache_write"])
            context_window = context_window_for(windows, main["provider"], main["model_id"])
            if context_window:
                context_percent = min(100.0, context_used / context_window * 100)
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
            "cost": round(e["cost"], 6) if e["requests"] else None,
            "last_request": {"input_tokens": last["input"], "output_tokens": last["output"]} if last else None,
            "last_request_cost": last["cost"] if last else None,
            "context_used_tokens": context_used,
            "context_window": context_window,
            "context_percent": context_percent,
            "mtime": mtime,
            "is_active": (now - mtime) <= ACTIVE_THRESHOLD_SECONDS,
        })
    summaries.sort(key=lambda s: s["mtime"], reverse=True)

    models = sorted(by_model.values(), key=lambda m: m["input"] + m["output"], reverse=True)
    usage = {
        "session_count": sum(1 for s in summaries if s["main_requests"]),
        "requests": sum(m["requests"] for m in models),
        "input": sum(m["input"] for m in models),
        "output": sum(m["output"] for m in models),
        "cost": round(sum(m["cost"] for m in models), 6),
        "by_model": models,
    }
    return summaries, usage


def _load(db_path, now):
    """(sessions, usage) for db_path, memoized on the files they depend on."""
    if not os.path.isfile(db_path):
        return [], None
    key = (db_path, _file_key(db_path), _file_key(db_path + "-wal"),
           _file_key(opencode_catalog_path()),
           tuple(_file_key(p) for p in opencode_config_paths()))
    if _cache["key"] != key:
        try:
            session_rows, message_rows = _read_rows(db_path)
            sessions, usage = _summarize(session_rows, message_rows, context_windows(), now)
        except Exception:
            return [], None
        _cache.update(key=key, sessions=sessions, usage=usage)
    return _cache["sessions"], _cache["usage"]


def get_opencode_sessions(db_path=None, now=None, include_empty=False):
    """
    OpenCode sessions, most recently active first; [] when there are none.
    Sessions without a single model reply are left out unless
    `include_empty` (Option 5 lists them, so abandoned ones can be deleted).
    """
    now = time.time() if now is None else now
    sessions, _usage = _load(db_path or opencode_db_path(), now)
    # Activity depends on the clock, not just the file, so refresh it.
    return [{**s, "is_active": (now - s["mtime"]) <= ACTIVE_THRESHOLD_SECONDS}
            for s in sessions if include_empty or s["main_requests"]]


def get_opencode_usage(db_path=None):
    """
    Machine-wide OpenCode totals and a per-model breakdown (most tokens first),
    or None when OpenCode isn't installed or has no usable data.
    """
    _sessions, usage = _load(db_path or opencode_db_path(), time.time())
    return usage if usage and usage["requests"] else None


_SESSION_ID = re.compile(r"ses_[A-Za-z0-9_-]+")


def read_opencode_conversation(session_id, db_path=None):
    """
    (title, [(role, text), ...] oldest first) for one root session: its title
    and the text parts of its user/assistant messages, for Option 5's preview
    only. Tool calls, reasoning, files and synthetic parts are skipped.
    Returns (None, []) when the session or the database can't be read.
    """
    def query(con):
        tables = _tables(con)
        if "session" not in tables and "session_v2" in tables:
            row = con.execute("select title from session_v2 where id = ?", (session_id,)).fetchone()
            records = con.execute(
                "select type, data from session_message where session_id = ? "
                "and type in ('user', 'assistant') order by seq", (session_id,)).fetchall()
            return (row[0] if row else None), None, records
        row = con.execute("select title from session where id = ?", (session_id,)).fetchone()
        columns = {r[1] for r in con.execute("pragma table_info(message)")}
        created = "m.time_created" if "time_created" in columns else "null"
        parts = con.execute(
            f"select m.data, p.data, {created} from part p join message m on m.id = p.message_id "
            "where p.session_id = ? order by p.rowid", (session_id,)).fetchall()
        return (row[0] if row else None), parts, None

    try:
        title, rows, v2_records = _query_ro(db_path or opencode_db_path(), query)
    except Exception:
        return None, []
    title = title if isinstance(title, str) else None
    if v2_records is not None:
        return title, _v2_conversation(v2_records)
    found = []
    for order, (message_blob, part_blob, created) in enumerate(rows):
        try:
            message, part = json.loads(message_blob), json.loads(part_blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(message, dict) or not isinstance(part, dict):
            continue
        role, text = message.get("role"), part.get("text")
        if (role not in ("user", "assistant") or part.get("type") != "text"
                or part.get("synthetic") or not isinstance(text, str) or not text.strip()):
            continue
        when = message.get("time") if isinstance(message.get("time"), dict) else {}
        found.append((_number(when.get("created")) or _number(created), order, role, text.strip()))
    found.sort(key=lambda f: (f[0], f[1]))
    return title, [(role, text) for _t, _o, role, text in found]


def _v2_conversation(records):
    """(role, text) pairs from 2.x `session_message` rows, already in `seq` order.

    A user record carries its prompt as `text`; an assistant record's
    `content` list holds text items next to tool calls and reasoning, of
    which only the text items are kept.
    """
    conversation = []
    for role, blob in records:
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("synthetic"):
            continue
        if role == "user":
            texts = [data.get("text")]
        else:
            content = data.get("content") if isinstance(data.get("content"), list) else []
            texts = [c.get("text") for c in content
                     if isinstance(c, dict) and c.get("type") == "text" and not c.get("synthetic")]
        text = "\n".join(t.strip() for t in texts if isinstance(t, str) and t.strip())
        if text:
            conversation.append((role, text))
    return conversation


def delete_opencode_session(session_id):
    """
    Deletes one OpenCode session (and its child sessions) through OpenCode's
    own `opencode session delete <id>` command - never by writing to its
    database, whose schema is internal and which OpenCode may have open.
    Returns (success, error_message) instead of raising.
    """
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        return False, f"not an OpenCode session id: {session_id!r}"
    exe = shutil.which("opencode")
    if not exe:
        return False, "the `opencode` command was not found on PATH"

    def run(*flags):
        return subprocess.run([exe, "session", "delete", *flags, session_id], capture_output=True,
                              stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                              errors="replace", timeout=120)

    try:
        # OpenCode 2.x otherwise routes the delete through a background
        # service it starts and leaves running; --standalone does the work in
        # this process and exits. 1.x has no service and rejects the flag by
        # printing the command's usage (1.18: no "unknown argument" line).
        result = run("--standalone")
        output = result.stdout + result.stderr
        if result.returncode != 0 and ("Positionals:" in output or "unknown argument" in output.lower()):
            result = run()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if result.returncode != 0:
        text = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr or result.stdout or "")
        message = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("at "):
                break  # stack trace
            line = re.sub(r"^error:\s*", "", line, flags=re.IGNORECASE)
            if line:
                message.append(line)
        return False, " - ".join(message[:3]) or f"opencode exited with code {result.returncode}"
    _cache.update(key=None)
    return True, None
