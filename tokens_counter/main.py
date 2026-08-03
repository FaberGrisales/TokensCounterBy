import os
import sys
from rich.prompt import Prompt

# Add parent dir to path to ensure package works
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import load_config
from tokens_counter import session_monitor
from tokens_counter import claude_config
import tokens_counter.tui as tui

def main():
    # Load configuration
    config_data = load_config()

    while True:
        tui.render_header()

        # Define menu choices
        menu_options = {
            "1": "Live Session Monitor (Claude Code usage 🔎)",
            "2": "Global Claude Usage (like /usage 📊)",
            "3": "Claude Code Config (MCP & Hooks 🔧)",
            "4": "Subagent Breakdown (per-agent tokens 🧩)",
            "5": "Exit 🚪"
        }

        tui.render_menu(menu_options)

        choice = Prompt.ask("\nEnter selection", choices=list(menu_options.keys()), default="1")

        if choice == "1":
            # Live Session Monitor: tails Claude Code's local session
            # transcripts (~/.claude/projects) to show real, live token/cost
            # usage per session, across every Claude Code window/tab running
            # under this subscription on this machine.
            tui.clear_screen()
            tui.console.print("[bold green]=== LIVE SESSION MONITOR (Claude Code) ===[/]\n")
            tui.console.print("[dim]Scanning local sessions under ~/.claude/projects ...[/]")
            tui.console.print("[yellow]Press Ctrl+C to stop and return to the menu.[/]\n")
            try:
                session_monitor.watch_sessions(config_data)
            except KeyboardInterrupt:
                pass
            tui.console.print("\n[bold yellow]Monitor stopped.[/]")
            input("\nPress Enter to return...")

        elif choice == "2":
            # Live-refreshing usage snapshot, modeled on Claude Code's own
            # /usage command (see https://code.claude.com/docs/en/costs):
            # plan/subscription status plus total cost and a "Usage by
            # model" breakdown, aggregated across every local session
            # instead of just the current one. Refreshes in place so the
            # Time-in-Window %/Time Elapsed counters visibly tick forward.
            tui.clear_screen()
            tui.console.print("[bold green]=== GLOBAL CLAUDE USAGE (like /usage) ===[/]\n")
            tui.console.print("[dim]Analyzing local sessions under ~/.claude/projects ...[/]")
            tui.console.print("[yellow]Press Ctrl+C to stop and return to the menu.[/]\n")

            try:
                session_monitor.watch_global_usage(config_data)
            except KeyboardInterrupt:
                pass
            tui.console.print("\n[bold yellow]Monitor stopped.[/]")
            input("\nPress Enter to return...")

        elif choice == "3":
            # Configured MCP servers + hooks, modeled on the real /mcp and
            # /hooks commands, read from this project's own config files.
            tui.clear_screen()
            tui.console.print("[bold green]=== CLAUDE CODE CONFIG (MCP & Hooks) ===[/]\n")
            tui.console.print("[dim]Reading .mcp.json / .claude/settings*.json for this project ...[/]\n")

            mcp_servers = claude_config.get_mcp_servers()
            hooks = claude_config.get_hooks_config()
            tui.render_claude_config(mcp_servers, hooks)
            input("\nPress Enter to return...")

        elif choice == "4":
            # Per-subagent breakdown: pick a session, then see exactly how
            # many tokens/how much cost each individual subagent invocation
            # (each "Task" tool call) consumed, instead of only the
            # session-wide total the Live Session Monitor shows.
            tui.clear_screen()
            tui.console.print("[bold green]=== SUBAGENT BREAKDOWN (per-agent tokens) ===[/]\n")
            tui.console.print("[dim]Scanning local sessions under ~/.claude/projects ...[/]\n")

            sessions = [s for s in session_monitor.get_all_sessions(config_data) if s["subagent_count"] > 0]
            if not sessions:
                tui.console.print("[yellow]No local session with subagents found.[/]")
                input("\nPress Enter to return...")
                continue

            picker = {}
            for i, s in enumerate(sessions[:15], start=1):
                project_label = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
                status = "[bold green]● LIVE[/]" if s["is_active"] else "[dim]○ idle[/]"
                tui.console.print(
                    f"  [{i}] {status} {project_label} "
                    f"[dim]{s['session_id'][:8]}…[/] — {s['subagent_count']} subagent(s)"
                )
                picker[str(i)] = s["session_id"]
            tui.console.print("  [0] Cancel\n")

            pick = Prompt.ask("Select a session", choices=list(picker.keys()) + ["0"], default="1")
            if pick == "0":
                continue

            tui.console.print("\n[yellow]Press Ctrl+C to stop and return to the menu.[/]\n")
            try:
                session_monitor.watch_subagent_breakdown(picker[pick], config_data)
            except KeyboardInterrupt:
                pass
            tui.console.print("\n[bold yellow]Monitor stopped.[/]")
            input("\nPress Enter to return...")

        elif choice == "5":
            tui.clear_screen()
            tui.console.print("\n[bold cyan]Exiting Token Monitor. Goodbye![/]")
            break

if __name__ == "__main__":
    main()
