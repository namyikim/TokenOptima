"""명령줄 진입점.

    python -m tokenoptima analyze                          # 내 기록(~/.claude/projects) 전체
    python -m tokenoptima analyze --redact                 # 프롬프트 글·경로를 가린 판
    python -m tokenoptima analyze --root <폴더> --name 홍길동   # 다른 사람이 보내 준 projects 폴더
    python -m tokenoptima analyze-team <팀 폴더>            # 사람마다 보고서 한 편씩(같은 형식)

팀 폴더는 사람마다 하위 폴더 하나다. 그 안은 ~/.claude/projects 를 그대로 복사한 것이거나
(<사람>/<프로젝트>/<세션>.jsonl), projects 폴더째 넣은 것(<사람>/projects/<프로젝트>/<세션>.jsonl) 둘 다 된다.
폴더 이름이 보고서 제목의 이름이 되므로, 실명 대신 가명 폴더를 쓰는 것을 권한다(docs/privacy.md).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from .analyze import analyse
from .loader import default_paths, load_all
from .report import render, score


def _person_paths(folder: Path) -> List[Path]:
    projects = folder / "projects"
    return default_paths(projects if projects.is_dir() else folder)


def _write(paths: List[Path], out: Path, name: str, redact: bool) -> bool:
    sessions = load_all(paths)
    if not sessions:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    reports = [analyse(s) for s in sessions]
    out.write_text(render(reports, redact=redact, name=name), encoding="utf-8")
    print(f"{name or '나'}: 대화 {len(sessions)}개 · 효율 점수 {score(reports)}/100 → {out}")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tokenoptima", description="AI 대화 기록의 토큰 낭비 분석")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("analyze", help="한 사람의 기록을 분석해 보고서 한 편을 쓴다")
    one.add_argument("paths", nargs="*", type=Path, help="jsonl 파일(없으면 --root 또는 ~/.claude/projects)")
    one.add_argument("--root", type=Path, help="분석할 projects 폴더(다른 사람이 보내 준 것)")
    one.add_argument("--name", default="", help="보고서 제목에 넣을 이름(가명 권장)")
    one.add_argument("--out", type=Path, default=Path("reports/report.md"), help="보고서 경로(기본 reports/report.md)")
    one.add_argument("--redact", action="store_true", help="프롬프트 글·폴더 이름·명령·경로를 가린다")

    team = sub.add_parser("analyze-team", help="팀 폴더 안의 사람마다 같은 형식의 보고서를 쓴다")
    team.add_argument("folder", type=Path, help="사람마다 하위 폴더가 있는 팀 폴더")
    team.add_argument("--out-dir", type=Path, default=Path("reports/team"), help="보고서 폴더(기본 reports/team)")
    team.add_argument("--no-redact", action="store_true",
                      help="프롬프트 글을 넣는다(기본은 가린 판 — 남의 대화 내용을 보고서에 옮기지 않는다)")
    args = parser.parse_args(argv)

    if args.command == "analyze":
        paths = args.paths or (_person_paths(args.root) if args.root else default_paths())
        if not _write(paths, args.out, args.name, args.redact):
            print("분석할 대화가 없습니다(토큰 기록이 있는 jsonl 을 찾지 못했습니다).")
            return 1
        return 0

    people = sorted(p for p in args.folder.iterdir() if p.is_dir())
    done = sum(_write(_person_paths(p), args.out_dir / f"{p.name}.md", p.name, not args.no_redact) for p in people)
    print(f"{done}명 보고서 작성(폴더 {len(people)}개 중)")
    return 0 if done else 1
