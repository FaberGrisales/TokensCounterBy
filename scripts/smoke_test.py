"""
End-to-end smoke test of the real app on the current OS, for CI.

The unit tests cover logic; this checks that the app actually starts and its
platform-specific pieces work on a real Windows / macOS / Linux machine:
system stats (psutil + GPU), the menu, the floating tkinter window and the
status line script. Runs against an empty Claude config dir, so it also
exercises the "nothing to show yet" paths. Exits non-zero on any failure.

    python scripts/smoke_test.py            # everything
    python scripts/smoke_test.py --no-window
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def _diagnose_cpu():
    import time
    try:
        import psutil
    except ImportError:
        print("  psutil not importable")
        return
    from tokens_counter import system_stats
    for delay in (0.0, 0.2, 1.0):
        time.sleep(delay)
        t = psutil.cpu_times()
        print(f"  cpu_times after {delay}s: {t} sum={sum(t)}")
    try:
        system_stats._last_cpu = None
        print("  _cpu_percent():", system_stats._cpu_percent(psutil))
    except Exception as e:
        print("  _cpu_percent() raised:", repr(e))


def _check_opencode(tmp):
    """A real SQLite database in OpenCode's schema, at OpenCode's path."""
    import sqlite3
    import time
    from tokens_counter.opencode_sessions import get_opencode_sessions, opencode_db_path
    path = opencode_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table session (id text, parent_id text, directory text, time_updated integer)")
    con.execute("create table message (id text, session_id text, data text)")
    now_ms = int(time.time() * 1000)
    con.execute("insert into session values ('ses_1', null, ?, ?)", (os.path.join(tmp, "proj"), now_ms))
    con.execute("insert into message values ('m1', 'ses_1', ?)", (json.dumps({
        "role": "assistant", "providerID": "opencode", "modelID": "big-pickle", "cost": 0,
        "time": {"created": now_ms}, "tokens": {"input": 120, "output": 30, "reasoning": 0,
                                                "cache": {"read": 0, "write": 0}}}),))
    con.commit()
    con.close()
    sessions = get_opencode_sessions()
    check("opencode: sessions and tokens read from its database",
          len(sessions) == 1 and sessions[0]["input_tokens"] == 120
          and sessions[0]["models"] == ["opencode/big-pickle"], repr(sessions[:1]))


def main():
    tmp = tempfile.mkdtemp()
    os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(tmp, "claude")
    os.environ["TOKENS_COUNTER_CACHE"] = os.path.join(tmp, "cache.json")
    os.environ["TOKENS_COUNTER_SETTINGS"] = os.path.join(tmp, "settings.json")
    os.environ["XDG_DATA_HOME"] = os.path.join(tmp, "xdg-data")
    print(f"platform={sys.platform} python={sys.version.split()[0]}", flush=True)

    from tokens_counter import system_stats, gpu_stats, claude_config
    from tokens_counter.config import load_config
    from tokens_counter import session_monitor

    stats = system_stats.get_system_stats()
    parts = dict((label, text) for label, text, _ in system_stats.format_stats(stats))
    check("system stats: CPU/RAM read via psutil",
          "CPU" in parts and "RAM" in parts, json.dumps(parts))
    if "CPU" not in parts:
        _diagnose_cpu()
    import time
    time.sleep(1)
    second = dict((label, text) for label, text, _ in
                  system_stats.format_stats(system_stats.get_system_stats()))
    check("system stats: disk activity on the second reading", "Disk" in second,
          json.dumps(second))
    gpu = gpu_stats.get_gpu_percent()
    # CI machines may have no GPU the OS reports on; the requirement is that
    # reading it never fails and never invents a number.
    check("gpu: read or honestly unavailable",
          gpu is None or 0.0 <= gpu <= 100.0, f"gpu={gpu}")

    config = load_config()
    check("sessions: empty config dir reads as no sessions",
          session_monitor.get_all_sessions(config) == [])
    _check_opencode(tmp)
    check("desktop dir resolves", bool(claude_config.claude_desktop_dir()),
          claude_config.claude_desktop_dir())

    env = {**os.environ, "PYTHONIOENCODING": ""}
    menu = subprocess.run([sys.executable, os.path.join(ROOT, "start.py")],
                          input="3\n\n8\n", capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)
    check("menu starts, shows Option 3 and exits",
          menu.returncode == 0 and "Goodbye" in menu.stdout
          and "MCP Servers" in menu.stdout,
          f"rc={menu.returncode} stderr={menu.stderr[-400:]!r}")

    status = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tokens_counter", "statusline.py")],
        input=b'{"model":{"display_name":"Opus"},"rate_limits_available":true,'
              b'"rate_limits":{"five_hour":{"used_percentage":40}}}',
        capture_output=True, timeout=60, env=env)
    try:
        printed = status.stdout.decode("utf-8")
    except UnicodeDecodeError:
        printed = None
    # Claude Code reads the status line as UTF-8; anything else shows as "�".
    check("status line script prints the captured % as UTF-8",
          status.returncode == 0 and printed is not None and "Opus · 5h 40%" in printed,
          repr(status.stdout))

    if "--no-window" not in sys.argv:
        from tokens_counter import floating
        check("tkinter available", floating.is_available())
        if floating.is_available():
            import tkinter as tk
            real_tk = tk.Tk

            def auto_close(*a, **k):
                root = real_tk(*a, **k)
                root.after(6000, root.destroy)
                return root

            tk.Tk = auto_close
            try:
                ok, error = floating.run_floating_monitor(config)
            finally:
                tk.Tk = real_tk
            check("floating window opens, refreshes and closes", ok, error or "")

    print(f"\n{len(failures)} failure(s)" if failures else "\nall smoke checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
