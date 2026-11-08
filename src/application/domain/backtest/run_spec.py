# -*- coding: utf-8 -*-
"""
Run Spec - walk-forward 실행 명세의 결정적 직렬화와 digest(동결·재검증용)

`canonical(value)`는 실행에 영향을 주는 설정 객체를 순서·표기 차이 없이 같은 JSON 구조로 바꾼다.
- pydantic 모델: 전체 필드(`model_dump(mode="python")`)를 재귀 정규화
- dataclass: `dataclasses.fields()` 전체 — `compare=False/hash=False` 필드도 포함한다
  (예: EntryGuardConfig.benchmark_returns는 비교에서 빠지지만 실제 매수 차단에 쓰인다)
- Decimal: float 변환 없이 정규화 문자열("1.0"과 "1.00" 동일, -0 → 0)
- 매핑: 키를 정규화해 정렬, 순서가 의미 있는 list/tuple은 순서 유지, set은 정렬
- NaN/Infinity, 알 수 없는 타입은 거부(객체 repr·내장 hash에 의존하지 않는다)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

HASH_SCHEMA_VERSION = 2


class SpecSerializationError(TypeError):
    """명세에 직렬화할 수 없는 값이 들어 있음."""


def _decimal_str(value: Decimal) -> str:
    if not value.is_finite():
        raise SpecSerializationError(f"non-finite Decimal in spec: {value}")
    if value == 0:
        return "0"
    # normalize()는 context 정밀도로 반올림하므로 쓰지 않는다(값이 다른데 digest가 같아질 수 있음).
    # format "f"는 정확한 고정소수 표기 — 소수부의 후행 0만 제거해 1.0/1.00/1E+0을 같게 만든다.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def canonical(value: Any) -> Any:
    """JSON 직렬화 가능한 결정적 구조로 변환한다."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, Enum):
        return {"enum": f"{type(value).__name__}.{value.name}", "value": canonical(value.value)}
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpecSerializationError(f"non-finite float in spec: {value}")
        return {"float": repr(0.0 if value == 0 else value)}
    if isinstance(value, Decimal):
        return {"decimal": _decimal_str(value)}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, BaseModel):
        return {
            "model": type(value).__name__,
            "fields": canonical(value.model_dump(mode="python")),
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass": type(value).__name__,
            "fields": {
                f.name: canonical(getattr(value, f.name)) for f in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        items = [(canonical(k), canonical(v)) for k, v in value.items()]
        items.sort(key=lambda kv: _dumps(kv[0]))
        return {"mapping": [[k, v] for k, v in items]}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {"set": sorted((canonical(v) for v in value), key=_dumps)}
    raise SpecSerializationError(f"unsupported type in spec: {type(value).__name__}")


def _dumps(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    """정규화 표현의 SHA-256(64자리 전체). 화면 표시는 앞부분만 잘라 쓴다."""
    return hashlib.sha256(_dumps(canonical(value)).encode("utf-8")).hexdigest()
