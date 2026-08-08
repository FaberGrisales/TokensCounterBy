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
            "4": "Session Breakdown (subagents + MCP calls 🧩)",
            "5": "Cleanup Inactive Sessions (delete 🗑️)",
            "6": "Exit 🚪"
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
            # Session Breakdown: pick a session, then see exactly how many
            # tokens/how much cost each individual subagent invocation and
            # each individual MCP tool-call turn consumed, instead of only
            # the session-wide total the Live Session Monitor shows.
            tui.clear_screen()
            tui.console.print("[bold green]=== SESSION BREAKDOWN (subagents + MCP calls) ===[/]\n")
            tui.console.print("[dim]Scanning local sessions under ~/.claude/projects ...[/]\n")

            sessions = session_monitor.get_all_sessions(config_data)
            if not sessions:
                tui.console.print("[yellow]No local Claude Code sessions found.[/]")
                input("\nPress Enter to return...")
                continue

            picker = {}
            for i, s in enumerate(sessions[:15], start=1):
                project_label = os.path.basename(s["cwd"]) if s.get("cwd") else s["project"]
                status = "[bold green]● LIVE[/]" if s["is_active"] else "[dim]○ idle[/]"
                subagent_note = f", {s['subagent_count']} subagent(s)" if s["subagent_count"] else ""
                tui.console.print(
                    f"  [{i}] {status} {project_label} "
                    f"[dim]{s['session_id'][:8]}…[/]{subagent_note}"
                )
                picker[str(i)] = s["session_id"]
            tui.console.print("  [0] Cancel\n")

            pick = Prompt.ask("Select a session", choices=list(picker.keys()) + ["0"], default="1")
            if pick == "0":
                continue

            tui.console.print("\n[yellow]Press Ctrl+C to stop and return to the menu.[/]\n")
            try:
                session_monitor.watch_session_breakdown(picker[pick], config_data)
            except KeyboardInterrupt:
                pass
            tui.console.print("\n[bold yellow]Monitor stopped.[/]")
            input("\nPress Enter to return...")

        elif choice == "5":
            # Cleanup: find sessions inactive for 7+ days and let the user
            # pick which ones to permanently delete (main transcript +
            # subagent files). This is the one destructive action in the
            # app - real, irreversible deletion of local Claude Code
            # history - so it requires seeing the exact list, picking
            # specific sessions, and typing "DELETE" to confirm.
            tui.clear_screen()
            tui.console.print("[bold red]=== CLEANUP INACTIVE SESSIONS ===[/]\n")
            tui.console.print("[dim]Scanning local sessions under ~/.claude/projects for sessions inactive 7+ days ...[/]\n")

            candidates = session_monitor.get_cleanup_candidates(config_data)
            if not candidates:
                tui.console.print("[green]No sessions inactive for more than 7 days. Nothing to clean up.[/]")
                input("\nPress Enter to return...")
                continue

            tui.render_cleanup_candidates(candidates)
            tui.console.print(
                "[yellow]Deleting a session permanently removes its local transcript file(s) - "
                "this cannot be undone, and Claude Code has no way to recover it.[/]\n"
            )

            selection = Prompt.ask(
                "Enter numbers to delete (e.g. 1,3,5), 'all', or 'c' to cancel",
                default="c"
            )
            if selection.strip().lower() in ("c", "cancel", ""):
                continue

            if selection.strip().lower() == "all":
                chosen = list(candidates)
            else:
                chosen = []
                seen_ids = set()
                for part in selection.split(","):
                    part = part.strip()
                    if not part.isdigit():
                        continue
                    idx = int(part)
                    if 1 <= idx <= len(candidates) and candidates[idx - 1]["session_id"] not in seen_ids:
                        seen_ids.add(candidates[idx - 1]["session_id"])
                        chosen.append(candidates[idx - 1])

            if not chosen:
                tui.console.print("[yellow]No valid sessions selected. Nothing deleted.[/]")
                input("\nPress Enter to return...")
                continue

            tui.console.print(f"\n[bold red]About to permanently delete {len(chosen)} session(s):[/]")
            for c in chosen:
                project_label = os.path.basename(c["cwd"]) if c.get("cwd") else c["project"]
                tui.console.print(f"  - {project_label} [dim]{c['session_id'][:8]}…[/]")

            confirm = Prompt.ask("\nType DELETE to confirm (anything else cancels)", default="")
            if confirm.strip() != "DELETE":
                tui.console.print("[yellow]Cancelled. Nothing was deleted.[/]")
                input("\nPress Enter to return...")
                continue

            deleted, failed = 0, []
            for c in chosen:
                ok, error = session_monitor.delete_session(c)
                if ok:
                    deleted += 1
                else:
                    failed.append((c["session_id"], error))

            tui.console.print(f"\n[bold green]Deleted {deleted} session(s).[/]")
            if failed:
                tui.console.print("[bold red]Failed to delete:[/]")
                for session_id, error in failed:
                    tui.console.print(f"  - {session_id}: {error}")

            input("\nPress Enter to return...")

        elif choice == "6":
            tui.clear_screen()
            tui.console.print("\n[bold cyan]Exiting Token Monitor. Goodbye![/]")
            break

if __name__ == "__main__":
    main()
