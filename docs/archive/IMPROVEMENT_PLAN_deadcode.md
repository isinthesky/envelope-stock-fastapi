# Dead Code 제거 계획

> 작성: 2026-08-01 · 도구: vulture(conf60) + pyflakes · 6영역 subagent 교차검증 + codex 루프
> 프로덕션 트레이딩 시스템 → **precision 우선**(오제거는 prod 파손). 목표: critical/high/medium=0.

## 0. 탐지 규모

vulture 194 후보(함수/메서드/클래스/프로퍼티/import) + pyflakes 35(미사용 import/변수). 6영역 subagent가 각 후보를 grep(문자열/템플릿/동적 포함)·프레임워크 훅으로 교차검증.

| 영역 | TRULY_DEAD | TEST_ONLY | FALSE_POSITIVE | UNCERTAIN |
|------|:---:|:---:|:---:|:---:|
| interface (라우터/페이지) | 0 | 0 | 55 | 0 |
| external (KIS/DART/Telegram) | 10 | 0 | 13 | 1 |
| domain(strategy 외) | 17 | 10 | 26 | 0 |
| common/settings/main | 18 | 0 | 다수 | 6 |
| strategy | 10 | 2 | 43 | 2 |
| database(모델/리포) | ~57 | 0 | 다수 | ~13 |

**핵심 교차검증**: `_upgrade_stage_for_personal_overheat`(회귀 의심 플래그)는 `_apply_overlay_stage_upgrade`(sell_strategy_service.py:644,709 배선)가 동일 로직을 인라인 처리 → **회귀 아님, superseded 중복**. 개인 과열 매도 upgrade는 정상 동작.

## 1. 제거(REMOVE) — 명백 abandoned/미사용, 저위험

### A. 미사용 import/변수/재정의 (pyflakes 확인, 런타임 무영향)
config warnings, strategy_symbol_state_repo `update`, websocket `Callable`/`approval_key`, auth `os`(+재정의), dart `json`/`date`, screener `Query`, background_tasks `datetime`/`settings`, indicators `Decimal`, order `httpx`/`OrderModel`/`OrderType`, market_data `cache`, position_manager `TradeDTO`, ohlcv_data_loader `field`, strategy_service `get_kis_client`(재정의), golden_cross_engine `Sequence`, state_machine 2건, engine `StrategyStatus`/`settings`/`strategy_id`/`order_result`×2, buy_strategy_service `StrategyError`+재정의 2, scheduler `Callable`/`StrategyStatus`, sell_strategy_service `asdict`, access_logging `path`.

### B. abandoned/superseded/중복 코드
- Telegram 레거시(교체됨): `send_buy_signal_alert`, `send_buy_signals_summary`, `send_no_buy_signals_alert`, `send_sell_signal_alert`
- `StrategyTypeEnum`(dto.py:19, adapters `StrategyType` 중복)
- state_machine `get_state_machine`/`reset_state_machine`+`_state_machine_cache`(직접 생성으로 대체된 캐싱 팩토리)
- `_upgrade_stage_for_personal_overheat`(+테스트) — superseded 중복
- `BacktestSummaryDTO`(미export 미사용 클래스), `BacktestConfigError`(미export), `ApplicationError.to_dict`(미사용), redis `delete_pattern`
- `BacktestService.print_result_summary`(디버그), `MA5BreakoutSignalGenerator.update_volume`(중복), `position_manager.to_dto`, `safety_guard.is_loss_day`, `get_strategy_performance_grade`
- DART `get_company_info_by_symbol`/`get_financial_summary`/`get_ownership_summary`/`screen_stocks_financial`, `CompanyInfoDTO.market_type`, KIS `get_hashkey`
- 순수 유틸(미사용): indicators 9개(generate_bollinger_signal, calculate_bollinger_bandwidth, is_bollinger_squeeze, is_golden_cross_active, calculate_ma_series, calculate_atr_from_ohlcv, calculate_atr_stop_loss_price, calculate_atr_trailing_stop_price, calculate_adx_from_ohlcv), performance_metrics 5개(calculate_monthly_returns, calculate_alpha, calculate_beta, calculate_tracking_error, calculate_information_ratio)
- StockScreener `exclude_symbol`/`include_symbol`/`get_universe_statistics`/`get_stocks_by_sector`, `default_start_date`, `scan_state_order`

## 2. 유지(KEEP) + 근거 — dead지만 의도적 API/toolkit surface (LOW)

precision 우선으로 아래는 **제거하지 않음**(동적/템플릿/imminent 사용 위험 + 데이터/ops 레이어 API 계약):
- **모델 @property 헬퍼 25개**(is_bullish, fill_rate, weight_ratio 등) — ORM 모델 API 관례, 순수 계산.
- **리포지토리 메서드 ~32개** — 데이터접근 API 계약 + 일부는 "미배선 트레이딩 엔진 API"(get_pending_signals, get_in_position, get_ready_to_buy, init_position_tracking, delete_by_strategy)로 imminent feature 위험.
- **ops/admin surface** — ohlcv scheduler `run_cleanup_now`/`run_update_now`/`get_next_run_times`, `health_check`×2, cache_manager `cleanup_symbol`/`validate_data_integrity`/`detect_gaps`.
- **TEST_ONLY 12개**(position_manager/safety_guard) — 테스트로 유지되는 API.
- **UNCERTAIN** — `analyze_sell_signal_hybrid`(의도적 overlay), `SellSignalRequestDTO`, Pagination DTO 헬퍼, `is_production`/`is_development`.

## 3. 실행 결과

- **미사용 import**: `autoflake`로 23파일 일괄 제거(pyflakes 잔여 0).
- **abandoned 메서드/클래스 44개** + 고아 import 3 + 전용 테스트 1 제거 → **36파일, −1054줄**.
- pytest: **526 passed**(=527 baseline − 삭제된 테스트 1) + 기존 asyncpg flake 1(무관).

## 4. codex 검토 루프

**Round 1 → 교차검증 → 보완:**

| codex 지적 | 심각도 | 교차검증 | 조치 |
|-----------|--------|----------|------|
| `print_result_summary`·`get_strategy_performance_grade` 제거했으나 `examples/backtest/*.py` 6곳에서 호출 | High×2 | 유효(subagent가 `examples/` 미포함 grep) | HEAD에서 원본 복원(dead 아님). examples 전수 재확인 |

**Round 2**: codex 확인 — src/tests/scripts/**examples**/templates/alembic 전수 재스캔, 다른 오제거 없음. **Critical/High/Medium = 0**.

**교훈**: dead-code grep 범위에 `examples/`·`templates/`·`alembic/`을 반드시 포함해야 오제거를 막는다.

**유지 근거(재확인)**: 모델 @property, 리포지토리 API, ops/admin 메서드, TEST_ONLY, UNCERTAIN은 의도적 API/toolkit surface로 보존(LOW).
