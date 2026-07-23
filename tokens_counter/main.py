import os
import sys
from rich.prompt import Prompt, Confirm

# Add parent dir to path to ensure package works
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import load_config, save_config, calculate_call_cost, DEFAULT_CONFIG
from tokens_counter.history import log_call, get_high_scores, get_totals, clear_history
from tokens_counter.live_client import LiveClientManager
from tokens_counter.mcp_simulator import simulate_mcp_call, estimate_tokens_from_text
import tokens_counter.tui as tui

def select_model(config_data):
    """Submenu to select an LLM model."""
    tui.console.print("\n[bold yellow]🕹️ SELECT YOUR FIGHTER (LLM Model) 🕹️[/]")
    
    models = list(config_data.keys())
    for i, m_key in enumerate(models):
        m_info = config_data[m_key]
        tui.console.print(f"[{i+1}] [cyan]{m_info['name']}[/] ({m_info['provider']})")
        
    choice = Prompt.ask("\nChoose model number", choices=[str(i+1) for i in range(len(models))], default="1")
    model_key = models[int(choice) - 1]
    return model_key

def main():
    # Initialize wallet balance (start with $0 to encourage insertion, but give option to insert)
    wallet_balance = 0.50  # Give $0.50 starting credit as an arcade "free play" demo!
    
    # Load configuration
    config_data = load_config()
    
    # Live API wrapper manager
    live_manager = LiveClientManager()
    
    while True:
        tui.render_header(wallet_balance)
        
        # Define menu choices
        menu_options = {
            "1": "Call Live API (Requires keys)",
            "2": "MCP Token Cost Simulator (Simulates Tool overhead)",
            "3": "View High Scores (Call History & aggregates)",
            "4": "Pay Table (View Pricing Guides)",
            "5": "Insert Coin (Add Wallet Credits 🪙)",
            "6": "Real Account Dashboard (Analyze CSV)",
            "7": "Exit Machine 🚪"
        }
        
        tui.render_menu(menu_options)
        
        choice = Prompt.ask("\nEnter selection", choices=list(menu_options.keys()), default="2")
        
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
                tui.console.print("Please set your keys or press any key to return to simulation mode.")
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
                
            # Check wallet
            if wallet_balance < 0.005:
                tui.console.print("\n[blink bold red]❌ INSUFFICIENT CREDITS! Live calls cost at least $0.0050. Insert coins first! ❌[/]")
                tui.play_beep()
                input("\nPress Enter to return...")
                continue
                
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
            else:
                res = live_manager.call_claude(model_key, prompt, system_instruction=system_instr or None, use_caching=use_caching)
                
            if res.get("error"):
                tui.console.print(f"\n[red]API ERROR: {res['error']}[/]")
                input("\nPress Enter to return...")
                continue
                
            # Calculate cost
            cost = calculate_call_cost(
                model_key, 
                res["input_tokens"], 
                res["output_tokens"], 
                cached_read_tokens=res["cached_read_tokens"], 
                cached_write_tokens=res["cached_write_tokens"]
            )
            
            # Update wallet & log
            wallet_balance -= cost
            log_call(
                model_key, 
                prompt, 
                "live", 
                res["input_tokens"], 
                res["output_tokens"], 
                cost, 
                cached_read_tokens=res["cached_read_tokens"], 
                cached_write_tokens=res["cached_write_tokens"]
            )
            
            # Render Results
            tui.clear_screen()
            tui.render_live_results(model_key, prompt, res["text"], res, cost)
            tui.console.print(f"[bold yellow]DEDUCTED FROM WALLET:[/] ${cost:.6f}")
            input("\nPress Enter to return...")
            
        elif choice == "2":
            # MCP Token Cost Simulator
            tui.clear_screen()
            tui.console.print("[bold green]=== MCP TOKEN COST SIMULATOR ===[/]\n")
            
            # Model Selection
            model_key = select_model(config_data)
            
            # Preset Selection
            tui.console.print("\n[bold yellow]🔧 SELECT MCP TOOL SYSTEM PRESET 🔧[/]")
            from tokens_counter.mcp_simulator import PRESETS
            for key, preset in PRESETS.items():
                tui.console.print(f"[{key}] [bold cyan]{preset.name}[/]: {preset.description} (Tools: {preset.tool_count}, Avg Result payload: {preset.avg_result_tokens} tokens)")
            tui.console.print("[c] [bold cyan]Custom Tool Configuration[/]")
            
            preset_choice = Prompt.ask("\nChoose tool preset", choices=list(PRESETS.keys()) + ["c"], default="1")
            
            custom_tool_count = 0
            custom_schema_tokens = 0
            custom_payload_tokens = 0
            
            if preset_choice == "c":
                preset_choice = "custom"
                custom_tool_count = int(Prompt.ask("Enter number of tools in schema", default="2"))
                custom_schema_tokens = int(Prompt.ask("Enter total tokens of tool declarations", default="600"))
                custom_payload_tokens = int(Prompt.ask("Enter expected tool return result tokens", default="1500"))
                
            prompt = Prompt.ask("\nEnter simulated user prompt text", default="Review our git diff and search the filesystem for any memory leaks.")
            
            # Run simulation
            sim_results = simulate_mcp_call(
                model_key,
                prompt,
                preset_choice,
                custom_tool_count=custom_tool_count,
                custom_schema_tokens=custom_schema_tokens,
                custom_payload_tokens=custom_payload_tokens
            )
            
            # Prompt user which caching scenario to deduct from wallet
            use_caching = Confirm.ask("\nPerform simulation using [bold green]Optimized (Cached)[/] credits?", default=True)
            scenario_key = "cache" if use_caching else "nocache"
            cost = sim_results[scenario_key]["total_cost"]
            
            # Check wallet
            if wallet_balance < cost:
                tui.console.print(f"\n[blink bold red]❌ INSUFFICIENT CREDITS! Simulation costs ${cost:.6f}. Insert coins first! ❌[/]")
                tui.play_beep()
                input("\nPress Enter to return...")
                continue
                
            # Deduct wallet & Log call
            wallet_balance -= cost
            
            # Extract scenario numbers to log
            in_tokens = sim_results[scenario_key]["total_input"]
            out_tokens = sim_results[scenario_key]["total_output"]
            cached_read = sim_results[scenario_key].get("cached_read_tokens", 0)
            cached_write = sim_results[scenario_key].get("cached_write_tokens", 0)
            
            log_call(
                model_key,
                f"MCP: {prompt}",
                "simulation",
                in_tokens,
                out_tokens,
                cost,
                cached_read_tokens=cached_read,
                cached_write_tokens=cached_write
            )
            
            # Render comparison dashboard
            tui.clear_screen()
            tui.render_mcp_simulation_results(sim_results, config_data[model_key])
            tui.console.print(f"[bold yellow]DEDUCTED FROM WALLET (using {scenario_key.upper()} mode):[/] ${cost:.6f}")
            input("\nPress Enter to return...")
            
        elif choice == "3":
            # High Scores
            tui.clear_screen()
            tui.console.print("[bold green]=== HIGH SCORES LEADERBOARD ===[/]\n")
            
            high_scores = get_high_scores(limit=10)
            totals = get_totals()
            
            tui.render_high_scores(high_scores, totals)
            
            print()
            opt = Prompt.ask("\nChoose action", choices=["r", "c"], default="r")
            # r = Return, c = Clear History
            if opt == "c":
                confirm = Confirm.ask("[bold red]Are you sure you want to WIPE the high scores database?[/]", default=False)
                if confirm:
                    clear_history()
                    tui.console.print("[bold green]History database wiped successfully! DB score reset.[/]")
                    input("\nPress Enter to return...")
            
        elif choice == "4":
            # Pay Table
            tui.clear_screen()
            tui.render_pricing_table(config_data)
            
            print()
            opt = Prompt.ask("Actions", choices=["r", "reset"], default="r")
            # r = Return, reset = Reset pricing to code defaults
            if opt == "reset":
                confirm = Confirm.ask("[bold red]Reset models_config.json back to default factory settings?[/]", default=False)
                if confirm:
                    save_config(DEFAULT_CONFIG)
                    config_data = load_config()
                    tui.console.print("[bold green]Pricing config restored to defaults![/]")
                    input("\nPress Enter to return...")
            
        elif choice == "5":
            # Insert Coin
            tui.clear_screen()
            tui.console.print(tui.COIN_ART, justify="center")
            
            tui.console.print("\n[bold yellow]🪙 INSERT COINS SLOT 🪙[/]")
            tui.console.print("[1] Insert $1.00 Credit")
            tui.console.print("[2] Insert $5.00 Credit")
            tui.console.print("[3] Custom Token Grant")
            
            c_choice = Prompt.ask("\nSelect amount to drop", choices=["1", "2", "3", "r"], default="1")
            
            if c_choice == "1":
                amount = 1.0
            elif c_choice == "2":
                amount = 5.0
            elif c_choice == "3":
                amount_str = Prompt.ask("Enter custom credit quantity ($)", default="10.0")
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = 0.0
            else:
                continue
                
            if amount > 0:
                tui.console.print("\n[bold blink yellow]Inserting coins...[/]")
                tui.play_coin_sound()
                wallet_balance += amount
                tui.console.print(f"[bold green]SUCCESS! Wallet updated: +${amount:.2f}[/]")
                time.sleep(1)
                
        elif choice == "6":
            tui.clear_screen()
            tui.console.print("[bold green]=== REAL ACCOUNT DASHBOARD ===[/]\n")
            
            csv_path = "anthropic_usage.csv"
            if not os.path.exists(csv_path):
                tui.console.print(f"[bold red]File not found:[/] {csv_path}")
                tui.console.print("Please place your Anthropic exported 'anthropic_usage.csv' in the project root.")
                input("\nPress Enter to return...")
                continue
                
            from tokens_counter.dashboard import parse_usage_csv
            data = parse_usage_csv(csv_path)
            tui.render_account_dashboard(data)
            
            input("\nPress Enter to return...")
            
        elif choice == "7":
            tui.clear_screen()
            tui.console.print("\n[bold yellow]GAME OVER. THANKS FOR PLAYING! 🕹️[/]")
            tui.play_beep()
            break

if __name__ == "__main__":
    main()
