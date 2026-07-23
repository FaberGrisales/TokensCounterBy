import os

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
            messages = []
            
            if use_caching:
                # To trigger caching, we tag the prompt block. Anthropic prompt caching requires >= 1024 tokens.
                # If prompt is short, we can still tag it, though it won't cache.
                content_block = [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            else:
                content_block = prompt

            messages.append({"role": "user", "content": content_block})

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
