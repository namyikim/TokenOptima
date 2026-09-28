"""명령줄 진입점.

    python -m tokenoptima analyze                    # ~/.claude/projects 의 모든 대화
    python -m tokenoptima analyze a.jsonl b.jsonl    # 지정한 대화만
    python -m tokenoptima analyze --redact           # 보고서에 프롬프트 글을 넣지 않음
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .analyze import analyse
from .loader import default_paths, load_all
from .report import render


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tokenoptima", description="Claude Code 대화 기록의 토큰 낭비 분석")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("analyze", help="대화 기록을 분석해 마크다운 보고서를 쓴다")
    run.add_argument("paths", nargs="*", type=Path, help="jsonl 파일(없으면 ~/.claude/projects/*/*.jsonl)")
    run.add_argument("--out", type=Path, default=Path("reports/report.md"), help="보고서 경로(기본 reports/report.md)")
    run.add_argument("--redact", action="store_true", help="보고서에 프롬프트 글을 넣지 않는다")
    args = parser.parse_args(argv)

    paths = args.paths or default_paths()
    sessions = load_all(paths)
    if not sessions:
        print("분석할 대화가 없습니다(토큰 기록이 있는 jsonl 을 찾지 못했습니다).")
        return 1
    text = render([analyse(s) for s in sessions], redact=args.redact)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"대화 {len(sessions)}개 분석 → {args.out}")
    return 0
