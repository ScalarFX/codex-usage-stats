from __future__ import annotations

import sys
from datetime import date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from codex_stats.parser import parse_all, parse_rollout  # noqa: E402
from codex_stats.stats import aggregate  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sessions"


def test_parse_rollout_picks_last_nonnull_token_count():
    path = next((FIXTURES / "2024" / "01" / "15").glob("rollout-*.jsonl"))
    s = parse_rollout(path)
    assert s is not None
    assert s.session_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    # Last non-null token_count has total_tokens=320 (cumulative), NOT 125+195=320 summed.
    assert s.usage.total_tokens == 320
    assert s.usage.input_tokens == 250
    assert s.usage.cached_input_tokens == 120
    assert s.usage.non_cached_input_tokens == 130
    assert s.usage.output_tokens == 55
    assert s.usage.reasoning_output_tokens == 15
    assert s.usage.effective_tokens == 185
    assert s.user_message_count == 2
    assert s.turn_count == 2
    assert s.models == ["gpt-test-a", "gpt-test-a"]
    assert s.timezone_name == "UTC"
    # duration = end (10:05:00) - start (10:00:00) = 300s
    assert s.duration_s == 300.0
    assert s.start.tzinfo == timezone.utc


def test_parse_all_sorts_by_start():
    sessions = parse_all(FIXTURES)
    assert len(sessions) == 2
    assert sessions[0].start < sessions[1].start
    assert sessions[0].session_id.startswith("a")
    assert sessions[1].session_id.startswith("b")


def test_aggregate_totals_and_active_days():
    sessions = parse_all(FIXTURES)
    agg = aggregate(sessions, "all")
    t = agg["totals"]
    assert t["session_count"] == 2
    assert t["raw_total_tokens"] == 320 + 50
    assert t["total_tokens"] == 320 + 50
    assert t["non_cached_input_tokens"] == 130 + 40
    assert t["effective_tokens"] == 185 + 50
    assert t["output_tokens"] == 55 + 10
    assert t["reasoning_output_tokens"] == 15
    assert t["cached_input_tokens"] == 120
    assert t["active_days"] == 2
    # top_model: gpt-test-a appears twice (two turns in session A), gpt-test-b once.
    assert t["top_model"] == "gpt-test-a"
    # Duration: 300s + 120s = 420s
    assert t["duration_s"] == 420.0


def test_aggregate_handles_empty():
    agg = aggregate([], "7d")
    assert agg["totals"]["session_count"] == 0
    assert agg["totals"]["total_tokens"] == 0
    assert agg["totals"]["top_model"] == ""
    # heatmap still produces a stable grid
    assert agg["heatmap"]["weeks"] == 53
    # heatmap columns start on Sunday so frontend dates don't drift.
    assert date.fromisoformat(agg["heatmap"]["start"]).weekday() == 6


def test_parse_missing_dir_returns_empty():
    assert parse_all(FIXTURES.parent / "nonexistent") == []


if __name__ == "__main__":
    # Minimal runner so tests run with or without pytest installed.
    import traceback
    fns = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
