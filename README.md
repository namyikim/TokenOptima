# TokenOptima

AI 코딩 도구(Claude Code 등)와 나눈 대화 기록에서 **토큰이 어디서 새는지** 찾고, **줄이는 방법**을 제안하는 도구입니다.

1단계는 **나 자신의 기록**을 분석해 낭비 패턴과 지표를 다듬는 것이고,
장기적으로는 **팀·회사 단위**에서 개인을 평가하지 않고 사용 패턴을 개선하도록 돕는 것이 목표입니다.

## 무엇을 찾나요?

| 패턴 | 어떻게 찾나 | 줄이는 방법 |
|---|---|---|
| 여러 작업을 한 대화에서 계속 이어감 | 맥락 크기가 계속 커짐. "작업마다 새 대화였다면" 평균 맥락과 비교 | 주제가 바뀌면 새 대화. 이어 갈 규칙은 CLAUDE.md로 |
| 오래 비운 뒤 긴 대화로 돌아옴 | 60분 이상 공백 뒤 큰 캐시 쓰기 | 오래 쉬었으면 새 대화로 시작 |
| 짧은 확인 답변의 왕복 | 짧은 답("네", "A")마다 커진 맥락을 다시 읽는 첫 호출 비용 | 요청할 때 결정을 미리 담기 |
| 큰 도구 결과가 맥락에 남음 | 1만 자가 넘는 도구 결과(파일 통째 출력 등) | grep·줄 범위로 필요한 부분만 |
| 모든 일에 같은 모델·설정 | 대화 안의 모델 종류 | 대화 시작 때 일의 크기에 맞게 고르기 |

지표 정의와 계산 방법은 [docs/metrics.md](docs/metrics.md)에 있습니다.

## 실행

Python 3.9 이상, 외부 패키지 없음.

```bash
python3 -m tokenoptima analyze              # ~/.claude/projects/*/*.jsonl 전체
python3 -m tokenoptima analyze --redact     # 보고서에 프롬프트 글을 넣지 않음
python3 -m tokenoptima analyze a.jsonl --out reports/a.md
```

보고서는 기본으로 `reports/report.md`에 생깁니다. **`reports/`와 `*.jsonl`은 `.gitignore`로 막혀 있어 저장소에 올라가지 않습니다.**

## 비용은 상대값입니다

달러 금액이 아니라 Claude 공통 비율로 계산한 **상대 비용**입니다(입력 1 · 캐시 읽기 0.1 · 캐시 쓰기 1.25 · 출력 5).
모델별 실제 단가를 알면 `tokenoptima/pricing.py`의 `USD_PER_MTOK_INPUT`에 넣어 금액으로 볼 수 있게 할 예정입니다.

## 개인정보

대화 기록에는 코드·회사 정보·개인 정보가 들어 있습니다. 이 저장소는 **공개**이므로 분석 도구만 두고,
기록과 보고서는 각자 컴퓨터에만 둡니다. 팀 단위로 넓힐 때의 원칙은 [docs/privacy.md](docs/privacy.md)에 적었습니다.

## 로드맵

[docs/roadmap.md](docs/roadmap.md)

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

테스트는 코드로 만든 가짜 대화 기록만 씁니다.
