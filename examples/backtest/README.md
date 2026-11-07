# 백테스팅 예제

이 디렉토리에는 골든크로스 계열 **탐색용(교육용)** 예제가 있습니다.

> ⚠️ **현황(2026-11-07)**
> - 레거시 볼린저+엔벨로프 평균회귀 예제(`simple_backtest.py`, `multi_symbol_backtest.py`,
>   `compare_strategies.py`, `optimize_strategy.py`, `optimized_backtest.py`,
>   `analyze_strategy.py`)는 제거되었습니다.
> - 두 예제는 자체 단순 백테스터(`GoldenCrossBacktester`, 단일 진입·고정 손절/익절)를 사용하며
>   **라이브 시그널과 일치하지 않습니다**. 라이브와 동일한 시그널(parity 100%)로 검증하려면
>   `scripts/research/run_walk_forward.py`(`golden_cross_parity.GoldenCrossParityReplay`)를 사용하세요.
> - 골든크로스는 실 데이터 walk-forward에서 OOS 엣지가 확인되지 않았습니다(NO-GO).
>   예제 결과를 전략 근거로 쓰지 마세요.

## 예제 목록

### 1. golden_cross_backtest.py
`analysis_history`의 활성 종목에 대해 최근 약 2년(730일) 일봉으로 골든크로스(MA55/MA165 +
Stochastic 과매도) 매수, 데드크로스/손절(-7%)/익절(+15%) 매도를 시뮬레이션합니다.
지표는 `TechnicalIndicators.prepare_golden_cross_indicators`, 비용은
`cost_schedule.get_backtest_cost_schedule(2025-01-01)` 기준입니다.

실행: 아래 「사전 준비」의 컨테이너 실행 방식으로 `examples/backtest/golden_cross_backtest.py`를 실행.

### 2. golden_cross_ma_optimizer.py
`short=55` 고정, 장기 MA(150/155/160/165/170) 스윕. 대상은 `stock_universe` 시가총액 상위
50종목. 백테스터는 `golden_cross_backtest.py`의 것을 재사용합니다.

실행: 위와 동일(`examples/backtest/golden_cross_ma_optimizer.py`).

### 3. YAML 예시
- `golden_cross_walk_forward.example.yaml`, `sell_rule_preregistered.example.yaml`:
  `scripts/research/validate_strategy_walk_forward.py` 입력 형식 예시(지표 값은 가상의 샘플).

## 사전 준비

- `.env`에 KIS 키(`KIS_APP_KEY`, `KIS_APP_SECRET`). Base URL은 `TRADING_ENVIRONMENT`에 따라
  `settings.kis_base_url`이 자동 선택합니다(별도 `KIS_BASE_URL` 변수 없음).
- Postgres(`analysis_history`/`stock_universe`/`ohlcv_cache`)와 Redis 실행 필요
  (예제가 `get_db`, `get_redis_client`, `KISAPIClient`를 사용).
- API 이미지에는 `examples/`·`scripts/`가 없고 호스트에는 `uv`가 없다. 저장소를 bind mount하고 compose
  네트워크에 붙여 실행한다(패턴: `scripts/research/research_suite_20261106.py` 상단 docstring,
  `--env-file` 금지).
- ⚠️ 예제는 DB 캐시 미스 시 **KIS API를 호출**한다. 토큰 캐시 볼륨(`kis_token_cache`)이 없는 임시
  컨테이너에서는 토큰이 재발급될 수 있으므로(1일 1회 원칙) 기간을 캐시 범위 안으로 두거나
  DB 전용 연구 스크립트(`scripts/research/*`)를 우선 사용한다.

## 전략 파라미터

- 예제 파라미터는 각 파일의 `GoldenCrossConfig` dataclass(예제 전용)에서 조정합니다.
- 서버 백테스트 API(`BacktestService`)용 설정은 중첩 구조의 `GoldenCrossConfigDTO`
  (`ma_config`, `stochastic_config`, `risk_config`, `position` …)이며, 프리셋은
  `scripts/common/strategy_presets.py`(`default/fast/slow_golden_cross`)를 참고하세요.

## 결과 해석 / 주의사항

- 지표 정의(Sharpe·Sortino·Profit Factor 등)는
  [PERFORMANCE_METRICS.md](../../docs/backtesting/PERFORMANCE_METRICS.md)를 따릅니다.
  단, 예제 백테스터는 자체 집계 로직을 사용하므로 수치가 서버 결과와 다를 수 있습니다.
- 예제는 매도세를 비용 스케줄 값 그대로 적용합니다(ETF 매도세 면제 미반영). 서버 엔진은
  `BacktestConfigDTO.etf_tax_exempt=True`(기본)로 ETF에 0%를 적용합니다.
- 파라미터 스윕 결과는 다중검정 편향이 큽니다. 검증은 walk-forward + DSR(누적 `--n-trials`)로 하세요.

## 추가 리소스

- [백테스팅 시스템 문서](../../docs/backtesting/README.md)
- 워크포워드 검증: `scripts/research/run_walk_forward.py`
