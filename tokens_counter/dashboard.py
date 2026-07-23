import csv
import os
from collections import defaultdict
from datetime import datetime

from tokens_counter.config import load_config

def parse_usage_csv(filepath):
    """
    Parses a CSV file containing LLM usage data.
    Expected columns (order-independent if headers match, or fallback indexing):
    Date, Model, Input Tokens, Output Tokens, Cache Read Tokens, Cache Write Tokens, Cost (USD)
    """
    if not os.path.exists(filepath):
        return None

    data = {
        "total_cost": 0.0,
        "total_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "by_model": defaultdict(lambda: {"cost": 0.0, "input": 0, "output": 0, "cache_read": 0}),
        "by_date": defaultdict(float),
        "total_saved_by_cache": 0.0
    }

    config = load_config()

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Standardize headers by stripping whitespace and lowercasing
            actual_headers = [h.strip().lower() for h in reader.fieldnames]
            
            for row in reader:
                # Map row to standardized keys
                row_clean = {k.strip().lower(): v for k, v in row.items()}
                
                # Extract values safely
                date_str = row_clean.get("date", "Unknown")
                model = row_clean.get("model", "unknown")
                
                try:
                    in_tokens = int(row_clean.get("input tokens", 0))
                    out_tokens = int(row_clean.get("output tokens", 0))
                    cr_tokens = int(row_clean.get("cache read tokens", 0))
                    cw_tokens = int(row_clean.get("cache write tokens", 0))
                    cost = float(row_clean.get("cost (usd)", 0.0))
                except ValueError:
                    continue
                
                # Aggregate totals
                data["total_cost"] += cost
                data["total_input"] += in_tokens
                data["total_output"] += out_tokens
                data["total_cache_read"] += cr_tokens
                data["total_cache_write"] += cw_tokens
                
                # Aggregate by model
                data["by_model"][model]["cost"] += cost
                data["by_model"][model]["input"] += in_tokens
                data["by_model"][model]["output"] += out_tokens
                data["by_model"][model]["cache_read"] += cr_tokens
                
                # Aggregate by date
                data["by_date"][date_str] += cost
                
                # Calculate Cache Savings
                m_cfg = config.get(model)
                if m_cfg and m_cfg.get("supports_caching"):
                    standard_rate = m_cfg.get("input_cost_per_1m", 0.0) / 1000000.0
                    cache_rate = m_cfg.get("cache_read_cost_per_1m", 0.0) / 1000000.0
                    # Savings = (Standard cost for those tokens) - (Discounted cache cost)
                    savings = cr_tokens * (standard_rate - cache_rate)
                    data["total_saved_by_cache"] += max(0.0, savings)

        # Sort date data chronologically
        sorted_dates = dict(sorted(data["by_date"].items()))
        data["by_date"] = sorted_dates

        # Sort models by cost descending
        data["by_model"] = dict(sorted(data["by_model"].items(), key=lambda item: item[1]["cost"], reverse=True))
        
        return data

    except Exception as e:
        return {"error": str(e)}
