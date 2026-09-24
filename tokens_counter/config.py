import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_config.json")

# Budgets live in their own file, NOT in models_config.json: that file is a
# map of model-id -> pricing, and several callers iterate it treating every
# key as a model name (`if model in config_data`). A non-model key there
# would be a trap waiting for whoever adds the next loop over it.
BUDGET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budget_config.json")

# Unset by default, and deliberately so. A budget is a number only the user
# can supply - it depends on their plan and on what they personally consider
# "a lot" - and the whole point of this feature is that the denominator is
# honest. With nothing set, the UI shows no bar instead of inventing a limit,
# which is exactly the failure mode the rolling-window percentages already
# guard against. `tokens` counts input + output + cache read + cache write.
DEFAULT_BUDGET = {
    "5h": {"tokens": None, "cost_usd": None},
    "7d": {"tokens": None, "cost_usd": None},
}

# Per-1M-token USD rates and context windows for the Claude models Claude Code
# can actually write into a local transcript. Input/output rates and context
# windows come from Anthropic's published model table; cache rates follow the
# documented standard multipliers (cache write = 1.25x input, cache read = 0.1x
# input) except where Anthropic publishes a specific rate - Claude Fable 5.1
# reads at a flat $0.25/1M, which is well below the 0.1x rule. Claude Mythos
# 5.1's cache-read rate was unpublished at launch, so it uses the 0.1x rule.
#
# Model IDs are the exact strings that appear as `message.model` in a
# transcript, complete as-is - never append a date suffix to one. The one
# dated key below (claude-haiku-4-5-20251001) is kept because that exact
# string has shown up in transcripts; it's the same model as claude-haiku-4-5
# and both are listed so either spelling prices correctly.
#
# The claude-3-* entries at the bottom are legacy and kept only so old
# transcripts (and the cost-math tests) still price; they are not current
# model IDs.
DEFAULT_CONFIG = {
    "claude-fable-5-1": {
        "name": "Claude Fable 5.1",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 10.00,
        "output_cost_per_1m": 50.00,
        "cache_write_cost_per_1m": 12.50,
        "cache_read_cost_per_1m": 0.25,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-fable-5": {
        "name": "Claude Fable 5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 10.00,
        "output_cost_per_1m": 50.00,
        "cache_write_cost_per_1m": 12.50,
        "cache_read_cost_per_1m": 1.00,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-mythos-5-1": {
        "name": "Claude Mythos 5.1",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 10.00,
        "output_cost_per_1m": 50.00,
        "cache_write_cost_per_1m": 12.50,
        "cache_read_cost_per_1m": 1.00,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-opus-5-5": {
        "name": "Claude Opus 5.5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 4.00,
        "output_cost_per_1m": 20.00,
        "cache_write_cost_per_1m": 5.00,
        "cache_read_cost_per_1m": 0.20,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-opus-5": {
        "name": "Claude Opus 5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 5.00,
        "output_cost_per_1m": 25.00,
        "cache_write_cost_per_1m": 6.25,
        "cache_read_cost_per_1m": 0.50,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-opus-4-8": {
        "name": "Claude Opus 4.8",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 5.00,
        "output_cost_per_1m": 25.00,
        "cache_write_cost_per_1m": 6.25,
        "cache_read_cost_per_1m": 0.50,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-opus-4-7": {
        "name": "Claude Opus 4.7",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 5.00,
        "output_cost_per_1m": 25.00,
        "cache_write_cost_per_1m": 6.25,
        "cache_read_cost_per_1m": 0.50,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-opus-4-6": {
        "name": "Claude Opus 4.6",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 5.00,
        "output_cost_per_1m": 25.00,
        "cache_write_cost_per_1m": 6.25,
        "cache_read_cost_per_1m": 0.50,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-sonnet-5": {
        "name": "Claude Sonnet 5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 2.00,
        "output_cost_per_1m": 10.00,
        "cache_write_cost_per_1m": 2.50,
        "cache_read_cost_per_1m": 0.20,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-sonnet-4-6": {
        "name": "Claude Sonnet 4.6",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "cache_write_cost_per_1m": 3.75,
        "cache_read_cost_per_1m": 0.30,
        "supports_caching": True,
        "context_window": 1000000
    },
    "claude-haiku-4-5": {
        "name": "Claude Haiku 4.5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
        "cache_write_cost_per_1m": 1.25,
        "cache_read_cost_per_1m": 0.10,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-haiku-4-5-20251001": {
        "name": "Claude Haiku 4.5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
        "cache_write_cost_per_1m": 1.25,
        "cache_read_cost_per_1m": 0.10,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-3-5-sonnet": {
        "name": "Claude 3.5 Sonnet (legacy)",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "cache_write_cost_per_1m": 3.75,
        "cache_read_cost_per_1m": 0.30,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-3-5-haiku": {
        "name": "Claude 3.5 Haiku (legacy)",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
        "cache_write_cost_per_1m": 1.25,
        "cache_read_cost_per_1m": 0.10,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-3-opus": {
        "name": "Claude 3 Opus (legacy)",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 15.00,
        "output_cost_per_1m": 75.00,
        "cache_write_cost_per_1m": 0.0,
        "cache_read_cost_per_1m": 0.0,
        "supports_caching": False,
        "context_window": 200000
    }
}

def load_config():
    """Load configurations from file, fallback to default and save it if not present."""
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except Exception:
        return DEFAULT_CONFIG

    # Backfill any model added to DEFAULT_CONFIG after this file was first
    # generated, so pricing for new models is available without a manual reset.
    missing_keys = [key for key in DEFAULT_CONFIG if key not in config_data]
    if missing_keys:
        for key in missing_keys:
            config_data[key] = DEFAULT_CONFIG[key]
        save_config(config_data)

    return config_data

def save_config(config_data):
    """Save configurations to models_config.json."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception:
        return False

def calculate_call_cost(model_key, input_tokens, output_tokens, cached_read_tokens=0, cached_write_tokens=0):
    """
    Calculate the cost of a call in USD based on input, output, and cache usage.
    Rates in config are per 1 Million tokens.
    """
    config = load_config()
    if model_key not in config:
        return 0.0

    m_cfg = config[model_key]

    # Base costs per token
    in_rate = m_cfg.get("input_cost_per_1m", 0.0) / 1000000.0
    out_rate = m_cfg.get("output_cost_per_1m", 0.0) / 1000000.0
    
    # Calculate costs
    # Input tokens that are NOT read from cache are charged the base input rate
    # For Claude: some input tokens are used to write cache (charged cache_write_cost_per_1m)
    # For standard tokens (neither cached_read nor cached_write), they are standard input tokens.
    standard_input_tokens = max(0, input_tokens - cached_read_tokens - cached_write_tokens)
    
    cost = 0.0
    cost += standard_input_tokens * in_rate
    cost += output_tokens * out_rate
    
    # Caching costs
    if m_cfg.get("supports_caching", False):
        cache_read_rate = m_cfg.get("cache_read_cost_per_1m", 0.0) / 1000000.0
        cache_write_rate = m_cfg.get("cache_write_cost_per_1m", 0.0) / 1000000.0
        
        cost += cached_read_tokens * cache_read_rate
        cost += cached_write_tokens * cache_write_rate
        
    return cost


def load_budget():
    """
    Load per-window budgets, falling back to the unset default.

    Never raises and never guesses: a missing, malformed or partial file just
    yields "no budget set" for whatever it doesn't define, so a typo in the
    file can't turn into a fabricated percentage on screen.
    """
    budget = {window: dict(limits) for window, limits in DEFAULT_BUDGET.items()}
    if not os.path.exists(BUDGET_FILE):
        return budget
    try:
        with open(BUDGET_FILE, 'r', encoding='utf-8') as f:
            on_disk = json.load(f)
    except Exception:
        return budget
    if not isinstance(on_disk, dict):
        return budget

    for window in budget:
        entry = on_disk.get(window)
        if not isinstance(entry, dict):
            continue
        for field in ("tokens", "cost_usd"):
            value = entry.get(field)
            # A zero or negative budget would divide by zero or read as
            # "already over 100%" on the first request - treat it as unset.
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                budget[window][field] = value
    return budget


def save_budget(budget):
    """Write budget_config.json. Returns True on success."""
    try:
        with open(BUDGET_FILE, 'w', encoding='utf-8') as f:
            json.dump(budget, f, indent=4)
        return True
    except Exception:
        return False


# Per-user preferences, deliberately outside the repo: they're personal, and
# a tracked file would put one user's choice into everyone's checkout.
# `None` means "never asked" - the app asks before the first use.
DEFAULT_APP_SETTINGS = {"show_desktop_chat_title": None}


def app_settings_path():
    import sys
    override = os.environ.get("TOKENS_COUNTER_SETTINGS")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, "TokensCounterBy", "settings.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/TokensCounterBy/settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "tokenscounterby", "settings.json")


def load_app_settings():
    """User preferences over the defaults; never raises."""
    settings = dict(DEFAULT_APP_SETTINGS)
    try:
        with open(app_settings_path(), "r", encoding="utf-8") as f:
            on_disk = json.load(f)
    except Exception:
        return settings
    if isinstance(on_disk, dict):
        value = on_disk.get("show_desktop_chat_title")
        if isinstance(value, bool):
            settings["show_desktop_chat_title"] = value
    return settings


def save_app_settings(settings):
    """Write the preferences file. Returns True on success."""
    path = app_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False
