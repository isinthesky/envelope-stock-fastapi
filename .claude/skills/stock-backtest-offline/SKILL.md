---
name: stock-backtest-offline
description: 합성 데이터로 전략을 오프라인 백테스트합니다. backtest, 백테스트, 전략 평가, Monte Carlo, 시뮬레이션 관련 작업에 사용하세요.
allowed-tools: Bash, Read, Glob, Grep
---

# Offline Backtest Skill

합성 데이터를 사용하여 DB나 API 연결 없이 전략을 빠르게 평가합니다.

## 사용법

### 기본 실행
```bash
cd /Users/inthesky/dev/stock/hantwo-stock-fastapi
uv run python -m scripts.evaluate_strategy
```

### 전략 프리셋 지정
```bash
# 보수적 전략
uv run python -m scripts.evaluate_strategy --preset conservative

# 공격적 전략
uv run python -m scripts.evaluate_strategy --preset aggressive

# 트레일링 스탑 전략
uv run python -m scripts.evaluate_strategy --preset trailing
```

### 시장 시나리오 지정
```bash
# 골든크로스 시나리오
uv run python -m scripts.evaluate_strategy --scenario-type gc_scenario

# 데드크로스 시나리오
uv run python -m scripts.evaluate_strategy --scenario-type dc_scenario

# 횡보장 시나리오
uv run python -m scripts.evaluate_strategy --scenario-type sideways
```

### 몬테카를로 시뮬레이션
```bash
# 50회 시뮬레이션
uv run python -m scripts.evaluate_strategy --simulations 50

# 결과 저장
uv run python -m scripts.evaluate_strategy --simulations 100 --output reports/mc_results.json
```

### 파라미터 조정
```bash
# 트렌드와 변동성 조정
uv run python -m scripts.evaluate_strategy --trend 0.0005 --volatility 0.02

# 기간 조정
uv run python -m scripts.evaluate_strategy --periods 500
```

## 주요 모듈

| 모듈 | 설명 |
|------|------|
| `scripts/common/data_generator.py` | 합성 OHLCV 데이터 생성 |
| `scripts/common/strategy_presets.py` | 전략 설정 프리셋 |
| `scripts/common/result_analyzer.py` | 결과 분석 및 포맷팅 |
| `scripts/common/backtest_runner.py` | 백테스트 실행 헬퍼 |

## 시나리오 유형

| 유형 | 설명 |
|------|------|
| `random` | 랜덤 워크 with Drift |
| `gc_scenario` | 골든크로스 발생 패턴 |
| `dc_scenario` | 데드크로스 발생 패턴 |
| `sideways` | 횡보장 패턴 |

## 전략 프리셋

| 프리셋 | 특징 |
|--------|------|
| `default` | BB 20/2σ, 손절 -3%, 익절 +5% |
| `conservative` | BB 20/2.5σ, 손절 -2%, 익절 +3%, 낮은 포지션 |
| `aggressive` | BB 15/1.5σ, 손절 -5%, 익절 +10%, 높은 포지션 |
| `trailing` | 익절 없이 트레일링 스탑 3% |

## 결과 해석

- `total_return`: 총 수익률 (%)
- `sharpe_ratio`: 샤프 비율 (> 1.0 양호)
- `mdd`: 최대 낙폭 (< -20% 주의)
- `win_rate`: 승률 (> 50% 권장)
- `profit_factor`: 총이익/총손실 비율 (> 1.5 양호)
