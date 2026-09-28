"""토큰 종류별 상대 가격.

모델마다 달러 가격은 다르고 자주 바뀌지만, 한 모델 안에서 토큰 종류 사이의 비율은 Claude 공통이다.
그래서 기본값은 '입력 1'에 대한 상대값으로 계산한다. 실제 금액이 필요하면 모델별 입력 단가(100만 토큰당 달러)를
USD_PER_MTOK_INPUT 에 넣는다 — 비워 두면 보고서는 상대 비용만 보인다(틀린 달러를 보이는 것보다 낫다).
"""
from __future__ import annotations

from typing import Dict, Optional

RELATIVE = {
    "input": 1.0,
    "cache_read": 0.1,     # 캐시 읽기
    "cache_write": 1.25,   # 5분 캐시 쓰기(1시간 캐시는 2.0)
    "output": 5.0,
}

# 예: {"claude-opus-5-5": 5.0}. 확인한 값만 넣는다.
USD_PER_MTOK_INPUT: Dict[str, float] = {}


def relative_cost(input_tokens: int, cache_read: int, cache_write: int, output_tokens: int) -> float:
    return (input_tokens * RELATIVE["input"] + cache_read * RELATIVE["cache_read"]
            + cache_write * RELATIVE["cache_write"] + output_tokens * RELATIVE["output"])


def usd(model: str, relative: float) -> Optional[float]:
    rate = USD_PER_MTOK_INPUT.get(model)
    return None if rate is None else relative * rate / 1_000_000
