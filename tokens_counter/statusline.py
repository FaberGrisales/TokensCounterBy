#!/usr/bin/env python3
"""
Claude Code status line script that captures your REAL plan rate limits.

Why this exists: the 5h/7d plan-quota percentages `/usage` shows are computed
server-side and are not cached to disk anywhere this app can read (verified
against ~/.claude.json, .credentials.json and policy-limits.json). The app
makes no network calls, so it cannot ask for them either.

But Claude Code itself already has the numbers, and since v2.1.80 it hands
them to status line scripts: it runs the configured `statusLine.command` and
pipes a JSON blob on stdin that includes

    {"rate_limits": {"five_hour":  {"used_percentage": 42.0, "resets_at": ...},
                     "seven_day":  {"used_percentage": 12.5, "resets_at": ...},
                     "spend_limit": {...}},
     "rate_limits_available": true, ...}

`rate_limits_available` is false (and `rate_limits` null) when plan limits
don't apply at all - API key, Bedrock, Vertex, or a profile missing the
scope. So this script caches whatever it's given and the app reads the cache.
Claude Code makes the network call; the app still makes none.

Two hard rules, because this runs inside the user's own Claude Code on every
status line render:

1. It must never fail in a way that breaks their status line. Every step is
   wrapped, and it always prints something.
2. It must be fast. No imports beyond the standard library, no disk scans.

Install it with Option 7 in the app, or by hand in ~/.claude/settings.json:

    {"statusLine": {"type": "command",
                    "command": "python3 /path/to/tokens_counter/statusline.py"}}
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

def _user_cache_dir():
    """
    Per-user cache directory, per platform convention.

    NOT next to this file: the repo may sit somewhere the user can't write
    (a system-wide or root-owned install, a read-only checkout), and writing
    into the source tree also means every clone carries a stale cache. Not
    inside ~/.claude either - the app treats Claude Code's own directory as
    strictly read-only, and this script is the one piece that writes.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "TokensCounterBy")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/TokensCounterBy")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "tokenscounterby")


# Overridable so a packaged or sandboxed install can redirect it without
# editing the source.
CACHE_FILE = os.environ.get(
    "TOKENS_COUNTER_CACHE",
    os.path.join(_user_cache_dir(), "rate_limits_cache.json"),
)

# Stamped into every cache write and required by the reader. Without it, any
# process that writes plausible-looking JSON to this path - a demo script, a
# half-finished experiment - produces a percentage the UI presents as a real
# quota reading. That happened during development and showed a fabricated
# "5h 43%" as if it came from Claude, which is precisely the believable-wrong
# number this app refuses to display everywhere else.
CACHE_SOURCE = "claude-code-statusline"


def _write_cache(payload):
    """
    Write the cache atomically.

    The app may read this file at any moment (its live views re-read every few
    seconds), and a status line render can happen at the same time. A plain
    truncate-then-write would let the reader see a half-written file; writing
    to a temp file in the same directory and renaming makes the swap atomic.
    """
    try:
        directory = os.path.dirname(CACHE_FILE)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(temp_path, CACHE_FILE)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    except Exception:
        # A cache we couldn't write is not worth breaking a status line over.
        pass


def _read_cache():
    """The previous cache, or None. Only ours - an unmarked file is ignored."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("source") == CACHE_SOURCE else None


def _usable(entry):
    """True if `entry` carries a real percentage."""
    if not isinstance(entry, dict):
        return False
    value = entry.get("used_percentage")
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _reset_epoch(value):
    """
    `resets_at` as epoch seconds for comparison, or None.

    Claude sends an integer Unix timestamp; ISO strings are accepted too.
    Kept local and stdlib-only: this script runs standalone from Claude Code,
    where the app's own modules may not be importable.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e11 else float(value)
    if isinstance(value, str) and value:
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def _is_stale_snapshot(incoming, previous):
    """
    True when `incoming` is an older view of the same window than `previous`.

    Every open Claude Code process holds its own in-memory copy of the rate
    limits, from whenever IT last heard from the server, and with
    refreshInterval every one of them rewrites this cache on a timer. An idle
    session therefore keeps pushing a reading from hours ago - observed live
    as the 5h figure flipping 83% -> 82% -> 83% every few seconds, and as a
    lingering "43%" from a session untouched since usage was at 43%.

    Two facts decide it without any clock on the snapshot itself:
      - a window that resets EARLIER than the one we hold is an older window;
      - within the SAME window, usage only ever goes up until the reset, so a
        lower percentage can only be an older snapshot.
    A later reset is a genuinely new window and is always accepted, even at a
    lower percentage. When either reset time is unknown there's nothing safe
    to compare, and the incoming value wins as before.
    """
    new_reset = _reset_epoch(incoming.get("resets_at"))
    old_reset = _reset_epoch(previous.get("resets_at"))
    if new_reset is None or old_reset is None:
        return False
    # Claude reports whole seconds; allow a little jitter between processes.
    if new_reset < old_reset - 60:
        return True
    if abs(new_reset - old_reset) <= 60:
        return incoming["used_percentage"] < previous["used_percentage"]
    return False


def _merge_with_previous(rate_limits, captured_at):
    """
    Stamp each fresh window, and carry the last good one forward when Claude
    sends none for it.

    A brand-new Claude Code session renders its status line before it has the
    account's rate limits, so it passes `rate_limits: null`. Writing that
    straight through wiped a perfectly good reading, and the UI dropped back
    to showing total spend until the user touched an older session - which is
    exactly the bug this fixes.

    A carried-forward window keeps its ORIGINAL `captured_at`, so it ages
    normally and the UI still marks it stale. Preserving the value must not
    also preserve the impression that it is current.
    """
    previous = (_read_cache() or {}).get("rate_limits") or {}
    if not isinstance(previous, dict):
        previous = {}
    incoming = rate_limits if isinstance(rate_limits, dict) else {}

    merged = {}
    for window in set(incoming) | set(previous):
        entry = incoming.get(window)
        prior = previous.get(window)
        if _usable(entry) and _usable(prior) and _is_stale_snapshot(entry, prior):
            # Another, fresher session already reported this window. Keep its
            # reading - with its own captured_at, so it still ages honestly.
            merged[window] = prior
        elif _usable(entry):
            merged[window] = {**entry, "captured_at": captured_at}
        elif _usable(prior):
            merged[window] = prior
    return merged or None


def _percent(rate_limits, window):
    entry = (rate_limits or {}).get(window)
    if not isinstance(entry, dict):
        return None
    value = entry.get("used_percentage")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    rate_limits = data.get("rate_limits") if isinstance(data, dict) else None
    available = data.get("rate_limits_available") if isinstance(data, dict) else None

    captured_at = datetime.now(timezone.utc).isoformat()
    previous = _read_cache() or {}
    rate_limits = _merge_with_previous(rate_limits, captured_at)
    if available is None:
        # Same reasoning as the windows: a new session reports nothing about
        # whether plan limits apply, which is not the same as reporting that
        # they don't.
        available = previous.get("rate_limits_available")

    _write_cache({
        "source": CACHE_SOURCE,
        "captured_at": captured_at,
        "rate_limits_available": available,
        "rate_limits": rate_limits,
    })

    # Whatever happens above, print a status line. This is the user's actual
    # status line, so it stays short and shows the two numbers this is for.
    parts = []
    five = _percent(rate_limits, "five_hour")
    seven = _percent(rate_limits, "seven_day")
    if five is not None:
        parts.append(f"5h {five:.0f}%")
    if seven is not None:
        parts.append(f"7d {seven:.0f}%")

    model = ((data.get("model") or {}).get("display_name")
             if isinstance(data, dict) and isinstance(data.get("model"), dict) else None)
    if model:
        parts.insert(0, model)

    line = " · ".join(parts) if parts else ""
    # Bytes, not print(): on Windows a piped stdout defaults to cp1252, which
    # encodes the "·" separator as a byte Claude Code (reading UTF-8) renders
    # as "�" in the status line.
    try:
        sys.stdout.buffer.write((line + "\n").encode("utf-8"))
        sys.stdout.flush()
    except Exception:
        print(line)


if __name__ == "__main__":
    main()
