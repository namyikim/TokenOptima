# CLAUDE.md

AI 대화 기록에서 토큰 낭비 패턴을 찾고 줄이는 방법을 제안하는 도구. 1단계는 사용자 본인의 Claude Code 기록 분석,
장기적으로는 팀·회사 단위의 사용 개선(개인 평가가 아니라 패턴과 가이드). 로드맵은 `docs/roadmap.md`.

## 대화와 작업 방식

- 사용자와는 한국어로 대화한다. 코드 주석·커밋 메시지·문서도 한국어로 쓴다.
- 커밋·push 전에는 물어본다. push 전에는 `git pull --rebase`.
- 끝나면 실제로 확인한 것과 확인하지 못한 것을 나눠 말한다.

## 구조

| 경로 | 역할 |
|---|---|
| `tokenoptima/loader.py` | `~/.claude/projects/*/*.jsonl` 읽기(호출·프롬프트·도구 결과) |
| `tokenoptima/analyze.py` | 대화 지표와 낭비 패턴(`findings`) |
| `tokenoptima/pricing.py` | 토큰 종류별 상대 가격 |
| `tokenoptima/report.py` | 마크다운 보고서 |
| `tokenoptima/cli.py` | `python3 -m tokenoptima analyze` |
| `docs/metrics.md` | 지표 정의 — 지표를 바꾸면 여기도 고친다 |
| `tests/` | `python3 -m unittest discover -s tests -v` |

## 지킬 것

- **공개 저장소다.** 실제 대화 기록(`*.jsonl`)과 분석 보고서(`reports/`)는 올리지 않는다(`.gitignore`). 테스트·예시는 가짜 데이터만 쓴다.
  문서나 커밋 메시지에 사용자의 실제 프롬프트 글을 옮겨 적지 않는다.
- 외부 패키지 없이 **표준 라이브러리만** 쓴다(Python 3.9 이상). 이 Mac의 기본 `python3`가 3.9이고 추가 패키지가 없다.
- 도구는 기록을 네트워크로 보내지 않는다.
- 비용은 확인된 단가가 없으면 **상대 비용**으로만 보인다. 추측한 달러 금액을 넣지 않는다.
- 조언은 "누가 낭비했나"가 아니라 "어떤 패턴이 비싼가"로 쓴다. 토큰을 많이 쓴 것 자체를 나쁘다고 판정하지 않는다.

## 토큰을 아끼는 작업 방식

- 대화 기록 jsonl은 수 MB라 통째로 읽지 않는다. 구조를 볼 때는 한두 줄만, 수치는 스크립트로 요약해서 본다.
- 명령 출력은 `head`·`tail`·`grep -c`로 짧게 받는다.
- 주제가 바뀌면 새 대화를 여는 편이 싸다. 이 도구가 찾는 패턴을 우리도 따르지 않는다.
