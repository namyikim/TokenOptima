"""분석 결과를 마크다운 보고서로 쓴다.

구성: ① 한눈에 보기(총 토큰 중 줄일 수 있었던 비율) → ② 대화별 → ③ 무엇이 문제이고 어떻게 고치나
→ ④ 잘하고 있는 것 → ⑤ 대화별 세부 → ⑥ 최종 평가(효율 점수). 먼저 결론(몇 %를 줄일 수 있나)을 보이고, 그 아래에 이유와 방법을 둔다.

보고서에는 프롬프트 앞부분·파일 경로가 들어갈 수 있다. --redact 면 프롬프트 글, 폴더 이름, 명령·경로를 모두 뺀다.
기본 출력 위치 reports/ 는 .gitignore 로 막혀 있다.
"""
from __future__ import annotations

from typing import List

from .analyze import SessionReport, findings
from .pricing import relative_cost


def _clip(text: str, n: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"


def _tokens(n: float) -> str:
    """사람이 읽기 쉬운 토큰 수(억·만)."""
    if n >= 1e8:
        return f"약 {n / 1e8:.2f}억"
    if n >= 1e4:
        return f"약 {n / 1e4:,.0f}만"
    return f"{n:,.0f}"


def _name(report: SessionReport, index: int, redact: bool) -> str:
    if redact:
        return f"대화 {index}"
    folder = report.session.cwd.rstrip("/").split("/")[-1] if report.session.cwd else report.session.project[-20:]
    return f"대화 {index} ({folder})"


def _summary(reports: List[SessionReport]) -> List[str]:
    total = sum(r.total_tokens for r in reports) or 1
    avoid = sum(r.avoidable_tokens for r in reports)
    cost = sum(r.cost for r in reports) or 1
    avoid_cost = sum(r.avoidable_cost for r in reports)
    return [
        "## 1. 한눈에 보기", "",
        "| | 토큰 | 비율 |", "|---|---:|---:|",
        f"| **총 사용** | {_tokens(total)} | 100% |",
        f"| **줄일 수 있었던 양 (최대)** | {_tokens(avoid)} | **{avoid / total:.0%}** |",
        f"| **꼭 필요했던 양** | {_tokens(total - avoid)} | {1 - avoid / total:.0%} |", "",
        f"가격 차이(캐시 읽기는 정가의 10% 등)를 반영한 **비용 기준으로는 약 {avoid_cost / cost:.0%}**를 줄일 수 있었다.",
        "'최대'인 이유: 새 대화에서 파일을 다시 읽는 비용을 빼지 않았다. 실제 절감은 이보다 작다(대략 절반 이상).", "",
    ]


def _per_session(reports: List[SessionReport], redact: bool) -> List[str]:
    lines = ["## 2. 대화별", "",
             "| 대화 | 사용 토큰 | 줄일 수 있었던 비율 | 대화 길이(시작 → 최대) | 새 작업 요청 수 |",
             "|---|---:|---:|---|---:|"]
    for i, r in enumerate(reports, 1):
        share = r.avoidable_tokens / r.total_tokens if r.total_tokens else 0
        lines.append(f"| {_name(r, i, redact)} | {_tokens(r.total_tokens)} | **{share:.0%}** | "
                     f"{_tokens(r.context_start)} → {_tokens(r.context_max)} | {r.task_count} |")
    return lines + [""]


def _problems(reports: List[SessionReport]) -> List[str]:
    total = sum(r.total_tokens for r in reports) or 1
    cost = sum(r.cost for r in reports) or 1
    lines = ["## 3. 무엇이 문제이고 어떻게 고치나", "", "영향이 큰 순서다.", ""]
    items = []

    long = [r for r in reports if r.task_count >= 3 and r.per_task_saving >= 0.2]
    if long:
        reread = sum((r.totals["input"] + r.totals["cache_read"]) * r.per_task_saving for r in long)
        worst = max(long, key=lambda r: r.context_max)
        items.append((reread / total, "🔴 한 대화에 여러 작업을 계속 이어감", [
            "**문제:** 질문할 때마다 그 대화의 앞부분 전체를 다시 읽는다. 대화가 길어질수록 질문 한 번이 비싸진다.",
            f"**기록:** 대화 {len(long)}개에 새 작업 요청이 {sum(r.task_count for r in long)}개 쌓였다. "
            f"가장 긴 대화는 {_tokens(worst.context_start)} → {_tokens(worst.context_max)} 토큰까지 커졌다. "
            f"이것만으로 총 토큰의 **{reread / total:.0%}**.",
            "**고치는 법:** 주제가 바뀌면 **새 대화**를 연다. 예: '구독 기능' 끝 → 새 대화에서 '탭 디자인'. "
            "이어 가야 할 규칙은 CLAUDE.md에 적어 두면 새 대화에도 자동으로 들어간다.",
        ]))

    shorts = sum(r.short_prompt_count for r in reports)
    short_cost = sum(r.short_prompt_share * r.cost for r in reports)
    if shorts >= 3 and short_cost / cost >= 0.02:
        items.append((short_cost / cost * 0.5, "🟠 짧은 확인 답이 많음 (\"네\", \"A\", \"2\")", [
            "**문제:** 한 글자 답에도 긴 대화 전체를 다시 읽는다. 오가는 횟수만큼 비용이 붙는다.",
            f"**기록:** 확인 왕복 {shorts}번. 다시 읽는 데만 비용의 **{short_cost / cost:.0%}**.",
            "**고치는 법:** 요청할 때 결정을 미리 담는다. 예: '메인에도 구독 버튼 넣고, 테스트 통과하면 커밋·push까지 해줘'. "
            "AI가 선택지를 물을 것 같은 일은 원하는 쪽을 먼저 적는다.",
        ]))

    breaks = [b for r in reports for b in r.idle_breaks]
    if breaks:
        rewritten = sum(b.rewritten_tokens for b in breaks)
        items.append((rewritten / total, "🟡 오래 쉬었다가 같은 긴 대화로 돌아옴", [
            "**문제:** 쉬는 동안 할인(캐시)이 만료되어, 돌아온 첫 질문에서 대화 전체를 비싼 값으로 다시 저장한다.",
            f"**기록:** {len(breaks)}번, 가장 긴 공백 {max(b.gap_minutes for b in breaks):.0f}분. "
            f"{_tokens(rewritten)} 토큰을 다시 저장했다.",
            "**고치는 법:** 한 시간 넘게 쉬었다면 긴 대화를 이어가지 말고 새 대화로 시작한다.",
        ]))

    big = [t for r in reports for t in r.big_tool_results]
    if big:
        items.append((0.005, "🟡 큰 출력이 대화에 남음", [
            "**문제:** 파일 전체 같은 큰 출력은 대화에 남아, 이후 모든 질문에서 다시 읽힌다.",
            f"**기록:** 1만 자가 넘는 출력 {len(big)}건, 합계 {sum(t.size for t in big) / 1000:.0f}k자. "
            "대부분 AI가 스스로 실행한 명령의 출력이다.",
            "**고치는 법:** CLAUDE.md에 '큰 파일은 필요한 부분만 읽고, 출력은 짧게 받는다'를 적어 둔다. "
            "코드 전체를 봐야 할 때만 한 번 출력하게 한다.",
        ]))

    models = sorted({m for r in reports for m in r.models})
    if len(models) <= 2 and sum(r.task_count for r in reports) >= 5:
        items.append((0.001, "⚪ 모든 일에 가장 무거운 설정", [
            "**문제:** 간단한 일(`git pull`, 문구 수정)도 큰 모델로 하면 같은 일에 돈이 더 든다.",
            f"**기록:** 쓴 모델 {', '.join(models)}.",
            "**고치는 법:** 간단한 일만 할 대화는 시작할 때 가벼운 모델이나 낮은 effort를 고른다. "
            "대화 중간에 바꾸면 할인(캐시)이 깨지므로 시작할 때 정한다.",
        ]))

    for _, title, body in sorted(items, key=lambda x: -x[0]):
        lines += [f"### {title}", ""] + [f"- {b}" for b in body] + [""]
    if not items:
        lines += ["눈에 띄는 낭비 패턴이 없다.", ""]
    return lines


def _good(reports: List[SessionReport]) -> List[str]:
    read = sum(r.totals["input"] + r.totals["cache_read"] + r.totals["cache_write"] for r in reports) or 1
    hit = sum(r.totals["cache_read"] for r in reports) / read
    lines = ["## 4. 잘하고 있는 것", ""]
    if hit >= 0.9:
        lines.append(f"- ✅ **할인(캐시) 적중률 {hit:.1%}** — 다시 읽는 내용의 대부분을 정가의 10%로 읽고 있다. "
                     "다만 이것은 **단가**가 싸다는 뜻이고, 읽는 **양**이 많으면 총액은 커진다(위 3절).")
    small = [r for r in reports if r.task_count <= 1 and len(r.session.calls) <= 10]
    if small:
        lines.append(f"- ✅ **짧게 끝낸 대화 {len(small)}개** — 한 가지 일을 새 대화에서 바로 끝냈다. 이렇게 쓰면 싸다.")
    if len(lines) == 2:
        lines.append("- (해당 없음)")
    return lines + [""]


def _details(reports: List[SessionReport], redact: bool) -> List[str]:
    lines = ["## 5. 대화별 세부", ""]
    for i, r in enumerate(reports, 1):
        lines += [f"### {_name(r, i, redact)}", "",
                  f"호출 {len(r.session.calls)}번 · 프롬프트 {len(r.session.prompts)}개 · 할인 적중 {r.cache_hit:.1%} · "
                  f"질문 한 번의 평균 대화 길이 {_tokens(r.context_avg)} → 작업마다 새 대화였다면 {_tokens(r.per_task_context_avg)}", ""]
        for f in findings(r):
            evidence = f.evidence
            if redact:
                evidence = evidence.split("예:")[0].strip() or "(가림)"
                if f.title == "큰 도구 결과가 맥락에 남음":
                    evidence = "(명령·경로 가림)"
            lines.append(f"- **{f.title}** — {f.impact}. {evidence}")
        top = sorted(r.prompts, key=lambda p: -p.share)[:5]
        if top:
            lines += ["", "| 비용 비중 | 호출 | 프롬프트 |", "|---:|---:|---|"]
            lines += [f"| {p.share:.1%} | {p.calls} | {f'({len(p.text)}자)' if redact else _clip(p.text, 60)} |" for p in top]
        lines.append("")
    return lines


# 효율 점수의 등급 경계(이상). docs/metrics.md 와 맞춘다.
GRADES = ((90, "A", "효율적으로 쓰고 있다"), (75, "B", "대체로 좋다. 3절의 첫 항목만 고쳐도 오른다"),
          (60, "C", "고칠 여지가 크다. 3절을 차례로 적용해 본다"), (0, "D", "같은 일을 훨씬 싸게 할 수 있다. 3절의 첫 항목부터"))


def score(reports: List[SessionReport]) -> int:
    """효율 점수(0~100) = 100 × (1 − 비용 기준 줄일 수 있었던 비율). 쓴 양이 아니라 쓰는 방식을 본다."""
    cost = sum(r.cost for r in reports)
    if not cost:
        return 100
    avoid = sum(r.avoidable_cost for r in reports)
    return max(0, min(100, round(100 * (1 - avoid / cost))))


def _verdict(reports: List[SessionReport]) -> List[str]:
    cost = sum(r.cost for r in reports) or 1
    reread = sum(r.avoidable_cost - sum(relative_cost(0, 0, b.rewritten_tokens, 0) for b in r.idle_breaks)
                 for r in reports)
    idle = sum(relative_cost(0, 0, b.rewritten_tokens, 0) for r in reports for b in r.idle_breaks)
    value = score(reports)
    grade, comment = next((g, c) for bound, g, c in GRADES if value >= bound)
    return [
        "## 6. 최종 평가", "",
        f"### 효율 점수: **{value}점 / 100** (등급 {grade})", "",
        f"{comment}.", "",
        "| 항목 | 점수 |", "|---|---:|",
        "| 기본 | 100 |",
        f"| − 한 대화에 여러 작업을 이어감 | −{100 * reread / cost:.0f} |",
        f"| − 오래 쉬었다가 돌아와 캐시를 다시 씀 | −{100 * idle / cost:.0f} |",
        f"| **효율 점수** | **{value}** |", "",
        "- 점수 = 100 × (1 − 비용 기준 줄일 수 있었던 비율). 등급: A 90 이상 · B 75 이상 · C 60 이상 · D 그 아래. 반올림 때문에 항목 합이 1점 다를 수 있다.",
        "- **토큰을 많이 쓴 양은 점수에 들어가지 않는다.** 같은 일을 얼마나 싸게 했는가(쓰는 방식)만 본다.",
        "- 줄일 수 있었던 양이 상한이므로 이 점수는 **보수적(낮게 나오는 쪽)** 이다. 사람끼리 줄 세우는 데 쓰지 않는다.", "",
    ]


# 보고서의 절 제목. 누구를 분석하든 이 순서·이름을 지킨다(tests 가 고정한다).
SECTIONS = ("## 1. 한눈에 보기", "## 2. 대화별", "## 3. 무엇이 문제이고 어떻게 고치나",
            "## 4. 잘하고 있는 것", "## 5. 대화별 세부", "## 6. 최종 평가")


def render(reports: List[SessionReport], redact: bool = False, name: str = "") -> str:
    """보고서 한 편. name 은 분석 대상(사람·가명)으로 제목에만 들어간다. 비우면 제목에 이름이 없다."""
    reports = sorted(reports, key=lambda r: -r.total_tokens)
    title = f"# 토큰 사용 분석 보고서 — {name}" if name else "# 토큰 사용 분석 보고서"
    period = [c.time for r in reports for c in r.session.calls if c.time]
    lines = [title, ""]
    if period:
        lines += [f"기간: {min(period):%Y-%m-%d} ~ {max(period):%Y-%m-%d} · 대화 {len(reports)}개", ""]
    lines += ["토큰 수는 AI가 실제로 읽고 쓴 양이다. 비용 비율은 달러가 아니라 상대값"
              "(입력 1 · 캐시 읽기 0.1 · 캐시 쓰기 1.25 · 출력 5)으로 계산했다. 계산 방법은 `docs/metrics.md`.", ""]
    lines += _summary(reports) + _per_session(reports, redact) + _problems(reports) + _good(reports) + _details(reports, redact)
    lines += _verdict(reports)
    return "\n".join(lines) + "\n"
