"""
Floating always-on-top monitor - a small window that stays above other
windows so session usage stays visible while working elsewhere.

This is a second presentation layer next to tui.py, not a second source of
truth: it reads the same `session_monitor.get_all_sessions()` dicts the TUI
renders, and contains no cost or token logic of its own.

Why tkinter and not GTK/Qt: `-topmost` is the only always-on-top mechanism
that works on Windows, macOS and Linux from the same code, and tkinter ships
with Python on Windows and macOS (on Linux it's the python3-tk OS package -
see dependencies.py). GTK4 removed its keep-above API entirely, and Qt would
add a large pip dependency to an app whose only current one is rich.

Wayland note: Wayland has no protocol letting a client raise itself, but
tkinter is an X11 client, so under GNOME it runs through XWayland and Mutter
honours the `_NET_WM_STATE_ABOVE` that `-topmost` sets. Verified working on
GNOME 46 / Ubuntu. On a compositor that ignores it the window still works,
it just won't stay on top - hence `toggle_on_top()` and the hint in the UI.
"""

import os

REFRESH_MS = 3000

# How often the UI thread checks whether a background read has finished.
# Short enough to feel instant, long enough to cost nothing.
POLL_MS = 150

# A plan-limit reading older than this is flagged rather than shown as
# current: the status line only rewrites its cache while a Claude Code
# session is rendering, so an idle machine's number ages silently.
STALE_AFTER_SECONDS = 300


def _stale_after(window):
    """Desktop only samples every ~15 min, so its readings age on that clock."""
    if (window or {}).get("source") == "desktop":
        from tokens_counter.claude_config import DESKTOP_SAMPLE_SECONDS
        return DESKTOP_SAMPLE_SECONDS + STALE_AFTER_SECONDS
    return STALE_AFTER_SECONDS

# Dark, low-contrast palette: this window sits on top of whatever the user is
# actually working on, so it should read at a glance without pulling focus.
BG = "#11131a"
FG = "#e6e6e6"
DIM = "#7a8290"
ACCENT = "#f5c542"
LIVE = "#4ade80"
BAR_BG = "#2a2f3a"


# Row tag per source: Claude Code, Claude Desktop's Code tab, OpenCode.
ORIGIN_TAGS = {"code": "code", "desktop": "desk", "opencode": "open"}


def _fmt_tokens(n):
    """Humanize a token count: 1234567 -> '1.2M'. Mirrors tui._fmt_tokens."""
    if n is None:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(cost):
    """Cost for a narrow column; never renders a real cost as a flat $0.00."""
    if cost is None:
        return "N/A"
    if cost == 0:
        return "free"
    return f"${cost:,.2f}" if cost >= 0.01 else "<$0.01"


def _context_color(percent):
    """Same green/yellow/red thresholds the TUI's context bar uses."""
    if percent is None:
        return DIM
    if percent < 50:
        return LIVE
    if percent < 80:
        return ACCENT
    return "#f87171"


def _to_datetime(value):
    """
    Parse a `resets_at` from Claude into a timezone-aware datetime.

    Claude Code sends it as an integer Unix timestamp in SECONDS (the schema
    in the binary is `resetsAt: v().int()`), not the ISO string the rest of
    this app's timestamps use. Both are accepted: the ISO branch keeps
    fixtures and any future format change working, and a value large enough
    to be milliseconds is rescaled rather than landing tens of thousands of
    years in the future. Returns None for anything unparseable.
    """
    from datetime import datetime, timezone

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:          # milliseconds, not seconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            return None
    return None


def _time_until(resets_at):
    """
    Compact time left until `resets_at`: '45m', '1h20m', '6d18h'.

    Precision matters more than brevity here. Rounding a duration up to whole
    hours turns 1h18m into "2h" - a 40-minute overstatement of how long you
    have left, which is the opposite of useful when you're watching a limit.
    So the hour and day ranges carry their remainder, and only the sub-hour
    range rounds (up, so a live window never reads "0m" for its last minute).

    Returns "now" once the moment has passed: the reset happened but no
    capture proves it yet, and a negative countdown would be worse.
    """
    import math
    from datetime import datetime, timezone

    when = _to_datetime(resets_at)
    if when is None:
        return None

    seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return "now"

    # One rounding rule for every scale: ceil to the next whole minute, then
    # format. Ceil because a countdown should never read "0m" while time
    # remains, and at minute granularity throughout because the alternatives
    # both misreport - rounding up to whole HOURS turns 1h18m into "2h" (40
    # minutes of overstatement), while truncating turns a 1h59m59s remainder
    # into "1h59m" when "2h" is what anyone would say.
    total_minutes = math.ceil(seconds / 60)
    if total_minutes < 60:
        return f"{total_minutes}m"

    hours, minutes = divmod(total_minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"

    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def _plan_headline(config_data, sessions=None):
    """
    What to show beside the live/idle counts: Claude's real 5h plan-limit
    percentage when it's available, else a fallback.

    Order is deliberate. The real number is the point, but it only exists when
    the status line capture is installed AND the account actually has plan
    limits (not API key / Bedrock / Vertex), so the widget degrades instead of
    going blank:

      1. real 5h plan % from Claude  ->  "5h 43%"
      2. the user's own 5h budget    ->  "5h 64%" (their denominator)
      3. neither                     ->  total spend, as before

    A stale capture is marked with a trailing "?" rather than shown as
    current - the cache only refreshes while a Claude Code session renders its
    status line.

    Returns (text, colour).
    """
    from tokens_counter import claude_config

    try:
        limits = claude_config.get_best_plan_limits()
    except Exception:
        limits = None

    five_hour = (limits or {}).get("five_hour")
    if five_hour:
        percent = five_hour["used_percentage"]
        # This window's own age, not the file's: a value carried forward
        # across a new session must still read as stale once it is.
        age = five_hour.get("age_seconds")
        if age is None:
            age = (limits or {}).get("age_seconds")
        stale = "?" if age is not None and age > _stale_after(five_hour) else ""
        # "5h 43% · resets 9m", not "5h:9m · 43%": juxtaposing the window name
        # with a duration reads as nonsense the moment the countdown is also
        # in hours ("5h:2h"), and a bare "9m left" beside a percentage reads
        # as remaining quota rather than time.
        left = _time_until(five_hour.get("resets_at"))
        label = f"5h {percent:.0f}%{stale}"
        seven_day = (limits or {}).get("seven_day")
        if seven_day:
            label += f" · 7d {seven_day['used_percentage']:.0f}%"
        if left:
            approx = "~" if five_hour.get("resets_at_estimated") else ""
            label += f" · resets {approx}{left}"
        return label, _context_color(percent)

    from tokens_counter.config import load_budget
    from tokens_counter import session_monitor

    try:
        windows = session_monitor.apply_budgets(
            session_monitor.get_rolling_window_usage(config_data), load_budget()
        )
        budget_percent = windows.get("5h", {}).get("budget_tokens_percent")
        if budget_percent is None:
            budget_percent = windows.get("5h", {}).get("budget_cost_percent")
        if budget_percent is not None:
            return f"5h · {budget_percent:.0f}%", _context_color(budget_percent)
    except Exception:
        pass

    try:
        if sessions is None:
            sessions = session_monitor.get_all_sessions(config_data)
        total = sum(s["cost"] for s in sessions if s["cost"] is not None)
        return _fmt_cost(total), ACCENT
    except Exception:
        return "", DIM


def _desktop_status(show_chat_title=False):
    """
    Claude Desktop's activity dict when it's been used recently, else None.

    With `show_chat_title` (the user's opt-in), also `chat`: the active
    chat's title/model from Desktop's cache, or None when it can't be read.
    """
    from tokens_counter import claude_config
    try:
        activity = claude_config.get_desktop_activity()
    except Exception:
        return None
    if not (activity and activity.get("is_active")):
        return None
    if show_chat_title:
        from tokens_counter import desktop_chats
        try:
            activity = {**activity,
                        "chat": desktop_chats.get_active_chat(claude_config.claude_desktop_dir())}
        except Exception:
            activity = {**activity, "chat": None}
    return activity


def _active_label(activity):
    """'active 2m ago' - activity only, never usage."""
    age = (activity or {}).get("age_seconds")
    if age is None:
        return "active"
    if age < 60:
        return "active now"
    return f"active {int(age // 60)}m ago"


def _system_status():
    """CPU/RAM/disk stats, or None without psutil or on any failure."""
    from tokens_counter import system_stats
    try:
        return system_stats.get_system_stats()
    except Exception:
        return None


def _header_counts(sessions, live_sessions, desktop):
    """(live, idle) for the header; an active Desktop counts as one live."""
    return live_sessions + (1 if desktop else 0), len(sessions or []) - live_sessions


def _rows(sessions, desktop, max_rows):
    """
    What the window lists, top to bottom, as plain dicts (no tkinter).

    A Desktop chat row comes first while Desktop is in use, alongside - never
    instead of - the Claude Code sessions: chats keep no per-chat token data
    anywhere on disk, so that row says only THAT Desktop is active. Code
    sessions (terminal/IDE `code`, or Desktop's Code tab `desk`) keep their
    full tokens / cost / context columns and fill the remaining rows.
    """
    rows = []
    if desktop:
        title = ((desktop.get("chat") or {}).get("title") or "").strip()
        rows.append({"kind": "chat", "name": title or "Claude Desktop",
                     "status": _active_label(desktop)})
    for s in (sessions or [])[:max(0, max_rows - len(rows))]:
        rows.append({"kind": "session", "session": s})
    return rows


def _collect_snapshot(config_data, show_chat_title=False):
    """
    Everything one refresh needs, gathered WITHOUT touching tkinter.

    This runs on a worker thread. Reading every transcript takes the better
    part of a second on a real machine (~0.6s measured), and the headline's
    budget fallback can add ~1.4s more; doing that on the window's own thread
    froze it - no redraw, no click, no Esc - for the whole read, every
    refresh. tkinter is not thread-safe, so the worker only computes plain
    data and the UI thread does all the drawing.

    Returns a dict: `sessions`, `live`, `headline` (text, colour), `desktop`
    (activity dict while Desktop is in use, else None), `system` (CPU/RAM/disk
    from system_stats, or None without psutil),
    and `error` (a message when the read failed, else None).
    """
    from tokens_counter import session_monitor
    try:
        sessions = session_monitor.get_live_sessions(config_data)
    except Exception as e:
        return {"sessions": None, "live": 0, "headline": None, "desktop": None,
                "system": None, "error": str(e)}

    from tokens_counter import claude_config
    try:
        desktop_ids = claude_config.get_desktop_code_session_ids()
    except Exception:
        desktop_ids = set()
    for s in sessions:
        if s.get("origin") != "opencode":
            s["origin"] = "desktop" if s["session_id"] in desktop_ids else "code"

    live = sum(1 for s in sessions if s["is_active"])
    try:
        headline = _plan_headline(config_data, sessions)
    except Exception:
        headline = None
    return {
        "sessions": sessions,
        "live": live,
        "headline": headline,
        "desktop": _desktop_status(show_chat_title),
        "system": _system_status(),
        "error": None,
    }


def is_available():
    """True if tkinter can be imported on this machine."""
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def run_floating_monitor(config_data, max_rows=5, show_chat_title=False):
    """
    Open the floating window and block until the user closes it.

    Blocking (rather than detaching a background process) is deliberate: it
    keeps the window's lifetime tied to the menu action that opened it, so
    quitting the app can't leave an orphaned window behind. The terminal is
    idle while it's open, which is fine - the window is the thing being used.

    Returns (ok, error_message).
    """
    try:
        import tkinter as tk
    except Exception as e:
        return False, f"tkinter is not available: {e}"
    import queue
    import threading

    from tokens_counter import session_monitor

    try:
        root = tk.Tk()
    except Exception as e:
        # No display (headless session, SSH without X forwarding, etc.).
        return False, f"Could not open a window: {e}"

    root.title("Tokens")
    root.configure(bg=BG)
    root.geometry("440x232+80+80")
    root.minsize(240, 120)
    root.attributes("-topmost", True)

    # CPU / RAM / disk / Claude memory, above everything else. Empty (and
    # zero-height) when psutil isn't installed.
    stats_frame = tk.Frame(root, bg=BG)
    stats_frame.pack(fill="x", padx=10, pady=(6, 0))

    header_frame = tk.Frame(root, bg=BG)
    header_frame.pack(fill="x", padx=10, pady=(2, 0))
    header = tk.Label(header_frame, bg=BG, fg=ACCENT, font=("sans", 9, "bold"), anchor="w")
    header.pack(side="left")
    # Separate label so the plan percentage can be green/yellow/red on its own
    # without recolouring the live/idle counts next to it.
    plan_label = tk.Label(header_frame, bg=BG, fg=DIM, font=("sans", 9, "bold"), anchor="e")
    plan_label.pack(side="right")
    # Packed after the plan label so it lands to its LEFT: a dim rule making
    # clear the percentage is a different measure from the session counts,
    # not a third count.
    tk.Label(header_frame, text="│", bg=BG, fg=BAR_BG,
             font=("sans", 9)).pack(side="right", padx=6)

    rows_frame = tk.Frame(root, bg=BG)
    rows_frame.pack(fill="both", expand=True, padx=10, pady=6)

    footer = tk.Label(root, bg=BG, fg=DIM, font=("sans", 7), anchor="w")
    footer.pack(fill="x", padx=10, pady=(0, 6))

    state = {"on_top": True, "job": None, "worker": None,
             "closed": False, "rendered": False}
    results = queue.Queue()

    def toggle_on_top(_event=None):
        """Let the user drop the window behind others without closing it."""
        state["on_top"] = not state["on_top"]
        root.attributes("-topmost", state["on_top"])
        render_footer()

    def render_footer():
        mark = "on top" if state["on_top"] else "normal"
        footer.config(text=f"click: toggle {mark} · Esc: close · refreshes every 3s")

    def close(_event=None):
        state["closed"] = True
        if state["job"] is not None:
            try:
                root.after_cancel(state["job"])
            except Exception:
                pass
        root.destroy()

    def render(snapshot):
        """Draw a snapshot. UI thread only."""
        if snapshot["error"]:
            # Keep the last good view on screen rather than blanking it; only
            # say something when there has never been anything to show.
            if not state["rendered"]:
                for child in rows_frame.winfo_children():
                    child.destroy()
                tk.Label(rows_frame, text=f"read error: {snapshot['error']}", bg=BG,
                         fg=DIM, font=("sans", 8), anchor="w",
                         wraplength=360).pack(fill="x")
            return

        if snapshot["headline"]:
            text, colour = snapshot["headline"]
            plan_label.config(text=text, fg=colour)

        for child in stats_frame.winfo_children():
            child.destroy()
        from tokens_counter.system_stats import format_stats
        for label, text, percent in format_stats(snapshot.get("system")):
            tk.Label(stats_frame, text=label, bg=BG, fg=DIM,
                     font=("sans", 7)).pack(side="left")
            tk.Label(stats_frame, text=text, bg=BG,
                     fg=FG if percent is None else _context_color(percent),
                     font=("monospace", 8)).pack(side="left", padx=(2, 8))

        for child in rows_frame.winfo_children():
            child.destroy()

        sessions = snapshot["sessions"]
        live, idle = _header_counts(sessions, snapshot["live"], snapshot["desktop"])
        header.config(text=f"● {live} live   ○ {idle} idle")

        for item in _rows(sessions, snapshot["desktop"], max_rows):
            row = tk.Frame(rows_frame, bg=BG)
            row.pack(fill="x", pady=1)

            if item["kind"] == "chat":
                # Desktop chats: activity only. No tokens, cost or context
                # exist on disk for them, so none are shown.
                tk.Label(row, text="●", bg=BG, fg=LIVE, font=("sans", 8)).pack(side="left")
                tk.Label(row, text="chat", bg=BG, fg=DIM, font=("sans", 7), anchor="w",
                         width=4).pack(side="left", padx=(4, 0))
                tk.Label(row, text=item["name"][:16], bg=BG, fg=FG, font=("sans", 8),
                         anchor="w", width=17).pack(side="left", padx=(4, 0))
                tk.Label(row, text=item["status"], bg=BG, fg=DIM, font=("monospace", 8),
                         anchor="e", width=21).pack(side="left")
                continue

            s = item["session"]
            name = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
            pct = s.get("context_percent")

            tk.Label(row, text="●" if s["is_active"] else "○", bg=BG,
                     fg=LIVE if s["is_active"] else DIM,
                     font=("sans", 8)).pack(side="left")
            # Which app the session was started from: both are real Claude
            # Code transcripts, so tokens and context mean the same thing.
            tk.Label(row, text=ORIGIN_TAGS.get(s.get("origin"), "code"),
                     bg=BG, fg=DIM, font=("sans", 7), anchor="w",
                     width=4).pack(side="left", padx=(4, 0))
            tk.Label(row, text=name[:16], bg=BG, fg=FG, font=("sans", 8),
                     anchor="w", width=17).pack(side="left", padx=(4, 0))
            tk.Label(row, text=_fmt_tokens(s["input_tokens"] + s["output_tokens"]),
                     bg=BG, fg=DIM, font=("monospace", 8), anchor="e",
                     width=7).pack(side="left")
            tk.Label(row, text=_fmt_cost(s["cost"]), bg=BG, fg=ACCENT,
                     font=("monospace", 8), anchor="e", width=9).pack(side="left")
            tk.Label(row, text="-" if pct is None else f"{pct:.0f}%", bg=BG,
                     fg=_context_color(pct), font=("monospace", 8), anchor="e",
                     width=5).pack(side="left")

        if not sessions and not snapshot["desktop"]:
            tk.Label(rows_frame, text="No Claude Code sessions or Desktop activity found.",
                     bg=BG, fg=DIM, font=("sans", 8), anchor="w").pack(fill="x")
        state["rendered"] = True

    def refresh():
        """Start a background read; the previous view stays up meanwhile."""
        if state["closed"]:
            return
        if state["worker"] is None or not state["worker"].is_alive():
            def work():
                results.put(_collect_snapshot(config_data, show_chat_title))
            state["worker"] = threading.Thread(target=work, daemon=True)
            state["worker"].start()
        state["job"] = root.after(POLL_MS, poll)

    def poll():
        """Pick up a finished read, if any. Never blocks the UI thread."""
        if state["closed"]:
            return
        try:
            snapshot = results.get_nowait()
        except queue.Empty:
            state["job"] = root.after(POLL_MS, poll)
            return
        render(snapshot)
        state["job"] = root.after(REFRESH_MS, refresh)

    root.bind("<Escape>", close)
    root.bind("<Button-1>", toggle_on_top)
    root.protocol("WM_DELETE_WINDOW", close)

    render_footer()
    refresh()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        close()
    return True, None
