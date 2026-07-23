class McpToolPreset:
    def __init__(self, name, description, tool_count, schema_tokens, avg_result_tokens):
        self.name = name
        self.description = description
        self.tool_count = tool_count
        self.schema_tokens = schema_tokens
        self.avg_result_tokens = avg_result_tokens

PRESETS = {
    "1": McpToolPreset("Filesystem Operations", "Tools like read_file, write_file, list_dir", 3, 750, 2500),
    "2": McpToolPreset("Web Search & Browsing", "Tools like search_web, read_url_content", 2, 500, 1800),
    "3": McpToolPreset("Database Executor", "Tools like execute_query, list_tables", 2, 550, 1500),
    "4": McpToolPreset("Minimal Agent Tool", "A single simple ping or utility tool", 1, 200, 100),
}

def estimate_tokens_from_text(text):
    """Simple estimation of token count from text (roughly 4 chars per token, or 1 token per 0.75 words)."""
    words = text.split()
    return int(len(words) / 0.75) if words else 0

def simulate_mcp_call(model_key, prompt_text, preset_key, custom_tool_count=0, custom_schema_tokens=0, custom_payload_tokens=0, use_caching=False):
    """
    Simulate a multi-turn MCP call sequence:
    Turn 1:
      - Input: User Prompt + Tool declarations schema
      - Output: Model decides to call a tool (Tool Call request)
    Turn 2:
      - Input: User Prompt + Tool declarations schema + Tool call request + Tool result payload
      - Output: Final response from the model
      
    Returns a dictionary breaking down tokens and costs for cached vs non-cached scenarios.
    """
    # 1. Base tokens estimation
    prompt_tokens = estimate_tokens_from_text(prompt_text)
    
    # 2. Tool schema overhead
    if preset_key == "custom":
        tool_count = custom_tool_count
        schema_tokens = custom_schema_tokens
        payload_tokens = custom_payload_tokens
        preset_name = "Custom Configuration"
    else:
        preset = PRESETS.get(preset_key, PRESETS["4"])
        tool_count = preset.tool_count
        schema_tokens = preset.schema_tokens
        payload_tokens = preset.avg_result_tokens
        preset_name = preset.name

    # 3. Model outputs estimation
    tool_call_request_tokens = 80  # Typical JSON schema for tool call
    final_response_tokens = 350    # Typical final answer size

    # 4. Scenario A: WITHOUT Caching (History is sent repeatedly)
    # Turn 1:
    turn1_in_nocache = prompt_tokens + schema_tokens
    turn1_out_nocache = tool_call_request_tokens
    
    # Turn 2:
    # Input is the full history: Prompt + Schema + Tool Call + Tool Result
    turn2_in_nocache = prompt_tokens + schema_tokens + tool_call_request_tokens + payload_tokens
    turn2_out_nocache = final_response_tokens
    
    total_in_nocache = turn1_in_nocache + turn2_in_nocache
    total_out_nocache = turn1_out_nocache + turn2_out_nocache

    # Scenario B: WITH Caching (Claude Ephemeral Cache or Gemini Context Cache)
    # Turn 1:
    # First turn writes the cache (Prompt + Schema are cached)
    turn1_in_cache = prompt_tokens + schema_tokens
    turn1_out_cache = tool_call_request_tokens
    
    # Turn 2:
    # The Prompt + Schema are read from cache.
    # The new input tokens (Tool Call + Tool Result) are charged as regular input tokens.
    cache_read_tokens = prompt_tokens + schema_tokens
    cache_write_tokens = 0
    
    # For Anthropic, cache write fees apply when writing the cache in Turn 1.
    # For Gemini, cache is written automatically, no special write fee (standard input rate applies, but read gets discount).
    # We will log the cache read/write tokens and let config.py compute the correct pricing.
    turn2_in_cache = tool_call_request_tokens + payload_tokens
    turn2_out_cache = final_response_tokens
    
    total_in_cache = turn1_in_cache + turn2_in_cache
    total_out_cache = turn1_out_cache + turn2_out_cache

    from tokens_counter.config import calculate_call_cost

    # Calculate Costs
    cost_nocache = calculate_call_cost(model_key, total_in_nocache, total_out_nocache)
    
    # Cost with cache:
    # Turn 1:
    # For Anthropic (Claude), Turn 1 writes to cache. So those tokens are "cached_write_tokens".
    # For Gemini, Turn 1 is just standard input.
    is_anthropic = model_key.startswith("claude")
    
    t1_write_tokens = turn1_in_cache if is_anthropic else 0
    t1_cost = calculate_call_cost(model_key, turn1_in_cache, turn1_out_cache, cached_write_tokens=t1_write_tokens)
    
    # Turn 2:
    # In turn 2, the cached tokens are read.
    t2_cost = calculate_call_cost(model_key, turn2_in_cache + cache_read_tokens, turn2_out_cache, cached_read_tokens=cache_read_tokens)
    
    cost_with_cache = t1_cost + t2_cost

    return {
        "preset_name": preset_name,
        "tool_count": tool_count,
        "prompt_tokens": prompt_tokens,
        "schema_tokens": schema_tokens,
        "payload_tokens": payload_tokens,
        "tool_call_request_tokens": tool_call_request_tokens,
        "final_response_tokens": final_response_tokens,
        
        # No Cache Breakdown
        "nocache": {
            "turn1_input": turn1_in_nocache,
            "turn1_output": turn1_out_nocache,
            "turn2_input": turn2_in_nocache,
            "turn2_output": turn2_out_nocache,
            "total_input": total_in_nocache,
            "total_output": total_out_nocache,
            "total_cost": cost_nocache
        },
        
        # Cache Breakdown
        "cache": {
            "turn1_input": turn1_in_cache,
            "turn1_output": turn1_out_cache,
            "turn2_input": turn2_in_cache,
            "turn2_output": turn2_out_cache,
            "cached_read_tokens": cache_read_tokens,
            "cached_write_tokens": turn1_in_cache if is_anthropic else 0,
            "total_input": total_in_cache + cache_read_tokens,
            "total_output": total_out_cache,
            "total_cost": cost_with_cache
        },
        
        # Cost saving details
        "savings_percentage": ((cost_nocache - cost_with_cache) / cost_nocache * 100) if cost_nocache > 0 else 0.0
    }
