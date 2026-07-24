import sys
import os
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

ARCADE_LOGO = """
 [cyan]╔═══════════════════════════════════════════════════════╗[/]
 [cyan]║[/]   [magenta]██████╗ ███████╗████████╗██████╗  ██████╗[/]          [cyan]║[/]
 [cyan]║[/]   [magenta]██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗[/]         [cyan]║[/]
 [cyan]║[/]   [magenta]██████╔╝█████╗     ██║   ██████╔╝██║   ██║[/]         [cyan]║[/]
 [cyan]║[/]   [magenta]██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║[/]         [cyan]║[/]
 [cyan]║[/]   [magenta]██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝[/]         [cyan]║[/]
 [cyan]║[/]   [magenta]╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝[/]          [cyan]║[/]
 [cyan]║[/]             [green]████████╗ ██████╗ ██╗  ██╗███████╗[/]       [cyan]║[/]
 [cyan]║[/]             [green]╚══██╔══╝██╔═══██╗██║ ██╔╝██╔════╝[/]       [cyan]║[/]
 [cyan]║[/]                [green]██║   ██║   ██║█████╔╝ █████╗[/]         [cyan]║[/]
 [cyan]║[/]                [green]██║   ██║   ██║██╔═██╗ ██╔══╝[/]         [cyan]║[/]
 [cyan]║[/]                [green]██║   ╚██████╔╝██║  ██╗███████╗[/]       [cyan]║[/]
 [cyan]║[/]                [green]╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝[/]       [cyan]║[/]
 [cyan]╚═══════════════════════════════════════════════════════╝[/]
       [yellow]--==[ TOKEN COUNTER ]==--[/]
"""

def play_beep():
    """Triggers an old-school terminal bell beep sound."""
    sys.stdout.write("\a")
    sys.stdout.flush()

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def render_header():
    """Renders the arcade logo banner."""
    clear_screen()
    console.print(ARCADE_LOGO, justify="center")
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

def render_live_results(model_key, prompt, response_text, meta, cost):
    """Renders the outcome of a live LLM call."""
    console.print(Panel(
        f"[bold green]Response Text:[/]\n{response_text}",
        title="[bold yellow]🖥️ CONSOLE OUTPUT 🖥️[/]",
        border_style="yellow",
        box=box.ROUNDED,
        width=75
    ), justify="center")
    console.print()
    
    # Breakdown Table
    table = Table(box=box.DOUBLE, border_style="cyan", title="[bold cyan]🪙 ACTUAL TRANSACTION RECEIPTS 🪙[/]")
    table.add_column("Metric", style="bold white")
    table.add_column("Quantity", style="yellow", justify="right")
    table.add_column("Rate (per 1M)", style="magenta", justify="right")
    
    from tokens_counter.config import load_config
    cfg = load_config()[model_key]
    
    table.add_row("Input Tokens", f"{meta['input_tokens']:,}", f"${cfg.get('input_cost_per_1m', 0.0):.2f}")
    table.add_row("Output Tokens", f"{meta['output_tokens']:,}", f"${cfg.get('output_cost_per_1m', 0.0):.2f}")
    
    if meta.get("cached_read_tokens", 0) > 0:
        table.add_row("Cache Read Tokens", f"[green]{meta['cached_read_tokens']:,}[/]", f"${cfg.get('cache_read_cost_per_1m', 0.0):.2f}")
    if meta.get("cached_write_tokens", 0) > 0:
        table.add_row("Cache Write Tokens", f"[blue]{meta['cached_write_tokens']:,}[/]", f"${cfg.get('cache_write_cost_per_1m', 0.0):.2f}")
        
    table.add_row("Final Cost (USD)", f"[bold green]${cost:.6f}[/]", "-")
    
    console.print(table, justify="center")
    console.print()

def render_mcp_live_results(model_key, prompt, res, cost):
    """Renders the outcome of a real Claude call made with Tool-Use/MCP enabled."""
    mcp_source = "[bold cyan]Remote MCP Server[/]" if res.get("used_remote_mcp") else "[bold cyan]Local Demo Tools[/]"

    console.print(Panel(
        f"[bold green]Final Response:[/]\n{res.get('text', '')}",
        title="[bold yellow]🖥️ CONSOLE OUTPUT 🖥️[/]",
        border_style="yellow",
        box=box.ROUNDED,
        width=75
    ), justify="center")
    console.print()

    turns = res.get("turns", [])
    table = Table(box=box.DOUBLE, border_style="magenta", title=f"[bold magenta]🔧 REAL MCP / TOOL-USE BREAKDOWN 🔧[/] (Source: {mcp_source})")
    table.add_column("Turn", style="bold white", justify="center")
    table.add_column("Input", style="cyan", justify="right")
    table.add_column("Output", style="magenta", justify="right")
    table.add_column("Cache Read", style="green", justify="right")
    table.add_column("Cache Write", style="blue", justify="right")
    table.add_column("Tool Calls", style="yellow", justify="right")
    table.add_column("Stop Reason", style="dim white")

    for turn in turns:
        table.add_row(
            str(turn["turn"]),
            f"{turn['input_tokens']:,}",
            f"{turn['output_tokens']:,}",
            f"{turn['cached_read_tokens']:,}",
            f"{turn['cached_write_tokens']:,}",
            str(turn["tool_calls"]),
            turn["stop_reason"] or "-"
        )

    console.print(table, justify="center")
    console.print()

    summary_text = (
        f"[bold yellow]Total Turns:[/] {len(turns)}  |  [bold yellow]Total Tool Calls:[/] {res.get('tool_calls', 0)}\n"
        f"[bold cyan]Total Input Tokens:[/] {res['input_tokens']:,}  |  [bold magenta]Total Output Tokens:[/] {res['output_tokens']:,}\n"
        f"[green]Cache Read:[/] {res.get('cached_read_tokens', 0):,}  |  [blue]Cache Write:[/] {res.get('cached_write_tokens', 0):,}\n"
        f"[bold green]Real Cost (USD):[/] ${cost:.6f}"
    )
    console.print(Panel(summary_text, title="[bold green]🪙 REAL MCP TRANSACTION RECEIPT 🪙[/]", border_style="green", box=box.ROUNDED, width=70), justify="center")
    console.print()

def _context_bar(percent, length=10):
    """Compact colored bar for context window usage, e.g. '███████░░░ 72%' (mirrors what /context shows)."""
    if percent is None:
        return "[dim]N/A[/]"
    ratio = min(1.0, max(0.0, percent / 100))
    filled = int(round(ratio * length))
    bar = "█" * filled + "░" * (length - filled)
    color = "green" if percent < 50 else "yellow" if percent < 80 else "red"
    return f"[{color}]{bar} {percent:.0f}%[/]"

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
        title="[bold cyan]🔎 CLAUDE CODE — LIVE SESSION MONITOR 🔎[/]",
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

def render_subscription_status(status, rolling_usage=None):
    """
    Renders Claude subscription/account status read from locally-cached OAuth
    account metadata — never the access/refresh tokens themselves — plus real
    local consumption over rolling 5h/7d windows. See
    claude_config.get_subscription_status() and
    session_monitor.get_rolling_window_usage() for exactly what's read/computed.
    """
    if not status:
        console.print(Panel(
            "[yellow]No local Claude subscription session found.[/]\n"
            "[dim]This shows up once you've logged in to Claude Code with a claude.ai account\n"
            "(Pro/Max/Team/Enterprise). If this machine only uses an API key, there's nothing to read.[/]",
            title="[bold cyan]👤 CLAUDE SUBSCRIPTION STATUS 👤[/]",
            border_style="yellow", box=box.ROUNDED, width=90
        ), justify="center")
        console.print()
        return

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

    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]👤 CLAUDE SUBSCRIPTION STATUS 👤[/]",
        border_style="cyan", box=box.DOUBLE, width=90
    ), justify="center")
    console.print()

    if rolling_usage:
        window_table = Table(box=box.ROUNDED, border_style="magenta", title="[bold magenta]⏱️ RECENT CONSUMPTION (local estimate) ⏱️[/]")
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

        console.print(window_table, justify="center")
        console.print()

    console.print(Panel(
        "[dim]\"Recent Consumption\" above is real usage summed from your local transcripts over rolling time windows —\n"
        "it is NOT the same as Claude Code's actual quota-used percentage or reset countdown for its 5h/weekly seat\n"
        "allowance. Those are computed server-side against a per-tier budget that isn't publicly documented and isn't\n"
        "cached anywhere on this machine; only the real `/usage` command inside Claude Code can show that % and\n"
        "reset time. This app never reads your access/refresh tokens either way.[/]",
        border_style="dim", width=95
    ), justify="center")
    console.print()

def render_usage_summary(data):
    """
    Renders a snapshot modeled on Claude Code's own `/usage` command: total
    cost and a "Usage by model" breakdown, plus a per-project breakdown this
    app can offer since it sees every local session, not just the current
    one. See session_monitor.get_global_usage_summary() for how it's built.
    """
    if not data["session_count"]:
        console.print("[yellow]No Claude Code sessions found on this machine.[/]")
        return

    cost_str = f"${data['total_cost']:.4f}" if data["total_cost"] is not None else "[dim]N/A (no priced model found)[/]"
    header = Panel(
        f"[bold yellow]Sessions found:[/] {data['session_count']}   [bold yellow]Total Requests:[/] {data['total_requests']:,}\n"
        f"[bold green]Total Estimated Cost:[/] {cost_str}",
        title="[bold cyan]📊 GLOBAL CLAUDE USAGE (like /usage) 📊[/]",
        border_style="cyan",
        box=box.DOUBLE,
        width=70
    )
    console.print(header, justify="center")
    console.print()

    # "Usage by model" — mirrors the list format /usage prints for the current session,
    # but aggregated across every local session this app can find.
    model_table = Table(box=box.ROUNDED, border_style="yellow", title="[bold yellow]Usage by Model[/]")
    model_table.add_column("Model", style="bold green")
    model_table.add_column("Input", justify="right")
    model_table.add_column("Output", justify="right")
    model_table.add_column("Cache Read", justify="right")
    model_table.add_column("Cache Write", justify="right")
    model_table.add_column("Cost", justify="right", style="bold yellow")

    for m in data["usage_by_model"]:
        cost_cell = f"${m['cost']:.4f}" if m["cost"] is not None else "[dim]N/A[/]"
        model_table.add_row(
            m["model"],
            f"{m['input']:,}",
            f"{m['output']:,}",
            f"{m['cache_read']:,}",
            f"{m['cache_write']:,}",
            cost_cell
        )
    if not data["usage_by_model"]:
        model_table.add_row("-", "-", "-", "-", "-", "-")

    console.print(model_table, justify="center")
    console.print()

    # By project — /usage doesn't have this (it's scoped to one session), but
    # this app sees every project's sessions, so it's a natural extension.
    project_table = Table(box=box.ROUNDED, border_style="cyan", title="[bold cyan]By Project[/]")
    project_table.add_column("Project", style="bold green")
    project_table.add_column("Requests", justify="right")
    project_table.add_column("Tokens (In / Out)", justify="right")
    project_table.add_column("Est. Cost", justify="right", style="bold yellow")

    for p in data["projects"]:
        cost_cell = f"${p['cost']:.4f}" if p["cost"] is not None else "[dim]N/A[/]"
        project_table.add_row(
            p["project"],
            f"{p['requests']:,}",
            f"{p['input']:,} / {p['output']:,}",
            cost_cell
        )

    console.print(project_table, justify="center")
    console.print()

    console.print(Panel(
        "[dim]Cost is estimated locally from token counts via models_config.json — it may differ from your actual bill.\n"
        "Unpriced models show N/A rather than $0. See Subscription Status above for plan/rate-limit-tier info.[/]",
        border_style="dim", width=95
    ), justify="center")
    console.print()

def render_claude_config(mcp_servers, hooks):
    """
    Renders MCP servers and hooks configured for Claude Code, read from its
    own local config files — the same data the real `/mcp` and `/hooks`
    commands show, scoped to this project's directory and this user.
    """
    mcp_table = Table(box=box.ROUNDED, border_style="magenta", title="[bold magenta]🔌 MCP SERVERS CONFIGURED 🔌[/]")
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

    hooks_table = Table(box=box.ROUNDED, border_style="cyan", title="[bold cyan]🪝 HOOKS CONFIGURED 🪝[/]")
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
        "[dim]Reads only this project's .mcp.json / .claude/settings*.json and your user-level ~/.claude.json /\n"
        "~/.claude/settings.json. Organization-managed policy files aren't read by this app.[/]",
        border_style="dim", width=95
    ), justify="center")
    console.print()

