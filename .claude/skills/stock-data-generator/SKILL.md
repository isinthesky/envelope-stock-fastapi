---
name: stock-data-generator
description: 합성 OHLCV 데이터를 생성합니다. 백테스트 및 전략 검증용. synthetic data, 합성 데이터, 테스트 데이터 생성 관련 작업에 사용하세요.
allowed-tools: Bash, Read, Glob, Grep
---

# Synthetic Data Generator Skill

백테스트 및 전략 검증을 위한 합성 OHLCV 데이터를 생성합니다.

## Python 사용법

### 기본 데이터 생성
```python
from scripts.common.data_generator import MarketScenario, SyntheticDataGenerator

# 시나리오 정의
scenario = MarketScenario(
    name="UpwardTrend",
    trend=0.0003,       # 일간 +0.03%
    volatility=0.015,   # 일간 1.5% 변동성
    periods=250,        # 250일
    seed=42,            # 재현성
)

# 데이터 생성
df = SyntheticDataGenerator.generate_ohlcv(scenario)
print(df.head())
```

### 골든크로스 시나리오
```python
from datetime import datetime
from scripts.common.data_generator import SyntheticDataGenerator

# MA60이 MA200을 상향 돌파하는 패턴
df = SyntheticDataGenerator.generate_gc_scenario(
    start_date=datetime(2024, 1, 1),
    periods=500,
    seed=42,
)
```

### 데드크로스 시나리오
```python
# MA60이 MA200을 하향 돌파하는 패턴
df = SyntheticDataGenerator.generate_dc_scenario(
    start_date=datetime(2024, 1, 1),
    periods=500,
    seed=42,
)
```

### 횡보장 시나리오
```python
# 추세 없이 변동성만 있는 패턴
df = SyntheticDataGenerator.generate_sideways(
    start_date=datetime(2024, 1, 1),
    periods=250,
    seed=42,
)
```

### 몬테카를로 시뮬레이션
```python
from scripts.common.data_generator import MarketScenario, SyntheticDataGenerator

base_scenario = MarketScenario(
    name="Base",
    trend=0.0002,
    volatility=0.015,
    periods=250,
)

# 100개의 다양한 시장 데이터 생성
datasets = SyntheticDataGenerator.generate_monte_carlo(
    base_scenario=base_scenario,
    simulations=100,
    trend_std=0.0005,        # 트렌드 변동
    vol_range=(0.01, 0.03),  # 변동성 범위
)

print(f"Generated {len(datasets)} datasets")
```

## 시나리오 파라미터

| 파라미터 | 설명 | 기본값 |
|---------|------|--------|
| `name` | 시나리오 이름 | "Default" |
| `trend` | 일간 평균 수익률 | 0.0002 (0.02%) |
| `volatility` | 일간 변동성 | 0.015 (1.5%) |
| `start_price` | 시작 가격 | 10000 |
| `periods` | 캔들 개수 | 250 |
| `seed` | 랜덤 시드 | 이름 해시 |
| `scenario_type` | 시나리오 유형 | "random" |

## 시나리오 유형

| 유형 | 설명 | 용도 |
|------|------|------|
| `random` | 랜덤 워크 with Drift | 일반 테스트 |
| `gc_scenario` | 골든크로스 패턴 | MA 교차 전략 검증 |
| `dc_scenario` | 데드크로스 패턴 | 하락장 전략 검증 |
| `sideways` | 횡보장 패턴 | 횡보 전략 검증 |

## 가상 시장 (다중 종목)

```python
from scripts.common.data_generator import SyntheticMarket, MarketScenario

# 가상 시장 생성
market = SyntheticMarket()

# 종목 추가
market.add_stock(
    symbol="001",
    name="대형주A",
    market_cap=50e12,
    volatility=0.015,
    per=15.0,
)

market.add_stock(
    symbol="002",
    name="중형주B",
    market_cap=5e12,
    volatility=0.025,
    per=25.0,
)

# 전체 데이터 생성
data_map = market.generate_all(periods=250)

# 스크리닝
passed = market.screen_stocks(
    min_volume=500000,
    max_volatility=0.03,
    max_per=30.0,
)
print(f"Screened: {passed}")
```

## 데이터 형식

생성된 DataFrame 컬럼:
- `timestamp`: 날짜 (datetime)
- `open`: 시가 (float)
- `high`: 고가 (float)
- `low`: 저가 (float)
- `close`: 종가 (float)
- `volume`: 거래량 (int)
