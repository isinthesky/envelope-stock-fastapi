---
name: stock-ohlcv-cache
description: OHLCV 일봉 캐시(ohlcv_cache) 동작·스케줄러·보존 정책·백필 작업을 안내합니다. 일봉 캐시, cache, warmup, backfill, 데이터 관리 관련 작업에 사용하세요.
allowed-tools: Bash, Read, Glob, Grep
---

# OHLCV Cache Management Skill

`ohlcv_cache` 테이블(일봉 `interval='1d'`)을 관리합니다. (현황 2026-11-07 기준)

> ⚠️ `/api/v1/ohlcv/*` REST API는 **존재하지 않습니다**(구현된 적 없음). 이 API만 호출하던
> `/mypage/ohlcv` 페이지(버튼 전부 404)는 2026-11-07 제거됐습니다.
> 캐시 조작은 아래 스케줄러/서비스/스크립트를 사용하세요.

## 구성 요소

| 역할 | 위치 |
|------|------|
| 저장/조회 | `src/adapters/database/repositories/ohlcv_repository.py` `OHLCVRepository` (`save_candles_bulk`, `get_candles_by_date_range`, `get_missing_date_ranges`, `get_symbols_with_stale_data`, `get_cache_summary`, `bulk_delete_old_data` 등) |
| 정리/무결성 | `src/application/domain/ohlcv/cache_manager.py` `OHLCVCacheManager` (`cleanup_old_data`, `cleanup_symbol`, `validate_data_integrity`) |
| 워밍업/증분 | `src/application/domain/ohlcv/warmup_service.py` `OHLCVWarmupService` (`warmup_symbols`, `update_stale_symbols`, `warmup_symbol_until`) |
| 스케줄러 | `src/application/domain/ohlcv/scheduler.py` `OHLCVCacheScheduler` (`run_cleanup_now`, `run_update_now`) |
| DTO | `src/application/domain/ohlcv/dto.py` (`CacheRetentionPolicyDTO`, `CacheStatisticsDTO`, `CacheHealthDTO`, `WarmupRequestDTO/ResultDTO`, `CleanupResultDTO`, `ApiCallEstimateDTO`) |

- 결측 구간 탐지 `cache_manager.detect_gaps` 및 `GapInfoDTO`/`SymbolGapsDTO`는 **제거됨**. 결측 구간은 `OHLCVRepository.get_missing_date_ranges` 사용.

## 저장 규칙

- **잠정 일봉 미저장**: 당일(KST) 일봉은 15:31 KST 이전이면 저장하지 않음 — `OHLCVRepository.save_candles_bulk` + `src/application/common/trading_calendar.py` `is_provisional_daily_bar` (`DAILY_BAR_FINAL_TIME_KST=(15,31)`).
- upsert(`on_conflict_do_update`) 시 `updated_at` 갱신.
- KIS 단일 호출 최대 100일(`ohlcv_max_api_days_per_call`, 초과 시 과거분 무음 절삭).
- 가격은 KIS 수정주가(분배금 반영으로 보임). ETF 일봉은 2018-01~ 적재.

## 설정 (`src/settings/config.py`)

| 설정 | 기본값 | 의미 |
|------|--------|------|
| `ohlcv_retention_days` | 3650 (2026-11-06 1400→3650) | 정리 job 보존 기간. 2018~ walk-forward 재현용 |
| `ohlcv_cleanup_batch_size` | 1000 | 정리 배치 크기(스케줄러는 1000 하드코딩) |
| `ohlcv_cache_freshness_days` | 1 | 캐시 신선도 기준 |
| `ohlcv_warmup_freshness_days` | 3 | 워밍업 신선도 기준 |
| `ohlcv_max_api_days_per_call` | 100 | KIS 호출당 최대 일수 |

## 스케줄러 작업 (Asia/Seoul)

| 작업 id | 시간 | 설명 |
|---------|------|------|
| `ohlcv_cleanup` | 매일 02:00 | `ohlcv_retention_days`(3650일) 이전 데이터 삭제 |
| `ohlcv_warmup_until_yesterday` | 매일 08:00 | 스캔 유니버스를 직전 거래일까지 누락 구간만 워밍업 |
| `ohlcv_update` | 평일 16:00 | `update_stale_symbols(freshness_days=3, concurrency=3)` 증분 업데이트 |

## 백필 스크립트 (컨테이너 실행, KIS 토큰+DB 필요)

- `scripts/ops/backfill_universe_with_coverage.py` — ETF 유니버스 다년 백필 + 커버리지 게이트 (`--start`, `--end`, `--codes`, `--min-bars`, `--min-coverage`, `--benchmark`, `--no-cache`)
- `scripts/ops/backfill_kospi.py`, `scripts/ops/backfill_2y.py` — 보조 백필
- 지수 일봉(KOSPI 0001, KOSPI200 2001)은 연구용으로 `reports/data`에 별도 저장(캐시 아님).

## 점검 쿼리 예

```sql
SELECT symbol, count(*), min(timestamp), max(timestamp)
FROM ohlcv_cache WHERE interval='1d' GROUP BY symbol ORDER BY 2 DESC;
```
