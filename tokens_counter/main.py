import os
import sys
from rich.prompt import Prompt, Confirm

# Add parent dir to path to ensure package works
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import load_config, calculate_call_cost
from tokens_counter.live_client import LiveClientManager
from tokens_counter import session_monitor
from tokens_counter import claude_config
import tokens_counter.tui as tui

def select_model(config_data):
    """Submenu to select an LLM model."""
    tui.console.print("\n[bold cyan]SELECT MODEL (LLM)[/]")

    models = list(config_data.keys())
    for i, m_key in enumerate(models):
        m_info = config_data[m_key]
        tui.console.print(f"[{i+1}] [cyan]{m_info['name']}[/] ({m_info['provider']})")

    choice = Prompt.ask("\nChoose model number", choices=[str(i+1) for i in range(len(models))], default="1")
    model_key = models[int(choice) - 1]
    return model_key

def main():
    # Load configuration
    config_data = load_config()

    # Live API wrapper manager
    live_manager = LiveClientManager()

    while True:
        tui.render_header()

        # Define menu choices
        menu_options = {
            "1": "Call Live API (Requires keys)",
            "2": "Live Session Monitor (Claude Code usage 🔎)",
            "3": "Global Claude Usage (like /usage 📊)",
            "4": "Claude Code Config (MCP & Hooks 🔧)",
            "5": "Exit 🚪"
        }

        tui.render_menu(menu_options)

        choice = Prompt.ask("\nEnter selection", choices=list(menu_options.keys()), default="1")

        if choice == "1":
            # Live API Mode
            tui.clear_screen()
            tui.console.print("[bold green]=== LIVE API PORTAL ===[/]\n")

            # Check availability
            gemini_ready = live_manager.is_gemini_ready()
            anthropic_ready = live_manager.is_anthropic_ready()

            tui.console.print(f"Gemini API Status : {'[green]READY (Key Found)[/]' if gemini_ready else '[red]DISABLED (Missing Key)[/]'}")
            tui.console.print(f"Claude API Status : {'[green]READY (Key Found)[/]' if anthropic_ready else '[red]DISABLED (Missing Key)[/]'}\n")

            if not gemini_ready and not anthropic_ready:
                tui.console.print("[yellow]WARNING: No API keys found in env variables (GEMINI_API_KEY / ANTHROPIC_API_KEY).[/]")
                tui.console.print("Please set your keys or press any key to return to the main menu.")
                input("\nPress Enter to return...")
                continue

            # Model selection
            model_key = select_model(config_data)
            provider = config_data[model_key]["provider"]

            # Check key specifically for this provider
            is_gemini = "gemini" in model_key or "Google" in provider
            if is_gemini and not gemini_ready:
                tui.console.print("[red]Error: GEMINI_API_KEY is missing. Can't launch Gemini Live mode.[/]")
                input("\nPress Enter to return...")
                continue
            if not is_gemini and not anthropic_ready:
                tui.console.print("[red]Error: ANTHROPIC_API_KEY is missing. Can't launch Claude Live mode.[/]")
                input("\nPress Enter to return...")
                continue

            # Real Tool-Use / MCP (Claude only): lets Claude actually call tools
            # (local demo tools, or a real remote MCP server) so token usage and
            # cost reflect a genuine multi-turn tool-calling exchange.
            use_real_mcp = False
            mcp_server_url = None
            mcp_server_token = None
            if not is_gemini:
                use_real_mcp = Confirm.ask(
                    "\n[bold cyan]Enable real Tool-Use / MCP for this call?[/] (Claude will actually invoke tools)",
                    default=False
                )
                if use_real_mcp:
                    mcp_server_url = Prompt.ask(
                        "Remote MCP server URL (leave empty to use local demo tools: clock, calculator, file listing)",
                        default=""
                    ) or None
                    if mcp_server_url:
                        mcp_server_token = Prompt.ask("MCP server auth token (optional, hit Enter to skip)", default="") or None

            # Input Prompt
            prompt = Prompt.ask("\nEnter prompt for the model")
            if not prompt:
                continue

            system_instr = Prompt.ask("Enter system instruction (optional, hit Enter to skip)", default="")
            use_caching = Confirm.ask("Enable Prompt Caching?", default=True)

            tui.console.print("\n[bold blink yellow]⏳ TRANSMITTING SIGNAL TO LLM CABINET...[/]")

            # Execute
            if is_gemini:
                res = live_manager.call_gemini(model_key, prompt, system_instruction=system_instr or None, use_caching=use_caching)
            elif use_real_mcp:
                res = live_manager.call_claude_with_tools(
                    model_key, prompt, system_instruction=system_instr or None, use_caching=use_caching,
                    mcp_server_url=mcp_server_url, mcp_server_token=mcp_server_token
                )
            else:
                res = live_manager.call_claude(model_key, prompt, system_instruction=system_instr or None, use_caching=use_caching)

            if res.get("error"):
                tui.console.print(f"\n[red]API ERROR: {res['error']}[/]")
                input("\nPress Enter to return...")
                continue

            # Calculate real cost
            cost = calculate_call_cost(
                model_key,
                res["input_tokens"],
                res["output_tokens"],
                cached_read_tokens=res["cached_read_tokens"],
                cached_write_tokens=res["cached_write_tokens"]
            )

            # Render Results
            tui.clear_screen()
            if use_real_mcp:
                tui.render_mcp_live_results(model_key, prompt, res, cost)
            else:
                tui.render_live_results(model_key, prompt, res["text"], res, cost)
            input("\nPress Enter to return...")

        elif choice == "2":
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

        elif choice == "3":
            # Global usage snapshot, modeled on Claude Code's own /usage
            # command (see https://code.claude.com/docs/en/costs): plan/
            # subscription status plus total cost and a "Usage by model"
            # breakdown, aggregated across every local session instead of
            # just the current one.
            tui.clear_screen()
            tui.console.print("[bold green]=== GLOBAL CLAUDE USAGE (like /usage) ===[/]\n")
            tui.console.print("[dim]Analyzing local sessions under ~/.claude/projects ...[/]\n")

            subscription_status = claude_config.get_subscription_status()
            tui.render_subscription_status(subscription_status)

            usage_data = session_monitor.get_global_usage_summary(config_data)
            tui.render_usage_summary(usage_data)
            input("\nPress Enter to return...")

        elif choice == "4":
            # Configured MCP servers + hooks, modeled on the real /mcp and
            # /hooks commands, read from this project's own config files.
            tui.clear_screen()
            tui.console.print("[bold green]=== CLAUDE CODE CONFIG (MCP & Hooks) ===[/]\n")
            tui.console.print("[dim]Reading .mcp.json / .claude/settings*.json for this project ...[/]\n")

            mcp_servers = claude_config.get_mcp_servers()
            hooks = claude_config.get_hooks_config()
            tui.render_claude_config(mcp_servers, hooks)
            input("\nPress Enter to return...")

        elif choice == "5":
            tui.clear_screen()
            tui.console.print("\n[bold cyan]Exiting Token Monitor. Goodbye![/]")
            break

if __name__ == "__main__":
    main()
