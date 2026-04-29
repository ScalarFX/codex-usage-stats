"""Parse a Codex Desktop rollout JSONL file into a SessionSummary.

Schema (observed on Codex Desktop 0.119.x):
    Each line: {"timestamp": ISO8601, "type": str, "payload": obj}
    type in {"session_meta", "turn_context", "event_msg", "response_item"}

    - session_meta  (1 per file): payload.id, payload.timestamp (start), payload.cwd,
                                  payload.originator, payload.cli_version, payload.model_provider
    - turn_context  (per turn):   payload.model, payload.timezone
    - event_msg/token_count:      payload.info.total_token_usage (CUMULATIVE),
                                  payload.info.last_token_usage  (TURN DELTA)
                                  early events may have info == null (pre-first-response)
    - event_msg/{task_started,task_complete,user_message,agent_message,...}
    - response_item/{function_call,message,reasoning,...}

Token dedup rule: take the LAST token_count event whose `info` is not null,
and read `info.total_token_usage` — this is the final cumulative usage for
the session. Summing `last_token_usage` across events is equivalent but
more error-prone if a turn is interrupted mid-emit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @property
    def non_cached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def effective_tokens(self) -> int:
        return self.non_cached_input_tokens + self.output_tokens

    @classmethod
    def from_dict(cls, d: dict) -> "TokenUsage":
        return cls(
            input_tokens=d.get("input_tokens", 0) or 0,
            cached_input_tokens=d.get("cached_input_tokens", 0) or 0,
            output_tokens=d.get("output_tokens", 0) or 0,
            reasoning_output_tokens=d.get("reasoning_output_tokens", 0) or 0,
            total_tokens=d.get("total_tokens", 0) or 0,
        )


@dataclass
class SessionSummary:
    session_id: str
    path: str
    start: datetime           # UTC
    end: datetime             # UTC — last line timestamp
    duration_s: float
    cwd: str
    originator: str
    cli_version: str
    model_provider: str
    timezone_name: str        # e.g. "Asia/Shanghai", or "" if unknown
    models: list[str]         # every turn's model, in order
    usage: TokenUsage
    user_message_count: int
    turn_count: int

    def to_json(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


def _parse_ts(s: str) -> datetime:
    # Python <3.11 doesn't accept trailing 'Z'
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_rollout(path: Path) -> SessionSummary | None:
    """Parse one rollout-*.jsonl file. Returns None if the file is unparseable
    (e.g. empty or missing session_meta)."""
    meta = None
    last_ts = None
    models: list[str] = []
    timezone_name = ""
    last_usage_dict: dict | None = None
    user_msgs = 0
    turns = 0

    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None

    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = o.get("timestamp")
            t = o.get("type")
            p = o.get("payload") or {}
            if ts:
                try:
                    last_ts = _parse_ts(ts)
                except ValueError:
                    pass

            if t == "session_meta":
                meta = p
            elif t == "turn_context":
                m = p.get("model")
                if m:
                    models.append(m)
                if not timezone_name:
                    timezone_name = p.get("timezone") or ""
            elif t == "event_msg":
                st = p.get("type")
                if st == "token_count":
                    info = p.get("info")
                    if info:
                        tu = info.get("total_token_usage")
                        if tu:
                            last_usage_dict = tu
                elif st == "user_message":
                    user_msgs += 1
                elif st == "task_started":
                    turns += 1

    if not meta:
        return None

    try:
        start = _parse_ts(meta.get("timestamp") or "")
    except ValueError:
        return None
    end = last_ts or start
    duration_s = max(0.0, (end - start).total_seconds())

    usage = TokenUsage.from_dict(last_usage_dict) if last_usage_dict else TokenUsage()

    return SessionSummary(
        session_id=meta.get("id", path.stem),
        path=str(path),
        start=start,
        end=end,
        duration_s=duration_s,
        cwd=meta.get("cwd", ""),
        originator=meta.get("originator", ""),
        cli_version=meta.get("cli_version", ""),
        model_provider=meta.get("model_provider", ""),
        timezone_name=timezone_name,
        models=models,
        usage=usage,
        user_message_count=user_msgs,
        turn_count=turns,
    )


def iter_rollouts(sessions_root: Path) -> Iterable[Path]:
    """Yield every rollout-*.jsonl under sessions_root/YYYY/MM/DD/."""
    if not sessions_root.exists():
        return
    yield from sessions_root.rglob("rollout-*.jsonl")


def parse_all(sessions_root: Path) -> list[SessionSummary]:
    out: list[SessionSummary] = []
    for p in iter_rollouts(sessions_root):
        s = parse_rollout(p)
        if s is not None:
            out.append(s)
    out.sort(key=lambda s: s.start)
    return out
