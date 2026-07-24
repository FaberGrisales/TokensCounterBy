import unittest
import os
import sys
import shutil
import tempfile
import json

# Add package root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import calculate_call_cost, load_config
from tokens_counter.mcp_tools import execute_tool, safe_arithmetic_eval
from tokens_counter import session_monitor


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

    def test_safe_arithmetic_eval(self):
        """Test the AST-restricted arithmetic evaluator used by the 'calculate' MCP tool."""
        self.assertEqual(safe_arithmetic_eval("12 * (3 + 4)"), 84)
        self.assertEqual(safe_arithmetic_eval("10 / 2 - 1"), 4.0)

        # Anything beyond plain arithmetic must be rejected, not executed.
        with self.assertRaises(Exception):
            safe_arithmetic_eval("__import__('os').system('echo hi')")

    def test_execute_tool_calculate(self):
        """Test the 'calculate' local MCP demo tool dispatch."""
        result = execute_tool("calculate", {"expression": "2 + 2"})
        self.assertEqual(result["result"], 4)

        bad_result = execute_tool("calculate", {"expression": "not a number"})
        self.assertIn("error", bad_result)

    def test_execute_tool_unknown(self):
        """Test that unrecognized tool names return an error instead of raising."""
        result = execute_tool("nonexistent_tool", {})
        self.assertIn("error", result)

def _usage_line(model, input_tokens, output_tokens, cache_read=0, cache_write=0, timestamp="2026-01-01T00:00:00.000Z", cwd="/home/user/project"):
    return json.dumps({
        "type": "assistant",
        "timestamp": timestamp,
        "cwd": cwd,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write
            }
        }
    })


class TestSessionMonitor(unittest.TestCase):
    """Tests for session_monitor.py using a synthetic ~/.claude/projects tree, never the real one."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._prev_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.temp_dir
        self.config_data = load_config()

    def tearDown(self):
        if self._prev_config_dir is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._prev_config_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_session(self, project, session_id, lines, subagent_lines=None):
        project_dir = os.path.join(self.temp_dir, "projects", project)
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, f"{session_id}.jsonl"), "w") as f:
            f.write("\n".join(lines) + "\n")
        if subagent_lines:
            subagents_dir = os.path.join(project_dir, session_id, "subagents")
            os.makedirs(subagents_dir, exist_ok=True)
            with open(os.path.join(subagents_dir, "agent-1.jsonl"), "w") as f:
                f.write("\n".join(subagent_lines) + "\n")

    def test_get_all_sessions_basic_cost_and_activity(self):
        self._write_session("proj-a", "session1", [
            _usage_line("claude-3-5-sonnet", 10000, 2000, cache_read=8000)
        ])
        now = session_monitor._safe_mtime(list(session_monitor.get_claude_config_dir().glob("projects/proj-a/*.jsonl"))[0]) + 1
        sessions = session_monitor.get_all_sessions(self.config_data, now=now)

        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["main_requests"], 1)
        self.assertEqual(s["input_tokens"], 10000)
        self.assertAlmostEqual(s["cost"], calculate_call_cost("claude-3-5-sonnet", 10000, 2000, cached_read_tokens=8000))
        self.assertTrue(s["is_active"])

    def test_get_all_sessions_idle_when_stale(self):
        self._write_session("proj-b", "session2", [_usage_line("claude-3-5-sonnet", 100, 50)])
        far_future = session_monitor.time.time() + 10_000
        sessions = session_monitor.get_all_sessions(self.config_data, now=far_future)
        self.assertEqual(len(sessions), 1)
        self.assertFalse(sessions[0]["is_active"])

    def test_get_all_sessions_includes_subagent_usage(self):
        self._write_session(
            "proj-c", "session3",
            [_usage_line("claude-3-5-sonnet", 1000, 200)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100)]
        )
        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["main_requests"], 1)
        self.assertEqual(s["subagent_requests"], 1)
        self.assertEqual(s["subagent_count"], 1)
        # Totals must include both the main conversation and its subagent
        self.assertEqual(s["input_tokens"], 1500)
        self.assertEqual(s["output_tokens"], 300)

    def test_get_all_sessions_unpriced_model_returns_none_cost(self):
        self._write_session("proj-d", "session4", [_usage_line("some-unknown-future-model", 100, 50)])
        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0]["cost"])

    def test_get_all_sessions_ignores_malformed_lines(self):
        project_dir = os.path.join(self.temp_dir, "projects", "proj-e")
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, "session5.jsonl"), "w") as f:
            f.write("not valid json\n")
            f.write(_usage_line("claude-3-5-sonnet", 100, 50) + "\n")
            f.write("{}\n")

        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["main_requests"], 1)

    def test_get_all_sessions_empty_when_no_projects_dir(self):
        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertEqual(sessions, [])


if __name__ == "__main__":
    unittest.main()
