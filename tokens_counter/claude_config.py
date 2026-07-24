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
