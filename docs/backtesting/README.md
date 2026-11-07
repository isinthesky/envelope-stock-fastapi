# 백테스팅 시스템 문서

> **현황(2026-11-07)**: 대상 전략은 **골든크로스(MA55/MA165 + Stochastic 눌림목)** 하나다.
> 볼린저+엔벨로프 평균회귀 전략과 관련 코드·예제(`StrategyConfigDTO(bollinger_band=…)` 등)는 완전 제거됐다.
> 연구 결론: 골든크로스 **NO-GO**(실 데이터 walk-forward에서 OOS 엣지 없음,
> `reports/research_2026-11-06_summary.md`). 이전 판의 `WORK_PLAN.md`·`strategy_guide.md` 링크는 존재하지 않는다.

## 📚 문서 구조

| 문서 | 내용 |
|---|---|
| [PERFORMANCE_METRICS.md](./PERFORMANCE_METRICS.md) | 성과·과적합 지표 정의(계산식 + 구현 심볼) |
| [DATA_VALIDATION.md](./DATA_VALIDATION.md) | 데이터 소스, ohlcv_cache, 로더 검증, 커버리지 게이트 |
| [PERFORMANCE_TEST_RESULTS.md](./PERFORMANCE_TEST_RESULTS.md) | (이력) 2025-11 파라미터 비교 결과 |
| [실행_결과_및_제한사항.md](./실행_결과_및_제한사항.md) | (이력) 2025-10 초기 실행 결과·제한사항 |
| [gc_rsi_mixed_buy_signal_review.md](./gc_rsi_mixed_buy_signal_review.md) | GC+RSI 혼합 매수 신호 검토 |
| [examples/backtest/README.md](../../examples/backtest/README.md) | 탐색용 예제 |

## 🔀 두 가지 실행 경로

| 경로 | 시그널 | 용도 |
|---|---|---|
| **온디맨드 엔진** `BacktestEngine` (`domain/backtest/engine.py`) | 레거시 `generators/golden_cross.GoldenCrossSignalGenerator` — **라이브와 불일치**(시그널 Jaccard 46/314) | API·`/mypage/backtest` 진단용 |
| **라이브 패리티** `GoldenCrossParityReplay` (`golden_cross_parity.py`) + `PortfolioParityEngine` (`portfolio_parity_engine.py`) | 실주문 FSM(`GoldenCrossStateMachine`) 그대로 리플레이 — 라이브 시그널 100% 일치(182/182) | **검증·연구는 반드시 이 경로** |

성과 집계는 두 경로 모두 `result_builder.build_backtest_result` 단일 출처.

### 온디맨드 엔진 주요 규칙(2026-11 수정 반영)
- 체결 시점 `BacktestConfigDTO.execution_timing`: `next_open`(기본) | `next_close` | `same_close`.
- 부분익절은 **포지션 단위로 추적**(`BacktestEngine.partial_tp_stage`): 1차(`partial_take_profit_1`, 기본 +10%)에
  첫 lot, 2차(기본 +16%)에 다음 lot만 청산. 이전에는 3개 lot이 같은 날 모두 청산돼 사실상 고정 +10% 익절이었고
  **승률이 부풀려졌다**.
- 리스크 청산 후 재진입은 **새 골든크로스** 필요(`require_fresh_cross_after_exit=True`, 라이브 FSM 정합).
- 유니버스 백테스트(`/run-universe-golden-cross`, `/universe/golden-cross`): 종목은 요청 `symbols` 또는
  종목코드 순 선택(오늘의 GC 상태·전체기간 수익률 랭킹 미사용), 포트폴리오는 진입일→종목코드 우선순위,
  **일별 MTM MDD**, 기간 종료 시 미청산분은 비용 차감 순청산가로 평가(`BacktestService.simulate_universe_portfolio`).

### 연구 옵션 (opt-in, `PortfolioExecutionOptions`)
기본값 = 기존 동작. `fill_timing`(`same_close`|`next_open`), `sizing_mode`(`cash_ratio`|`equal_weight_equity`),
`cash_interest`(`cash_interest.py`), `liquidate_at_end`, `exit_overlay`(`exit_overlay.py`),
`entry_guard`(SafetyGuard 재현, `entry_guard.py`, `same_close` 전용).
별도 연구 모듈: `momentum_rotation.py`, `state_overlay.py`, `leverage_overlay.py`,
`regime_filter.py`(`RegimeEntryFilter`, `use_di_direction`, `wilder_dmi_series`; di_sum=0은 NaN 처리).

## 💸 거래 비용 (`domain/backtest/cost_schedule.py`, `order_manager.py`)

- 매도세(증권거래세+농특세, 주식): 2018 0.30% → 2019-06-03 0.25% → 2020 0.25% → 2021 0.23% →
  2023 0.20% → 2024 0.18% → 2025 0.15% → 2026 0.20%(약 80% 확신, 확정치 재확인 필요).
  2018-01-01 이전 날짜는 `UnsupportedBacktestCostDateError`.
- **국내 ETF 매도세 면제**: `etf_tax_exempt=True`(기본), 대상 `tax_exempt_symbols`(None이면 `settings.etf_universe_symbols`).
- 수수료 0.015%, 슬리피지 0.05%(기본, `BacktestConfigDTO`로 오버라이드 가능). 확인: `scripts/common/print_backtest_cost_schedule.py`.
- 해외/채권형 ETF 매매차익 배당소득세(15.4%)는 반영하지 않는다.

## 🚀 실행

| 대상 | 방법 |
|---|---|
| 단일/다종목 | `POST /api/v1/backtest/run`, `/run-multi` |
| 유니버스 | `POST /api/v1/backtest/run-universe-golden-cross`, `GET /api/v1/backtest/universe/golden-cross` |
| 데이터 품질 | `POST /api/v1/backtest/validate-data` |
| 최신 walk-forward 리포트(read-only) | `GET /api/v1/backtest/walk-forward/latest` (기준선 `reports/walk_forward_YYYYMMDD_HHMMSS.json`만 — A/B 변형 리포트 제외) |
| 페이지 | `/mypage/backtest` (관리자 로그인 필요) |
| Walk-forward | `scripts/research/run_walk_forward.py` — `--n-trials`(누적 시도 수, DSR), `--output-dir`, `--regime-ab`, `--sector-cap-ab` 등 |

- API는 관리자 로그인 세션 + `AdminAccessDep`(IP allowlist, 쓰기 메서드는 `X-Requested-With: XMLHttpRequest`) 필요.
- 연구 스크립트는 DB 캐시만 읽는다(KIS 미호출). 실행 패턴: `scripts/research/research_suite_20261106.py` 상단 docstring.

## 📊 연구 결론 요약 (2026-11-07)

| 주제 | 판정 | 근거 |
|---|---|---|
| 골든크로스 | NO-GO | `reports/research_2026-11-06_summary.md` |
| 모멘텀 로테이션 | B&H 하회 | 동일 |
| State overlay | CONDITIONAL | `reports/state_overlay_prereg_result.md` |
| 2x 레버리지 overlay | NO-GO | `reports/leverage_overlay_prereg_result.md` |
| SafetyGuard 연결 | 연결(dev OOS Sharpe 0.128→0.435) | `reports/entry_guard_eval_20261107.json` |

## ⚠️ 주의사항
- 과최적화: 파라미터 스윕은 walk-forward OOS + DSR(누적 `--n-trials`) + PBO로 검증. 게이트는 `gates.py`.
- 생존 편향: 유니버스·적격성은 현재 스냅샷.
- Look-ahead: 일봉 신호 종가 체결(`same_close`)은 장후 시간외 종가 주문을 전제로 한다.
- 데이터: 당일 15:31 이전 잠정 봉은 캐시되지 않는다. 보존 3650일.

## 🧪 테스트

```bash
docker run --rm -v /Users/m2-dev/Apps/kis-strategy-alert-server:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q
```

## 🔗 관련 문서
- [아키텍처](../base/ARCHITECTURE.md), [서비스 가이드](../base/SERVICE.md)

---

**마지막 업데이트**: 2026-11-07
