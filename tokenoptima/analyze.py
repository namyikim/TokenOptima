"""세션 하나의 지표와 낭비 패턴.

지표 정의는 docs/metrics.md 에 있다. 금액이 아니라 상대 비용(입력 1 기준)으로 계산한다(pricing.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .loader import Call, Session
from .pricing import relative_cost

# 캐시 유효시간. Claude Code 는 1시간 캐시를 쓰는 경우가 많고, 기본 API 캐시는 5분이다.
# 이보다 긴 공백 뒤의 큰 캐시 쓰기는 '자리를 비워 캐시가 만료된 것'으로 본다.
IDLE_MINUTES = 60
BIG_WRITE_TOKENS = 50_000
# 이 길이 이하의 프롬프트는 '확인 답변'(네, A, 2 …)으로 본다. 새 작업 요청과 가르는 기준이다.
SHORT_PROMPT_CHARS = 25
BIG_TOOL_RESULT_CHARS = 10_000


def call_cost(call: Call) -> float:
    return relative_cost(call.input_tokens, call.cache_read, call.cache_write, call.output_tokens)


@dataclass
class PromptCost:
    text: str
    share: float
    calls: int
    tool_chars: int
    short: bool
    resume_share: float   # 첫 호출 비용 = 대화를 다시 이어 받는 데 든 몫(왕복 한 번의 고정비)


@dataclass
class IdleBreak:
    gap_minutes: float
    rewritten_tokens: int
    share: float


@dataclass
class SessionReport:
    session: Session
    totals: Dict[str, int]
    cost: float
    cost_share: Dict[str, float]
    cache_hit: float
    context_start: int
    context_max: int
    context_avg: float
    per_task_context_avg: float
    per_task_saving: float
    prompts: List[PromptCost]
    idle_breaks: List[IdleBreak]
    big_tool_results: list
    tool_totals: Dict[str, List[int]]
    models: Dict[str, int]
    short_prompt_share: float = 0.0
    short_prompt_count: int = 0
    task_count: int = 0
    notes: List[str] = field(default_factory=list)


def _segments(session: Session, starts: List[int]) -> List[List[Call]]:
    bounds = starts + [10 ** 12]
    return [[c for c in session.calls if bounds[i] <= c.order < bounds[i + 1]] for i in range(len(starts))]


def per_task_context(session: Session, task_starts: List[int]) -> float:
    """작업마다 새 대화를 열었다면 호출 한 번의 평균 맥락이 얼마였을지.

    새 대화는 첫 호출의 맥락(시스템 프롬프트·도구 정의·CLAUDE.md)에서 다시 시작하고, 그 작업 안에서 늘어난
    만큼만 더한다. 새 대화에서 파일을 다시 읽는 비용은 넣지 않으므로 절감의 상한에 가까운 값이다.
    """
    calls = session.calls
    if not calls:
        return 0.0
    base = calls[0].context
    total = 0.0
    bounds = task_starts + [10 ** 12]
    for call in calls:
        if not task_starts or call.order < task_starts[0]:
            total += call.context
            continue
    for i in range(len(task_starts)):
        seg = [c for c in calls if bounds[i] <= c.order < bounds[i + 1]]
        if not seg:
            continue
        start = seg[0].context
        total += sum(base + max(0, c.context - start) for c in seg)
    return total / len(calls)


def analyse(session: Session) -> SessionReport:
    calls = session.calls
    totals = {
        "input": sum(c.input_tokens for c in calls),
        "cache_read": sum(c.cache_read for c in calls),
        "cache_write": sum(c.cache_write for c in calls),
        "output": sum(c.output_tokens for c in calls),
    }
    parts = {
        "input": totals["input"] * 1.0,
        "cache_read": relative_cost(0, totals["cache_read"], 0, 0),
        "cache_write": relative_cost(0, 0, totals["cache_write"], 0),
        "output": relative_cost(0, 0, 0, totals["output"]),
    }
    cost = sum(parts.values()) or 1.0
    read_side = totals["input"] + totals["cache_read"] + totals["cache_write"]
    models: Dict[str, int] = {}
    for c in calls:
        models[c.model] = models.get(c.model, 0) + 1

    # 프롬프트별 비용: 다음 프롬프트 전까지의 호출을 그 프롬프트에 붙인다.
    starts = [p.order for p in session.prompts]
    prompt_costs = []
    for prompt, seg in zip(session.prompts, _segments(session, starts)):
        end = next((p.order for p in session.prompts if p.order > prompt.order), 10 ** 12)
        tool_chars = sum(t.size for t in session.tool_results if prompt.order <= t.order < end)
        prompt_costs.append(PromptCost(
            text=prompt.text, share=sum(call_cost(c) for c in seg) / cost, calls=len(seg),
            tool_chars=tool_chars, short=len(prompt.text) <= SHORT_PROMPT_CHARS,
            resume_share=call_cost(seg[0]) / cost if seg else 0.0))

    # 자리를 비운 뒤의 캐시 만료
    idle = []
    for prev, call in zip(calls, calls[1:]):
        if prev.time and call.time and call.cache_write >= BIG_WRITE_TOKENS:
            gap = (call.time - prev.time).total_seconds() / 60
            if gap >= IDLE_MINUTES:
                idle.append(IdleBreak(gap, call.cache_write, relative_cost(0, 0, call.cache_write, 0) / cost))

    tool_totals: Dict[str, List[int]] = {}
    for t in session.tool_results:
        entry = tool_totals.setdefault(t.tool, [0, 0])
        entry[0] += 1
        entry[1] += t.size

    task_starts = [p.order for p in session.prompts if len(p.text) > SHORT_PROMPT_CHARS]
    context_avg = sum(c.context for c in calls) / len(calls)
    per_task = per_task_context(session, task_starts)
    return SessionReport(
        session=session,
        totals=totals,
        cost=cost,
        cost_share={k: v / cost for k, v in parts.items()},
        cache_hit=totals["cache_read"] / read_side if read_side else 0.0,
        context_start=calls[0].context,
        context_max=max(c.context for c in calls),
        context_avg=context_avg,
        per_task_context_avg=per_task,
        per_task_saving=1 - per_task / context_avg if context_avg else 0.0,
        prompts=prompt_costs,
        idle_breaks=idle,
        big_tool_results=sorted((t for t in session.tool_results if t.size >= BIG_TOOL_RESULT_CHARS),
                                key=lambda t: -t.size),
        tool_totals=tool_totals,
        models=models,
        # 짧은 답 뒤에 이어진 실제 작업은 낭비가 아니다. 왕복 자체의 고정비(첫 호출)만 센다.
        short_prompt_share=sum(p.resume_share for p in prompt_costs if p.short),
        short_prompt_count=sum(1 for p in prompt_costs if p.short),
        task_count=len(task_starts),
    )


@dataclass
class Finding:
    title: str
    impact: str
    evidence: str
    advice: str
    weight: float   # 정렬용: 대략적인 절감 비중(0~1)


def findings(report: SessionReport) -> List[Finding]:
    """지표를 사람이 읽을 조언으로 바꾼다. 영향이 큰 순서로 돌려준다."""
    out: List[Finding] = []
    if report.task_count >= 3 and report.per_task_saving >= 0.2:
        read_share = report.cost_share["cache_read"] + report.cost_share["input"]
        out.append(Finding(
            title="여러 작업을 한 대화에서 계속 이어감",
            impact=f"입력 쪽 비용(전체의 {read_share:.0%})의 최대 {report.per_task_saving:.0%}",
            evidence=(f"새 작업 요청 {report.task_count}개가 한 대화에 있음. 맥락 {report.context_start:,} → "
                      f"최대 {report.context_max:,} 토큰. 호출 한 번의 평균 맥락 {report.context_avg:,.0f} → "
                      f"작업마다 새 대화였다면 {report.per_task_context_avg:,.0f}"),
            advice="주제가 바뀌면 새 대화를 연다. 이어 가야 할 규칙·맥락은 CLAUDE.md 나 짧은 메모로 넘긴다.",
            weight=read_share * report.per_task_saving))
    for brk in report.idle_breaks:
        out.append(Finding(
            title="오래 비운 뒤 긴 대화로 돌아옴(캐시 만료)",
            impact=f"이 한 번에 대화 비용의 {brk.share:.0%}",
            evidence=f"{brk.gap_minutes:.0f}분 공백 뒤 {brk.rewritten_tokens:,} 토큰을 캐시에 다시 씀",
            advice="한 시간 넘게 쉬었다면 긴 대화를 이어가지 말고 새 대화로 시작한다.",
            weight=brk.share))
    # 한두 번의 짧은 답은 패턴이 아니다. 세 번 이상 되풀이될 때만 본다.
    if report.short_prompt_count >= 3 and report.short_prompt_share >= 0.02:
        shorts = sorted((p for p in report.prompts if p.short), key=lambda p: -p.resume_share)[:3]
        examples = ", ".join(f'"{p.text[:15]}"' for p in shorts)
        out.append(Finding(
            title="짧은 확인 답변이 큰 맥락을 다시 읽음",
            impact=(f"확인 왕복 {report.short_prompt_count}번의 고정비(다시 이어 받는 첫 호출)가 "
                    f"대화 비용의 {report.short_prompt_share:.0%}"),
            evidence=f"예: {examples}",
            advice=("요청할 때 결정을 미리 담는다(예: '테스트 통과하면 커밋·push까지 해줘'). "
                    "선택지를 묻는 규칙(CLAUDE.md 등)이 왕복을 늘리지 않는지 본다."),
            weight=report.short_prompt_share * 0.5))
    if report.big_tool_results:
        total_big = sum(t.size for t in report.big_tool_results)
        top = report.big_tool_results[0]
        out.append(Finding(
            title="큰 도구 결과가 맥락에 남음",
            impact=f"{len(report.big_tool_results)}건, 합계 {total_big / 1000:.0f}k자(이후 모든 호출이 다시 읽음)",
            evidence=f"가장 큰 것: {top.tool} · {top.summary[:60]} ({top.size / 1000:.1f}k자)",
            advice="파일 전체 출력 대신 grep·줄 범위로 필요한 부분만 본다. 출력은 head/tail 로 줄인다.",
            weight=0.03))
    if len(report.models) == 1 and report.task_count >= 5:
        model = next(iter(report.models))
        out.append(Finding(
            title="모든 일에 같은 모델·설정",
            impact="작은 작업만 하는 대화라면 더 가벼운 설정이 더 쌈",
            evidence=f"호출 {sum(report.models.values())}회 전부 {model}",
            advice="대화를 시작할 때 일의 크기에 맞게 모델·effort 를 고른다(중간에 바꾸면 캐시가 깨진다).",
            weight=0.01))
    return sorted(out, key=lambda f: -f.weight)
