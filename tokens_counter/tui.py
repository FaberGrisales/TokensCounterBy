import sys
import os
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.prompt import Prompt, Confirm

console = Console()

# Pixel Art Icons
COIN_ART = """
   ▄███▄
  ▐█▀█▀█▌  [yellow]COIN[/]
  ▐█▄█▄█▌
   ▀███▀
"""

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
       [yellow]--==[ TOKEN PRICE MONITOR - RETRO TUI v1.0 ]==--[/]
"""

CABINET_ART = """
     .---------.
    /  (◕) (◕)  \\
   /   ________  \\
  /   /        \\  \\
 /   /          \\  \\
 |  |  [yellow]$[/] [cyan]PLAY[/] [yellow]$[/]  |  |
 |  |            |  |
 |  |            |  |
 |  '------------'  |
  \\                /
   '--------------'
"""

def play_beep():
    """Triggers an old-school terminal bell beep sound."""
    sys.stdout.write("\a")
    sys.stdout.flush()

def play_coin_sound():
    """Simulates a multi-tone insert coin sound."""
    play_beep()
    time.sleep(0.1)
    play_beep()

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def render_wallet(balance):
    """Renders the virtual coin wallet status in retro layout."""
    balance_text = f"${balance:.4f}"
    
    if balance <= 0:
        wallet_content = "[blink bold red]══ INSERT COIN TO PLAY ══[/]\n[red]CREDITS: $0.0000[/]"
        style = "bold red"
    else:
        wallet_content = f"[bold yellow]══ ACTIVE SESSION CREDITS ══[/]\n[bold green]CREDITS: {balance_text}[/]"
        style = "bold green"
        
    return Panel(
        wallet_content,
        title="[yellow]WALLET[/]",
        title_align="center",
        border_style=style,
        box=box.DOUBLE,
        width=40
    )

def render_header(balance):
    """Renders logo and wallet info side-by-side."""
    clear_screen()
    console.print(ARCADE_LOGO, justify="center")
    console.print(render_wallet(balance), justify="center")
    console.print()

def get_progress_bar(used, total, length=30):
    """Renders a pixelated progress bar."""
    ratio = used / total if total > 0 else 0
    ratio = min(1.0, max(0.0, ratio))
    filled = int(ratio * length)
    empty = length - filled
    
    # Pixel style block characters
    bar = "█" * filled + "░" * empty
    percent = ratio * 100
    
    if ratio < 0.5:
        color = "green"
    elif ratio < 0.8:
        color = "yellow"
    else:
        color = "red"
        
    return f"[{color}]{bar}[/] {percent:.2f}% ({used}/{total} tokens)"

def render_menu(options):
    """Renders an old-school BIOS/arcade style menu option list."""
    table = Table(show_header=False, box=box.ROUNDED, border_style="cyan", padding=(0, 2))
    
    table.add_column("Key", style="bold yellow", justify="right")
    table.add_column("Description", style="white")
    
    for key, desc in options.items():
        table.add_row(f"[{key}]", desc)
        
    console.print(Panel(
        table,
        title="[bold magenta]SELECT GAME MODE[/]",
        title_align="left",
        border_style="cyan",
        box=box.DOUBLE,
        width=55
    ), justify="center")

def render_pricing_table(config_data):
    """Renders a grid of model prices."""
    table = Table(title="[bold yellow]🕹️ MODEL PAY TABLE (Rates per 1 Million Tokens) 🕹️[/]", box=box.DOUBLE, border_style="cyan")
    
    table.add_column("Model Key", style="bold green")
    table.add_column("Provider", style="magenta")
    table.add_column("Input Cost", style="cyan", justify="right")
    table.add_column("Output Cost", style="cyan", justify="right")
    table.add_column("Cache Read", style="yellow", justify="right")
    table.add_column("Cache Write", style="yellow", justify="right")
    table.add_column("Ctx Limit", style="white", justify="right")
    
    for key, data in config_data.items():
        cache_read = f"${data.get('cache_read_cost_per_1m', 0.0):.2f}" if data.get("supports_caching") else "[dim]N/A[/]"
        cache_write = f"${data.get('cache_write_cost_per_1m', 0.0):.2f}" if data.get("supports_caching") and data.get('cache_write_cost_per_1m') else "[dim]N/A[/]"
        
        table.add_row(
            key,
            data.get("provider", ""),
            f"${data.get('input_cost_per_1m', 0.0):.2f}",
            f"${data.get('output_cost_per_1m', 0.0):.2f}",
            cache_read,
            cache_write,
            f"{data.get('context_window', 0):,}"
        )
        
    console.print(table, justify="center")

def render_high_scores(rows, totals):
    """Renders an arcade-style HIGH SCORES screen."""
    # Totals card
    totals_panel = Panel(
        f"[bold yellow]TOTAL PLAYS (Calls):[/] [white]{totals['total_calls']}[/]\n"
        f"[bold cyan]TOTAL INPUT TOKENS :[/] [white]{totals['total_input_tokens']:,}[/]\n"
        f"[bold magenta]TOTAL OUTPUT TOKENS:[/] [white]{totals['total_output_tokens']:,}[/]\n"
        f"[bold green]TOTAL SPENT (USD)  :[/] [green]${totals['total_cost']:.6f}[/]",
        title="[bold green]📊 MACHINE LIFETIME STATS 📊[/]",
        border_style="green",
        box=box.ROUNDED,
        width=50
    )
    console.print(totals_panel, justify="center")
    console.print()
    
    # Leaderboard Table
    table = Table(title="[blink bold yellow]🏆 HIGH SCORE SPENDERS (Leaderboard) 🏆[/]", box=box.DOUBLE, border_style="yellow")
    table.add_column("Rank", style="bold red", justify="center")
    table.add_column("Timestamp", style="dim white")
    table.add_column("Model", style="bold green")
    table.add_column("Mode", style="magenta", justify="center")
    table.add_column("Tokens", style="cyan", justify="right")
    table.add_column("Cost (USD)", style="bold yellow", justify="right")
    
    for i, row in enumerate(rows):
        mode_tag = "[green]LIVE[/]" if row['mode'] == 'live' else "[blue]SIM[/]"
        rank = f"{i+1}ST" if i == 0 else f"{i+1}ND" if i == 1 else f"{i+1}RD" if i == 2 else f"{i+1}TH"
        
        table.add_row(
            rank,
            row['timestamp'],
            row['model'],
            mode_tag,
            f"{row['total_tokens']:,}",
            f"${row['total_cost']:.6f}"
        )
        
    if not rows:
        table.add_row("-", "-", "No plays recorded yet!", "-", "-", "-")
        
    console.print(table, justify="center")

def render_mcp_simulation_results(results, model_info):
    """Renders simulation results with side-by-side comparison of caching efficiency."""
    
    preset_name = results["preset_name"]
    model_name = model_info["name"]
    ctx_limit = model_info["context_window"]
    
    overview_text = (
        f"[bold yellow]Model:[/] {model_name} ({model_info['provider']})\n"
        f"[bold yellow]Preset:[/] {preset_name} ({results['tool_count']} tools)\n"
        f"[bold yellow]Prompt Tokens:[/] {results['prompt_tokens']}  |  [bold yellow]Tool Schema:[/] {results['schema_tokens']} tokens\n"
        f"[bold yellow]Tool Response payload:[/] {results['payload_tokens']} tokens\n"
    )
    
    # Render Overview
    console.print(Panel(overview_text, title="[bold cyan]🎮 SIMULATION SPECIFICATIONS 🎮[/]", border_style="cyan", box=box.ROUNDED, width=70), justify="center")
    console.print()

    # Compare Cache vs No Cache
    comparison_table = Table(box=box.DOUBLE, border_style="magenta", title="[bold magenta]🪙 COST AND TOKEN SAVINGS COMPARISON 🪙[/]")
    comparison_table.add_column("Metric", style="bold white")
    comparison_table.add_column("Standard (No Caching)", style="bold red", justify="right")
    comparison_table.add_column("Optimized (With Caching)", style="bold green", justify="right")
    
    nocache_data = results["nocache"]
    cache_data = results["cache"]
    
    comparison_table.add_row(
        "Turn 1 Input (Prompt + Schema)",
        f"{nocache_data['turn1_input']:,} tokens",
        f"{cache_data['turn1_input']:,} tokens [dim](Cache Write)[/]"
    )
    comparison_table.add_row(
        "Turn 1 Output (Tool Call Request)",
        f"{nocache_data['turn1_output']:,} tokens",
        f"{cache_data['turn1_output']:,} tokens"
    )
    comparison_table.add_row(
        "Turn 2 Input (Full History / Payload)",
        f"{nocache_data['turn2_input']:,} tokens",
        f"{cache_data['turn2_input']:,} tokens [dim](+{cache_data['cached_read_tokens']:,} Cached Read)[/]"
    )
    comparison_table.add_row(
        "Turn 2 Output (Final Response)",
        f"{nocache_data['turn2_output']:,} tokens",
        f"{cache_data['turn2_output']:,} tokens"
    )
    comparison_table.add_row(
        "Total Input / Output Tokens",
        f"{nocache_data['total_input']:,} / {nocache_data['total_output']:,}",
        f"{cache_data['total_input']:,} / {cache_data['total_output']:,}"
    )
    comparison_table.add_row(
        "Total Turn-by-Turn Cost (USD)",
        f"[bold red]${nocache_data['total_cost']:.6f}[/]",
        f"[bold green]${cache_data['total_cost']:.6f}[/]"
    )
    
    console.print(comparison_table, justify="center")
    console.print()
    
    # Cost savings alert
    savings_text = f"[bold green]SAVINGS METRIC:[/] Caching saves [bold yellow]{results['savings_percentage']:.2f}%[/] on this multi-turn MCP execution!"
    console.print(Panel(savings_text, border_style="green", box=box.ROUNDED, width=70), justify="center")
    console.print()
    
    # Progress bars showing context window usage
    nocache_used = nocache_data['total_input'] + nocache_data['total_output']
    cache_used = cache_data['total_input'] + cache_data['total_output']
    
    console.print("[bold red]Standard Session Context Usage:[/]", justify="left")
    console.print(get_progress_bar(nocache_used, ctx_limit), justify="left")
    console.print("[bold green]Cached Session Context Usage:[/]", justify="left")
    console.print(get_progress_bar(cache_used, ctx_limit), justify="left")
    console.print()

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

def render_account_dashboard(data):
    """Renders the real account usage dashboard from CSV data."""
    if "error" in data:
        console.print(f"[bold red]Error parsing CSV:[/] {data['error']}")
        return

    # Total Panel
    total_panel = Panel(
        f"[bold yellow]TOTAL ACCOUNT SPEND:[/] [bold green]${data['total_cost']:.2f}[/]\n"
        f"[cyan]Input Tokens:[/] {data['total_input']:,}  |  [magenta]Output Tokens:[/] {data['total_output']:,}\n"
        f"[green]Cache Read Tokens:[/] {data['total_cache_read']:,}\n"
        f"[bold yellow]💰 TOTAL SAVED BY CACHING:[/] [bold green]${data['total_saved_by_cache']:.2f}[/]",
        title="[bold green]📊 REAL ACCOUNT LIFETIME USAGE 📊[/]",
        border_style="green",
        box=box.DOUBLE,
        width=70
    )
    console.print(total_panel, justify="center")
    console.print()

    # Spenders Table
    table = Table(title="[bold yellow]🔥 TOP SPENDERS BY MODEL 🔥[/]", box=box.ROUNDED, border_style="yellow")
    table.add_column("Model", style="bold green")
    table.add_column("Total Cost", style="bold yellow", justify="right")
    table.add_column("Input", style="cyan", justify="right")
    table.add_column("Output", style="magenta", justify="right")
    table.add_column("Cache Read", style="green", justify="right")

    for model, stats in data["by_model"].items():
        table.add_row(
            model,
            f"${stats['cost']:.2f}",
            f"{stats['input']:,}",
            f"{stats['output']:,}",
            f"{stats['cache_read']:,}"
        )
    console.print(table, justify="center")
    console.print()

    # Timeline Chart
    if data["by_date"]:
        max_val = max(data["by_date"].values()) if data["by_date"] else 1.0
        chart_lines = ["[bold cyan]📅 SPEND TIMELINE (By Date)[/]"]
        for date_str, cost in data["by_date"].items():
            blocks_count = int((cost / max_val) * 40)
            bar = "█" * blocks_count
            chart_lines.append(f"[yellow]{date_str}[/] | [green]${cost:6.2f}[/] | [magenta]{bar}[/]")
        
        console.print(Panel("\n".join(chart_lines), border_style="cyan", box=box.ROUNDED, width=70), justify="center")
        console.print()
