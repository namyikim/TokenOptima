"""Claude Code 대화 기록(~/.claude/projects/<프로젝트>/<세션>.jsonl)을 읽어 분석용 구조로 바꾼다.

기록 한 줄이 한 사건이다. 분석에 쓰는 것은 세 가지뿐이다.
- assistant 줄의 message.usage: API 호출 한 번의 토큰 수. 스트리밍 때문에 같은 message.id 가 여러 줄
  나올 수 있어 id 로 한 번만 센다(마지막 줄을 쓴다).
- user 줄 중 도구 결과가 아닌 것: 사람이 친 프롬프트.
- user 줄 중 tool_result: 도구가 돌려준 결과의 크기(맥락을 키운 주범을 찾는다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class Call:
    order: int
    time: Optional[datetime]
    model: str
    input_tokens: int
    cache_read: int
    cache_write: int
    output_tokens: int

    @property
    def context(self) -> int:
        """이 호출이 읽은 맥락 크기(입력 + 캐시 읽기 + 캐시 쓰기)."""
        return self.input_tokens + self.cache_read + self.cache_write


@dataclass
class Prompt:
    order: int
    time: Optional[datetime]
    text: str


@dataclass
class ToolResult:
    order: int
    size: int          # 글자 수
    tool: str
    summary: str       # 명령·파일 경로 등 앞부분


@dataclass
class Session:
    path: Path
    project: str
    session_id: str
    cwd: str = ""          # 대화를 연 작업 폴더(보고서의 대화 이름)
    calls: List[Call] = field(default_factory=list)
    prompts: List[Prompt] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)


def _time(record: dict) -> Optional[datetime]:
    raw = record.get("timestamp")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif item.get("type") == "tool_result":
            parts.append(_text(item.get("content")))
    return "\n".join(parts)


def _is_prompt(record: dict) -> bool:
    if record.get("type") != "user" or record.get("isMeta"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
        return False
    text = _text(content).strip()
    # 시스템이 끼워 넣은 알림(<task-notification> 등)은 사람이 친 글이 아니다.
    return bool(text) and not text.startswith("<")


def load_session(path: Path) -> Session:
    path = Path(path)
    session = Session(path=path, project=path.parent.name, session_id=path.stem)
    calls: Dict[str, Call] = {}
    tool_names: Dict[str, tuple] = {}
    with path.open(encoding="utf-8") as handle:
        for order, line in enumerate(handle):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message") or {}
            if not session.cwd and record.get("cwd"):
                session.cwd = record["cwd"]
            if record.get("type") == "assistant" and message.get("usage"):
                usage = message["usage"]
                key = message.get("id") or f"line-{order}"
                previous = calls.get(key)
                calls[key] = Call(
                    order=previous.order if previous else order,
                    time=_time(record),
                    model=message.get("model", "?"),
                    input_tokens=usage.get("input_tokens", 0) or 0,
                    cache_read=usage.get("cache_read_input_tokens", 0) or 0,
                    cache_write=usage.get("cache_creation_input_tokens", 0) or 0,
                    output_tokens=usage.get("output_tokens", 0) or 0,
                )
                for item in message.get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        args = item.get("input") or {}
                        summary = (args.get("command") or args.get("file_path") or args.get("url")
                                   or args.get("query") or args.get("pattern") or "")
                        tool_names[item.get("id")] = (item.get("name", "?"), str(summary).split("\n")[0][:100])
            elif record.get("type") == "user":
                content = message.get("content")
                if _is_prompt(record):
                    session.prompts.append(Prompt(order, _time(record), _text(content).strip()))
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            name, summary = tool_names.get(item.get("tool_use_id"), ("?", ""))
                            session.tool_results.append(ToolResult(order, len(_text([item])), name, summary))
    session.calls = sorted(calls.values(), key=lambda c: c.order)
    return session


def default_paths(root: Optional[Path] = None) -> List[Path]:
    root = root or Path.home() / ".claude" / "projects"
    return sorted(root.glob("*/*.jsonl"))


def load_all(paths: Iterable[Path]) -> List[Session]:
    sessions = [load_session(p) for p in paths]
    return [s for s in sessions if s.calls]
