# 백테스팅 성과 지표 가이드

## 📋 목차
1. [개요](#개요)
2. [수익 지표](#수익-지표)
3. [리스크 지표](#리스크-지표)
4. [거래 통계](#거래-통계)
5. [벤치마크 비교](#벤치마크-비교)
6. [종합 성과 분석](#종합-성과-분석)

---

## 개요

백테스팅 결과를 정량적으로 평가하기 위한 다양한 성과 지표를 제공합니다. 각 지표는 전략의 수익성, 안정성, 효율성을 다각도로 측정합니다.

### 지표 카테고리

| 카테고리 | 주요 지표 | 목적 |
|---------|---------|------|
| **수익 지표** | 총 수익률, 연환산 수익률, CAGR | 전략의 수익성 측정 |
| **리스크 지표** | MDD, 변동성, Sharpe Ratio | 전략의 안정성 측정 |
| **거래 통계** | 승률, Profit Factor, 평균 거래 | 전략의 효율성 측정 |
| **벤치마크 비교** | Alpha, Beta, Tracking Error | 시장 대비 성과 |

---

## 수익 지표

### 1. 총 수익률 (Total Return)

전체 백테스팅 기간 동안의 누적 수익률

#### 계산식

```
총 수익률 = (최종 자산 - 초기 자산) / 초기 자산 × 100%
```

#### Python 구현

```python
from decimal import Decimal

def calculate_total_return(
    initial_capital: Decimal,
    final_capital: Decimal
) -> float:
    """
    총 수익률 계산

    Args:
        initial_capital: 초기 자본
        final_capital: 최종 자본

    Returns:
        float: 총 수익률 (%)
    """
    total_return = (final_capital - initial_capital) / initial_capital * 100

    return float(total_return)
```

#### 예제

```python
# 초기 자본: 1,000만원
# 최종 자본: 1,300만원
total_return = calculate_total_return(
    Decimal("10_000_000"),
    Decimal("13_000_000")
)
print(f"총 수익률: {total_return:.2f}%")  # 30.00%
```

### 2. 연환산 수익률 (Annualized Return)

1년 단위로 환산한 평균 수익률

#### 계산식

```
연환산 수익률 = ((최종 자산 / 초기 자산) ^ (365 / 총 거래일수) - 1) × 100%
```

#### Python 구현

```python
from datetime import datetime

def calculate_annualized_return(
    initial_capital: Decimal,
    final_capital: Decimal,
    start_date: datetime,
    end_date: datetime
) -> float:
    """
    연환산 수익률 계산

    Args:
        initial_capital: 초기 자본
        final_capital: 최종 자본
        start_date: 시작일
        end_date: 종료일

    Returns:
        float: 연환산 수익률 (%)
    """
    total_days = (end_date - start_date).days

    if total_days == 0:
        return 0.0

    # 연환산 계산
    annualized_return = (
        (float(final_capital / initial_capital)) ** (365 / total_days) - 1
    ) * 100

    return annualized_return
```

#### 예제

```python
# 2년간 30% 수익
annualized = calculate_annualized_return(
    Decimal("10_000_000"),
    Decimal("13_000_000"),
    datetime(2022, 1, 1),
    datetime(2024, 1, 1)
)
print(f"연환산 수익률: {annualized:.2f}%")  # 약 14.02%
```

### 3. CAGR (Compound Annual Growth Rate)

복리 연평균 성장률

#### 계산식

```
CAGR = ((최종 자산 / 초기 자산) ^ (1 / 연수) - 1) × 100%
```

#### Python 구현

```python
def calculate_cagr(
    initial_capital: Decimal,
    final_capital: Decimal,
    years: float
) -> float:
    """
    CAGR 계산

    Args:
        initial_capital: 초기 자본
        final_capital: 최종 자본
        years: 연수

    Returns:
        float: CAGR (%)
    """
    if years <= 0:
        return 0.0

    cagr = (
        (float(final_capital / initial_capital)) ** (1 / years) - 1
    ) * 100

    return cagr
```

### 4. 월별 수익률

매월 수익률 분석

#### Python 구현

```python
import pandas as pd

def calculate_monthly_returns(equity_curve: pd.DataFrame) -> pd.Series:
    """
    월별 수익률 계산

    Args:
        equity_curve: 날짜별 자산 가치 DataFrame
                     (컬럼: date, equity)

    Returns:
        pd.Series: 월별 수익률 (%)
    """
    # 월별 마지막 날 자산 가치
    monthly_equity = equity_curve.resample('M', on='date')['equity'].last()

    # 월별 수익률
    monthly_returns = monthly_equity.pct_change() * 100

    return monthly_returns
```

#### 예제

```python
# 자산 곡선 데이터
equity_df = pd.DataFrame({
    'date': pd.date_range('2023-01-01', '2023-12-31', freq='D'),
    'equity': [10_000_000 + i * 10_000 for i in range(365)]
})

monthly_returns = calculate_monthly_returns(equity_df)
print(monthly_returns)
```

---

## 리스크 지표

### 1. MDD (Maximum Drawdown)

최대 낙폭 - 고점에서 저점까지의 최대 하락률

#### 계산식

```
MDD = (저점 - 고점) / 고점 × 100%
```

#### Python 구현

```python
import numpy as np

def calculate_mdd(equity_curve: list[Decimal]) -> dict[str, any]:
    """
    MDD 계산

    Args:
        equity_curve: 날짜별 자산 가치 리스트

    Returns:
        dict: MDD 정보
    """
    equity_array = np.array([float(e) for e in equity_curve])

    # 누적 최대값
    cummax = np.maximum.accumulate(equity_array)

    # 낙폭 계산
    drawdown = (equity_array - cummax) / cummax * 100

    # MDD
    mdd = drawdown.min()

    # MDD 발생 지점
    mdd_index = drawdown.argmin()
    peak_index = cummax[:mdd_index].argmax() if mdd_index > 0 else 0

    return {
        "mdd": mdd,
        "peak_index": int(peak_index),
        "valley_index": int(mdd_index),
        "recovery_days": len(equity_array) - mdd_index if mdd < -0.01 else 0,
    }
```

#### 예제

```python
# 자산 곡선
equity = [
    Decimal("10_000_000"),
    Decimal("11_000_000"),
    Decimal("10_500_000"),  # 낙폭 시작
    Decimal("9_000_000"),   # 최저점
    Decimal("10_000_000"),
]

mdd_info = calculate_mdd(equity)
print(f"MDD: {mdd_info['mdd']:.2f}%")  # -18.18%
print(f"회복 기간: {mdd_info['recovery_days']}일")
```

### 2. 변동성 (Volatility)

수익률의 표준편차 (연환산)

#### 계산식

```
변동성 = 일별 수익률의 표준편차 × √252
```

#### Python 구현

```python
def calculate_volatility(equity_curve: pd.DataFrame) -> float:
    """
    연환산 변동성 계산

    Args:
        equity_curve: 날짜별 자산 가치 DataFrame

    Returns:
        float: 연환산 변동성 (%)
    """
    # 일별 수익률
    daily_returns = equity_curve['equity'].pct_change().dropna()

    # 연환산 변동성 (252 거래일 기준)
    volatility = daily_returns.std() * np.sqrt(252) * 100

    return volatility
```

### 3. Sharpe Ratio

위험 대비 수익률 (무위험 수익률 고려)

#### 계산식 (2026-11-06 변경)

```
Sharpe = mean(r_d − rf_d) / std(r_d, ddof=1) × √252,   rf_d = (1 + rf_연)^(1/252) − 1  (기본 rf_연 = 3%)
```

- 구현: `src/application/common/performance_metrics.py` `calculate_daily_sharpe_ratio`
- 결과·walk-forward 리포트는 `sharpe`(rf 3%)와 `sharpe_rf0`(DSR과 같은 rf=0 기준)를 함께 낸다.
- 이전 정의 `(CAGR − 3%) / 연 변동성`(`calculate_sharpe_ratio`)은 DSR과 기준이 달라 제거했다.

#### 해석 가이드

| Sharpe Ratio | 평가 |
|--------------|------|
| < 0 | 무위험 자산보다 낮음 |
| 0 ~ 1 | 보통 |
| 1 ~ 2 | 좋음 |
| 2 ~ 3 | 매우 좋음 |
| > 3 | 탁월함 |

### 4. Sortino Ratio

하방 위험만 고려한 위험 대비 수익률

#### 계산식

```
Sortino Ratio = (연환산 수익률 - 무위험 수익률) / 하방 변동성
하방 변동성 = 음수 수익률의 표준편차 × √252
```

#### Python 구현

```python
def calculate_sortino_ratio(
    equity_curve: pd.DataFrame,
    annualized_return: float,
    risk_free_rate: float = 3.0
) -> float:
    """
    Sortino Ratio 계산

    Args:
        equity_curve: 날짜별 자산 가치 DataFrame
        annualized_return: 연환산 수익률 (%)
        risk_free_rate: 무위험 이자율 (%)

    Returns:
        float: Sortino Ratio
    """
    # 일별 수익률
    daily_returns = equity_curve['equity'].pct_change().dropna()

    # 음수 수익률만 추출
    negative_returns = daily_returns[daily_returns < 0]

    # 하방 변동성
    downside_volatility = negative_returns.std() * np.sqrt(252) * 100

    if downside_volatility == 0:
        return 0.0

    sortino = (annualized_return - risk_free_rate) / downside_volatility

    return sortino
```

### 5. Calmar Ratio

수익률 / MDD 비율

#### 계산식

```
Calmar Ratio = 연환산 수익률 / |MDD|
```

#### Python 구현

```python
def calculate_calmar_ratio(
    annualized_return: float,
    mdd: float
) -> float:
    """
    Calmar Ratio 계산

    Args:
        annualized_return: 연환산 수익률 (%)
        mdd: MDD (%)

    Returns:
        float: Calmar Ratio
    """
    if mdd >= 0:
        return 0.0

    calmar = annualized_return / abs(mdd)

    return calmar
```

#### 예제

```python
calmar = calculate_calmar_ratio(
    annualized_return=15.0,  # 15% 수익률
    mdd=-10.0                # -10% MDD
)
print(f"Calmar Ratio: {calmar:.2f}")  # 1.50
```

### 6. VaR (Value at Risk)

특정 신뢰수준에서 예상 최대 손실

#### 계산식 (Historical VaR)

```
VaR (95%) = 일별 수익률의 5% 분위수
```

#### Python 구현

```python
def calculate_var(
    equity_curve: pd.DataFrame,
    confidence_level: float = 0.95
) -> float:
    """
    Historical VaR 계산

    Args:
        equity_curve: 날짜별 자산 가치 DataFrame
        confidence_level: 신뢰수준 (기본 95%)

    Returns:
        float: VaR (%)
    """
    # 일별 수익률
    daily_returns = equity_curve['equity'].pct_change().dropna()

    # VaR
    var = daily_returns.quantile(1 - confidence_level) * 100

    return var
```

#### 예제

```python
var_95 = calculate_var(equity_df, confidence_level=0.95)
print(f"VaR (95%): {var_95:.2f}%")  # 예: -2.5%
# 해석: 95% 확률로 하루 손실이 -2.5%를 초과하지 않음
```

---

## 거래 통계

### 1. 총 거래 횟수

전체 진입/청산 거래 수

#### Python 구현

```python
def calculate_trade_count(trades: list[dict]) -> dict[str, int]:
    """
    거래 통계

    Args:
        trades: 거래 내역 리스트
                [{"type": "buy"/"sell", "profit": 0.05, ...}, ...]

    Returns:
        dict: 거래 통계
    """
    total = len(trades)
    wins = sum(1 for t in trades if t.get("profit", 0) > 0)
    losses = sum(1 for t in trades if t.get("profit", 0) < 0)
    breakeven = total - wins - losses

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
    }
```

### 2. 승률 (Win Rate)

이익 거래 / 전체 거래 비율

#### 계산식

```
승률 = 이익 거래 수 / 전체 거래 수 × 100%
```

#### Python 구현

```python
def calculate_win_rate(trades: list[dict]) -> float:
    """
    승률 계산

    Args:
        trades: 거래 내역

    Returns:
        float: 승률 (%)
    """
    if not trades:
        return 0.0

    wins = sum(1 for t in trades if t.get("profit", 0) > 0)

    win_rate = wins / len(trades) * 100

    return win_rate
```

### 3. Profit Factor

총 이익 / 총 손실 비율

#### 계산식

```
Profit Factor = 총 이익 / |총 손실|
```

#### Python 구현

```python
def calculate_profit_factor(trades: list[dict]) -> float:
    """
    Profit Factor 계산

    Args:
        trades: 거래 내역

    Returns:
        float: Profit Factor
    """
    total_profit = sum(t.get("profit", 0) for t in trades if t.get("profit", 0) > 0)
    total_loss = abs(sum(t.get("profit", 0) for t in trades if t.get("profit", 0) < 0))

    if total_loss == 0:
        return float('inf') if total_profit > 0 else 0.0

    profit_factor = total_profit / total_loss

    return profit_factor
```

#### 예제

```python
trades = [
    {"profit": 0.05},   # +5%
    {"profit": -0.02},  # -2%
    {"profit": 0.03},   # +3%
    {"profit": -0.01},  # -1%
]

pf = calculate_profit_factor(trades)
print(f"Profit Factor: {pf:.2f}")  # (5+3)/(2+1) = 2.67
```

#### 해석 가이드

| Profit Factor | 평가 |
|---------------|------|
| < 1.0 | 손실 전략 |
| 1.0 ~ 1.5 | 수익 나지만 개선 필요 |
| 1.5 ~ 2.0 | 양호 |
| > 2.0 | 우수 |

### 4. 평균 수익/손실

#### Python 구현

```python
def calculate_avg_profit_loss(trades: list[dict]) -> dict[str, float]:
    """
    평균 수익/손실 계산

    Args:
        trades: 거래 내역

    Returns:
        dict: 평균 수익/손실 통계
    """
    winning_trades = [t["profit"] for t in trades if t.get("profit", 0) > 0]
    losing_trades = [t["profit"] for t in trades if t.get("profit", 0) < 0]

    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0.0
    avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0.0

    return {
        "avg_win": avg_win * 100,    # %로 변환
        "avg_loss": avg_loss * 100,
        "avg_win_loss_ratio": abs(avg_win / avg_loss) if avg_loss != 0 else 0.0,
    }
```

### 5. 평균 보유 기간

#### Python 구현

```python
from datetime import timedelta

def calculate_avg_holding_period(trades: list[dict]) -> dict[str, float]:
    """
    평균 보유 기간 계산

    Args:
        trades: 거래 내역
                [{"entry_date": datetime, "exit_date": datetime, ...}, ...]

    Returns:
        dict: 평균 보유 기간 통계
    """
    if not trades:
        return {"avg_days": 0.0, "max_days": 0, "min_days": 0}

    holding_periods = [
        (t["exit_date"] - t["entry_date"]).days
        for t in trades
        if "entry_date" in t and "exit_date" in t
    ]

    if not holding_periods:
        return {"avg_days": 0.0, "max_days": 0, "min_days": 0}

    return {
        "avg_days": sum(holding_periods) / len(holding_periods),
        "max_days": max(holding_periods),
        "min_days": min(holding_periods),
    }
```

### 6. 연속 승/패 기록

#### Python 구현

```python
def calculate_consecutive_wins_losses(trades: list[dict]) -> dict[str, int]:
    """
    연속 승/패 기록

    Args:
        trades: 거래 내역

    Returns:
        dict: 연속 승/패 통계
    """
    if not trades:
        return {
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "current_streak": 0,
        }

    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for trade in trades:
        profit = trade.get("profit", 0)

        if profit > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        elif profit < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)

    # 현재 연속 기록
    current_streak = current_wins if current_wins > 0 else -current_losses

    return {
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "current_streak": current_streak,
    }
```

---

## 벤치마크 비교

### 1. Alpha

벤치마크 대비 초과 수익률

#### 계산식

```
Alpha = 전략 수익률 - (무위험 이자율 + Beta × (시장 수익률 - 무위험 이자율))
```

#### Python 구현

```python
def calculate_alpha(
    strategy_return: float,
    market_return: float,
    beta: float,
    risk_free_rate: float = 3.0
) -> float:
    """
    Alpha 계산

    Args:
        strategy_return: 전략 수익률 (%)
        market_return: 시장 수익률 (%)
        beta: 베타 계수
        risk_free_rate: 무위험 이자율 (%)

    Returns:
        float: Alpha (%)
    """
    expected_return = risk_free_rate + beta * (market_return - risk_free_rate)
    alpha = strategy_return - expected_return

    return alpha
```

### 2. Beta

시장 민감도

#### 계산식

```
Beta = Cov(전략 수익률, 시장 수익률) / Var(시장 수익률)
```

#### Python 구현

```python
def calculate_beta(
    strategy_returns: pd.Series,
    market_returns: pd.Series
) -> float:
    """
    Beta 계산

    Args:
        strategy_returns: 전략 일별 수익률
        market_returns: 시장 일별 수익률

    Returns:
        float: Beta
    """
    # 공분산
    covariance = strategy_returns.cov(market_returns)

    # 시장 분산
    market_variance = market_returns.var()

    if market_variance == 0:
        return 0.0

    beta = covariance / market_variance

    return beta
```

### 3. Tracking Error

벤치마크와의 수익률 차이 변동성

#### 계산식

```
Tracking Error = Std(전략 수익률 - 벤치마크 수익률) × √252
```

#### Python 구현

```python
def calculate_tracking_error(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series
) -> float:
    """
    Tracking Error 계산

    Args:
        strategy_returns: 전략 일별 수익률
        benchmark_returns: 벤치마크 일별 수익률

    Returns:
        float: Tracking Error (%)
    """
    # 초과 수익률
    excess_returns = strategy_returns - benchmark_returns

    # 연환산 표준편차
    tracking_error = excess_returns.std() * np.sqrt(252) * 100

    return tracking_error
```

### 4. Information Ratio

벤치마크 대비 위험 조정 수익률

#### 계산식

```
Information Ratio = (전략 수익률 - 벤치마크 수익률) / Tracking Error
```

#### Python 구현

```python
def calculate_information_ratio(
    strategy_return: float,
    benchmark_return: float,
    tracking_error: float
) -> float:
    """
    Information Ratio 계산

    Args:
        strategy_return: 전략 수익률 (%)
        benchmark_return: 벤치마크 수익률 (%)
        tracking_error: Tracking Error (%)

    Returns:
        float: Information Ratio
    """
    if tracking_error == 0:
        return 0.0

    ir = (strategy_return - benchmark_return) / tracking_error

    return ir
```

---

## 종합 성과 분석

### 전체 지표 계산 클래스

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class BacktestResult:
    """백테스팅 결과 DTO"""

    # 기본 정보
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal

    # 수익 지표
    total_return: float
    annualized_return: float
    cagr: float

    # 리스크 지표
    mdd: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    var_95: float

    # 거래 통계
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_win_loss_ratio: float
    avg_holding_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int

    # 벤치마크 비교
    benchmark_return: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None


class PerformanceAnalyzer:
    """
    성과 분석 클래스

    이 클래스는 위에서 정의한 모든 계산 함수들을 재사용하여 종합 분석을 수행합니다.

    ⚠️ 실제 구현 시 권장사항:
    - 모든 계산 함수들을 별도의 유틸리티 모듈로 분리 (예: src/application/common/performance_metrics.py)
    - PerformanceAnalyzer는 해당 유틸리티 모듈의 함수들을 import하여 사용
    - 이렇게 하면 함수 정의가 한 곳에만 존재하여 유지보수 시 일관성 보장

    예시 구조:
    ```
    src/application/common/
    ├── performance_metrics.py  # 모든 계산 함수 정의
    └── performance_analyzer.py # PerformanceAnalyzer 클래스만 정의
    ```
    """

    def __init__(
        self,
        initial_capital: Decimal,
        equity_curve: pd.DataFrame,
        trades: list[dict],
        benchmark_returns: Optional[pd.Series] = None
    ):
        """
        Args:
            initial_capital: 초기 자본
            equity_curve: 날짜별 자산 가치 DataFrame
            trades: 거래 내역
            benchmark_returns: 벤치마크 수익률 (선택)
        """
        self.initial_capital = initial_capital
        self.equity_curve = equity_curve
        self.trades = trades
        self.benchmark_returns = benchmark_returns

    def calculate_all_metrics(self) -> BacktestResult:
        """모든 성과 지표 계산"""

        final_capital = Decimal(str(self.equity_curve['equity'].iloc[-1]))
        start_date = self.equity_curve['date'].iloc[0]
        end_date = self.equity_curve['date'].iloc[-1]

        # 수익 지표
        total_return = calculate_total_return(self.initial_capital, final_capital)
        annualized_return = calculate_annualized_return(
            self.initial_capital, final_capital, start_date, end_date
        )
        years = (end_date - start_date).days / 365
        cagr = calculate_cagr(self.initial_capital, final_capital, years)

        # 리스크 지표
        mdd_info = calculate_mdd(self.equity_curve['equity'].tolist())
        volatility = calculate_volatility(self.equity_curve)
        sharpe = calculate_daily_sharpe_ratio(daily_returns)  # rf 3%, 일별 초과수익 기준
        sortino = calculate_sortino_ratio(self.equity_curve, annualized_return)
        calmar = calculate_calmar_ratio(annualized_return, mdd_info["mdd"])
        var_95 = calculate_var(self.equity_curve)

        # 거래 통계
        trade_stats = calculate_trade_count(self.trades)
        win_rate = calculate_win_rate(self.trades)
        profit_factor = calculate_profit_factor(self.trades)
        avg_stats = calculate_avg_profit_loss(self.trades)
        holding_stats = calculate_avg_holding_period(self.trades)
        streak_stats = calculate_consecutive_wins_losses(self.trades)

        # 벤치마크 비교
        alpha = None
        beta = None
        tracking_error = None
        information_ratio = None
        benchmark_return = None

        if self.benchmark_returns is not None:
            strategy_returns = self.equity_curve['equity'].pct_change().dropna()
            beta = calculate_beta(strategy_returns, self.benchmark_returns)
            # benchmark_return을 % 단위로 변환 (0.1 -> 10%)
            benchmark_return = ((self.benchmark_returns + 1).prod() - 1) * 100
            alpha = calculate_alpha(annualized_return, benchmark_return, beta)
            tracking_error = calculate_tracking_error(strategy_returns, self.benchmark_returns)
            information_ratio = calculate_information_ratio(
                annualized_return, benchmark_return, tracking_error
            )

        return BacktestResult(
            symbol="STRATEGY",
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annualized_return=annualized_return,
            cagr=cagr,
            mdd=mdd_info["mdd"],
            volatility=volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            var_95=var_95,
            total_trades=trade_stats["total"],
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_stats["avg_win"],
            avg_loss=avg_stats["avg_loss"],
            avg_win_loss_ratio=avg_stats["avg_win_loss_ratio"],
            avg_holding_days=holding_stats["avg_days"],
            max_consecutive_wins=streak_stats["max_consecutive_wins"],
            max_consecutive_losses=streak_stats["max_consecutive_losses"],
            benchmark_return=benchmark_return,
            alpha=alpha,
            beta=beta,
            tracking_error=tracking_error,
            information_ratio=information_ratio,
        )

    def print_summary(self) -> None:
        """성과 요약 출력"""
        result = self.calculate_all_metrics()

        print("\n" + "=" * 80)
        print("📊 백테스팅 성과 요약")
        print("=" * 80)

        print(f"\n📅 기간: {result.start_date.date()} ~ {result.end_date.date()}")
        print(f"💰 초기 자본: {result.initial_capital:,.0f}원")
        print(f"💰 최종 자본: {result.final_capital:,.0f}원")

        print(f"\n📈 수익 지표:")
        print(f"  - 총 수익률: {result.total_return:.2f}%")
        print(f"  - 연환산 수익률: {result.annualized_return:.2f}%")
        print(f"  - CAGR: {result.cagr:.2f}%")

        print(f"\n📉 리스크 지표:")
        print(f"  - MDD: {result.mdd:.2f}%")
        print(f"  - 변동성: {result.volatility:.2f}%")
        print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"  - Sortino Ratio: {result.sortino_ratio:.2f}")
        print(f"  - Calmar Ratio: {result.calmar_ratio:.2f}")
        print(f"  - VaR (95%): {result.var_95:.2f}%")

        print(f"\n🎯 거래 통계:")
        print(f"  - 총 거래: {result.total_trades}회")
        print(f"  - 승률: {result.win_rate:.2f}%")
        print(f"  - Profit Factor: {result.profit_factor:.2f}")
        print(f"  - 평균 수익: {result.avg_win:.2f}%")
        print(f"  - 평균 손실: {result.avg_loss:.2f}%")
        print(f"  - 평균 보유: {result.avg_holding_days:.1f}일")
        print(f"  - 최대 연승: {result.max_consecutive_wins}회")
        print(f"  - 최대 연패: {result.max_consecutive_losses}회")

        if result.benchmark_return is not None:
            print(f"\n📊 벤치마크 비교:")
            print(f"  - 벤치마크 수익률: {result.benchmark_return:.2f}%")
            print(f"  - Alpha: {result.alpha:.2f}%")
            print(f"  - Beta: {result.beta:.2f}")
            print(f"  - Tracking Error: {result.tracking_error:.2f}%")
            print(f"  - Information Ratio: {result.information_ratio:.2f}")

        print("\n" + "=" * 80)
```

### 사용 예제

```python
# 백테스팅 실행 후
analyzer = PerformanceAnalyzer(
    initial_capital=Decimal("10_000_000"),
    equity_curve=equity_df,
    trades=trade_list,
    benchmark_returns=kospi_returns  # KOSPI 수익률
)

# 전체 지표 출력
analyzer.print_summary()

# 개별 지표 접근
result = analyzer.calculate_all_metrics()
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
```

---

## 성과 평가 기준표

### 우수한 전략의 기준

| 지표 | 🟢 우수 | 🟡 양호 | 🔴 부족 |
|-----|--------|--------|--------|
| **연환산 수익률** | > 20% | 10-20% | < 10% |
| **MDD** | < 15% | 15-25% | > 25% |
| **Sharpe Ratio** | > 2.0 | 1.0-2.0 | < 1.0 |
| **승률** | > 60% | 50-60% | < 50% |
| **Profit Factor** | > 2.0 | 1.5-2.0 | < 1.5 |
| **Calmar Ratio** | > 2.0 | 1.0-2.0 | < 1.0 |
| **Alpha** | > 5% | 0-5% | < 0% |

---

## 주의사항

### ⚠️ 과최적화 (Overfitting) 방지

- Out-of-sample 테스트 필수
- 파라미터 튜닝 과도하게 하지 않기
- Walk-forward 분석 권장

### ⚠️ 생존 편향 (Survivorship Bias)

- 상장폐지 종목 포함 필요
- 전체 유니버스 대상 테스트

### ⚠️ 거래 비용 반영

- 수수료, 세금, 슬리피지 포함
- 현실적인 체결 가정

---

## 참고 자료

- [Sharpe Ratio - Investopedia](https://www.investopedia.com/terms/s/sharperatio.asp)
- [Maximum Drawdown - Wikipedia](https://en.wikipedia.org/wiki/Drawdown_(economics))
- [Backtesting Best Practices](https://www.quantstart.com/)

---

**마지막 업데이트**: 2025-10-22
**문서 버전**: 1.0
