# -*- coding: utf-8 -*-
"""
Walk-Forward Window Scheduler (P3)

거래일 인덱스 기반으로 롤링 (train, test) 창을 생성한다. 달력일이 아니라
**실제 거래일 수**로 슬라이스하므로 공휴일 드리프트가 없다.

train_end 와 test_start 사이에 **embargo**(거래일 갭)를 둬 두 결정 구간의
인접도를 낮춘다.

⚠️ 이것은 '엄격한 정보 embargo'가 아니다: test 구간의 지표는 warmup lookback으로
train/embargo 구간의 과거 바를 의도적으로 재사용한다. 이는 지표가 과거 데이터만
쓰므로 인과적으로 유효하며(미래 참조 없음), 파라미터는 train에서만 선택된다.
따라서 embargo는 라벨 누수를 막는 장치가 아니라 구간 분리 여백일 뿐이다.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if self.train_end < self.train_start:
            raise ValueError("train_end must be on/after train_start")
        if self.test_end < self.test_start:
            raise ValueError("test_end must be on/after test_start")
        if self.train_end >= self.test_start:
            raise ValueError("train/test overlap: train_end must be before test_start")


def generate_rolling_windows(
    trading_days: list[date],
    *,
    train_size: int,
    test_size: int,
    step: int,
    embargo: int = 0,
) -> list[WalkForwardWindow]:
    """정렬된 거래일 리스트에서 롤링 창을 생성한다.

    Args:
        trading_days: 오름차순 거래일(예: 벤치마크 달력)
        train_size: train 거래일 수
        test_size: test 거래일 수
        step: 다음 fold까지 train_start 이동 거래일 수
        embargo: train_end 와 test_start 사이 갭(거래일 수)
    """
    if train_size < 1 or test_size < 1 or step < 1:
        raise ValueError("train_size/test_size/step must be >= 1")
    if embargo < 0:
        raise ValueError("embargo must be >= 0")

    days = sorted(set(trading_days))
    n = len(days)
    windows: list[WalkForwardWindow] = []

    train_start_idx = 0
    while True:
        train_end_idx = train_start_idx + train_size - 1
        test_start_idx = train_end_idx + 1 + embargo
        test_end_idx = test_start_idx + test_size - 1
        if test_end_idx >= n:
            break
        windows.append(
            WalkForwardWindow(
                train_start=days[train_start_idx],
                train_end=days[train_end_idx],
                test_start=days[test_start_idx],
                test_end=days[test_end_idx],
            )
        )
        train_start_idx += step

    return windows
