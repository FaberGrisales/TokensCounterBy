import os
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

BANNER = """
 [cyan]╔═══════════════════════════════════════════════════════════════════╗[/]
 [cyan]║[/][magenta]           ████████╗ ██████╗ ██╗  ██╗███████╗███╗   ██╗            [/][cyan]║[/]
 [cyan]║[/][magenta]           ╚══██╔══╝██╔═══██╗██║ ██╔╝██╔════╝████╗  ██║            [/][cyan]║[/]
 [cyan]║[/][magenta]              ██║   ██║   ██║█████╔╝ █████╗  ██╔██╗ ██║            [/][cyan]║[/]
 [cyan]║[/][magenta]              ██║   ██║   ██║██╔═██╗ ██╔══╝  ██║╚██╗██║            [/][cyan]║[/]
 [cyan]║[/][magenta]              ██║   ╚██████╔╝██║  ██╗███████╗██║ ╚████║            [/][cyan]║[/]
 [cyan]║[/][magenta]              ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝            [/][cyan]║[/]
 [cyan]║[/][green]    ██████╗ ██████╗ ██╗   ██╗███╗   ██╗████████╗███████╗██████╗    [/][cyan]║[/]
 [cyan]║[/][green]   ██╔════╝██╔═══██╗██║   ██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗   [/][cyan]║[/]
 [cyan]║[/][green]   ██║     ██║   ██║██║   ██║██╔██╗ ██║   ██║   █████╗  ██████╔╝   [/][cyan]║[/]
 [cyan]║[/][green]   ██║     ██║   ██║██║   ██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗   [/][cyan]║[/]
 [cyan]║[/][green]   ╚██████╗╚██████╔╝╚██████╔╝██║ ╚████║   ██║   ███████╗██║  ██║   [/][cyan]║[/]
 [cyan]║[/][green]    ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   [/][cyan]║[/]
 [cyan]╚═══════════════════════════════════════════════════════════════════╝[/]
          [yellow]Token Usage & Cost Visualizer[/]
"""

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def render_header():
    """Renders the app's title banner."""
    clear_screen()
    console.print(BANNER, justify="center")
    console.print()

def render_menu(options):
    """Renders the main menu option list."""
    table = Table(show_header=False, box=box.ROUNDED, border_style="cyan", padding=(0, 2))
    
    table.add_column("Key", style="bold yellow", justify="right")
    table.add_column("Description", style="white")
    
    for key, desc in options.items():
        table.add_row(f"[{key}]", desc)
        
    console.print(Panel(
        table,
        title="[bold magenta]MAIN MENU[/]",
        title_align="left",
        border_style="cyan",
        box=box.DOUBLE,
        width=55
    ), justify="center")

def _context_bar(percent, length=10):
    """Compact colored bar for context window usage, e.g. '███████░░░ 72%' (mirrors what /context shows)."""
    if percent is None:
        return "[dim]N/A[/]"
    ratio = min(1.0, max(0.0, percent / 100))
    filled = int(round(ratio * length))
    bar = "█" * filled + "░" * (length - filled)
    color = "green" if percent < 50 else "yellow" if percent < 80 else "red"
    return f"[{color}]{bar} {percent:.0f}%[/]"

def _neutral_bar(percent, length=10):
    """
    Compact bar with no red/green health semantics, e.g. '████░░░░░░ 40.00%'.
    Used for values that aren't a real quota (e.g. how much of a rolling
    usage window's timespan is currently occupied by continuous activity -
    see session_monitor.get_rolling_window_usage). Two decimal places so it
    visibly ticks on every refresh even without new activity (whole-number %
    only moves once every few minutes on the 5h window, which reads as
    "frozen" at a 5s refresh interval).
    """
    if percent is None:
        return "[dim]N/A[/]"
    ratio = min(1.0, max(0.0, percent / 100))
    filled = int(round(ratio * length))
    bar = "█" * filled + "░" * (length - filled)
    return f"[cyan]{bar} {percent:.2f}%[/]"

def _format_duration(seconds):
    """
    Formats a duration in seconds as e.g. '1d 4h', '3h 12m 05s', or '45s'.
    Always includes seconds below the 1-day mark so it visibly ticks on
    every refresh - whole-minute-only formatting can look frozen for up to a
    minute at a time at a few-second refresh interval.
    """
    if seconds is None:
        return "N/A"
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"

def _format_local_time(dt):
    """Formats a UTC datetime as a local-time string, e.g. '2026-07-24 19:57 (local)'."""
    if dt is None:
        return "N/A"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M (local)")

def render_session_monitor_view(sessions):
    """
    Builds (does not print) a Rich renderable summarizing local Claude Code
    sessions and their real token usage/cost. Meant to be passed to
    rich.live.Live.update() for a self-refreshing view.
    """
    active = [s for s in sessions if s["is_active"]]
    idle = [s for s in sessions if not s["is_active"]]

    total_cost = sum(s["cost"] for s in sessions if s["cost"] is not None)
    unpriced_count = sum(1 for s in sessions if s["cost"] is None)
    total_input = sum(s["input_tokens"] for s in sessions)
    total_output = sum(s["output_tokens"] for s in sessions)

    header_lines = [
        f"[bold green]● Active sessions:[/] {len(active)}   [dim]○ Idle (5+ min):[/] {len(idle)}",
        f"[cyan]Total Input:[/] {total_input:,}  |  [magenta]Total Output:[/] {total_output:,}",
        f"[bold yellow]Estimated Total Spend:[/] ${total_cost:.4f}"
    ]
    if unpriced_count:
        header_lines.append(f"[dim](+{unpriced_count} session(s) using a model with no price in models_config.json)[/]")

    header = Panel(
        "\n".join(header_lines),
        title="[bold cyan]Claude Code — Live Session Monitor[/]",
        border_style="cyan",
        box=box.DOUBLE,
        width=92
    )

    table = Table(box=box.ROUNDED, border_style="yellow", title="[bold yellow]Sessions (most recently active first)[/]")
    table.add_column("Status", justify="center")
    table.add_column("Project / Session", style="bold green")
    table.add_column("Model(s)", style="cyan")
    table.add_column("Reqs", justify="right")
    table.add_column("Session Tokens (in/out)", justify="right")
    table.add_column("Session Cost", justify="right", style="bold yellow")
    table.add_column("Last Prompt (in/out)", justify="right")
    table.add_column("Last Prompt Cost", justify="right")
    table.add_column("Context", justify="center")

    for s in sessions[:15]:
        status = "[bold green]● LIVE[/]" if s["is_active"] else "[dim]○ idle[/]"
        project_label = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
        session_label = f"{project_label}\n[dim]{s['session_id'][:8]}…[/]"

        subagent_note = f" [dim](+{s['subagent_count']} subagent(s))[/]" if s["subagent_count"] else ""
        reqs = f"{s['main_requests']}{subagent_note}"

        cost_str = f"${s['cost']:.4f}" if s["cost"] is not None else "[dim]N/A[/]"

        last_req = s.get("last_request")
        if last_req:
            last_tokens = f"{last_req['input_tokens']:,} / {last_req['output_tokens']:,}"
            last_cost_str = f"${s['last_request_cost']:.4f}" if s.get("last_request_cost") is not None else "[dim]N/A[/]"
        else:
            last_tokens = "-"
            last_cost_str = "-"

        table.add_row(
            status,
            session_label,
            ", ".join(s["models"]) or "-",
            reqs,
            f"{s['input_tokens']:,} / {s['output_tokens']:,}",
            cost_str,
            last_tokens,
            last_cost_str,
            _context_bar(s.get("context_percent"))
        )

    if not sessions:
        table.add_row("-", "No local Claude Code sessions found", "-", "-", "-", "-", "-", "-", "-")

    footer = "[dim]Refreshing every few seconds · Press Ctrl+C to stop and return to the menu[/]"

    return Group(header, table, footer)

def render_session_breakdown_view(session_id, session_summary, subagents, mcp_calls):
    """
    Builds (does not print) a single session's per-subagent breakdown plus
    its per-turn MCP tool-call log, so you can see exactly how much a single
    subagent invocation OR a single prompt/turn that called an MCP tool
    consumed, rather than only the session-wide total. Meant to be passed to
    rich.live.Live.update() for a self-refreshing view. See
    session_monitor.build_subagent_breakdown() / build_mcp_call_log() for how
    each row is built.
    """
    if session_summary is None:
        return Group(f"[yellow]Session {session_id} not found (its transcript may have been removed).[/]")

    project_label = os.path.basename(session_summary["cwd"]) if session_summary.get("cwd") else session_summary["project"]
    header = Panel(
        f"[bold green]{project_label}[/]  [dim]{session_id}[/]\n"
        f"[cyan]Subagents found:[/] {len(subagents)}   [cyan]MCP calls found:[/] {len(mcp_calls)}",
        title="[bold cyan]Session Breakdown[/]",
        border_style="cyan",
        box=box.DOUBLE,
        width=92
    )

    subagent_table = Table(box=box.ROUNDED, border_style="yellow", title="[bold yellow]Subagents (most recently active first)[/]")
    subagent_table.add_column("Agent Type", style="bold green")
    subagent_table.add_column("Task", style="white")
    subagent_table.add_column("Model(s)", style="cyan")
    subagent_table.add_column("Reqs", justify="right")
    subagent_table.add_column("Tokens (In/Out)", justify="right")
    subagent_table.add_column("Cache (Read/Write)", justify="right")
    subagent_table.add_column("Cost", justify="right", style="bold yellow")

    for a in subagents[:15]:
        cost_str = f"${a['cost']:.4f}" if a["cost"] is not None else "[dim]N/A[/]"
        subagent_table.add_row(
            a["agent_type"],
            a.get("description") or "[dim]-[/]",
            ", ".join(a["models"]) or "-",
            f"{a['requests']:,}",
            f"{a['input_tokens']:,} / {a['output_tokens']:,}",
            f"{a['cache_read_tokens']:,} / {a['cache_write_tokens']:,}",
            cost_str
        )
    if not subagents:
        subagent_table.add_row("-", "No subagents found for this session", "-", "-", "-", "-", "-")

    mcp_table = Table(box=box.ROUNDED, border_style="green", title="[bold green]MCP Calls (one row per turn, most recent first)[/]")
    mcp_table.add_column("Time", style="dim")
    mcp_table.add_column("Source", style="bold green")
    mcp_table.add_column("Tool(s) Called", style="white")
    mcp_table.add_column("Tokens (In/Out)", justify="right")
    mcp_table.add_column("Turn Cost", justify="right", style="bold yellow")

    for c in mcp_calls[:15]:
        cost_str = f"${c['cost']:.4f}" if c["cost"] is not None else "[dim]N/A[/]"
        tool_labels = []
        for name in c["tools"]:
            rest = name[len("mcp__"):] if name.startswith("mcp__") else name
            server, _, tool = rest.rpartition("__")
            tool_labels.append(f"{server}/{tool}" if server else rest)
        mcp_table.add_row(
            _format_local_time(c["timestamp"]),
            c["source"],
            ", ".join(tool_labels) or "-",
            f"{c['input_tokens']:,} / {c['output_tokens']:,}",
            cost_str
        )
    if not mcp_calls:
        mcp_table.add_row("-", "No MCP tool calls found for this session", "-", "-", "-")

    footer_lines = ["[dim]Refreshing every few seconds · Press Ctrl+C to stop and return to the menu[/]"]
    if mcp_calls:
        footer_lines.insert(0,
            "[dim]\"Turn Cost\" is the cost of the whole assistant turn that called this tool, not an isolated "
            "per-call cost - Claude bills per turn, and one turn can call more than one tool.[/]"
        )

    return Group(header, subagent_table, mcp_table, *footer_lines)

MAX_TABLE_ROWS = 8

def _build_subscription_status_renderables(status, rolling_usage=None):
    """
    Builds the Subscription Status panels/tables as a list, without printing.
    Shared by the static (one-shot) and live-refreshing views.
    """
    if not status:
        return [Panel(
            "[yellow]No local Claude subscription session found.[/]\n"
            "[dim]This shows up once you've logged in to Claude Code with a claude.ai account\n"
            "(Pro/Max/Team/Enterprise). If this machine only uses an API key, there's nothing to read.[/]",
            title="[bold cyan]Claude Subscription Status[/]",
            border_style="yellow", box=box.ROUNDED, width=90
        )]

    plan_label = status.get("organization_type") or status.get("subscription_type") or "unknown"
    extra_usage = "[green]Enabled[/]" if status.get("has_extra_usage_enabled") else "[dim]Disabled[/]"

    lines = [
        f"[bold yellow]Account:[/] {status.get('display_name') or '-'} ({status.get('email') or '-'})",
        f"[bold yellow]Organization:[/] {status.get('organization_name') or '-'}   "
        f"[bold yellow]Plan:[/] {plan_label}   [bold yellow]Seat:[/] {status.get('seat_tier') or '-'}",
        f"[bold yellow]Rate-limit tier:[/] {status.get('rate_limit_tier') or '-'}   [bold yellow]Extra usage:[/] {extra_usage}"
    ]
    if status.get("trial_ends_at"):
        lines.append(f"[bold yellow]Trial ends:[/] {status['trial_ends_at']}")

    renderables = [Panel(
        "\n".join(lines),
        title="[bold cyan]Claude Subscription Status[/]",
        border_style="cyan", box=box.DOUBLE, width=90
    )]

    if rolling_usage:
        window_table = Table(box=box.ROUNDED, border_style="magenta", title="[bold magenta]Recent Consumption (local estimate)[/]")
        window_table.add_column("Window", style="bold green")
        window_table.add_column("Requests", justify="right")
        window_table.add_column("Tokens (In/Out)", justify="right")
        window_table.add_column("Cache (Read/Write)", justify="right")
        window_table.add_column("Est. Cost", justify="right", style="bold yellow")

        for key, label in (("5h", "Last 5 hours"), ("7d", "Last 7 days")):
            w = rolling_usage.get(key, {})
            cost_str = f"${w['cost']:.4f}" if w.get("cost") is not None else "[dim]N/A[/]"
            window_table.add_row(
                label,
                f"{w.get('requests', 0):,}",
                f"{w.get('input', 0):,} / {w.get('output', 0):,}",
                f"{w.get('cache_read', 0):,} / {w.get('cache_write', 0):,}",
                cost_str
            )
        renderables.append(window_table)

        usage_window_table = Table(box=box.ROUNDED, border_style="blue", title="[bold blue]Time-in-Window % (local, NOT your plan quota)[/]")
        usage_window_table.add_column("Window", style="bold green")
        usage_window_table.add_column("Status", justify="center")
        usage_window_table.add_column("Time-in-Window %", justify="center")
        usage_window_table.add_column("Window Started", justify="right")
        usage_window_table.add_column("Time Elapsed", justify="right")

        for key, label in (("5h", "5h window"), ("7d", "7d window")):
            w = rolling_usage.get(key, {})
            if w.get("window_start_at") is None:
                usage_window_table.add_row(label, "[dim]Empty (no recent activity)[/]", "[dim]N/A[/]", "-", "-")
            else:
                usage_window_table.add_row(
                    label,
                    "[green]Active[/]",
                    _neutral_bar(w.get("percent_used")),
                    _format_local_time(w.get("window_start_at")),
                    _format_duration(w.get("elapsed_seconds"))
                )
        renderables.append(usage_window_table)
        renderables.append(
            "[dim]Time-in-Window % is real local elapsed time, NOT Claude Code's plan-quota %/usage limit "
            "(that's computed server-side and requires a live account check this app doesn't make).[/]"
        )

    return renderables

def render_subscription_status(status, rolling_usage=None):
    """
    Renders Claude subscription/account status read from locally-cached OAuth
    account metadata — never the access/refresh tokens themselves — plus real
    local consumption over rolling 5h/7d windows. See
    claude_config.get_subscription_status() and
    session_monitor.get_rolling_window_usage() for exactly what's read/computed.
    """
    for renderable in _build_subscription_status_renderables(status, rolling_usage):
        console.print(renderable, justify="center")
        console.print()

def _build_usage_summary_renderables(data):
    """
    Builds the Global Usage panels/tables as a list, without printing. Shared
    by the static (one-shot) and live-refreshing views. "Usage by Model" and
    "By Project" are capped to MAX_TABLE_ROWS (sorted by cost, already
    descending) with a "+N more" note, so an account with many models/
    projects doesn't grow the view past a typical terminal's height.
    """
    if not data["session_count"]:
        return ["[yellow]No Claude Code sessions found on this machine.[/]"]

    cost_str = f"${data['total_cost']:.4f}" if data["total_cost"] is not None else "[dim]N/A (no priced model found)[/]"
    header = Panel(
        f"[bold yellow]Sessions found:[/] {data['session_count']}   [bold yellow]Total Requests:[/] {data['total_requests']:,}\n"
        f"[bold green]Total Estimated Cost:[/] {cost_str}",
        title="[bold cyan]Global Claude Usage (like /usage)[/]",
        border_style="cyan",
        box=box.DOUBLE,
        width=70
    )
    renderables = [header]

    # "Usage by model" — mirrors the list format /usage prints for the current session,
    # but aggregated across every local session this app can find.
    model_rows = data["usage_by_model"]
    model_table = Table(box=box.ROUNDED, border_style="yellow", title="[bold yellow]Usage by Model[/]")
    model_table.add_column("Model", style="bold green")
    model_table.add_column("Input", justify="right")
    model_table.add_column("Output", justify="right")
    model_table.add_column("Cache Read", justify="right")
    model_table.add_column("Cache Write", justify="right")
    model_table.add_column("Cost", justify="right", style="bold yellow")

    for m in model_rows[:MAX_TABLE_ROWS]:
        cost_cell = f"${m['cost']:.4f}" if m["cost"] is not None else "[dim]N/A[/]"
        model_table.add_row(
            m["model"],
            f"{m['input']:,}",
            f"{m['output']:,}",
            f"{m['cache_read']:,}",
            f"{m['cache_write']:,}",
            cost_cell
        )
    if not model_rows:
        model_table.add_row("-", "-", "-", "-", "-", "-")
    elif len(model_rows) > MAX_TABLE_ROWS:
        model_table.add_row(f"[dim]+{len(model_rows) - MAX_TABLE_ROWS} more[/]", "", "", "", "", "")
    renderables.append(model_table)

    # By project — /usage doesn't have this (it's scoped to one session), but
    # this app sees every project's sessions, so it's a natural extension.
    project_rows = data["projects"]
    project_table = Table(box=box.ROUNDED, border_style="cyan", title="[bold cyan]By Project[/]")
    project_table.add_column("Project", style="bold green")
    project_table.add_column("Requests", justify="right")
    project_table.add_column("Tokens (In / Out)", justify="right")
    project_table.add_column("Est. Cost", justify="right", style="bold yellow")

    for p in project_rows[:MAX_TABLE_ROWS]:
        cost_cell = f"${p['cost']:.4f}" if p["cost"] is not None else "[dim]N/A[/]"
        project_table.add_row(
            p["project"],
            f"{p['requests']:,}",
            f"{p['input']:,} / {p['output']:,}",
            cost_cell
        )
    if len(project_rows) > MAX_TABLE_ROWS:
        project_table.add_row(f"[dim]+{len(project_rows) - MAX_TABLE_ROWS} more[/]", "", "", "")
    renderables.append(project_table)

    return renderables

def render_usage_summary(data):
    """
    Renders a snapshot modeled on Claude Code's own `/usage` command: total
    cost and a "Usage by model" breakdown, plus a per-project breakdown this
    app can offer since it sees every local session, not just the current
    one. See session_monitor.get_global_usage_summary() for how it's built.
    """
    for renderable in _build_usage_summary_renderables(data):
        console.print(renderable, justify="center")
        console.print()

def render_global_usage_live_view(status, rolling_usage, data):
    """
    Builds (does not print) the combined Subscription Status + Global Usage
    renderables as a single Group, for use with rich.live.Live so the whole
    screen (including Time-in-Window %/Time Elapsed) refreshes in place instead
    of requiring the user to exit and re-run the menu option.

    Keeping this Group's height down matters: a Live renderable taller than
    the terminal either gets silently cropped (the default "ellipsis"
    overflow mode) or, worse, causes Live to reprint the whole thing on every
    refresh instead of redrawing in place (vertical_overflow="visible"),
    which is what "By Project" scrolling forever every few seconds turned
    out to be - see MAX_TABLE_ROWS for the other half of that fix.
    """
    renderables = _build_subscription_status_renderables(status, rolling_usage)
    renderables += _build_usage_summary_renderables(data)
    renderables.append("[dim]Refreshing every few seconds · Press Ctrl+C to stop and return to the menu[/]")
    return Group(*renderables)

def render_cleanup_candidates(candidates):
    """
    Prints a numbered table of sessions inactive long enough to be cleanup
    candidates (see session_monitor.get_cleanup_candidates()), most inactive
    first. main.py uses the printed row numbers to build its interactive
    picker; this function only renders the list, it never deletes anything.
    """
    table = Table(box=box.ROUNDED, border_style="red", title="[bold red]Inactive Sessions (cleanup candidates)[/]")
    table.add_column("#", justify="right", style="bold yellow")
    table.add_column("Project / Session", style="bold green")
    table.add_column("Last Activity", justify="right")
    table.add_column("Tokens (In/Out)", justify="right")
    table.add_column("Cost", justify="right")

    for i, c in enumerate(candidates, start=1):
        project_label = os.path.basename(c["cwd"]) if c.get("cwd") else c["project"]
        session_label = f"{project_label}\n[dim]{c['session_id'][:8]}…[/]"
        cost_str = f"${c['cost']:.4f}" if c["cost"] is not None else "[dim]N/A[/]"
        table.add_row(
            str(i),
            session_label,
            f"{_format_duration(c['age_seconds'])} ago",
            f"{c['input_tokens']:,} / {c['output_tokens']:,}",
            cost_str
        )

    console.print(table, justify="center")
    console.print()

def render_claude_config(mcp_servers, hooks):
    """
    Renders MCP servers and hooks configured for Claude Code, read from its
    own local config files — the same data the real `/mcp` and `/hooks`
    commands show, scoped to this project's directory and this user.
    """
    mcp_table = Table(box=box.ROUNDED, border_style="magenta", title="[bold magenta]MCP Servers Configured[/]")
    mcp_table.add_column("Name", style="bold green")
    mcp_table.add_column("Scope", style="cyan")
    mcp_table.add_column("Type", style="yellow")
    mcp_table.add_column("Command / URL", style="white")

    for s in mcp_servers:
        cfg = s.get("config") or {}
        server_type = cfg.get("type", "stdio")
        target = cfg.get("url") or cfg.get("command") or "-"
        mcp_table.add_row(s["name"], s["scope"], server_type, str(target))

    if not mcp_servers:
        mcp_table.add_row("-", "No MCP servers found in .mcp.json or ~/.claude.json for this project", "-", "-")

    console.print(mcp_table, justify="center")
    console.print()

    hooks_table = Table(box=box.ROUNDED, border_style="cyan", title="[bold cyan]Hooks Configured[/]")
    hooks_table.add_column("Scope", style="bold green")
    hooks_table.add_column("Event", style="yellow")
    hooks_table.add_column("Matcher", style="cyan")
    hooks_table.add_column("Commands", justify="right")

    for h in hooks:
        hooks_table.add_row(h["scope"], h["event"], str(h["matcher"]), str(h["command_count"]))

    if not hooks:
        hooks_table.add_row("-", "No hooks found in settings.json (user/project/local)", "-", "-")

    console.print(hooks_table, justify="center")
    console.print()

    console.print(Panel(
        Text(
            "Reads only this project's .mcp.json / .claude/settings*.json and your user-level "
            "~/.claude.json / ~/.claude/settings.json. Organization-managed policy files aren't read by this app.",
            style="dim", justify="left"
        ),
        border_style="dim", width=95
    ), justify="center")
    console.print()

