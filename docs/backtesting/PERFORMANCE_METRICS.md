# 백테스팅 성과 지표 가이드

> **현황(2026-11-07)**: 이 문서는 계산식 + 구현 심볼 포인터만 유지한다(샘플 코드 제거).
> 단일 출처: `src/application/common/performance_metrics.py`(`PerformanceMetrics`) →
> `src/application/domain/backtest/result_builder.py`(`build_backtest_result`)가 엔진과
> `GoldenCrossParityReplay`에 공통 적용. 2026-11 정의 변경: Sharpe(일별 초과수익 기준),
> Sortino(전체 관측치 하방편차), Profit Factor(금액 기준), MDD 회복기간(저점→직전 고점 회복).
> 이전 리포트의 Sharpe/Sortino/PF 수치는 **구 정의 기준**이므로 신규 수치와 직접 비교하지 말 것.

## 📋 목차
1. [공통 규약](#공통-규약)
2. [수익 지표](#수익-지표)
3. [리스크 지표](#리스크-지표)
4. [거래 통계](#거래-통계)
5. [과적합 통계 (walk-forward)](#과적합-통계-walk-forward)
6. [벤치마크 비교](#벤치마크-비교)
7. [결과 DTO / 해석](#결과-dto--해석)

---

## 공통 규약

- 일별 수익 `r_d` = 일별 자산곡선(`DailyStatsDTO.equity`)의 `pct_change`. 연환산 계수 252.
- 무위험이자율 `rf_연` 기본 3%(`build_backtest_result(risk_free_rate=3.0)`), 일별 환산
  `rf_d = (1 + rf_연)^(1/252) − 1` (`PerformanceMetrics.daily_risk_free_rate`).
- 거래 통계 입력(`completed_trades`)은 청산 완료 거래 dict
  `{"profit_rate", "holding_days", "profit"}` 리스트. 승/패 판정은 `profit_rate` 부호.
- 비용(수수료·세금·슬리피지)은 체결 단계에서 반영된 **순** 자산/손익 기준이다.

## 수익 지표

| 지표 | 계산식 | 구현 |
|---|---|---|
| 총 수익률 | (최종 − 초기) / 초기 × 100 | `calculate_total_return` |
| 연환산 수익률 | ((최종/초기)^(365/달력일수) − 1) × 100 | `calculate_annualized_return` |
| CAGR | ((최종/초기)^(1/years) − 1) × 100, years = 달력일수/365 | `calculate_cagr` |

- 월별 수익률 함수는 구현되어 있지 않다.

## 리스크 지표

| 지표 | 계산식 | 구현 |
|---|---|---|
| MDD | min((equity − cummax) / cummax) × 100 (일별 자산곡선) | `calculate_mdd` |
| 회복 기간 | MDD 저점 → 직전 고점 이상 회복까지 **관측 바 수**. 미회복 `None`, 낙폭 ≈0(>−0.01%)이면 0 | `calculate_mdd()["recovery_days"]` |
| 변동성 | std(r_d) × √252 × 100 | `calculate_volatility` |
| **Sharpe** | mean(r_d − rf_d) / std(r_d, ddof=1) × √252 | `calculate_daily_sharpe_ratio` |
| Sharpe(rf0) | 위 식에서 rf=0 — DSR과 같은 기준(per-period Sharpe × √252) | 동일 함수, `risk_free_rate=0.0` |
| Sortino | mean(r_d − rf_d) / DD × √252, DD = sqrt(mean(min(r_d − rf_d, 0)²)) (**전체 관측치** 평균) | `calculate_sortino_ratio` |
| Calmar | 연환산 수익률 / \|MDD\| (MDD ≥ 0이면 0) | `calculate_calmar_ratio` |
| VaR 95% | r_d의 5% 분위수 × 100 (Historical, 일간) | `calculate_var` |

- 구 Sharpe `(CAGR − 3%) / 연변동성`(`calculate_sharpe_ratio`)은 DSR과 기준이 달라 **제거**됨.
- 구 Sortino는 "음수 수익만의 표준편차"를 써서 하방편차를 과소/과대 추정했다(수정됨).
- 결과(`BacktestResultDTO.sharpe_ratio`/`sharpe_ratio_rf0`)와 walk-forward 리포트
  (`sharpe`/`sharpe_rf0`)는 두 값을 함께 낸다.
- 포트폴리오(유니버스) 시뮬레이션 MDD는 일별 시가평가(MTM) 자산곡선 기준
  (`BacktestService._portfolio_equity_curve`).

## 거래 통계

| 지표 | 계산식 | 구현 |
|---|---|---|
| 거래 수 | total / wins(`profit_rate`>0) / losses(<0) / breakeven | `calculate_trade_count` |
| 승률 | wins / total × 100 | `calculate_win_rate` |
| **Profit Factor** | Σ이익 / \|Σ손실\|. 모든 거래에 `profit`(KRW, 비용 차감)이 있으면 **금액 기준**, 아니면 `profit_rate` 합 폴백. 손실 0이면 9999.99(이익>0) 또는 0 | `calculate_profit_factor` |
| 평균 수익/손실/손익비 | 수익률(%) 평균, 손익비 = \|avg_win / avg_loss\| | `calculate_avg_profit_loss` |
| 보유 기간 | `holding_days` 평균/최대/최소 | `calculate_avg_holding_period` |
| 연속 승/패 | `profit_rate` 부호 기준 최대 연속 | `calculate_consecutive_wins_losses` |

- ⚠️ 부분익절 lot이 같은 날 함께 청산되던 엔진 버그(2026-11 수정, `BacktestEngine.partial_tp_stage`)로
  과거 리포트의 승률·거래수는 부풀려져 있다(PERFORMANCE_TEST_RESULTS.md 현황 참고).

## 과적합 통계 (walk-forward)

구현: `src/application/domain/backtest/statistics.py`, 집계: `WalkForwardRunner._overfitting_stats`.

| 통계 | 정의 | 구현 |
|---|---|---|
| per-period Sharpe | mean(r)/std(r, ddof=1), rf=0 + 왜도/원첨도 | `sharpe_stats` |
| SR0 (기대 최대 Sharpe) | sqrt(Var(trial SR)) · [(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))] | `expected_max_sharpe` |
| DSR | Φ((SR − SR0)·√(n−1) / √(1 − skew·SR + (kurt−1)/4·SR²)) | `deflated_sharpe_ratio` |
| PBO | CSCV: IS 최적 설정이 OOS 중위 이하로 떨어지는 조합 비율 | `probability_of_backtest_overfitting` |
| Bootstrap CI | per-period Sharpe 부트스트랩 신뢰구간(기본 2000회, 95%) | `bootstrap_sharpe_ci` |

- **N(시도 수)은 누적 연구 시도 수**를 연구자가 공급한다: `WalkForwardRunner(n_trials=...)`,
  CLI `scripts/research/run_walk_forward.py --n-trials`. 실제 사용값은
  `max(공급값, 이번 실행 후보×fold)`이며, 리포트에 `n_trials_source`
  (`researcher_supplied` | `default_in_run_only`)가 기록된다. 과소 입력 시 DSR 과대평가.
- `bootstrap_mean_ci`는 제거됨(Sharpe CI만 유지).
- 게이트(`gates.GateThresholds`): DSR ≥ 0.95, OOS Sharpe ≥ 1.0, 벤치 초과수익 ≥ 0%p,
  PBO ≤ 0.2, IS→OOS Sharpe 감쇠 ≤ 30%, OOS 거래일 ≥ 250. 판정 `evaluate_gates`.
  게이트의 OOS Sharpe는 리포트 `sharpe`(rf 3%) 값을 사용한다.

## 벤치마크 비교

- `BacktestResultDTO`에 `benchmark_return/alpha/beta/tracking_error/information_ratio` 필드가
  있으나 **단일 종목 엔진은 계산하지 않는다(항상 None)**. Alpha/Beta/TE/IR 계산 함수는 없다.
- 유니버스 포트폴리오 요약의 `benchmark_return`은 **종목별 매수후보유(B&H) 수익률의 단순 평균**이다
  (`BacktestService._average_benchmark_return`: 종목별 백테스트 기간 첫/마지막 종가, 엔진 값이 있으면 우선).
  2026-11-07 이전에는 엔진이 값을 채우지 않아 항상 0.0이었고 `excess_return` = `total_return`이었다.
- walk-forward는 `--benchmark`(기본 069500) 종목으로 OOS 초과수익·국면 분해를 산출한다.

## 결과 DTO / 해석

- 결과 스키마: `src/application/domain/backtest/dto.py` `BacktestResultDTO`
  (수익·리스크·거래 통계·`trades`·`daily_stats`).
- 아래 기준은 참고용 일반 휴리스틱이며 게이트가 아니다. 채택 판단은 walk-forward 게이트를 따른다.

| 지표 | 우수 | 양호 | 부족 |
|-----|------|------|------|
| 연환산 수익률 | > 20% | 10-20% | < 10% |
| MDD | > −15% | −15 ~ −25% | < −25% |
| Sharpe (일별, rf 3%) | > 2.0 | 1.0-2.0 | < 1.0 |
| Profit Factor (금액) | > 2.0 | 1.5-2.0 | < 1.5 |
| Calmar | > 2.0 | 1.0-2.0 | < 1.0 |

### 주의사항
- 과최적화: 파라미터 스윕 결과는 반드시 walk-forward OOS + DSR(누적 N)로 검증.
- 생존 편향: 운영 유니버스(현재 상장 ETF) 기준이므로 상폐/신규상장 편향이 남는다.
- 거래 비용: 날짜별 스케줄(`cost_schedule.py`)과 ETF 매도세 면제가 기본 반영된다
  ([DATA_VALIDATION.md](./DATA_VALIDATION.md) 비용 절 참고).

---

**마지막 업데이트**: 2026-11-07
