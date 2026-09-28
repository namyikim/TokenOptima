"""가짜 대화 기록으로 읽기·지표·조언을 확인한다. 실제 대화 기록은 저장소에 두지 않는다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tokenoptima.analyze import analyse, findings, per_task_context  # noqa: E402
from tokenoptima.loader import load_session  # noqa: E402
from tokenoptima.cli import main  # noqa: E402
from tokenoptima.report import SECTIONS, render, score  # noqa: E402


def _ts(minute):
    return f"2026-09-28T{9 + minute // 60:02d}:{minute % 60:02d}:00Z"


class Builder:
    def __init__(self):
        self.lines = []
        self.n = 0

    def prompt(self, text, minute):
        self.lines.append({"type": "user", "timestamp": _ts(minute), "message": {"role": "user", "content": text}})

    def call(self, context, minute, write=0, output=100, tool=None, result_size=0):
        self.n += 1
        content = []
        if tool:
            content.append({"type": "tool_use", "id": f"t{self.n}", "name": "Bash", "input": {"command": tool}})
        usage = {"input_tokens": 1, "cache_read_input_tokens": context - write - 1,
                 "cache_creation_input_tokens": write, "output_tokens": output}
        record = {"type": "assistant", "timestamp": _ts(minute),
                  "message": {"id": f"m{self.n}", "model": "claude-test", "usage": usage, "content": content}}
        self.lines.append(record)
        self.lines.append(record)      # 스트리밍으로 같은 id 가 두 번 나와도 한 번만 센다
        if tool:
            self.lines.append({"type": "user", "timestamp": _ts(minute), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{self.n}", "content": "x" * result_size}]}})

    def write(self, directory):
        path = Path(directory) / "proj" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(r) for r in self.lines) + "\n", encoding="utf-8")
        return path


def long_session():
    """작업 넷을 한 대화에서 이어가고, 80분 쉬었다 돌아오고, 짧은 확인 답변이 섞인 대화."""
    b = Builder()
    minute = 0
    context = 50_000
    for task in range(4):
        b.prompt(f"작업 {task}: 관리자 페이지에 새 화면을 추가하고 테스트까지 확인해 주세요", minute)
        for step in range(5):
            context += 8_000
            minute += 1
            b.call(context, minute, write=8_000, tool="cat big_file.js" if step == 0 else "ls", result_size=20_000 if step == 0 else 100)
        b.prompt("네", minute + 1)
        minute += 2
        b.call(context, minute)
    minute += 80
    b.prompt("다시 왔습니다. 이어서 README 를 고쳐 주세요 부탁합니다", minute)
    b.call(context + 1_000, minute + 1, write=context)
    return b


class LoaderTests(unittest.TestCase):
    def test_counts_calls_once_and_separates_prompts_from_tool_results(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_session(long_session().write(d))
        self.assertEqual(len(s.calls), 4 * 6 + 1)
        self.assertEqual(len(s.prompts), 4 * 2 + 1)
        self.assertEqual(s.project, "proj")
        big = [t for t in s.tool_results if t.size >= 20_000]
        self.assertEqual(len(big), 4)
        self.assertEqual(big[0].summary, "cat big_file.js")

    def test_system_notifications_are_not_prompts(self):
        b = Builder()
        b.prompt("<task-notification>done</task-notification>", 0)
        b.prompt("진짜 질문", 1)
        b.call(1000, 2)
        with tempfile.TemporaryDirectory() as d:
            s = load_session(b.write(d))
        self.assertEqual([p.text for p in s.prompts], ["진짜 질문"])


class AnalyseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as d:
            cls.session = load_session(long_session().write(d))
        cls.report = analyse(cls.session)

    def test_totals_and_cache_hit(self):
        r = self.report
        self.assertEqual(r.totals["input"], len(self.session.calls))
        self.assertGreater(r.cache_hit, 0.5)
        self.assertAlmostEqual(sum(r.cost_share.values()), 1.0, places=6)
        self.assertEqual(r.context_start, 58_000)

    def test_per_task_simulation_is_smaller_than_actual(self):
        r = self.report
        self.assertEqual(r.task_count, 5)
        self.assertLess(r.per_task_context_avg, r.context_avg)
        self.assertGreater(r.per_task_saving, 0.2)
        # 작업 경계가 없으면 실제와 같다
        self.assertAlmostEqual(per_task_context(self.session, []), r.context_avg)

    def test_idle_break_is_detected(self):
        self.assertEqual(len(self.report.idle_breaks), 1)
        self.assertGreaterEqual(self.report.idle_breaks[0].gap_minutes, 60)

    def test_findings_are_ranked_and_cover_the_patterns(self):
        found = findings(self.report)
        weights = [f.weight for f in found]
        self.assertEqual(weights, sorted(weights, reverse=True), "영향이 큰 순서")
        titles = [f.title for f in found]
        for expected in ("여러 작업을 한 대화에서 계속 이어감", "오래 비운 뒤 긴 대화로 돌아옴(캐시 만료)",
                         "짧은 확인 답변이 큰 맥락을 다시 읽음", "큰 도구 결과가 맥락에 남음"):
            self.assertIn(expected, titles)

    def test_report_redacts_prompt_text(self):
        plain = render([self.report])
        hidden = render([self.report], redact=True)
        self.assertIn("관리자 페이지에 새 화면", plain)
        self.assertNotIn("관리자 페이지에 새 화면", hidden)
        self.assertNotIn("| 네 |", hidden)
        self.assertNotIn("cat big_file.js", hidden)



def short_session():
    """새 대화에서 한 가지 일만 하고 끝낸 사람 — 낭비 패턴이 거의 없다."""
    b = Builder()
    b.prompt("README 오타 하나만 고쳐 주세요 부탁드립니다 감사합니다", 0)
    b.call(50_000, 1, write=50_000)
    b.call(51_000, 2)
    return b


class FormatTests(unittest.TestCase):
    """누구를 분석하든 같은 형식: 같은 절이 같은 순서로 나온다."""

    def sections_of(self, text):
        return [line for line in text.splitlines() if line.startswith("## ")]

    def test_same_sections_for_heavy_and_light_users(self):
        with tempfile.TemporaryDirectory() as d:
            heavy = render([analyse(load_session(long_session().write(Path(d) / "a")))], name="가명A")
            light = render([analyse(load_session(short_session().write(Path(d) / "b")))], name="가명B")
        for text in (heavy, light):
            self.assertEqual(self.sections_of(text), list(SECTIONS))
        self.assertTrue(heavy.startswith("# 토큰 사용 분석 보고서 — 가명A"))
        self.assertIn("| **줄일 수 있었던 양 (최대)** |", light)
        self.assertNotIn("내 기록", heavy)

    def test_score_ends_the_report_and_rewards_short_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            heavy = [analyse(load_session(long_session().write(Path(d) / "a")))]
            light = [analyse(load_session(short_session().write(Path(d) / "b")))]
        self.assertLess(score(heavy), score(light))
        for reports in (heavy, light):
            self.assertTrue(0 <= score(reports) <= 100)
            text = render(reports)
            self.assertIn(f"### 효율 점수: **{score(reports)}점 / 100**", text)
            self.assertEqual(self.sections_of(text)[-1], "## 6. 최종 평가")

    def test_team_command_writes_one_redacted_report_per_person(self):
        with tempfile.TemporaryDirectory() as d:
            team = Path(d) / "team"
            long_session().write(team / "person1")                 # <사람>/<프로젝트>/<세션>.jsonl
            short_session().write(team / "person2" / "projects")    # <사람>/projects/<프로젝트>/<세션>.jsonl
            (team / "empty").mkdir(parents=True)
            out = Path(d) / "out"
            self.assertEqual(main(["analyze-team", str(team), "--out-dir", str(out)]), 0)
            reports = sorted(p.name for p in out.iterdir())
            self.assertEqual(reports, ["person1.md", "person2.md"])
            text = (out / "person1.md").read_text(encoding="utf-8")
        self.assertEqual(self.sections_of(text), list(SECTIONS))
        self.assertIn("— person1", text)
        self.assertNotIn("관리자 페이지에 새 화면", text, "팀 보고서는 기본으로 프롬프트 글을 가린다")


if __name__ == "__main__":
    unittest.main()
