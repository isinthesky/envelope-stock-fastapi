# 데이터 수집 및 검증 가이드

> **현황(2026-11-07)**: 이전 판은 구현되지 않은 설계안(`ChartData` 모델, CSV 백업, Redis 차트 캐시,
> 결측 보간·분할 조정 함수 등)의 샘플 코드였다. 이 판은 **실제 구현 기준**으로 다시 썼다.

## 📋 목차
1. [데이터 소스](#데이터-소스)
2. [저장: ohlcv_cache](#저장-ohlcv_cache)
3. [백테스트 로더 검증](#백테스트-로더-검증)
4. [커버리지 게이트 (walk-forward)](#커버리지-게이트-walk-forward)
5. [알려진 데이터 이슈](#알려진-데이터-이슈)
6. [체크리스트](#체크리스트)

---

## 데이터 소스

| 대상 | 경로 / TR | 비고 |
|---|---|---|
| 종목·ETF 일봉 | `inquire-daily-itemchartprice` / `FHKST03010100` | `MarketDataService` (`domain/market_data/service.py`), `FID_ORG_ADJ_PRC="0"`(수정주가) |
| 지수 일봉 | `inquire-daily-indexchartprice` / `FHKUP03500100` | 50행 캡 → 60일 청크. `scripts/ops/backfill_kospi.py`(ohlcv_cache `symbol='KOSPI'`) |
| 장기 지수(연구 전용) | 동일 TR | `reports/data/index_daily_{0001,2001}[_1990s].csv` — KOSPI(0001) 1990~, KOSPI200(2001) 1992~. 소비: `scripts/research/{state,leverage}_overlay_prereg_20261107.py` |

- 수정주가: KIS 수정주가는 분할/병합을 반영한다. ETF는 **분배금도 반영된 것으로 보인다**
  (가격 ETF와 TR ETF의 CAGR 차이가 ~0.1–0.2%p에 그침, 약 70% 확신). 별도 수동 분할 조정 로직은 없다.
- 단일 호출 캡: `settings.ohlcv_max_api_days_per_call`(기본·최대 100) — 100행 초과분은 KIS가
  과거분을 무음 절삭. 백테스트 로더는 `chunk_days=90`으로 역방향 분할 수집
  (`BacktestDataLoader._collect_long_period`).
- 빈 패딩 행(`stck_bsop_date` 없음)은 스킵한다.

## 저장: ohlcv_cache

- 모델/리포지토리: `adapters/database/models/ohlcv.py`(`ohlcv_cache`, UNIQUE(symbol, timestamp, interval)),
  `adapters/database/repositories/ohlcv_repository.py`.
- 적재 범위: ETF 유니버스 일봉 **2018-01~** (walk-forward 홀드아웃 2018~19 포함).
  백필: `scripts/ops/backfill_universe_with_coverage.py`.
- 저장: `OHLCVRepository.save_candles_bulk` — PostgreSQL `ON CONFLICT DO UPDATE` 업서트,
  업서트 시 `updated_at` 갱신.
- **잠정 봉 차단**: 15:31 KST 이전에 받은 당일 일봉은 저장하지 않는다
  (`common/trading_calendar.is_provisional_daily_bar`). 로더는 메모리로는 그대로 반환.
- 보존: `OHLCV_RETENTION_DAYS` 기본 **3650**(이전 1400 — 2023 이전 연구 데이터가 지워져 재현 불가했음).
  줄이면 02:00 정리 job이 2018~ 데이터를 삭제한다.
- 스케줄(`domain/ohlcv/scheduler.py`): 02:00 정리, 08:00 어제까지 워밍업, 평일 16:00 증분 업데이트.
- 무결성 점검: `OHLCVCacheManager.validate_data_integrity`(OHLC 관계·중복).
  누락 구간 조회는 `OHLCVRepository.get_missing_date_ranges`.
  (`cache_manager.detect_gaps`, `GapInfoDTO`/`SymbolGapsDTO`는 **제거됨**.)

## 백테스트 로더 검증

구현: `domain/backtest/data_loader.py` `BacktestDataLoader`.

1. `load_ohlcv_data`: DB 캐시 우선 → 앞/뒤 부족 구간만 KIS로 보충 후 캐시 저장. 반환은
   `(df, actual_start, actual_end)` — 요청 구간 일부만 있으면 실제 구간으로 축소(서비스가 경고 출력).
2. `_preprocess_data`: 정렬 → forward fill → timestamp 중복 제거.
3. `_validate_data`(위반 시 `BacktestDataError`):
   - 20행 미만, OHLC 관계 위반(`_validate_ohlc_relationship`), 결측치, 가격 ≤ 0, 음수 거래량.
4. `validate_missing_dates`: 결측일·커버리지율 산출.

API: `POST /api/v1/backtest/validate-data` → `BacktestService.validate_data_quality`
(`coverage_rate`, `missing_count`, `is_truncated`, 가격 통계).

> 이상치(z-score) 탐지, 결측 보간 정책 선택, 휴장일 API 필터는 구현되어 있지 않다.

## 커버리지 게이트 (walk-forward)

- 구현: `domain/backtest/coverage_gate.py`(순수 로직), 실행: `scripts/ops/backfill_universe_with_coverage.py`.
- 분모: 벤치마크(기본 069500 KODEX 200)의 **실제 거래일**. 커버리지 = 벤치 거래일 중 종목 데이터 보유 비율.
- 임계값(`CoverageParams`): `--min-bars`(기본 285), `--min-coverage`(기본 0.98). 제외 종목도 사유와 함께 리포트.
- `run_walk_forward.py --coverage`가 이 리포트의 included 종목을 사용한다.

## 알려진 데이터 이슈

- 2026-03-30~11-06 사이 5개 날짜에 장중/보합 잠정 봉이 캐시되어 있었음 → 221종 재조회로 복구,
  이후 잠정 봉 가드로 차단. 재발 탐지: 봉 날짜와 같은 날 15:31 이전 `updated_at`.
- 생존 편향: 유니버스는 현재 상장 ETF 기준.

## 체크리스트

- [ ] 대상 구간이 ohlcv_cache 범위(2018-01~) 안인가 (밖이면 KIS 호출·토큰 발급 발생)
- [ ] 커버리지 게이트 통과 종목만 사용했는가
- [ ] 벤치마크 거래일 달력과 정렬되는가
- [ ] 당일 잠정 봉이 포함되지 않았는가
- [ ] 비용 스케줄 지원 시작일(2018-01-01) 이후인가 (`UnsupportedBacktestCostDateError`)

---

**마지막 업데이트**: 2026-11-07
