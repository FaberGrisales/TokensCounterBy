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
            if found and not found.startswith(sys.prefix):
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
        return {"installed": False, "ours": False, "command": None, "problems": []}

    ours = "statusline.py" in command and "tokens_counter" in command
    report = {"installed": True, "ours": ours, "command": command, "problems": []}
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

    settings["statusLine"] = {"type": "command", "command": statusline_command()}

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(settings, f, indent=2)
            f.write("\n")
    except OSError as e:
        return False, f"Could not write {path}: {e}"

    return True, f"Status line installed in {path} (previous file saved as settings.json.bak-tokenscounter)."
