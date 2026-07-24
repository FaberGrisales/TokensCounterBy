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
