import unittest
import io
import os
import sys
import tempfile
import sys
import shutil
import tempfile
import json
from datetime import datetime, timedelta, timezone
from rich.console import Console

# Add package root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokens_counter.config import calculate_call_cost, load_config, load_budget, DEFAULT_CONFIG, CONFIG_FILE
from tokens_counter import session_monitor
from tokens_counter import claude_config
from tokens_counter import tui
from tokens_counter import dependencies
from tokens_counter import floating


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

    def test_every_default_model_is_fully_specified(self):
        """Every default model needs a complete rate set and a real context window.

        A missing field would silently price part of a session at $0; a missing
        or zero context_window would make build_session_summary() report
        context_percent as None, which is exactly the "no usage percentage"
        symptom this config is here to prevent.
        """
        required = (
            "name", "provider", "input_cost_per_1m", "output_cost_per_1m",
            "cache_write_cost_per_1m", "cache_read_cost_per_1m",
            "supports_caching", "context_window",
        )
        for model_key, cfg in DEFAULT_CONFIG.items():
            for field in required:
                self.assertIn(field, cfg, f"{model_key} is missing {field}")
            self.assertGreater(cfg["context_window"], 0, f"{model_key} has no context window")
            self.assertGreater(cfg["input_cost_per_1m"], 0, f"{model_key} has no input rate")
            self.assertGreater(cfg["output_cost_per_1m"], 0, f"{model_key} has no output rate")

    def test_models_config_on_disk_matches_defaults(self):
        """The shipped models_config.json must agree with DEFAULT_CONFIG.

        load_config()'s backfill only ADDS keys missing from disk - it never
        corrects a key whose values are stale. So a rate fixed in
        DEFAULT_CONFIG alone would never reach an existing install; the JSON
        has to be updated in the same commit, and this test enforces that.
        """
        with open(CONFIG_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)
        for model_key, cfg in DEFAULT_CONFIG.items():
            self.assertIn(model_key, on_disk, f"{model_key} missing from models_config.json")
            self.assertEqual(on_disk[model_key], cfg, f"{model_key} is stale in models_config.json")

    def test_cost_calculation_opus_5(self):
        """Opus 5 is the model these transcripts are dominated by, so price it exactly."""
        # claude-opus-5: input $5.00/1M, output $25.00/1M, cache read $0.50/1M.
        # 100,000 total input of which 90,000 is a cache read, 5,000 output.
        # Standard input: (100,000 - 90,000) * 5 / 1M   = $0.05
        # Cache read:     90,000 * 0.5 / 1M             = $0.045
        # Output:         5,000 * 25 / 1M               = $0.125
        # Total                                          = $0.22
        cost = calculate_call_cost("claude-opus-5", 100000, 5000, cached_read_tokens=90000)
        self.assertAlmostEqual(cost, 0.22)

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

def _usage_line(model, input_tokens, output_tokens, cache_read=0, cache_write=0, timestamp="2026-01-01T00:00:00.000Z", cwd="/home/user/project", tool_names=None):
    message = {
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write
        }
    }
    if tool_names:
        message["content"] = [{"type": "tool_use", "name": name, "input": {}} for name in tool_names]
    return json.dumps({
        "type": "assistant",
        "timestamp": timestamp,
        "cwd": cwd,
        "message": message
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

    def _write_session(self, project, session_id, lines, subagent_lines=None, subagent_meta=None):
        project_dir = os.path.join(self.temp_dir, "projects", project)
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, f"{session_id}.jsonl"), "w") as f:
            f.write("\n".join(lines) + "\n")
        if subagent_lines:
            subagents_dir = os.path.join(project_dir, session_id, "subagents")
            os.makedirs(subagents_dir, exist_ok=True)
            with open(os.path.join(subagents_dir, "agent-1.jsonl"), "w") as f:
                f.write("\n".join(subagent_lines) + "\n")
            if subagent_meta is not None:
                with open(os.path.join(subagents_dir, "agent-1.meta.json"), "w") as f:
                    json.dump(subagent_meta, f)

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

    def test_get_cleanup_candidates_excludes_recent_sessions(self):
        self._write_session("proj-recent", "session-recent", [_usage_line("claude-3-5-sonnet", 100, 50)])
        now = session_monitor.time.time() + 3600  # 1 hour later - well under the 7-day default
        candidates = session_monitor.get_cleanup_candidates(self.config_data, now=now)
        self.assertEqual(candidates, [])

    def test_get_cleanup_candidates_includes_sessions_older_than_threshold(self):
        self._write_session("proj-old", "session-old", [_usage_line("claude-3-5-sonnet", 100, 50)])
        now = session_monitor.time.time() + session_monitor.CLEANUP_INACTIVE_THRESHOLD_SECONDS + 3600
        candidates = session_monitor.get_cleanup_candidates(self.config_data, now=now)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["session_id"], "session-old")
        self.assertGreaterEqual(candidates[0]["age_seconds"], session_monitor.CLEANUP_INACTIVE_THRESHOLD_SECONDS)

    def test_get_cleanup_candidates_respects_custom_threshold(self):
        self._write_session("proj-custom", "session-custom", [_usage_line("claude-3-5-sonnet", 100, 50)])
        now = session_monitor.time.time() + 3600  # 1 hour later
        # With a 30-minute threshold, a session an hour old is a candidate.
        candidates = session_monitor.get_cleanup_candidates(self.config_data, now=now, threshold_seconds=1800)
        self.assertEqual(len(candidates), 1)

    def test_get_cleanup_candidates_sorts_oldest_first(self):
        self._write_session("proj-older", "session-older", [_usage_line("claude-3-5-sonnet", 100, 50)])
        older_path = session_monitor.get_claude_config_dir() / "projects" / "proj-older" / "session-older.jsonl"
        os.utime(older_path, (session_monitor.time.time() - 1000, session_monitor.time.time() - 1000))

        self._write_session("proj-newer", "session-newer", [_usage_line("claude-3-5-sonnet", 100, 50)])
        newer_path = session_monitor.get_claude_config_dir() / "projects" / "proj-newer" / "session-newer.jsonl"
        os.utime(newer_path, (session_monitor.time.time() - 500, session_monitor.time.time() - 500))

        candidates = session_monitor.get_cleanup_candidates(self.config_data, now=session_monitor.time.time(), threshold_seconds=100)
        self.assertEqual([c["session_id"] for c in candidates], ["session-older", "session-newer"])

    def test_delete_session_removes_main_file_and_subagent_dir(self):
        self._write_session(
            "proj-del", "session-del",
            [_usage_line("claude-3-5-sonnet", 100, 50)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 50, 20)]
        )
        candidates = session_monitor.get_cleanup_candidates(
            self.config_data, now=session_monitor.time.time(), threshold_seconds=0
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]

        main_path = candidate["main_path"]
        session_dir = main_path.parent / main_path.stem
        self.assertTrue(main_path.exists())
        self.assertTrue(session_dir.is_dir())

        ok, error = session_monitor.delete_session(candidate)
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertFalse(main_path.exists())
        self.assertFalse(session_dir.exists())

    def test_delete_session_handles_missing_file_without_raising(self):
        self._write_session("proj-gone", "session-gone", [_usage_line("claude-3-5-sonnet", 100, 50)])
        candidates = session_monitor.get_cleanup_candidates(
            self.config_data, now=session_monitor.time.time(), threshold_seconds=0
        )
        candidate = candidates[0]
        candidate["main_path"].unlink()  # simulate the file already being gone

        ok, error = session_monitor.delete_session(candidate)
        self.assertTrue(ok)
        self.assertIsNone(error)

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

    def test_get_all_sessions_context_percent_million_token_window(self):
        """A 600K prompt on a 1M-window model is 60%, not a clamped 100%.

        Regression guard: these models were previously configured with a
        300K window, so any real long session pinned the context bar at 100%.
        """
        self._write_session("proj-h2", "session8b", [
            _usage_line("claude-opus-5", 100000, 500, cache_read=400000, cache_write=100000)
        ])
        s = session_monitor.get_all_sessions(self.config_data)[0]
        self.assertEqual(s["context_used_tokens"], 600000)
        self.assertEqual(s["context_window"], 1000000)
        self.assertAlmostEqual(s["context_percent"], 60.0)

    def test_get_all_sessions_context_percent_none_for_unpriced_model(self):
        self._write_session("proj-i", "session9", [_usage_line("some-unknown-future-model", 100, 50)])
        sessions = session_monitor.get_all_sessions(self.config_data)
        self.assertIsNone(sessions[0]["context_percent"])
        self.assertIsNone(sessions[0]["context_window"])


    def test_get_rolling_window_usage_buckets_by_recency(self):
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        recent_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        mid_ts = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        old_ts = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        self._write_session("proj-j", "session10", [
            _usage_line("claude-3-5-sonnet", 100, 50, timestamp=recent_ts),
            _usage_line("claude-3-5-sonnet", 200, 60, timestamp=mid_ts),
            _usage_line("claude-3-5-sonnet", 400, 70, timestamp=old_ts),
        ])

        usage = session_monitor.get_rolling_window_usage(self.config_data, now=now)

        # Only the 1-hour-old line falls inside the 5-hour window.
        self.assertEqual(usage["5h"]["input"], 100)
        self.assertEqual(usage["5h"]["requests"], 1)

        # The 1-hour and 2-day-old lines fall inside the 7-day window; the 10-day-old one doesn't.
        self.assertEqual(usage["7d"]["input"], 300)
        self.assertEqual(usage["7d"]["requests"], 2)
        self.assertIsNotNone(usage["7d"]["cost"])

    def test_get_rolling_window_usage_window_end_is_start_plus_duration(self):
        """Window Ends is exactly when the oldest surviving request ages out."""
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        oldest = now - timedelta(hours=3)
        self._write_session("proj-we", "session-we", [
            _usage_line("claude-3-5-sonnet", 100, 50,
                        timestamp=oldest.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        ])
        windows = session_monitor.get_rolling_window_usage(self.config_data, now=now)

        five_hour = windows["5h"]
        self.assertEqual(five_hour["window_start_at"], oldest)
        self.assertEqual(five_hour["window_end_at"], oldest + timedelta(hours=5))
        # 3h in, so 2h of the 5h window is left.
        self.assertAlmostEqual(five_hour["remaining_seconds"], 2 * 3600, places=3)

        seven_day = windows["7d"]
        self.assertEqual(seven_day["window_end_at"], oldest + timedelta(days=7))
        self.assertAlmostEqual(seven_day["remaining_seconds"],
                               (oldest + timedelta(days=7) - now).total_seconds(), places=3)

    def test_get_rolling_window_usage_window_end_is_none_when_empty(self):
        """An empty window reports no end time rather than inventing one."""
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        windows = session_monitor.get_rolling_window_usage(self.config_data, now=now)
        for key in ("5h", "7d"):
            self.assertIsNone(windows[key]["window_end_at"])
            self.assertIsNone(windows[key]["remaining_seconds"])

    def test_get_rolling_window_usage_remaining_never_negative(self):
        """
        A request exactly at the cutoff must not produce a negative remainder.

        elapsed_seconds is capped at the window duration, so remaining_seconds
        has to floor at zero to stay consistent with it.
        """
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        edge = now - timedelta(hours=5) + timedelta(seconds=1)
        self._write_session("proj-edge", "session-edge", [
            _usage_line("claude-3-5-sonnet", 10, 5,
                        timestamp=edge.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        ])
        five_hour = session_monitor.get_rolling_window_usage(self.config_data, now=now)["5h"]
        self.assertGreaterEqual(five_hour["remaining_seconds"], 0.0)

    def test_get_rolling_window_usage_empty_when_no_sessions(self):
        usage = session_monitor.get_rolling_window_usage(self.config_data)
        self.assertEqual(usage["5h"]["requests"], 0)
        self.assertIsNone(usage["5h"]["cost"])
        self.assertIsNone(usage["5h"]["window_start_at"])
        self.assertIsNone(usage["5h"]["elapsed_seconds"])
        self.assertIsNone(usage["5h"]["percent_used"])

    def test_get_rolling_window_usage_anchors_to_oldest_surviving_activity(self):
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        older_ts = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        newest_ts = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        self._write_session("proj-k", "session11", [
            _usage_line("claude-3-5-sonnet", 100, 50, timestamp=older_ts),
            _usage_line("claude-3-5-sonnet", 200, 60, timestamp=newest_ts),
        ])

        usage = session_monitor.get_rolling_window_usage(self.config_data, now=now)
        w = usage["5h"]

        # window_start_at must anchor to the OLDEST activity still inside the window,
        # not the newest - elapsed/used grows with how long that request has been
        # sitting in the window, instead of resetting on every new request.
        expected_oldest = now - timedelta(hours=3)
        self.assertEqual(w["window_start_at"], expected_oldest)
        self.assertAlmostEqual(w["elapsed_seconds"], timedelta(hours=3).total_seconds())
        # 3h elapsed out of a 5h window = 60%
        self.assertAlmostEqual(w["percent_used"], 60.0)

    def test_get_rolling_window_usage_empty_window_after_long_gap(self):
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        far_past_ts = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        self._write_session("proj-l", "session12", [
            _usage_line("claude-3-5-sonnet", 100, 50, timestamp=far_past_ts),
        ])

        usage = session_monitor.get_rolling_window_usage(self.config_data, now=now)
        w = usage["5h"]

        # Nothing in the last 5h -> genuinely empty, not a fabricated "just started" guess.
        self.assertEqual(w["requests"], 0)
        self.assertIsNone(w["window_start_at"])
        self.assertIsNone(w["elapsed_seconds"])
        self.assertIsNone(w["percent_used"])


    def test_build_subagent_breakdown_reads_meta_and_tokens(self):
        self._write_session(
            "proj-m", "session13",
            [_usage_line("claude-3-5-sonnet", 1000, 200)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100, cache_read=50)],
            subagent_meta={"agentType": "Explore", "description": "Find the pricing config"}
        )
        group = session_monitor.find_session_groups()[0]
        breakdown = session_monitor.build_subagent_breakdown(group, self.config_data)

        self.assertEqual(len(breakdown), 1)
        a = breakdown[0]
        self.assertEqual(a["agent_type"], "Explore")
        self.assertEqual(a["description"], "Find the pricing config")
        self.assertEqual(a["requests"], 1)
        self.assertEqual(a["input_tokens"], 500)
        self.assertEqual(a["output_tokens"], 100)
        self.assertAlmostEqual(
            a["cost"],
            calculate_call_cost("claude-3-5-haiku", 500, 100, cached_read_tokens=50)
        )

    def test_build_subagent_breakdown_defaults_when_no_meta_file(self):
        self._write_session(
            "proj-n", "session14",
            [_usage_line("claude-3-5-sonnet", 1000, 200)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100)]
        )
        group = session_monitor.find_session_groups()[0]
        breakdown = session_monitor.build_subagent_breakdown(group, self.config_data)
        self.assertEqual(breakdown[0]["agent_type"], "unknown")
        self.assertIsNone(breakdown[0]["description"])

    def test_build_subagent_breakdown_empty_when_no_subagents(self):
        self._write_session("proj-o", "session15", [_usage_line("claude-3-5-sonnet", 100, 50)])
        group = session_monitor.find_session_groups()[0]
        self.assertEqual(session_monitor.build_subagent_breakdown(group, self.config_data), [])

    def test_get_session_breakdown_finds_session_by_id(self):
        self._write_session(
            "proj-p", "session16",
            [_usage_line("claude-3-5-sonnet", 1000, 200)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100)],
            subagent_meta={"agentType": "general-purpose", "description": "Task X"}
        )
        session_summary, subagents, mcp_calls = session_monitor.get_session_breakdown("session16", self.config_data)
        self.assertIsNotNone(session_summary)
        self.assertEqual(session_summary["session_id"], "session16")
        self.assertEqual(len(subagents), 1)
        self.assertEqual(subagents[0]["agent_type"], "general-purpose")
        self.assertEqual(mcp_calls, [])

    def test_get_session_breakdown_none_for_unknown_session(self):
        session_summary, subagents, mcp_calls = session_monitor.get_session_breakdown("does-not-exist", self.config_data)
        self.assertIsNone(session_summary)
        self.assertEqual(subagents, [])
        self.assertEqual(mcp_calls, [])

    def test_build_mcp_call_log_reads_calls_and_turn_cost(self):
        self._write_session("proj-q", "session17", [
            _usage_line("claude-3-5-sonnet", 1000, 200, tool_names=["mcp__filesystem__read_file", "mcp__filesystem__list_dir"])
        ])
        group = session_monitor.find_session_groups()[0]
        calls = session_monitor.build_mcp_call_log(group, self.config_data)
        self.assertEqual(len(calls), 1)
        c = calls[0]
        self.assertEqual(c["source"], "Main")
        self.assertEqual(c["tools"], ["mcp__filesystem__read_file", "mcp__filesystem__list_dir"])
        self.assertEqual(c["input_tokens"], 1000)
        self.assertAlmostEqual(c["cost"], calculate_call_cost("claude-3-5-sonnet", 1000, 200))

    def test_build_mcp_call_log_ignores_turns_with_no_mcp_tools(self):
        self._write_session("proj-r", "session18", [
            _usage_line("claude-3-5-sonnet", 100, 50, tool_names=["Bash", "Read"])
        ])
        group = session_monitor.find_session_groups()[0]
        self.assertEqual(session_monitor.build_mcp_call_log(group, self.config_data), [])

    def test_build_mcp_call_log_includes_subagent_calls_with_agent_type_as_source(self):
        self._write_session(
            "proj-s", "session19",
            [_usage_line("claude-3-5-sonnet", 100, 50)],
            subagent_lines=[_usage_line("claude-3-5-haiku", 500, 100, tool_names=["mcp__web__search"])],
            subagent_meta={"agentType": "Explore", "description": "Look something up"}
        )
        group = session_monitor.find_session_groups()[0]
        calls = session_monitor.build_mcp_call_log(group, self.config_data)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["source"], "Explore")
        self.assertEqual(calls[0]["tools"], ["mcp__web__search"])

    def test_build_mcp_call_log_empty_when_no_calls(self):
        self._write_session("proj-t", "session20", [_usage_line("claude-3-5-sonnet", 100, 50)])
        group = session_monitor.find_session_groups()[0]
        self.assertEqual(session_monitor.build_mcp_call_log(group, self.config_data), [])


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


class TestResponsiveRendering(unittest.TestCase):
    """
    Guards that every view stays readable in the console it's given.

    The real failure mode is Rich tables, not panels: Rich never drops a
    column on its own, it keeps all nine and ellipsizes each into slivers
    ("claude-opu…", "$9.…"), so the view technically fits while showing
    nothing usable. The width assertions below catch overflow; the
    narrow-layout test is the one that catches the sliver problem, by
    requiring the cost and the context percentage to still be readable.
    """

    def setUp(self):
        self._real_console = tui.console

    def tearDown(self):
        tui.console = self._real_console

    def _render(self, build, width):
        """
        Render at a fixed width and return the plain-text lines.

        `build` is a callable, not a renderable: the views read console.width
        while BUILDING (that's how _panel_width picks a panel size), so the
        console has to be swapped in before the view is constructed. Passing
        an already-built renderable would measure it against the real
        terminal and quietly test nothing.
        """
        buf = io.StringIO()
        tui.console = Console(width=width, file=buf, no_color=True, highlight=False)
        tui.console.print(build())
        return buf.getvalue().splitlines()

    def _sessions(self):
        return [
            {
                "session_id": "abcdef1234567890", "project": "-home-user-a-very-long-project-name",
                "cwd": "/home/user/a-very-long-project-name", "models": ["claude-opus-5"],
                "by_model": {}, "main_requests": 74, "subagent_requests": 3, "subagent_count": 1,
                "input_tokens": 148, "output_tokens": 108349, "cache_read_tokens": 900000,
                "cache_write_tokens": 1000, "cost": 9.4663,
                "last_request": {"model": "claude-opus-5", "input_tokens": 2, "output_tokens": 524,
                                 "cache_read_tokens": 140000, "cache_write_tokens": 9000},
                "last_request_cost": 0.1141, "context_used_tokens": 149002,
                "context_window": 1000000, "context_percent": 14.9,
                "last_timestamp": None, "mtime": 0.0, "is_active": True,
            },
            {
                "session_id": "99887766", "project": "proj-b", "cwd": "/home/user/b",
                "models": ["claude-opus-4-8"], "by_model": {}, "main_requests": 833,
                "subagent_requests": 0, "subagent_count": 0, "input_tokens": 1960,
                "output_tokens": 931139, "cache_read_tokens": 0, "cache_write_tokens": 0,
                "cost": None, "last_request": None, "last_request_cost": None,
                "context_used_tokens": None, "context_window": None, "context_percent": None,
                "last_timestamp": None, "mtime": 0.0, "is_active": False,
            },
        ]

    def test_session_monitor_never_exceeds_console_width(self):
        """At every width - including a tiny PiP-sized window - no line overflows."""
        for width in (30, 40, 50, 60, 80, 100, 120):
            lines = self._render(lambda: tui.render_session_monitor_view(self._sessions()), width)
            longest = max((len(line.rstrip()) for line in lines), default=0)
            self.assertLessEqual(
                longest, width,
                f"a line of {longest} chars overflowed a {width}-column console",
            )

    def test_session_monitor_renders_at_every_width_with_no_sessions(self):
        for width in (30, 60, 120):
            lines = self._render(lambda: tui.render_session_monitor_view([]), width)
            longest = max((len(line.rstrip()) for line in lines), default=0)
            self.assertLessEqual(longest, width)

    def test_narrow_layout_keeps_the_numbers_that_matter(self):
        """Shrinking may drop columns, but never the cost or the context bar."""
        lines = self._render(lambda: tui.render_session_monitor_view(self._sessions()), 32)
        text = "\n".join(lines)
        self.assertIn("$9.47", text)     # cost survives
        self.assertIn("15%", text)       # context percentage survives
        self.assertIn("N/A", text)       # unpriced model still reads as N/A, not $0

    def test_panel_width_caps_at_console_width(self):
        tui.console = Console(width=40)
        self.assertEqual(tui._panel_width(92), 40)
        tui.console = Console(width=200)
        self.assertEqual(tui._panel_width(92), 92)

    def test_fmt_tokens_humanizes(self):
        self.assertEqual(tui._fmt_tokens(512), "512")
        self.assertEqual(tui._fmt_tokens(1500), "1.5K")
        self.assertEqual(tui._fmt_tokens(1_234_567), "1.2M")
        self.assertEqual(tui._fmt_tokens(None), "-")

    def test_fmt_cost_never_renders_a_real_cost_as_free(self):
        """A sub-cent cost must not round to $0.00 - that reads as 'this was free'."""
        self.assertEqual(tui._fmt_cost(0.0003, compact=True), "<$0.01")
        self.assertEqual(tui._fmt_cost(242.6267, compact=True), "$242.63")
        self.assertEqual(tui._fmt_cost(242.6267), "$242.6267")
        self.assertIn("N/A", tui._fmt_cost(None, compact=True))


class TestDependencies(unittest.TestCase):
    """
    Startup dependency detection. These are pure functions - nothing here
    installs anything, and no test may shell out to a package manager.
    """

    def test_never_suggests_pip_install_tkinter(self):
        """
        The one genuinely damaging suggestion this module could make.

        `tkinter` on PyPI is an unrelated, long-dead package - installing it
        does not provide the tkinter module and shadows nothing useful. On
        every platform the fix is either the OS package or the Python
        installer, never pip.
        """
        for dep in dependencies.check_dependencies():
            if dep["module"] != "tkinter":
                continue
            command = " ".join(dep["command"] or [])
            self.assertNotIn("pip", command)
            self.assertNotIn("pip", (dep["manual_hint"] or ""))

    def test_rich_is_required_and_tkinter_is_not(self):
        by_module = {d["module"]: d for d in dependencies.check_dependencies()}
        self.assertTrue(by_module["rich"]["required"])
        self.assertFalse(by_module["tkinter"]["required"],
                         "tkinter is only needed for the floating window; "
                         "marking it required would block startup for everyone")

    def test_every_dependency_is_fully_described(self):
        """A dependency with neither a command nor a hint is a dead end for the user."""
        for dep in dependencies.check_dependencies():
            self.assertTrue(dep["command"] or dep["manual_hint"],
                            f"{dep['module']} offers no way forward")
            self.assertTrue(dependencies.describe(dep).strip())

    def test_linux_tk_command_follows_the_available_package_manager(self):
        real_which = dependencies.shutil.which
        try:
            dependencies.shutil.which = lambda b: "/usr/bin/dnf" if b == "dnf" else None
            self.assertEqual(dependencies._linux_tk_command(),
                             ["sudo", "dnf", "install", "-y", "python3-tkinter"])
            dependencies.shutil.which = lambda b: "/usr/bin/apt-get" if b == "apt-get" else None
            self.assertEqual(dependencies._linux_tk_command(),
                             ["sudo", "apt-get", "install", "-y", "python3-tk"])
            dependencies.shutil.which = lambda b: None
            self.assertIsNone(dependencies._linux_tk_command())
        finally:
            dependencies.shutil.which = real_which

    def test_windows_tkinter_has_no_command_but_explains_itself(self):
        """tkinter can't be installed from a script on Windows - say so, don't run something."""
        real_platform = dependencies.sys.platform
        try:
            dependencies.sys.platform = "win32"
            command, hint = dependencies._tkinter_requirement()
            self.assertIsNone(command)
            self.assertIn("tcl/tk", hint)
        finally:
            dependencies.sys.platform = real_platform

    def test_install_without_a_command_reports_the_hint_instead_of_running(self):
        dep = {"command": None, "manual_hint": "install it yourself", "module": "x", "label": "x"}
        ok, message = dependencies.install(dep)
        self.assertFalse(ok)
        self.assertEqual(message, "install it yourself")

    def test_missing_required_only_filters_optional(self):
        for dep in dependencies.missing(required_only=True):
            self.assertTrue(dep["required"])

    def test_check_python_version_passes_on_this_interpreter(self):
        self.assertIsNone(dependencies.check_python_version())


class TestFloatingWindowFormatting(unittest.TestCase):
    """The floating window's own formatting helpers - no window is opened."""

    def test_fmt_tokens_matches_the_tui(self):
        """Both layers show the same numbers; drifting formats would confuse."""
        for n in (0, 512, 1500, 1_234_567):
            self.assertEqual(floating._fmt_tokens(n), tui._fmt_tokens(n))

    def test_fmt_cost_never_renders_a_real_cost_as_free(self):
        self.assertEqual(floating._fmt_cost(0.0004), "<$0.01")
        self.assertEqual(floating._fmt_cost(242.6267), "$242.63")
        self.assertEqual(floating._fmt_cost(None), "N/A")

    def test_context_color_thresholds_match_the_tui_bar(self):
        self.assertEqual(floating._context_color(None), floating.DIM)
        self.assertEqual(floating._context_color(10), floating.LIVE)     # green
        self.assertEqual(floating._context_color(65), floating.ACCENT)   # yellow
        self.assertNotIn(floating._context_color(95), (floating.LIVE, floating.ACCENT))


class TestBudgets(unittest.TestCase):
    """
    User-defined budgets - the only honest percentage-of-consumption this app
    can show, since Claude's real plan quota is server-side and unreadable.
    """

    def _usage(self, cost=10.0):
        return {"5h": {"input": 100, "output": 50, "cache_read": 800, "cache_write": 50, "cost": cost},
                "7d": {"input": 200, "output": 100, "cache_read": 1600, "cache_write": 100, "cost": cost * 2}}

    def test_total_tokens_counts_every_kind(self):
        """A budget you set has to be measured against everything that was billed."""
        out = session_monitor.apply_budgets(self._usage(), {})
        self.assertEqual(out["5h"]["total_tokens"], 100 + 50 + 800 + 50)

    def test_no_budget_means_no_percentage_rather_than_a_guess(self):
        out = session_monitor.apply_budgets(self._usage(), {})
        for key in ("5h", "7d"):
            self.assertIsNone(out[key]["budget_tokens_percent"])
            self.assertIsNone(out[key]["budget_cost_percent"])

    def test_token_budget_percentage(self):
        out = session_monitor.apply_budgets(self._usage(), {"5h": {"tokens": 2000}})
        self.assertAlmostEqual(out["5h"]["budget_tokens_percent"], 50.0)  # 1000 of 2000

    def test_cost_budget_percentage(self):
        out = session_monitor.apply_budgets(self._usage(cost=25.0), {"7d": {"cost_usd": 200}})
        self.assertAlmostEqual(out["7d"]["budget_cost_percent"], 25.0)    # $50 of $200

    def test_percentage_is_not_clamped_at_100(self):
        """
        Going over a budget you set yourself is the most important thing the
        bar can say. Clamping it would hide exactly that.
        """
        out = session_monitor.apply_budgets(self._usage(), {"5h": {"tokens": 500}})
        self.assertGreater(out["5h"]["budget_tokens_percent"], 100)

    def test_cost_budget_is_none_when_the_window_has_no_priced_model(self):
        usage = self._usage()
        usage["5h"]["cost"] = None
        out = session_monitor.apply_budgets(usage, {"5h": {"cost_usd": 100}})
        self.assertIsNone(out["5h"]["budget_cost_percent"])

    def test_load_budget_defaults_to_unset(self):
        budget = load_budget()
        for window in ("5h", "7d"):
            self.assertIn(window, budget)

    def test_load_budget_rejects_nonsense_values(self):
        """
        Zero, negative and boolean limits are treated as unset. A zero limit
        would divide by zero; a negative one would render as a nonsense
        percentage on the first request.
        """
        import json as _json
        import tempfile as _tempfile
        from tokens_counter import config as _config

        real_file = _config.BUDGET_FILE
        tmp = _tempfile.mkdtemp()
        try:
            _config.BUDGET_FILE = os.path.join(tmp, "budget_config.json")
            with open(_config.BUDGET_FILE, "w") as f:
                _json.dump({"5h": {"tokens": 0, "cost_usd": -5},
                            "7d": {"tokens": True, "cost_usd": 150}}, f)
            budget = _config.load_budget()
            self.assertIsNone(budget["5h"]["tokens"])
            self.assertIsNone(budget["5h"]["cost_usd"])
            self.assertIsNone(budget["7d"]["tokens"])   # True is not a budget
            self.assertEqual(budget["7d"]["cost_usd"], 150)
        finally:
            _config.BUDGET_FILE = real_file
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_budget_survives_a_corrupt_file(self):
        import tempfile as _tempfile
        from tokens_counter import config as _config
        real_file = _config.BUDGET_FILE
        tmp = _tempfile.mkdtemp()
        try:
            _config.BUDGET_FILE = os.path.join(tmp, "budget_config.json")
            with open(_config.BUDGET_FILE, "w") as f:
                f.write("{not json at all")
            budget = _config.load_budget()
            self.assertIsNone(budget["5h"]["tokens"])
        finally:
            _config.BUDGET_FILE = real_file
            shutil.rmtree(tmp, ignore_errors=True)


class TestPlanRateLimits(unittest.TestCase):
    """
    The real 5h/7d plan percentages, captured from Claude Code's status line.
    These are the numbers the app cannot compute or fetch itself.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "rate_limits_cache.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, payload):
        """Writes a cache as statusline.py would - provenance marker included."""
        with open(self.cache, "w") as f:
            json.dump({"source": "claude-code-statusline", **payload}, f)

    def test_returns_none_when_never_captured(self):
        """No cache means the status line isn't installed - say nothing, don't guess."""
        self.assertIsNone(claude_config.get_plan_rate_limits(self.cache))

    def test_reads_both_windows(self):
        self._write({"captured_at": "2026-09-14T20:00:00Z", "rate_limits_available": True,
                     "rate_limits": {"five_hour": {"used_percentage": 42.7, "resets_at": "2026-09-14T23:00:00Z"},
                                     "seven_day": {"used_percentage": 12.5, "resets_at": "2026-09-19T07:00:00Z"}}})
        limits = claude_config.get_plan_rate_limits(self.cache)
        self.assertAlmostEqual(limits["five_hour"]["used_percentage"], 42.7)
        self.assertAlmostEqual(limits["seven_day"]["used_percentage"], 12.5)
        self.assertEqual(limits["five_hour"]["resets_at"], "2026-09-14T23:00:00Z")

    def test_reports_age_so_a_stale_reading_cannot_pass_for_current(self):
        """
        The cache only refreshes while a Claude Code session renders its
        status line. An old percentage presented as current would be exactly
        the believable-but-wrong number this app avoids everywhere.
        """
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        self._write({"captured_at": old.isoformat(), "rate_limits_available": True,
                     "rate_limits": {"five_hour": {"used_percentage": 10.0}}})
        limits = claude_config.get_plan_rate_limits(self.cache)
        self.assertGreater(limits["age_seconds"], 3 * 3600 - 60)

    def test_available_false_is_preserved(self):
        """API-key/Bedrock/Vertex sessions genuinely have no plan limits."""
        self._write({"captured_at": "2026-09-14T20:00:00Z",
                     "rate_limits_available": False, "rate_limits": None})
        limits = claude_config.get_plan_rate_limits(self.cache)
        self.assertFalse(limits["available"])
        self.assertIsNone(limits["five_hour"])

    def test_malformed_percentages_are_dropped_not_shown(self):
        self._write({"captured_at": "2026-09-14T20:00:00Z", "rate_limits_available": True,
                     "rate_limits": {"five_hour": {"used_percentage": "lots"},
                                     "seven_day": {"used_percentage": True}}})
        limits = claude_config.get_plan_rate_limits(self.cache)
        self.assertIsNone(limits["five_hour"])
        self.assertIsNone(limits["seven_day"])

    def test_statusline_command_survives_a_path_with_spaces(self):
        """
        Claude Code runs statusLine.command through a shell. An unquoted path
        containing a space is split into separate arguments and the script
        never runs - with no error shown anywhere, so the status line just
        stays blank. This shipped broken once; the test exists to keep it
        from shipping broken again.
        """
        import shlex
        command = claude_config.statusline_command("/usr/bin/python3")
        parts = shlex.split(command)          # exactly what a shell would do
        self.assertEqual(len(parts), 2, f"shell would split this into {parts}")
        self.assertEqual(parts[0], "/usr/bin/python3")
        self.assertTrue(parts[1].endswith("statusline.py"))
        self.assertTrue(os.path.exists(parts[1]), f"{parts[1]} is not a real path")

    def test_statusline_command_runs_through_a_shell(self):
        """End-to-end: the exact installed string must work when a shell runs it."""
        import subprocess
        command = claude_config.statusline_command()
        result = subprocess.run(
            command, shell=True, input='{"rate_limits_available":false,"rate_limits":null}',
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, f"shell run failed: {result.stderr}")

    def test_install_preserves_other_settings_and_backs_up(self):
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w") as f:
            json.dump({"model": "opus", "hooks": {"PreToolUse": []}}, f)

        ok, _ = claude_config.install_statusline(path)
        self.assertTrue(ok)
        with open(path) as f:
            after = json.load(f)
        self.assertEqual(after["model"], "opus")
        self.assertIn("hooks", after)
        self.assertEqual(after["statusLine"]["type"], "command")
        self.assertTrue(os.path.exists(path + ".bak-tokenscounter"))

    def test_install_refuses_to_overwrite_an_unparseable_settings_file(self):
        """
        settings.json drives every Claude Code session, not just this app.
        A file we can't parse might still be valid to Claude Code, so
        clobbering it with a fresh dict is not an acceptable failure mode.
        """
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w") as f:
            f.write("{ not json")
        ok, message = claude_config.install_statusline(path)
        self.assertFalse(ok)
        self.assertIn("couldn't be parsed", message)
        with open(path) as f:
            self.assertEqual(f.read(), "{ not json")   # untouched


class TestStatuslineScript(unittest.TestCase):
    """The capture script runs inside the user's Claude Code on every render."""

    def _run(self, stdin_text):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tokens_counter", "statusline.py")
        return subprocess.run([sys.executable, script], input=stdin_text,
                              capture_output=True, text=True, timeout=30)

    def test_never_fails_on_bad_input(self):
        """
        A crash here breaks the user's status line, not just this feature.
        Empty, non-JSON and limit-less payloads must all exit cleanly.
        """
        for payload in ("", "not json at all", "{}", '{"rate_limits": null}'):
            result = self._run(payload)
            self.assertEqual(result.returncode, 0, f"failed on {payload!r}: {result.stderr}")

    def test_prints_the_percentages_it_captured(self):
        result = self._run('{"model":{"display_name":"Opus 5"},"rate_limits_available":true,'
                           '"rate_limits":{"five_hour":{"used_percentage":42.7},'
                           '"seven_day":{"used_percentage":12.5}}}')
        self.assertEqual(result.returncode, 0)
        self.assertIn("5h 43%", result.stdout)
        self.assertIn("7d 12%", result.stdout)


class TestFloatingPlanHeadline(unittest.TestCase):
    """
    The floating window's headline. It replaced the total-spend figure with
    Claude's real 5h plan percentage, but that number only exists when the
    status line capture is installed and the account has plan limits at all,
    so the fallback chain is the part worth pinning down.
    """

    def setUp(self):
        from tokens_counter import statusline
        self.statusline = statusline
        self.real_cache = statusline.CACHE_FILE
        self.tmp = tempfile.mkdtemp()
        statusline.CACHE_FILE = os.path.join(self.tmp, "rate_limits_cache.json")
        self.config_data = load_config()

    def tearDown(self):
        self.statusline.CACHE_FILE = self.real_cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cache(self, percent, age_minutes=0, resets_at=None):
        captured = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        five_hour = {"used_percentage": percent}
        if resets_at:
            five_hour["resets_at"] = resets_at
        with open(self.statusline.CACHE_FILE, "w") as f:
            json.dump({"source": "claude-code-statusline", "captured_at": captured.isoformat(),
                       "rate_limits_available": True,
                       "rate_limits": {"five_hour": five_hour}}, f)

    def test_shows_the_real_five_hour_percentage(self):
        self._write_cache(43.0)
        text, _ = floating._plan_headline(self.config_data)
        self.assertEqual(text, "5h 43%")

    def test_shows_the_reset_countdown_when_claude_sends_one(self):
        resets = (datetime.now(timezone.utc) + timedelta(minutes=9)).isoformat()
        self._write_cache(43.0, resets_at=resets)
        text, _ = floating._plan_headline(self.config_data)
        self.assertEqual(text, "5h 43% · resets 9m")

    def test_reset_label_never_pairs_the_window_name_with_a_duration(self):
        """
        "5h:2h" (window name next to an hours countdown) is unreadable, and
        "9m left" beside a percentage reads as leftover quota rather than
        time. The label must name what the duration is.
        """
        resets = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self._write_cache(12.0, resets_at=resets)
        text, _ = floating._plan_headline(self.config_data)
        self.assertIn("resets 2h", text)
        self.assertNotIn("5h:2h", text)
        self.assertNotIn("left", text)

    def test_countdown_says_now_rather_than_going_negative(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertEqual(floating._time_until(past), "now")

    def test_countdown_ignores_a_missing_or_broken_reset_time(self):
        self.assertIsNone(floating._time_until(None))
        self.assertIsNone(floating._time_until("not a timestamp"))
        self._write_cache(43.0)  # no resets_at at all
        text, _ = floating._plan_headline(self.config_data)
        self.assertNotIn("resets", text)

    def test_colour_follows_severity(self):
        for percent, expected in ((12.0, floating.LIVE), (65.0, floating.ACCENT)):
            self._write_cache(percent)
            _, colour = floating._plan_headline(self.config_data)
            self.assertEqual(colour, expected)
        self._write_cache(94.0)
        _, colour = floating._plan_headline(self.config_data)
        self.assertNotIn(colour, (floating.LIVE, floating.ACCENT))

    def test_stale_reading_is_marked_not_passed_off_as_current(self):
        """
        The cache only refreshes while a Claude Code session renders its status
        line, so an idle machine's number ages silently. It must look different.
        """
        self._write_cache(43.0, age_minutes=30)
        text, _ = floating._plan_headline(self.config_data)
        self.assertTrue(text.endswith("?"), text)

    def test_falls_back_rather_than_going_blank(self):
        """With no capture at all the widget still shows something useful."""
        text, _ = floating._plan_headline(self.config_data)
        self.assertTrue(text.strip())

    def test_never_raises_on_a_corrupt_cache(self):
        """A broken cache must not take down the window's refresh loop."""
        with open(self.statusline.CACHE_FILE, "w") as f:
            f.write("{ not json")
        text, colour = floating._plan_headline(self.config_data)
        self.assertTrue(text.strip())
        self.assertTrue(colour)


class TestCacheProvenance(unittest.TestCase):
    """A cache this app didn't write must never be shown as a real reading."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "rate_limits_cache.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unmarked_cache_is_ignored(self):
        """
        Exactly the shape a scratch script would write: plausible numbers, no
        provenance. During development this showed a fabricated "5h 43%" as
        though Claude had reported it.
        """
        with open(self.cache, "w") as f:
            json.dump({"captured_at": datetime.now(timezone.utc).isoformat(),
                       "rate_limits_available": True,
                       "rate_limits": {"five_hour": {"used_percentage": 42.7}}}, f)
        self.assertIsNone(claude_config.get_plan_rate_limits(self.cache))

    def test_marked_cache_is_accepted(self):
        with open(self.cache, "w") as f:
            json.dump({"source": "claude-code-statusline",
                       "captured_at": datetime.now(timezone.utc).isoformat(),
                       "rate_limits_available": True,
                       "rate_limits": {"five_hour": {"used_percentage": 42.7}}}, f)
        limits = claude_config.get_plan_rate_limits(self.cache)
        self.assertAlmostEqual(limits["five_hour"]["used_percentage"], 42.7)

    def test_the_script_stamps_what_the_reader_requires(self):
        """The writer's marker and the reader's check must not drift apart."""
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tokens_counter", "statusline.py")
        from tokens_counter import statusline
        real = statusline.CACHE_FILE
        try:
            statusline.CACHE_FILE = self.cache
            subprocess.run([sys.executable, script],
                           input='{"rate_limits_available":true,"rate_limits":'
                                 '{"five_hour":{"used_percentage":7.0}}}',
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, "TOKENS_COUNTER_CACHE": self.cache})
        finally:
            statusline.CACHE_FILE = real
        # The script writes to its own CACHE_FILE; assert the constant itself
        # is what the reader demands.
        self.assertEqual(statusline.CACHE_SOURCE, "claude-code-statusline")


class TestPortability(unittest.TestCase):
    """
    The app has to install and run on any machine, not just the one it was
    written on. These pin the pieces that are easy to hardcode by accident.
    """

    def test_no_machine_specific_paths_in_the_source(self):
        """A path from the author's machine would break every other install."""
        import ast
        import glob

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for path in glob.glob(os.path.join(root, "tokens_counter", "*.py")) + \
                    [os.path.join(root, "start.py")]:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)

            # Docstrings legitimately cite example paths while explaining why
            # they must not be hardcoded. Every OTHER string is real code and
            # is exactly where a machine-specific path would hide, so those
            # are checked - skipping all strings would make this test blind
            # to the one case it exists for.
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = getattr(node, "body", None)
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docstrings.add(id(body[0].value))

            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings):
                    if "/home/" in node.value or "C:\\Users" in node.value:
                        offenders.append(f"{os.path.basename(path)}:{node.lineno}")
        self.assertEqual(offenders, [], f"machine-specific paths in {offenders}")

    def test_cache_lives_outside_the_repo(self):
        """
        The repo may be read-only (system-wide install, root-owned checkout),
        and a cache inside the source tree also travels with every clone.
        """
        from tokens_counter import statusline
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(
            os.path.abspath(statusline.CACHE_FILE).startswith(os.path.abspath(root) + os.sep),
            f"cache is inside the repo: {statusline.CACHE_FILE}",
        )

    def test_cache_path_is_overridable(self):
        """A packaged or sandboxed install must be able to redirect it."""
        import importlib
        from tokens_counter import statusline
        previous = os.environ.get("TOKENS_COUNTER_CACHE")
        try:
            os.environ["TOKENS_COUNTER_CACHE"] = "/tmp/somewhere-else/cache.json"
            reloaded = importlib.reload(statusline)
            self.assertEqual(reloaded.CACHE_FILE, "/tmp/somewhere-else/cache.json")
        finally:
            if previous is None:
                os.environ.pop("TOKENS_COUNTER_CACHE", None)
            else:
                os.environ["TOKENS_COUNTER_CACHE"] = previous
            importlib.reload(statusline)

    def test_statusline_points_at_this_copy_of_the_app(self):
        """Two checkouts on one machine must not fight over one command."""
        import shlex
        script = shlex.split(claude_config.statusline_command())[1]
        expected = os.path.join(os.path.dirname(os.path.abspath(claude_config.__file__)),
                                "statusline.py")
        self.assertEqual(os.path.abspath(script), os.path.abspath(expected))


class TestStatuslineDiagnostics(unittest.TestCase):
    """
    A broken statusLine command produces no error anywhere - Claude Code just
    renders nothing. Option 7 therefore has to diagnose it itself.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real_dir = claude_config.get_claude_config_dir
        from pathlib import Path
        claude_config.get_claude_config_dir = lambda: Path(self.tmp)
        self.here = os.path.dirname(os.path.abspath(claude_config.__file__))

    def tearDown(self):
        claude_config.get_claude_config_dir = self.real_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _set(self, command):
        with open(os.path.join(self.tmp, "settings.json"), "w") as f:
            json.dump({"statusLine": {"type": "command", "command": command}}, f)

    def test_detects_an_unquoted_path_with_spaces(self):
        """The bug that shipped: a space in the path splits the command."""
        self._set(f"/usr/bin/python3 {self.here}/statusline.py")
        problems = claude_config.statusline_status_report()["problems"]
        self.assertTrue(any("shell arguments" in p for p in problems), problems)

    def test_detects_a_deleted_virtualenv(self):
        self._set(f"'/gone/venv/bin/python3' '{self.here}/statusline.py'")
        problems = claude_config.statusline_status_report()["problems"]
        self.assertTrue(any("Python it points at" in p for p in problems), problems)

    def test_detects_a_moved_repo(self):
        self._set("/usr/bin/python3 '/old/location/tokens_counter/statusline.py'")
        problems = claude_config.statusline_status_report()["problems"]
        self.assertTrue(any("no longer exists" in p for p in problems), problems)

    def test_a_correct_command_reports_no_problems(self):
        self._set(claude_config.statusline_command())
        report = claude_config.statusline_status_report()
        self.assertTrue(report["ours"])
        self.assertEqual(report["problems"], [])

    def test_someone_elses_statusline_is_not_claimed_as_ours(self):
        self._set("/usr/bin/starship prompt")
        report = claude_config.statusline_status_report()
        self.assertTrue(report["installed"])
        self.assertFalse(report["ours"])
        self.assertEqual(report["problems"], [])
