# 백테스팅 예제

이 디렉토리에는 백테스팅 시스템의 사용 예제가 포함되어 있습니다.

> 레거시 볼린저+엔벨로프 평균회귀 예제(`simple_backtest.py`, `multi_symbol_backtest.py`,
> `compare_strategies.py`, `optimize_strategy.py`, `optimized_backtest.py`,
> `analyze_strategy.py`)는 생성기 폐기와 함께 제거되었습니다. 남은 예제는 골든크로스 계열입니다.
> 라이브와 동일한 시그널로 검증하려면 온디맨드 예제가 아닌
> `scripts/research/run_walk_forward.py`(`GoldenCrossParityReplay`)를 사용하세요.

## 예제 목록

### 1. golden_cross_backtest.py
단일 종목 골든크로스 백테스트 예제 (`prepare_golden_cross_indicators` 기반).

**실행 방법:**
```bash
python examples/backtest/golden_cross_backtest.py
```

### 2. golden_cross_ma_optimizer.py
장기 MA 파라미터(150/155/160/165/170) 스윕 최적화 예제. `short=55` 고정.

**실행 방법:**
```bash
python examples/backtest/golden_cross_ma_optimizer.py
```

## 사전 준비

### 1. 환경 변수 설정
`.env` 파일에 KIS API 키 설정:
```
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_BASE_URL=https://openapi.koreainvestment.com:9443
```

### 2. 의존성 설치
```bash
uv sync
```

### 3. Redis 실행
```bash
docker run -d -p 6379:6379 redis
```

## 전략 파라미터 조정

골든크로스 파라미터는 `GoldenCrossConfigDTO`로 조정합니다
(`scripts/common/strategy_presets.py`의 `default/fast/slow` 프리셋 참고):

```python
GoldenCrossConfigDTO(
    short_ma_period=55,   # 단기 MA
    long_ma_period=165,   # 장기 MA
    stochastic_k=14,
    stochastic_d=3,
    stochastic_smooth=3,
    stop_loss_ratio=-0.05,
    take_profit_ratio=0.10,
    allocation_ratio=0.1,
)
```

## 결과 해석

### 수익 지표
- **총 수익률**: 전체 기간 동안의 누적 수익률
- **연환산 수익률**: 1년 단위로 환산한 평균 수익률
- **CAGR**: 복리 연평균 성장률

### 리스크 지표
- **MDD**: 최대 낙폭 (고점 대비 최대 하락률)
- **변동성**: 수익률의 표준편차 (연환산)
- **Sharpe Ratio**: 위험 대비 수익률 (2.0 이상 우수)
- **Sortino Ratio**: 하방 위험만 고려한 수익률
- **Calmar Ratio**: 수익률 / MDD (2.0 이상 우수)

### 거래 통계
- **승률**: 이익 거래 비율
- **Profit Factor**: 총 이익 / 총 손실 (2.0 이상 우수)
- **평균 보유 기간**: 포지션 평균 보유 일수

## 주의사항

### 1. 과최적화 (Overfitting) 방지
- 너무 많은 파라미터 조정은 과거 데이터에만 최적화될 위험
- Out-of-sample(walk-forward) 테스트 권장

### 2. 거래 비용 고려
- 수수료, 세금, 슬리피지가 수익률에 큰 영향
- 실제 거래 환경을 정확히 반영

### 3. 데이터 품질
- 결측치, 이상치가 결과를 왜곡할 수 있음
- 데이터 검증 필수

## 추가 리소스

- [백테스팅 시스템 문서](../../docs/backtesting/README.md)
- 워크포워드 검증: `scripts/research/run_walk_forward.py`
