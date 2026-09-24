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
        width=_panel_width(55)
    ), justify="center")

# Below this console width the full multi-column tables stop fitting: Rich
# wraps every cell into unreadable slivers and the fixed-width panels below
# overflow. Under it the views switch to a reduced column set with humanized
# numbers, so the app stays readable in a small window (which is also what a
# picture-in-picture / always-on-top mini view needs).
COMPACT_WIDTH = 100

# Below this, a 5-column table stops working no matter how the widths are
# assigned: Rich shrinks every column proportionally once their combined
# minimum exceeds the console, so the status dot collapses to nothing and the
# cost ellipsizes into "$9.…". Narrower than this the views stack each
# session onto two short lines instead of tabulating them.
NARROW_WIDTH = 50


def _is_compact():
    """True when the console is too narrow for the full-width tables."""
    return console.width < COMPACT_WIDTH


def _is_narrow():
    """True when even the compact table won't fit and rows must stack."""
    return console.width < NARROW_WIDTH


def _panel_width(preferred):
    """
    Cap a panel's preferred width at the real console width.

    Rich already clamps an over-wide Panel itself, so this changes no output
    today - it states the cap explicitly instead of leaving a bare width=92
    that reads like a bug in a 40-column window, and pins the behaviour if
    Rich's clamping ever changes. It is NOT what makes the views fit: that's
    the compact/narrow tiers below. Tables, unlike panels, genuinely do not
    degrade on their own - Rich keeps all the columns and ellipsizes each one
    into unreadable slivers ("claude-opu…", "$9.…"), which is the real
    "the text doesn't adjust when I shrink the terminal" behaviour.
    """
    return min(preferred, console.width)


def _fmt_tokens(n):
    """Humanize a token count for narrow layouts: 1234567 -> '1.2M'."""
    if n is None:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(cost, compact=False):
    """
    Cost as a string, or a dim N/A for an unpriced model. The compact form
    trades the 4-decimal precision for width, but never rounds a real cost
    down to a flat $0.00 - that would read as "this was free".
    """
    if cost is None:
        return "[dim]N/A[/]"
    if cost == 0:
        # Exactly zero is a reported "no charge" (an OpenCode free or local
        # model), not a rounded-down real cost.
        return "free"
    if not compact:
        return f"${cost:.4f}"
    return f"${cost:,.2f}" if cost >= 0.01 else "<$0.01"


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

def _budget_bar(percent, used_label, limit_label, length=10):
    """
    Usage against the user's OWN budget, e.g. '███████░░░ 64%\n25.9M / 40.0M'.

    Deliberately not clamped at 100%: going over a budget you set yourself is
    the single most important thing this bar can tell you, so it turns red and
    keeps counting rather than sitting at a reassuring full bar.
    """
    if percent is None:
        return "[dim]not set[/]"
    filled = int(round(min(1.0, percent / 100) * length))
    bar = "█" * filled + "░" * (length - filled)
    color = "green" if percent < 50 else "yellow" if percent < 80 else "red"
    return f"[{color}]{bar} {percent:.0f}%[/]\n[dim]{used_label} / {limit_label}[/]"


def _plan_limit_cell(percent, resets_at, length=10, estimated=False):
    """
    Claude's own plan-quota usage for one window, e.g. '████░░░░░░ 43%' over
    'resets 18:00'. Separate from _budget_bar because that one's second line
    is a 'used / limit' pair; here the limit is the plan's and unknown to us -
    only the percentage and the reset time are.
    """
    if percent is None:
        return "[dim]n/a[/]"
    filled = int(round(min(1.0, max(0.0, percent / 100)) * length))
    bar = "█" * filled + "░" * (length - filled)
    color = "green" if percent < 50 else "yellow" if percent < 80 else "red"
    cell = f"[{color}]{bar} {percent:.0f}%[/]"
    when = _parse_iso(resets_at)
    if when is not None:
        approx = "~" if estimated else ""
        cell += f"\n[dim]resets {approx}{when.astimezone().strftime('%b %d %H:%M')}[/]"
    return cell


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

def _parse_iso(value):
    """
    Parse a timestamp from Claude (`resets_at`) to a datetime, or None.

    Delegates to floating._to_datetime so the two presentation layers cannot
    disagree about a format - Claude sends an integer Unix timestamp here,
    not the ISO strings used elsewhere in the app.
    """
    from tokens_counter.floating import _to_datetime
    return _to_datetime(value)


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

    compact = _is_compact()

    if compact:
        header_lines = [
            f"[bold green]●[/] {len(active)} live   [dim]○[/] {len(idle)} idle",
            f"[cyan]In[/] {_fmt_tokens(total_input)}   [magenta]Out[/] {_fmt_tokens(total_output)}",
            f"[bold yellow]Spend[/] {_fmt_cost(total_cost, compact=True)}",
        ]
    else:
        header_lines = [
            f"[bold green]● Active sessions:[/] {len(active)}   [dim]○ Idle (5+ min):[/] {len(idle)}",
            f"[cyan]Total Input:[/] {total_input:,}  |  [magenta]Total Output:[/] {total_output:,}",
            f"[bold yellow]Estimated Total Spend:[/] ${total_cost:.4f}"
        ]
    if unpriced_count:
        header_lines.append(f"[dim](+{unpriced_count} unpriced)[/]" if compact
                            else f"[dim](+{unpriced_count} session(s) using a model with no price in models_config.json)[/]")

    header = Panel(
        "\n".join(header_lines),
        title="[bold cyan]Sessions[/]" if compact else "[bold cyan]Live Session Monitor — Claude Code + OpenCode[/]",
        border_style="cyan",
        box=box.DOUBLE,
        width=_panel_width(92)
    )

    if compact:
        # Five columns is what fits around 46 chars - the width a small
        # always-on-top window realistically has. Project names get
        # ellipsized rather than wrapped so each session stays on one line.
        if _is_narrow():
            lines = []
            for s_ in sessions[:15]:
                project_label = os.path.basename(s_["cwd"]) if s_.get("cwd") else s_["project"]
                dot = "[bold green]●[/]" if s_["is_active"] else "[dim]○[/]"
                lines.append(f"{dot} [bold green]{project_label}[/]")
                lines.append(
                    f"  {_fmt_tokens(s_['input_tokens'] + s_['output_tokens'])}"
                    f"  [bold yellow]{_fmt_cost(s_['cost'], compact=True)}[/]"
                    f"  {_context_bar(s_.get('context_percent'), length=4)}"
                )
            if not sessions:
                lines.append("[dim]No sessions[/]")
            return Group(header, "\n".join(lines), "[dim]Ctrl+C[/]")

        # Every column except the project name gets an explicit width, so
        # Rich can only take space from the name. Left flexible, Rich
        # squeezes whichever column it likes - it will collapse the status
        # column to zero (the ●/○ silently vanish) and ellipsize the cost
        # into "$9.…" long before it shortens a long project name.
        table = Table(box=box.SIMPLE, border_style="yellow", padding=(0, 1), pad_edge=False)
        table.add_column("S", justify="center", no_wrap=True, width=1)
        table.add_column("Project", style="bold green", no_wrap=True, overflow="ellipsis")
        table.add_column("Tokens", justify="right", no_wrap=True, width=6)
        table.add_column("Cost", justify="right", style="bold yellow", no_wrap=True, width=9)
        table.add_column("Ctx", justify="center", no_wrap=True, width=9)

        for s_ in sessions[:15]:
            project_label = os.path.basename(s_["cwd"]) if s_.get("cwd") else s_["project"]
            table.add_row(
                "[bold green]●[/]" if s_["is_active"] else "[dim]○[/]",
                project_label,
                _fmt_tokens(s_["input_tokens"] + s_["output_tokens"]),
                _fmt_cost(s_["cost"], compact=True),
                _context_bar(s_.get("context_percent"), length=5),
            )

        if not sessions:
            table.add_row("-", "No sessions", "-", "-", "-")

        return Group(header, table, "[dim]Ctrl+C to stop[/]")

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
        if s.get("origin") == "opencode":
            # OpenCode ids share a time-ordered "ses_…" prefix; the tail differs.
            session_label = f"{project_label}\n[dim]OpenCode · …{s['session_id'][-8:]}[/]"
        else:
            session_label = f"{project_label}\n[dim]{s['session_id'][:8]}…[/]"

        subagent_note = f" [dim](+{s['subagent_count']} subagent(s))[/]" if s["subagent_count"] else ""
        reqs = f"{s['main_requests']}{subagent_note}"

        cost_str = _fmt_cost(s["cost"])

        last_req = s.get("last_request")
        if last_req:
            last_tokens = f"{last_req['input_tokens']:,} / {last_req['output_tokens']:,}"
            last_cost_str = _fmt_cost(s.get("last_request_cost"))
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
        table.add_row("-", "No local Claude Code or OpenCode sessions found", "-", "-", "-", "-", "-", "-", "-")

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
        width=_panel_width(92)
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

def _build_subscription_status_renderables(status, rolling_usage=None, plan_limits=None):
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
            border_style="yellow", box=box.ROUNDED, width=_panel_width(90)
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
        border_style="cyan", box=box.DOUBLE, width=_panel_width(90)
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
        # Only shown when the user has actually set a budget: with none set
        # the column would be a row of "not set" teaching nothing, and the
        # table is already wide.
        # Claude's own plan-quota percentage wins over a self-set budget when
        # it's there: it's the real number, the budget was only ever the
        # honest stand-in for it. Both are absent for API-key users, in which
        # case the column disappears rather than showing a row of "not set".
        plan_windows = {"5h": "five_hour", "7d": "seven_day"}
        has_plan = bool(plan_limits) and any(
            (plan_limits or {}).get(field) for field in plan_windows.values()
        )
        has_budget = any(
            (rolling_usage.get(k) or {}).get("budget_tokens_percent") is not None
            or (rolling_usage.get(k) or {}).get("budget_cost_percent") is not None
            for k in ("5h", "7d")
        )
        if has_plan:
            usage_window_table.add_column("Plan Limit Used (real)", justify="center")
        elif has_budget:
            usage_window_table.add_column("vs Your Budget", justify="center")
        usage_window_table.add_column("Window Started", justify="right")
        usage_window_table.add_column("Window Ends", justify="right")
        usage_window_table.add_column("Time Elapsed", justify="right")

        for key, label in (("5h", "5h window"), ("7d", "7d window")):
            w = rolling_usage.get(key, {})
            budget_cell = []
            if has_plan:
                entry = (plan_limits or {}).get(plan_windows[key])
                budget_cell = [
                    _plan_limit_cell(entry["used_percentage"], entry.get("resets_at"),
                                     estimated=bool(entry.get("resets_at_estimated")))
                    if entry else "[dim]n/a[/]"
                ]
            elif has_budget:
                if w.get("budget_tokens_percent") is not None:
                    budget_cell = [_budget_bar(
                        w["budget_tokens_percent"],
                        _fmt_tokens(w.get("total_tokens", 0)),
                        _fmt_tokens(w["budget_tokens"]),
                    )]
                elif w.get("budget_cost_percent") is not None:
                    budget_cell = [_budget_bar(
                        w["budget_cost_percent"],
                        f"${w.get('cost', 0):,.2f}",
                        f"${w['budget_cost']:,.0f}",
                    )]
                else:
                    budget_cell = ["[dim]not set[/]"]

            if w.get("window_start_at") is None:
                usage_window_table.add_row(
                    label, "[dim]Empty (no recent activity)[/]", "[dim]N/A[/]",
                    *budget_cell, "-", "-", "-"
                )
            else:
                remaining = w.get("remaining_seconds")
                usage_window_table.add_row(
                    label,
                    "[green]Active[/]",
                    _neutral_bar(w.get("percent_used")),
                    *budget_cell,
                    _format_local_time(w.get("window_start_at")),
                    f"{_format_local_time(w.get('window_end_at'))}\n[dim]in {_format_duration(remaining)}[/]"
                    if remaining is not None else "-",
                    _format_duration(w.get("elapsed_seconds"))
                )
        renderables.append(usage_window_table)
        if has_plan:
            # Oldest of the windows shown, so the note can't understate how
            # stale the table is.
            ages = [w.get("age_seconds") for w in
                    ((plan_limits or {}).get(f) for f in plan_windows.values())
                    if w and w.get("age_seconds") is not None]
            age = max(ages) if ages else (plan_limits or {}).get("age_seconds")
            freshness = (f"captured {_format_duration(age)} ago"
                         if age is not None else "capture time unknown")
            # The cache only refreshes while a Claude Code session renders its
            # status line, so an old reading must say so rather than passing
            # for current.
            sources = {w.get("source") for w in
                       ((plan_limits or {}).get(f) for f in plan_windows.values()) if w}
            if sources == {"desktop"}:
                origin = ("recorded by Claude Desktop, which samples it every ~15 min while open; "
                          "a '~' reset time is estimated from when usage started rising")
                stale_after = 900 + 300
            else:
                origin = ("captured from Claude Code's status line, which only updates while a "
                          "Claude Code session is running")
                stale_after = 300
            style = "yellow" if age is not None and age > stale_after else "dim"
            renderables.append(
                f"[{style}]Plan Limit Used is Claude's own account-wide number ({freshness}), "
                f"{origin}.[/]"
            )
        renderables.append(
            "[dim]Time-in-Window % is real local elapsed time, NOT Claude Code's plan-quota %/usage limit "
            "(that's computed server-side and requires a live account check this app doesn't make). "
            "Window Ends is when the oldest request still in the window ages out of it - the window then "
            "re-anchors to the next oldest, it does not reset a quota. 'vs Your Budget' compares real local "
            "usage against the limit YOU set in budget_config.json - it is not a Claude plan limit either.[/]"
        )

    return renderables

def render_subscription_status(status, rolling_usage=None, plan_limits=None):
    """
    Renders Claude subscription/account status read from locally-cached OAuth
    account metadata — never the access/refresh tokens themselves — plus real
    local consumption over rolling 5h/7d windows. See
    claude_config.get_subscription_status() and
    session_monitor.get_rolling_window_usage() for exactly what's read/computed.
    """
    for renderable in _build_subscription_status_renderables(status, rolling_usage, plan_limits):
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
        width=_panel_width(70)
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

def render_global_usage_live_view(status, rolling_usage, data, plan_limits=None):
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
    renderables = _build_subscription_status_renderables(status, rolling_usage, plan_limits)
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
        border_style="dim", width=_panel_width(95)
    ), justify="center")
    console.print()

