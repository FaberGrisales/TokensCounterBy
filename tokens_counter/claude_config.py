import json
import os

from tokens_counter.session_monitor import get_claude_config_dir

# Read-only, best-effort readers for Claude Code's own local configuration
# (MCP servers, hooks) — the same data the real `/mcp` and `/hooks` commands
# show. These are documented file locations (code.claude.com/docs/en/mcp,
# code.claude.com/docs/en/hooks, code.claude.com/docs/en/settings) but this
# only covers project + user scope, not organization-managed policy files,
# so a missing/unreadable file just contributes nothing rather than raising.


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_mcp_servers(project_dir=None):
    """
    Lists MCP servers configured for this project (`.mcp.json`) and this
    user (`~/.claude.json`, including its per-project `mcpServers` entries).
    """
    project_dir = project_dir or os.getcwd()
    servers = []

    project_mcp = _load_json(os.path.join(project_dir, ".mcp.json"))
    if isinstance(project_mcp, dict):
        for name, cfg in (project_mcp.get("mcpServers") or {}).items():
            servers.append({"name": name, "scope": "project (.mcp.json)", "config": cfg if isinstance(cfg, dict) else {}})

    user_config = _load_json(os.path.expanduser("~/.claude.json"))
    if isinstance(user_config, dict):
        for name, cfg in (user_config.get("mcpServers") or {}).items():
            servers.append({"name": name, "scope": "user (~/.claude.json)", "config": cfg if isinstance(cfg, dict) else {}})

        project_entry = (user_config.get("projects") or {}).get(project_dir)
        if isinstance(project_entry, dict):
            for name, cfg in (project_entry.get("mcpServers") or {}).items():
                servers.append({"name": name, "scope": "user (~/.claude.json, this project)", "config": cfg if isinstance(cfg, dict) else {}})

    return servers


def _describe_hooks(hooks_config):
    """Flatten a {"PreToolUse": [{"matcher": ..., "hooks": [...]}], ...} dict into display rows."""
    rows = []
    if not isinstance(hooks_config, dict):
        return rows
    for event, entries in hooks_config.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            matcher = entry.get("matcher", "*") if isinstance(entry, dict) else "*"
            commands = entry.get("hooks", []) if isinstance(entry, dict) else []
            rows.append({
                "event": event,
                "matcher": matcher or "*",
                "command_count": len(commands) if isinstance(commands, list) else 0
            })
    return rows


def get_hooks_config(project_dir=None):
    """
    Lists hooks configured for this user (`~/.claude/settings.json`) and this
    project (`.claude/settings.json`, `.claude/settings.local.json`).
    """
    project_dir = project_dir or os.getcwd()
    sources = [
        ("user", get_claude_config_dir() / "settings.json"),
        ("project", os.path.join(project_dir, ".claude", "settings.json")),
        ("project local", os.path.join(project_dir, ".claude", "settings.local.json")),
    ]

    hooks = []
    for scope, path in sources:
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        for row in _describe_hooks(data.get("hooks")):
            hooks.append({"scope": scope, **row})

    return hooks


def get_subscription_status():
    """
    Reads locally-cached Claude account/plan metadata: ~/.claude.json's
    `oauthAccount` block (org name/type, seat tier, extra-usage flag, trial
    dates) and ~/.claude/.credentials.json's `claudeAiOauth` block (rate-limit
    tier, subscription type). Deliberately never reads the access/refresh
    token fields in either file - only the surrounding account metadata.

    Returns None if there's no local Claude subscription session (e.g. this
    machine only uses an ANTHROPIC_API_KEY, which has no oauthAccount at all).

    This cannot report live usage-limit percentages (the 5h/weekly windows
    shown by `/usage` on subscription plans): those require a live call to
    Anthropic's usage endpoint that only Claude Code itself makes, and aren't
    cached to disk anywhere this app can read.
    """
    user_config = _load_json(os.path.expanduser("~/.claude.json"))
    oauth_account = user_config.get("oauthAccount") if isinstance(user_config, dict) else None
    if not isinstance(oauth_account, dict):
        return None

    credentials = _load_json(get_claude_config_dir() / ".credentials.json")
    oauth_creds = credentials.get("claudeAiOauth") if isinstance(credentials, dict) else None
    rate_limit_tier = None
    subscription_type = None
    if isinstance(oauth_creds, dict):
        rate_limit_tier = oauth_creds.get("rateLimitTier")
        subscription_type = oauth_creds.get("subscriptionType")

    return {
        "email": oauth_account.get("emailAddress"),
        "display_name": oauth_account.get("displayName"),
        "organization_name": oauth_account.get("organizationName"),
        "organization_type": oauth_account.get("organizationType"),
        "seat_tier": oauth_account.get("seatTier"),
        "subscription_type": subscription_type,
        "billing_type": oauth_account.get("billingType"),
        "rate_limit_tier": rate_limit_tier or oauth_account.get("organizationRateLimitTier"),
        "has_extra_usage_enabled": bool(oauth_account.get("hasExtraUsageEnabled")),
        "trial_ends_at": oauth_account.get("claudeCodeTrialEndsAt"),
        "subscription_created_at": oauth_account.get("subscriptionCreatedAt"),
    }


def get_plan_rate_limits(cache_file=None):
    """
    The REAL 5h/7d plan-quota percentages, as reported by Claude Code itself.

    These cannot be computed locally and are not cached by Claude Code
    anywhere readable - they come from a live account check only Claude Code
    makes. Since v2.1.80 it passes them to a configured status line script,
    so `statusline.py` captures them into a small cache file and this reads
    it. The app still makes no network call of its own.

    Returns None when the cache doesn't exist (status line not installed, or
    never rendered yet). Otherwise a dict with `five_hour`/`seven_day` - each
    `{"used_percentage", "resets_at"}` or None - plus:

    - `available`: False when plan limits don't apply at all (API key,
      Bedrock, Vertex, or a profile missing the scope), in which case Claude
      Code itself reports no limits and there is genuinely nothing to show.
    - `captured_at` / `age_seconds`: the cache only refreshes while a Claude
      Code session is rendering its status line, so a reading can be stale.
      Callers must surface the age rather than presenting an old percentage
      as current - a stale quota number is exactly the kind of believable
      wrong number this app avoids everywhere else.
    """
    from datetime import datetime, timezone

    if cache_file is None:
        from tokens_counter.statusline import CACHE_FILE
        cache_file = CACHE_FILE

    from tokens_counter.statusline import CACHE_SOURCE

    data = _load_json(cache_file)
    if not isinstance(data, dict):
        return None

    # Only honour a cache actually written by statusline.py. Anything else at
    # this path - a test fixture, a scratch script - is ignored rather than
    # rendered as a real plan percentage.
    if data.get("source") != CACHE_SOURCE:
        return None

    rate_limits = data.get("rate_limits")
    rate_limits = rate_limits if isinstance(rate_limits, dict) else {}

    def parse_captured(value):
        if not isinstance(value, str):
            return None
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            return None

    def window(key):
        entry = rate_limits.get(key)
        if not isinstance(entry, dict):
            return None
        percent = entry.get("used_percentage")
        if not isinstance(percent, (int, float)) or isinstance(percent, bool):
            return None

        # Per-window age, from the window's OWN capture time. A window carried
        # forward because a new session reported nothing keeps its original
        # timestamp, while the file's top-level captured_at is refreshed on
        # every render - reading the top-level one would make a preserved
        # value look freshly measured, which is the impression this whole
        # feature exists not to give.
        own_captured = parse_captured(entry.get("captured_at"))
        own_age = (max(0.0, (datetime.now(timezone.utc) - own_captured).total_seconds())
                   if own_captured else None)
        return {
            "used_percentage": float(percent),
            "resets_at": entry.get("resets_at"),
            "captured_at": own_captured,
            "age_seconds": own_age,
            "source": "claude_code",
        }

    captured_at = None
    age_seconds = None
    raw_captured = data.get("captured_at")
    if isinstance(raw_captured, str):
        try:
            text = raw_captured[:-1] + "+00:00" if raw_captured.endswith("Z") else raw_captured
            captured_at = datetime.fromisoformat(text)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - captured_at).total_seconds())
        except ValueError:
            captured_at = None

    return {
        "available": data.get("rate_limits_available"),
        "captured_at": captured_at,
        "age_seconds": age_seconds,
        "five_hour": window("five_hour"),
        "seven_day": window("seven_day"),
    }


# Seconds between status line re-runs, on top of Claude Code's own
# event-driven updates ("Re-run the status line command every N seconds in
# addition to event-driven updates" - its settings schema, where the field is
# in seconds with a minimum of 1).
#
# This is what keeps the captured plan percentage fresh while you work, so an
# actively-used session doesn't drift into showing a stale reading. It costs
# nothing beyond spawning a local stdlib-only script: no network call, no
# tokens. And it is inherently activity-gated - Claude Code only runs the
# command while a session is open, so an idle machine polls nothing at all.
STATUSLINE_REFRESH_SECONDS = 30


def _stable_python():
    """
    An interpreter that will still exist later, for the installed command.

    `sys.executable` is whatever is running right now - often a project venv.
    Baking that into Claude Code's settings means deleting or rebuilding the
    venv silently breaks the status line. statusline.py imports nothing
    outside the standard library, so any python3 works; a system one on PATH
    outlives the venv. Falls back to sys.executable when there's no better
    candidate (notably Windows, where `python3` often isn't on PATH).
    """
    import shutil
    import sys

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        for name in ("python3", "python"):
            found = shutil.which(name)
            # WindowsApps\python*.exe are Microsoft Store stubs: they open the
            # Store instead of running Python, so the status line would stay
            # blank with no error anywhere.
            if (found and not found.startswith(sys.prefix)
                    and "windowsapps" not in found.lower()):
                return found
    return sys.executable


def statusline_status_report():
    """
    Diagnose the installed status line, for Option 7 and its repair flow.

    Exists because the failure this catches is invisible: Claude Code runs
    `statusLine.command` through a shell and shows nothing at all when it
    fails, so a command broken by an unquoted space in the path, a deleted
    venv, or a moved repo just leaves the status line blank forever. Every
    one of those is a normal thing to happen when moving the app between
    machines.

    Returns a dict with `installed`, `ours`, `command` and `problems` - a
    list of human-readable strings, empty when the installed command is
    sound.
    """
    import shlex
    import sys

    settings = _load_json(get_claude_config_dir() / "settings.json")
    status_line = settings.get("statusLine") if isinstance(settings, dict) else None
    command = status_line.get("command") if isinstance(status_line, dict) else None
    if not isinstance(command, str) or not command.strip():
        return {"installed": False, "ours": False, "command": None,
                "refresh_interval": None, "problems": []}

    ours = "statusline.py" in command and "tokens_counter" in command
    report = {
        "installed": True,
        "ours": ours,
        "command": command,
        "refresh_interval": status_line.get("refreshInterval"),
        "problems": [],
    }
    if not ours:
        return report

    try:
        parts = shlex.split(command)
    except ValueError as e:
        report["problems"].append(f"The command can't be parsed by a shell ({e}).")
        return report

    if len(parts) != 2:
        report["problems"].append(
            "The command splits into "
            f"{len(parts)} shell arguments instead of 2 - an unquoted space in the path. "
            "Claude Code runs it through a shell, so it fails silently."
        )

    script = next((p for p in parts if p.endswith("statusline.py")), None)
    if script is None:
        report["problems"].append("No statusline.py argument found in the command.")
    elif not os.path.exists(script):
        report["problems"].append(f"The script it points at no longer exists: {script}")
    elif os.path.abspath(script) != os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")):
        report["problems"].append(
            f"It points at a different copy of the app: {script}"
        )

    interpreter = parts[0] if parts else None
    if interpreter and os.path.isabs(interpreter) and not os.path.exists(interpreter):
        report["problems"].append(
            f"The Python it points at no longer exists: {interpreter} "
            "(a deleted or rebuilt virtualenv does this)."
        )

    return report


def statusline_command(python_executable=None):
    """
    The exact `statusLine.command` string that installs statusline.py.

    Both halves are shell-quoted. Claude Code runs this command through a
    shell, so an unquoted path containing a space - "/home/me/Personal
    Projects/..." - is split into separate arguments and the script silently
    never runs: the status line just stays empty, with no error surfaced
    anywhere. That failure mode cost a real debugging session, so quoting
    here is not optional tidiness.
    """
    import shlex
    from tokens_counter.statusline import __file__ as statusline_path
    executable = python_executable or _stable_python()
    return f"{shlex.quote(executable)} {shlex.quote(os.path.abspath(statusline_path))}"


def get_statusline_status():
    """
    Whether this app's status line capture is installed in Claude Code.

    Returns (installed, current_command). `installed` is True only when the
    configured command actually points at this repo's statusline.py - a
    different status line script is reported as not-installed WITH its
    command, so the caller can warn instead of silently replacing something
    the user wrote themselves.
    """
    settings = _load_json(get_claude_config_dir() / "settings.json")
    status_line = settings.get("statusLine") if isinstance(settings, dict) else None
    if not isinstance(status_line, dict):
        return False, None
    command = status_line.get("command")
    if not isinstance(command, str):
        return False, None
    return "statusline.py" in command and "tokens_counter" in command, command


def install_statusline(settings_path=None):
    """
    Add this app's status line capture to Claude Code's user settings.

    **This is the only function in this module that writes**, and the only
    place the app touches Claude Code's own configuration - everywhere else
    here is strictly read-only. It therefore:

    - backs the file up first (`settings.json.bak-tokenscounter`), because
      settings.json holds the user's real Claude Code configuration and a
      botched write would affect every session they run, not just this app;
    - preserves every other key, writing only `statusLine`;
    - refuses to run on an unreadable-but-present file rather than
      overwriting whatever is there with a fresh dict.

    main.py must keep asking before calling this, and must keep warning when
    a different status line is already configured - replacing one the user
    wrote themselves is not a routine change.

    Returns (success, message).
    """
    import json as _json
    import shutil as _shutil

    path = settings_path or (get_claude_config_dir() / "settings.json")
    path = os.fspath(path)

    settings = {}
    if os.path.exists(path):
        loaded = _load_json(path)
        if loaded is None:
            return False, (
                f"{path} exists but couldn't be parsed as JSON. Fix or move it first - "
                "refusing to overwrite a settings file that might still be valid to Claude Code."
            )
        if not isinstance(loaded, dict):
            return False, f"{path} doesn't contain a JSON object; refusing to replace it."
        settings = loaded

        backup = path + ".bak-tokenscounter"
        try:
            _shutil.copy2(path, backup)
        except OSError as e:
            return False, f"Could not back up {path}: {e}"

    settings["statusLine"] = {
        "type": "command",
        "command": statusline_command(),
        "refreshInterval": STATUSLINE_REFRESH_SECONDS,
    }

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(settings, f, indent=2)
            f.write("\n")
    except OSError as e:
        return False, f"Could not write {path}: {e}"

    return True, f"Status line installed in {path} (previous file saved as settings.json.bak-tokenscounter)."


# Subdirectories of the Claude Desktop profile that a conversation writes to.
# Deliberately NOT the whole profile: Cache/, GPUCache/, Code Cache/ and the
# bundled claude-code/ binary change for reasons unrelated to anyone chatting
# (GPU shader compiles, updates), and would make an idle, merely-open app look
# active.
DESKTOP_ACTIVITY_SUBDIRS = ("IndexedDB", "Local Storage", "Session Storage", "WebStorage")


def _windows_desktop_dirs(roaming, local):
    """
    Desktop profile candidates on Windows. The Microsoft Store (MSIX) build
    doesn't use %APPDATA%\\Claude: Windows virtualizes it under
    %LOCALAPPDATA%\\Packages\\Claude_<publisher-hash>\\LocalCache\\Roaming\\Claude.
    """
    import glob
    return [os.path.join(roaming, "Claude")] + glob.glob(
        os.path.join(local, "Packages", "Claude_*", "LocalCache", "Roaming", "Claude"))


def claude_desktop_dir():
    """Claude Desktop's profile directory for this platform (it may not exist)."""
    import sys
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Claude")
    if sys.platform != "win32":
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "Claude")
    roaming = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    candidates = _windows_desktop_dirs(roaming, local)
    existing = [c for c in candidates if os.path.isdir(c)]
    # Both installers can leave a profile behind; the most recently touched
    # one is the one actually in use.
    return max(existing, key=os.path.getmtime) if existing else candidates[0]


def get_desktop_activity(desktop_dir=None, now=None, active_seconds=None):
    """
    Whether Claude Desktop has been used recently - ACTIVITY ONLY, no usage.

    Claude Desktop keeps no per-session token or cost data anywhere on disk
    (investigated and ruled out: its conversations live server-side and its
    local store carries no usage fields). So the only honest thing to report
    about it is *that* it is being used and when, taken from the newest mtime
    under the storage directories a conversation writes to. Anything more -
    tokens, cost, a per-chat breakdown - would be invented.

    Returns None when Desktop isn't installed (no profile directory), else a
    dict with `last_activity_at` (datetime or None), `age_seconds` and
    `is_active`. Read-only: it stats files, it never opens them.
    """
    import time
    from datetime import datetime, timezone
    from tokens_counter.session_monitor import ACTIVE_THRESHOLD_SECONDS

    root = desktop_dir or claude_desktop_dir()
    if not os.path.isdir(root):
        return None

    now = time.time() if now is None else now
    threshold = ACTIVE_THRESHOLD_SECONDS if active_seconds is None else active_seconds

    newest = None
    for sub in DESKTOP_ACTIVITY_SUBDIRS:
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # *.indexeddb.blob holds attachments in hundreds of near-empty
            # dirs; every blob write also appends to the sibling leveldb log,
            # so skipping it loses nothing and cut a scan on a slow drive from
            # ~4s to ~0.3s.
            dirnames[:] = [d for d in dirnames if not d.endswith(".blob")]
            for name in filenames:
                try:
                    mtime = os.stat(os.path.join(dirpath, name)).st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime

    if newest is None:
        return {"last_activity_at": None, "age_seconds": None, "is_active": False}

    age = max(0.0, now - newest)
    return {
        "last_activity_at": datetime.fromtimestamp(newest, timezone.utc),
        "age_seconds": age,
        "is_active": age <= threshold,
    }


# Claude Desktop samples the account's real plan usage into this file while
# it's open: {"version": 2, "samples": [{"t": <ms>, "org": ..., "u": {"fh": 5h%,
# "sd": 7d%}}]}, one sample every ~15 minutes, integer percentages, no reset
# times. It's the same account-wide quota Claude Code's status line reports,
# so it covers Desktop chats and Code sessions alike.
DESKTOP_PLAN_HISTORY_FILE = "plan-usage-history.json"
DESKTOP_SAMPLE_SECONDS = 900
FIVE_HOUR_SECONDS = 5 * 3600


def _desktop_samples(data):
    """Valid samples of the most recent org, oldest first."""
    raw = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    samples = [s for s in raw if isinstance(s, dict) and number(s.get("t"))
               and isinstance(s.get("u"), dict)
               and number(s["u"].get("fh")) and number(s["u"].get("sd"))]
    samples.sort(key=lambda s: s["t"])
    if not samples:
        return []
    org = samples[-1].get("org")
    return [s for s in samples if s.get("org") == org]


def _estimate_five_hour_reset(samples, now):
    """
    When the current 5h window resets, from where its usage started rising.

    Desktop records no reset time, but a 5h window starts with the first
    request after the previous one ended, and usage only climbs within a
    window. So the window began between the last sample before the climb and
    the first sample of it. Returns the EARLIEST possible reset (epoch
    seconds) - never promising more time than you have - or None when the
    start isn't pinned to within two sample intervals, when there's no active
    window, or when even the latest possible reset has already passed.
    """
    if not samples or samples[-1]["u"]["fh"] <= 0:
        return None
    j = len(samples) - 1
    while j > 0 and 0 < samples[j - 1]["u"]["fh"] <= samples[j]["u"]["fh"]:
        j -= 1
    if j == 0:
        return None
    before, first = samples[j - 1], samples[j]
    if (first["t"] - before["t"]) / 1000 > 2 * DESKTOP_SAMPLE_SECONDS:
        return None
    earliest = before["t"] / 1000 + FIVE_HOUR_SECONDS
    latest = first["t"] / 1000 + FIVE_HOUR_SECONDS
    return earliest if now < latest else None


def get_desktop_plan_usage(desktop_dir=None, now=None):
    """
    The real 5h/7d plan percentages Claude Desktop last recorded, or None.

    Same shape as get_plan_rate_limits(), with `source: "desktop"` on each
    window. Reads only the timestamp/org/percentage fields of each sample.
    The 5h `resets_at` is an estimate (`resets_at_estimated: True`), see
    _estimate_five_hour_reset(); the 7d one is always None because its resets
    fall in overnight sampling gaps too wide to pin down.
    """
    import time
    from datetime import datetime, timezone

    root = desktop_dir or claude_desktop_dir()
    samples = _desktop_samples(_load_json(os.path.join(root, DESKTOP_PLAN_HISTORY_FILE)))
    if not samples:
        return None

    now = time.time() if now is None else now
    latest = samples[-1]
    captured_at = datetime.fromtimestamp(latest["t"] / 1000, timezone.utc)
    age = max(0.0, now - latest["t"] / 1000)

    def window(key, resets_at):
        return {
            "used_percentage": float(latest["u"][key]),
            "resets_at": resets_at,
            "resets_at_estimated": resets_at is not None,
            "captured_at": captured_at,
            "age_seconds": age,
            "source": "desktop",
        }

    return {
        "available": True,
        "captured_at": captured_at,
        "age_seconds": age,
        "five_hour": window("fh", _estimate_five_hour_reset(samples, now)),
        "seven_day": window("sd", None),
    }


def get_desktop_code_session_ids(desktop_dir=None):
    """
    Claude Code session ids started from Claude Desktop's Code tab.

    Desktop runs a regular Claude Code under the hood, so those sessions
    already have normal transcripts (and real tokens/context) under a
    `.claude/projects` dir; Desktop's own metadata only tells us which ones it
    launched. Reads just the `cliSessionId` field - never titles or prompts.
    """
    import glob
    root = desktop_dir or claude_desktop_dir()
    ids = set()
    for path in glob.glob(os.path.join(root, "claude-code-sessions", "*", "*", "*.json")):
        data = _load_json(path)
        session_id = data.get("cliSessionId") if isinstance(data, dict) else None
        if isinstance(session_id, str) and session_id:
            ids.add(session_id)
    return ids


def get_best_plan_limits(now=None):
    """
    The freshest real plan reading from either source, per window.

    Claude Code's status line (get_plan_rate_limits) and Claude Desktop's own
    history (get_desktop_plan_usage) report the same account-wide quota, so
    whichever captured a window more recently wins it. A reset time is only
    borrowed from the other source when that one is exact (not estimated) and
    still in the future - a future reset means the window it belongs to is
    still the current one. Returns None when neither source has anything.
    """
    import time
    now = time.time() if now is None else now
    code = get_plan_rate_limits()
    desktop = get_desktop_plan_usage(now=now)
    if not code or not desktop:
        return code or desktop

    def reset_epoch(entry):
        from tokens_counter.statusline import _reset_epoch
        return _reset_epoch((entry or {}).get("resets_at"))

    merged = {}
    for key in ("five_hour", "seven_day"):
        a, b = code.get(key), desktop.get(key)
        if not a or not b:
            merged[key] = a or b
            continue
        newer, other = (a, b) if (a.get("captured_at") and a["captured_at"] >= b["captured_at"]) else (b, a)
        chosen = dict(newer)
        other_reset = reset_epoch(other)
        if ((chosen.get("resets_at") is None or chosen.get("resets_at_estimated"))
                and not other.get("resets_at_estimated")
                and other_reset is not None and other_reset > now):
            chosen["resets_at"] = other.get("resets_at")
            chosen["resets_at_estimated"] = False
        merged[key] = chosen

    ages = [w["age_seconds"] for w in merged.values() if w and w.get("age_seconds") is not None]
    return {
        "available": True if any(merged.values()) else code.get("available"),
        "captured_at": max(d["captured_at"] for d in (code, desktop) if d.get("captured_at")),
        "age_seconds": min(ages) if ages else None,
        **merged,
    }
