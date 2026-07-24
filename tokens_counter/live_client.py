import os
import json

from tokens_counter import mcp_tools

# Safe imports to prevent crashing if packages aren't installed
ANTHROPIC_AVAILABLE = False
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    pass

GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    pass


class LiveClientManager:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def is_gemini_ready(self):
        return GEMINI_AVAILABLE and bool(self.gemini_key)

    def is_anthropic_ready(self):
        return ANTHROPIC_AVAILABLE and bool(self.anthropic_key)

    def call_gemini(self, model_name, prompt, system_instruction=None, use_caching=False):
        """
        Calls Gemini API using the new google-genai SDK.
        Returns a dictionary with text, input_tokens, output_tokens, and cached_tokens.
        """
        if not GEMINI_AVAILABLE:
            raise ImportError("The 'google-genai' package is not installed. Run 'pip install google-genai' to use Live Mode.")
        if not self.gemini_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")

        # Initialize client
        client = genai.Client(api_key=self.gemini_key)

        config = {}
        if system_instruction:
            config["system_instruction"] = system_instruction
            
        # In Gemini 1.5/2.0/3.6, content caching is context-caching, which requires creating a cache resource first.
        # But we can also simulate standard metadata. Let's make a standard call.
        # To make a call:
        try:
            # We construct config object
            config_obj = types.GenerateContentConfig(**config) if config else None
            
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config_obj
            )
            
            # Extract usage metadata
            meta = response.usage_metadata
            input_tokens = meta.prompt_token_count if meta else 0
            output_tokens = meta.candidates_token_count if meta else 0
            cached_tokens = getattr(meta, "cached_content_token_count", 0) or 0
            
            return {
                "text": response.text or "",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_read_tokens": cached_tokens,
                "cached_write_tokens": 0, # Gemini handles write dynamically without extra fees (only charging standard input or read cached)
                "error": None
            }
        except Exception as e:
            return {
                "text": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "error": str(e)
            }

    def _build_prompt_content(self, prompt, use_caching):
        """Build the user message content block, tagging it for ephemeral caching if requested."""
        if use_caching:
            # To trigger caching, we tag the prompt block. Anthropic prompt caching requires >= 1024 tokens.
            # If prompt is short, we can still tag it, though it won't cache.
            return [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        return prompt

    def call_claude(self, model_name, prompt, system_instruction=None, use_caching=False):
        """
        Calls Anthropic API using anthropic SDK.
        Returns a dictionary with text, input_tokens, output_tokens, cache_read_tokens, and cache_write_tokens.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("The 'anthropic' package is not installed. Run 'pip install anthropic' to use Live Mode.")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

        client = anthropic.Anthropic(api_key=self.anthropic_key)

        try:
            # Build messages
            messages = [{"role": "user", "content": self._build_prompt_content(prompt, use_caching)}]

            kwargs = {
                "model": model_name,
                "max_tokens": 1024,
                "messages": messages
            }
            if system_instruction:
                kwargs["system"] = system_instruction

            response = client.messages.create(**kwargs)
            
            # Extract response text
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            # Extract token details from response.usage
            # Usage fields: input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_read_tokens": cache_read,
                "cached_write_tokens": cache_write,
                "error": None
            }
        except Exception as e:
            return {
                "text": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "error": str(e)
            }

    def call_claude_with_tools(self, model_name, prompt, system_instruction=None, use_caching=False,
                                mcp_server_url=None, mcp_server_token=None, max_turns=4):
        """
        Calls the real Anthropic API with tool-use/MCP enabled, looping through
        turns until the model stops requesting tools (or max_turns is hit).

        Two tool sources are supported:
          - Local demo tools (mcp_tools.py), executed client-side, used when no
            mcp_server_url is given.
          - A real remote MCP server (Anthropic's MCP connector beta), which the
            API calls and resolves server-side, when mcp_server_url is given.

        Returns a dict with aggregated real token usage across all turns, plus a
        'turns' list with the per-turn breakdown for detailed cost inspection.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("The 'anthropic' package is not installed. Run 'pip install anthropic' to use Live Mode.")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

        client = anthropic.Anthropic(api_key=self.anthropic_key)

        request_kwargs = {"model": model_name, "max_tokens": 1024}
        if system_instruction:
            request_kwargs["system"] = system_instruction

        using_remote_mcp = bool(mcp_server_url)
        if using_remote_mcp:
            mcp_server = {"type": "url", "url": mcp_server_url, "name": "remote-mcp-server"}
            if mcp_server_token:
                mcp_server["authorization_token"] = mcp_server_token
            request_kwargs["extra_body"] = {"mcp_servers": [mcp_server]}
            request_kwargs["extra_headers"] = {"anthropic-beta": "mcp-client-2025-04-04"}
        else:
            request_kwargs["tools"] = mcp_tools.TOOL_DEFINITIONS

        messages = [{"role": "user", "content": self._build_prompt_content(prompt, use_caching)}]
        turns = []
        final_text = ""
        aggregate = {"input_tokens": 0, "output_tokens": 0, "cached_read_tokens": 0, "cached_write_tokens": 0, "tool_calls": 0}

        try:
            for turn_index in range(max_turns):
                response = client.messages.create(messages=messages, **request_kwargs)

                usage = response.usage
                t_in = getattr(usage, "input_tokens", 0) or 0
                t_out = getattr(usage, "output_tokens", 0) or 0
                t_cr = getattr(usage, "cache_read_input_tokens", 0) or 0
                t_cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
                t_tool_calls = sum(1 for b in response.content if b.type in ("tool_use", "mcp_tool_use"))

                turns.append({
                    "turn": turn_index + 1,
                    "input_tokens": t_in,
                    "output_tokens": t_out,
                    "cached_read_tokens": t_cr,
                    "cached_write_tokens": t_cw,
                    "tool_calls": t_tool_calls,
                    "stop_reason": response.stop_reason
                })

                aggregate["input_tokens"] += t_in
                aggregate["output_tokens"] += t_out
                aggregate["cached_read_tokens"] += t_cr
                aggregate["cached_write_tokens"] += t_cw
                aggregate["tool_calls"] += t_tool_calls

                for block in response.content:
                    if block.type == "text":
                        final_text += block.text

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason != "tool_use":
                    break

                # Only client-defined "tool_use" blocks need local execution;
                # "mcp_tool_use"/"mcp_tool_result" blocks from a remote MCP
                # server are already resolved by the API itself.
                tool_results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(mcp_tools.execute_tool(block.name, block.input))
                    }
                    for block in response.content if block.type == "tool_use"
                ]
                if not tool_results:
                    break
                messages.append({"role": "user", "content": tool_results})

            return {
                "text": final_text,
                "input_tokens": aggregate["input_tokens"],
                "output_tokens": aggregate["output_tokens"],
                "cached_read_tokens": aggregate["cached_read_tokens"],
                "cached_write_tokens": aggregate["cached_write_tokens"],
                "tool_calls": aggregate["tool_calls"],
                "turns": turns,
                "used_remote_mcp": using_remote_mcp,
                "error": None
            }
        except Exception as e:
            return {
                "text": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "tool_calls": 0,
                "turns": turns,
                "used_remote_mcp": using_remote_mcp,
                "error": str(e)
            }
