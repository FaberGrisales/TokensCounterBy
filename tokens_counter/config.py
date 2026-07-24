import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_config.json")

DEFAULT_CONFIG = {
    "gemini-3.6-flash": {
        "name": "Gemini 3.6 Flash",
        "provider": "Google Gemini",
        "input_cost_per_1m": 1.50,
        "output_cost_per_1m": 7.50,
        "cache_read_cost_per_1m": 0.15,
        "supports_caching": True,
        "context_window": 1000000
    },
    "gemini-3.5-flash-lite": {
        "name": "Gemini 3.5 Flash-Lite",
        "provider": "Google Gemini",
        "input_cost_per_1m": 0.30,
        "output_cost_per_1m": 2.50,
        "cache_read_cost_per_1m": 0.075,
        "supports_caching": True,
        "context_window": 1000000
    },
    "gemini-1.5-flash": {
        "name": "Gemini 1.5 Flash",
        "provider": "Google Gemini",
        "input_cost_per_1m": 0.075,
        "output_cost_per_1m": 0.30,
        "cache_read_cost_per_1m": 0.01875,
        "supports_caching": True,
        "context_window": 1048576
    },
    "gemini-1.5-pro": {
        "name": "Gemini 1.5 Pro",
        "provider": "Google Gemini",
        "input_cost_per_1m": 1.25,
        "output_cost_per_1m": 5.00,
        "cache_read_cost_per_1m": 0.3125,
        "supports_caching": True,
        "context_window": 2097152
    },
    "claude-3-5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "cache_write_cost_per_1m": 3.75,
        "cache_read_cost_per_1m": 0.30,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-3-5-haiku": {
        "name": "Claude 3.5 Haiku",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
        "cache_write_cost_per_1m": 1.25,
        "cache_read_cost_per_1m": 0.10,
        "supports_caching": True,
        "context_window": 200000
    },
    "claude-3-opus": {
        "name": "Claude 3 Opus",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 15.00,
        "output_cost_per_1m": 75.00,
        "cache_write_cost_per_1m": 0.0,
        "cache_read_cost_per_1m": 0.0,
        "supports_caching": False,
        "context_window": 200000
    },
    "claude-fable-5": {
        "name": "Claude Fable 5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 10.00,
        "output_cost_per_1m": 50.00,
        "cache_write_cost_per_1m": 12.50,
        "cache_read_cost_per_1m": 1.00,
        "supports_caching": True,
        "context_window": 300000
    },
    "claude-sonnet-5": {
        "name": "Claude Sonnet 5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "cache_write_cost_per_1m": 3.75,
        "cache_read_cost_per_1m": 0.30,
        "supports_caching": True,
        "context_window": 300000
    },
    "claude-opus-4-8": {
        "name": "Claude Opus 4.8",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 15.00,
        "output_cost_per_1m": 75.00,
        "cache_write_cost_per_1m": 18.75,
        "cache_read_cost_per_1m": 1.50,
        "supports_caching": True,
        "context_window": 300000
    },
    "claude-haiku-4-5-20251001": {
        "name": "Claude Haiku 4.5",
        "provider": "Anthropic Claude",
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
        "cache_write_cost_per_1m": 1.25,
        "cache_read_cost_per_1m": 0.10,
        "supports_caching": True,
        "context_window": 300000
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
