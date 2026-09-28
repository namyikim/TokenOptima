"""분석 결과를 마크다운 보고서로 쓴다.

보고서에는 프롬프트 앞부분이 들어갈 수 있다(--redact 면 뺀다). 그래서 기본 출력 위치 reports/ 는
.gitignore 로 막혀 있다 — 개인 대화 내용이 저장소에 올라가지 않게 한다.
"""
from __future__ import annotations

from typing import List

from .analyze import SessionReport, findings


def _clip(text: str, n: int, redact: bool) -> str:
    if redact:
        return f"({len(text)}자)"
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"


def render(reports: List[SessionReport], redact: bool = False) -> str:
    lines = ["# TokenOptima 분석 보고서", ""]
    total_cost = sum(r.cost for r in reports) or 1.0
    lines += [
        "비용은 달러가 아니라 **상대 비용**(입력 1 · 캐시 읽기 0.1 · 캐시 쓰기 1.25 · 출력 5)이다. "
        "지표 정의는 `docs/metrics.md`.",
        "",
        "## 대화별 요약",
        "",
        "| 대화 | 호출 | 프롬프트 | 비용 비중 | 맥락(시작→최대) | 캐시 적중 | 작업마다 새 대화 시 평균 맥락 |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for r in sorted(reports, key=lambda r: -r.cost):
        s = r.session
        lines.append(
            f"| {s.project[-30:]}/{s.session_id[:8]} | {len(s.calls)} | {len(s.prompts)} | {r.cost / total_cost:.0%} | "
            f"{r.context_start:,}→{r.context_max:,} | {r.cache_hit:.1%} | "
            f"{r.context_avg:,.0f}→{r.per_task_context_avg:,.0f} (−{r.per_task_saving:.0%}) |")
    shares = {k: sum(r.cost_share[k] * r.cost for r in reports) / total_cost for k in ("input", "cache_read", "cache_write", "output")}
    lines += ["", "비용 구성: " + " · ".join(f"{k} {v:.0%}" for k, v in shares.items()), ""]

    for r in sorted(reports, key=lambda r: -r.cost):
        s = r.session
        found = findings(r)
        lines += [f"## {s.project[-30:]}/{s.session_id[:8]}", ""]
        if not found:
            lines += ["눈에 띄는 낭비 패턴이 없다.", ""]
        for i, f in enumerate(found, 1):
            lines += [f"### {i}. {f.title}", "",
                      f"- **영향:** {f.impact}",
                      f"- **근거:** {f.evidence if not redact else f.evidence.split('예:')[0]}",
                      f"- **방법:** {f.advice}", ""]
        top = sorted(r.prompts, key=lambda p: -p.share)[:8]
        if top:
            lines += ["**비용이 큰 프롬프트**", "", "| 비중 | 호출 | 도구 결과 | 프롬프트 |", "|---:|---:|---:|---|"]
            lines += [f"| {p.share:.1%} | {p.calls} | {p.tool_chars / 1000:.0f}k자 | {_clip(p.text, 60, redact)} |" for p in top]
            lines.append("")
    return "\n".join(lines) + "\n"
