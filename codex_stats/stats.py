"""Aggregate SessionSummary list into dashboard-ready stats."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from .parser import SessionSummary, TokenUsage


RANGE_CHOICES = ("all", "30d", "7d")


def _resolve_tz(sessions: list[SessionSummary]) -> tuple[tzinfo, str]:
    """Return (tzinfo used for date math, display label).

    Prefers the most common IANA name seen in sessions. If ZoneInfo can't load
    it (e.g. on stock Windows Python without the `tzdata` package), falls back
    to the system local tzinfo but keeps the IANA name as the display label.
    """
    names = [s.timezone_name for s in sessions if s.timezone_name]
    if names:
        name, _ = Counter(names).most_common(1)[0]
        try:
            return ZoneInfo(name), name
        except Exception:
            # Can't resolve, but still show the intended name.
            sys_tz = datetime.now().astimezone().tzinfo or timezone.utc
            return sys_tz, name
    sys_tz = datetime.now().astimezone().tzinfo or timezone.utc
    return sys_tz, str(sys_tz)


def _filter_by_range(sessions: list[SessionSummary], range_: str, tz: tzinfo) -> list[SessionSummary]:
    if range_ == "all":
        return sessions
    days = 7 if range_ == "7d" else 30
    today_local = datetime.now(tz).date()
    cutoff = today_local - timedelta(days=days - 1)
    return [s for s in sessions if s.start.astimezone(tz).date() >= cutoff]


def _local_date(s: SessionSummary, tz: tzinfo) -> date:
    return s.start.astimezone(tz).date()


def aggregate(sessions: list[SessionSummary], range_: str = "all") -> dict:
    if range_ not in RANGE_CHOICES:
        range_ = "all"

    tz, tz_label = _resolve_tz(sessions)
    filtered = _filter_by_range(sessions, range_, tz)

    # Totals
    total = TokenUsage()
    total_duration_s = 0.0
    model_counter: Counter[str] = Counter()
    daily_tokens: dict[str, int] = {}
    daily_sessions: dict[str, int] = {}
    active_days: set[date] = set()

    for s in filtered:
        total.input_tokens += s.usage.input_tokens
        total.cached_input_tokens += s.usage.cached_input_tokens
        total.output_tokens += s.usage.output_tokens
        total.reasoning_output_tokens += s.usage.reasoning_output_tokens
        total.total_tokens += s.usage.total_tokens
        total_duration_s += s.duration_s
        for m in s.models:
            model_counter[m] += 1
        d = _local_date(s, tz)
        active_days.add(d)
        key = d.isoformat()
        daily_tokens[key] = daily_tokens.get(key, 0) + s.usage.effective_tokens
        daily_sessions[key] = daily_sessions.get(key, 0) + 1

    top_model = model_counter.most_common(1)[0][0] if model_counter else ""

    # Daily trend — dense range
    trend = _dense_daily(daily_tokens, daily_sessions, range_, tz)

    # Heatmap window: fixed 53 calendar weeks ending in the current local week.
    heatmap = _heatmap(sessions, tz)

    return {
        "range": range_,
        "timezone": tz_label,
        "totals": {
            "effective_tokens": total.effective_tokens,
            "raw_total_tokens": total.total_tokens,
            "total_tokens": total.total_tokens,
            "input_tokens": total.input_tokens,
            "non_cached_input_tokens": total.non_cached_input_tokens,
            "cached_input_tokens": total.cached_input_tokens,
            "output_tokens": total.output_tokens,
            "reasoning_output_tokens": total.reasoning_output_tokens,
            "duration_s": round(total_duration_s, 1),
            "session_count": len(filtered),
            "active_days": len(active_days),
            "top_model": top_model,
            "models": dict(model_counter.most_common()),
        },
        "trend": trend,
        "heatmap": heatmap,
    }


def _dense_daily(
    tokens_by_day: dict[str, int],
    sessions_by_day: dict[str, int],
    range_: str,
    tz: tzinfo,
) -> list[dict]:
    today = datetime.now(tz).date()
    if range_ == "7d":
        start = today - timedelta(days=6)
    elif range_ == "30d":
        start = today - timedelta(days=29)
    else:
        if not tokens_by_day and not sessions_by_day:
            return []
        earliest = min(
            [date.fromisoformat(k) for k in list(tokens_by_day) + list(sessions_by_day)]
        )
        start = earliest
    out = []
    cur = start
    while cur <= today:
        k = cur.isoformat()
        out.append({
            "date": k,
            "effective_tokens": tokens_by_day.get(k, 0),
            "tokens": tokens_by_day.get(k, 0),
            "sessions": sessions_by_day.get(k, 0),
        })
        cur += timedelta(days=1)
    return out


def _heatmap(sessions: list[SessionSummary], tz: tzinfo) -> dict:
    """Return a fixed 53-week x 7-day grid ending in the current local week.

    The grid starts on Sunday. This keeps frontend date placement simple and
    prevents the last few days from falling outside the 53 visible columns.
    """
    today = datetime.now(tz).date()
    weeks = 53
    # Python weekday: Mon=0..Sun=6. Convert to days since Sunday.
    days_since_sunday = (today.weekday() + 1) % 7
    current_week_start = today - timedelta(days=days_since_sunday)
    start = current_week_start - timedelta(weeks=weeks - 1)
    tokens: dict[str, int] = {}
    for s in sessions:
        d = _local_date(s, tz)
        if d < start or d > today:
            continue
        k = d.isoformat()
        tokens[k] = tokens.get(k, 0) + s.usage.effective_tokens
    return {
        "start": start.isoformat(),
        "end": today.isoformat(),
        "weeks": weeks,
        "effective_tokens_by_day": tokens,
        "tokens_by_day": tokens,
    }
