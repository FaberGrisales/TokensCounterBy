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

# Dark, low-contrast palette: this window sits on top of whatever the user is
# actually working on, so it should read at a glance without pulling focus.
BG = "#11131a"
FG = "#e6e6e6"
DIM = "#7a8290"
ACCENT = "#f5c542"
LIVE = "#4ade80"
BAR_BG = "#2a2f3a"


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


def is_available():
    """True if tkinter can be imported on this machine."""
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def run_floating_monitor(config_data, max_rows=5):
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

    from tokens_counter import session_monitor

    try:
        root = tk.Tk()
    except Exception as e:
        # No display (headless session, SSH without X forwarding, etc.).
        return False, f"Could not open a window: {e}"

    root.title("Tokens")
    root.configure(bg=BG)
    root.geometry("330x210+80+80")
    root.minsize(240, 120)
    root.attributes("-topmost", True)

    header = tk.Label(root, bg=BG, fg=ACCENT, font=("sans", 9, "bold"), anchor="w")
    header.pack(fill="x", padx=10, pady=(8, 0))

    rows_frame = tk.Frame(root, bg=BG)
    rows_frame.pack(fill="both", expand=True, padx=10, pady=6)

    footer = tk.Label(root, bg=BG, fg=DIM, font=("sans", 7), anchor="w")
    footer.pack(fill="x", padx=10, pady=(0, 6))

    state = {"on_top": True, "job": None}

    def toggle_on_top(_event=None):
        """Let the user drop the window behind others without closing it."""
        state["on_top"] = not state["on_top"]
        root.attributes("-topmost", state["on_top"])
        render_footer()

    def render_footer():
        mark = "on top" if state["on_top"] else "normal"
        footer.config(text=f"click: toggle {mark} · Esc: close · refreshes every 3s")

    def close(_event=None):
        if state["job"] is not None:
            try:
                root.after_cancel(state["job"])
            except Exception:
                pass
        root.destroy()

    def refresh():
        for child in rows_frame.winfo_children():
            child.destroy()

        try:
            sessions = session_monitor.get_all_sessions(config_data)
        except Exception as e:
            # Same contract as the rest of the app: a read failure degrades
            # to a visible message, it never takes the window down.
            tk.Label(rows_frame, text=f"read error: {e}", bg=BG, fg=DIM,
                     font=("sans", 8), anchor="w", wraplength=300).pack(fill="x")
            state["job"] = root.after(REFRESH_MS, refresh)
            return

        live = sum(1 for s in sessions if s["is_active"])
        total = sum(s["cost"] for s in sessions if s["cost"] is not None)
        header.config(text=f"● {live} live   ○ {len(sessions) - live} idle   {_fmt_cost(total)}")

        for s in sessions[:max_rows]:
            name = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
            pct = s.get("context_percent")

            row = tk.Frame(rows_frame, bg=BG)
            row.pack(fill="x", pady=1)

            tk.Label(row, text="●" if s["is_active"] else "○", bg=BG,
                     fg=LIVE if s["is_active"] else DIM,
                     font=("sans", 8)).pack(side="left")
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

        if not sessions:
            tk.Label(rows_frame, text="No local Claude Code sessions found.", bg=BG,
                     fg=DIM, font=("sans", 8), anchor="w").pack(fill="x")

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
