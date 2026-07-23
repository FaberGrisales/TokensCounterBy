import unittest
import os
import sys
import shutil

# Add package root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import calculate_call_cost, load_config
from tokens_counter.history import log_call, get_totals, clear_history, get_high_scores
from tokens_counter.mcp_simulator import simulate_mcp_call, estimate_tokens_from_text


class TestTokensCalculator(unittest.TestCase):
    
    def test_cost_calculation_claude_no_cache(self):
        """Test basic Claude pricing without caching."""
        # Claude 3.5 Sonnet: Input = $3.00/1M, Output = $15.00/1M
        # 10,000 input, 2,000 output.
        # Expected input cost: 10,000 * 3 / 1,000,000 = $0.03
        # Expected output cost: 2,000 * 15 / 1,000,000 = $0.03
        # Total: $0.06
        cost = calculate_call_cost("claude-3-5-sonnet", 10000, 2000)
        self.assertAlmostEqual(cost, 0.06)
        
    def test_cost_calculation_claude_with_cache(self):
        """Test Claude caching calculation."""
        # Claude 3.5 Sonnet: 
        # input_cost_per_1m: 3.00, output_cost_per_1m: 15.00
        # cache_read_cost_per_1m: 0.30, cache_write_cost_per_1m: 3.75
        # Call with: 10,000 total input, where 8,000 read from cache, 0 write, 2,000 output.
        # Standard input tokens = 10,000 - 8,000 = 2,000 tokens
        # Standard input cost: 2,000 * 3 / 1M = $0.006
        # Cache read cost: 8,000 * 0.3 / 1M = $0.0024
        # Output cost: 2,000 * 15 / 1M = $0.03
        # Expected Total: 0.006 + 0.0024 + 0.03 = $0.0384
        cost = calculate_call_cost("claude-3-5-sonnet", 10000, 2000, cached_read_tokens=8000)
        self.assertAlmostEqual(cost, 0.0384)
        
    def test_cost_calculation_gemini(self):
        """Test basic Gemini pricing."""
        # Gemini 1.5 Flash: Input = $0.075/1M, Output = $0.30/1M
        # 100,000 input, 50,000 output
        # Expected input cost: 100,000 * 0.075 / 1M = $0.0075
        # Expected output cost: 50,000 * 0.30 / 1M = $0.015
        # Total: 0.0225
        cost = calculate_call_cost("gemini-1.5-flash", 100000, 50000)
        self.assertAlmostEqual(cost, 0.0225)

    def test_estimate_tokens(self):
        """Test estimation of token count from simple text."""
        text = "Hello world from the retro console app" # 7 words
        # 7 / 0.75 = 9.33 -> 9 tokens
        tokens = estimate_tokens_from_text(text)
        self.assertEqual(tokens, 9)
        
    def test_database_logging(self):
        """Test database storage and aggregation functions."""
        # Clear existing logs
        clear_history()
        
        # Log a call
        log_call(
            model="gemini-1.5-flash",
            prompt_summary="Test prompt details",
            mode="simulation",
            input_tokens=1000,
            output_tokens=500,
            total_cost=0.001,
            cached_read_tokens=0,
            cached_write_tokens=0
        )
        
        # Log another call
        log_call(
            model="claude-3-5-sonnet",
            prompt_summary="Second call test",
            mode="live",
            input_tokens=2000,
            output_tokens=1000,
            total_cost=0.02,
            cached_read_tokens=1000,
            cached_write_tokens=0
        )
        
        # Verify aggregates
        totals = get_totals()
        self.assertEqual(totals["total_calls"], 2)
        self.assertEqual(totals["total_input_tokens"], 3000)
        self.assertEqual(totals["total_output_tokens"], 1500)
        self.assertEqual(totals["total_cache_read_tokens"], 1000)
        self.assertAlmostEqual(totals["total_cost"], 0.021)
        
        # Verify high scores sorting
        scores = get_high_scores()
        self.assertEqual(len(scores), 2)
        # Claude (0.02) should be first, Gemini (0.001) second
        self.assertEqual(scores[0]["model"], "claude-3-5-sonnet")
        self.assertEqual(scores[1]["model"], "gemini-1.5-flash")
        
        # Wipe DB
        clear_history()
        totals_empty = get_totals()
        self.assertEqual(totals_empty["total_calls"], 0)

    def test_mcp_simulator(self):
        """Test MCP tool calling simulation calculations."""
        # Perform simulation on Claude 3.5 Sonnet with Filesystem operations preset
        results = simulate_mcp_call("claude-3-5-sonnet", "List files and search index.", "1")
        
        # Ensure all key properties are present
        self.assertIn("nocache", results)
        self.assertIn("cache", results)
        self.assertIn("savings_percentage", results)
        self.assertEqual(results["tool_count"], 3) # Filesystem is 3 tools
        
        # Verify no cache costs are larger than cache costs
        self.assertGreater(results["nocache"]["total_cost"], results["cache"]["total_cost"])
        self.assertGreater(results["savings_percentage"], 0.0)


if __name__ == "__main__":
    unittest.main()
