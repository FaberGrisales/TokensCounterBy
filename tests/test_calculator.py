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
from tokens_counter import claude_config


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

    def test_get_all_sessions_exposes_by_model_breakdown(self):
        self._write_session(
            "proj-f", "session6",
            [_usage_line("claude-3-5-sonnet", 1000, 200)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100)]
        )
        sessions = session_monitor.get_all_sessions(self.config_data)
        by_model = sessions[0]["by_model"]
        self.assertEqual(by_model["claude-3-5-sonnet"]["input"], 1000)
        self.assertEqual(by_model["claude-3-5-haiku"]["input"], 500)

    def test_get_global_usage_summary_aggregates_by_model_and_project(self):
        self._write_session("proj-a", "session1", [_usage_line("claude-3-5-sonnet", 1000, 200, cwd="/home/user/proj-a")])
        self._write_session("proj-a", "session2", [_usage_line("claude-3-5-sonnet", 500, 100, cwd="/home/user/proj-a")])
        self._write_session("proj-b", "session3", [_usage_line("claude-3-5-haiku", 300, 50, cwd="/home/user/proj-b")])

        summary = session_monitor.get_global_usage_summary(self.config_data)

        self.assertEqual(summary["session_count"], 3)
        self.assertEqual(summary["total_requests"], 3)

        model_totals = {m["model"]: m for m in summary["usage_by_model"]}
        self.assertEqual(model_totals["claude-3-5-sonnet"]["input"], 1500)
        self.assertEqual(model_totals["claude-3-5-haiku"]["input"], 300)

        expected_cost = (
            calculate_call_cost("claude-3-5-sonnet", 1500, 300)
            + calculate_call_cost("claude-3-5-haiku", 300, 50)
        )
        self.assertAlmostEqual(summary["total_cost"], expected_cost)

        project_totals = {p["project"]: p for p in summary["projects"]}
        self.assertEqual(project_totals["proj-a"]["requests"], 2)
        self.assertEqual(project_totals["proj-a"]["input"], 1500)
        self.assertEqual(project_totals["proj-b"]["requests"], 1)

    def test_get_global_usage_summary_handles_unpriced_models(self):
        self._write_session("proj-g", "session7", [_usage_line("some-unknown-future-model", 100, 50)])
        summary = session_monitor.get_global_usage_summary(self.config_data)

        model_entry = summary["usage_by_model"][0]
        self.assertEqual(model_entry["model"], "some-unknown-future-model")
        self.assertIsNone(model_entry["cost"])
        self.assertIsNone(summary["projects"][0]["cost"])
        # Total cost stays None only if truly nothing was priced.
        self.assertIsNone(summary["total_cost"])

    def test_get_global_usage_summary_empty_when_no_sessions(self):
        summary = session_monitor.get_global_usage_summary(self.config_data)
        self.assertEqual(summary["session_count"], 0)
        self.assertEqual(summary["usage_by_model"], [])
        self.assertEqual(summary["projects"], [])
        self.assertIsNone(summary["total_cost"])

    def test_get_all_sessions_context_percent(self):
        self._write_session("proj-h", "session8", [
            _usage_line("claude-3-5-sonnet", 1000, 200, cache_read=5000, cache_write=2000)
        ])
        sessions = session_monitor.get_all_sessions(self.config_data)
        s = sessions[0]
        expected_used = 1000 + 5000 + 2000
        expected_window = self.config_data["claude-3-5-sonnet"]["context_window"]
        self.assertEqual(s["context_used_tokens"], expected_used)
        self.assertEqual(s["context_window"], expected_window)
        self.assertAlmostEqual(s["context_percent"], expected_used / expected_window * 100)

    def test_get_all_sessions_context_percent_none_for_unpriced_model(self):
        self._write_session("proj-i", "session9", [_usage_line("some-unknown-future-model", 100, 50)])
        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertIsNone(sessions[0]["context_percent"])
        self.assertIsNone(sessions[0]["context_window"])


class TestClaudeConfig(unittest.TestCase):
    """Tests for claude_config.py using synthetic project dirs / HOME, never the real ones."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "project")
        self.fake_home = os.path.join(self.temp_dir, "home")
        self.fake_claude_dir = os.path.join(self.temp_dir, "dot_claude")
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.fake_home, exist_ok=True)
        os.makedirs(self.fake_claude_dir, exist_ok=True)

        self._prev_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        self._prev_home = os.environ.get("HOME")
        os.environ["CLAUDE_CONFIG_DIR"] = self.fake_claude_dir
        os.environ["HOME"] = self.fake_home

    def tearDown(self):
        for var, prev in (("CLAUDE_CONFIG_DIR", self._prev_config_dir), ("HOME", self._prev_home)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_mcp_servers_reads_project_file(self):
        with open(os.path.join(self.project_dir, ".mcp.json"), "w") as f:
            json.dump({"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "pkg"]}}}, f)

        servers = claude_config.get_mcp_servers(project_dir=self.project_dir)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["name"], "filesystem")
        self.assertEqual(servers[0]["scope"], "project (.mcp.json)")

    def test_get_mcp_servers_reads_user_file_and_per_project_entry(self):
        with open(os.path.join(self.fake_home, ".claude.json"), "w") as f:
            json.dump({
                "mcpServers": {"global-tool": {"command": "global"}},
                "projects": {self.project_dir: {"mcpServers": {"scoped-tool": {"command": "scoped"}}}}
            }, f)

        servers = claude_config.get_mcp_servers(project_dir=self.project_dir)
        names = {s["name"] for s in servers}
        self.assertEqual(names, {"global-tool", "scoped-tool"})

    def test_get_mcp_servers_empty_when_no_config(self):
        self.assertEqual(claude_config.get_mcp_servers(project_dir=self.project_dir), [])

    def test_get_hooks_config_reads_project_and_user_settings(self):
        project_claude_dir = os.path.join(self.project_dir, ".claude")
        os.makedirs(project_claude_dir, exist_ok=True)
        with open(os.path.join(project_claude_dir, "settings.json"), "w") as f:
            json.dump({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}}, f)

        with open(os.path.join(self.fake_claude_dir, "settings.json"), "w") as f:
            json.dump({"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "a"}, {"type": "command", "command": "b"}]}]}}, f)

        hooks = claude_config.get_hooks_config(project_dir=self.project_dir)
        by_scope = {h["scope"]: h for h in hooks}
        self.assertEqual(by_scope["project"]["event"], "PreToolUse")
        self.assertEqual(by_scope["project"]["matcher"], "Bash")
        self.assertEqual(by_scope["project"]["command_count"], 1)
        self.assertEqual(by_scope["user"]["event"], "PostToolUse")
        self.assertEqual(by_scope["user"]["command_count"], 2)

    def test_get_hooks_config_empty_when_no_settings(self):
        self.assertEqual(claude_config.get_hooks_config(project_dir=self.project_dir), [])

    def test_get_subscription_status_reads_account_and_credentials(self):
        with open(os.path.join(self.fake_home, ".claude.json"), "w") as f:
            json.dump({
                "oauthAccount": {
                    "emailAddress": "dev@example.com",
                    "displayName": "Dev",
                    "organizationName": "Acme Corp",
                    "organizationType": "claude_team",
                    "seatTier": "team_standard",
                    "billingType": "stripe_subscription",
                    "hasExtraUsageEnabled": True,
                    "claudeCodeTrialEndsAt": None,
                    "subscriptionCreatedAt": "2026-01-01T00:00:00Z"
                }
            }, f)
        with open(os.path.join(self.fake_claude_dir, ".credentials.json"), "w") as f:
            json.dump({
                "claudeAiOauth": {
                    "accessToken": "should-never-be-read",
                    "refreshToken": "should-never-be-read-either",
                    "rateLimitTier": "default_raven",
                    "subscriptionType": "team"
                }
            }, f)

        status = claude_config.get_subscription_status()
        self.assertEqual(status["email"], "dev@example.com")
        self.assertEqual(status["organization_name"], "Acme Corp")
        self.assertEqual(status["organization_type"], "claude_team")
        self.assertEqual(status["rate_limit_tier"], "default_raven")
        self.assertEqual(status["subscription_type"], "team")
        self.assertTrue(status["has_extra_usage_enabled"])
        # Must never surface the actual tokens.
        self.assertNotIn("should-never-be-read", str(status))
        self.assertNotIn("accessToken", status)
        self.assertNotIn("refreshToken", status)

    def test_get_subscription_status_none_when_no_oauth_account(self):
        with open(os.path.join(self.fake_home, ".claude.json"), "w") as f:
            json.dump({"someOtherKey": True}, f)
        self.assertIsNone(claude_config.get_subscription_status())

    def test_get_subscription_status_none_when_no_claude_json(self):
        self.assertIsNone(claude_config.get_subscription_status())


if __name__ == "__main__":
    unittest.main()
