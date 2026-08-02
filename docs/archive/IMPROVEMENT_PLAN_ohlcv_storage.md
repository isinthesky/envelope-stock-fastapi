# OHLCV 일봉 저장 서브시스템 개선 계획

> 작성: 2026-08-01 · 대상: OHLCV 적재/보존/조회 경로 + 백테스트 데이터
> 근거: 3개 초기 버그 발견 → 6개 영역 subagent 검토 + 교차검증 → 보완 → codex 루프
> 목표: **critical/high/medium = 0**. 2년치 일봉 저장 + 2년 백테스트.

## 0. 발단

"2년 백테스트"를 위해 2년치 일봉을 DB에 저장하려 했으나 데이터가 1년으로 잘려 있었고, 저장 시도가 실패했다. 원인은 **세 개의 연쇄 버그**:

| ID | 버그 | 증상 |
|----|------|------|
| S1 | `scheduler.py`가 `retention_days=365` 하드코딩(config 무시) | 야간 cleanup이 1년 초과분 삭제 |
| S2 | `load_from_api`가 `.date()`를 `get_chart_data`에 전달 → `_as_kst`의 `.tzinfo` 접근 크래시 | 100일 초과 이력 페치 전부 실패 |
| S3 | 청크 오버랩으로 중복 timestamp → `ON CONFLICT ... cannot affect row a second time` | 저장 saved=0(심볼 통째 실패) |

## 1. 6개 영역 subagent 검토 + 교차검증 결과

### 적용 완료 (fix)

| 영역 | 이슈 | 심각도 | 조치 |
|------|------|--------|------|
| retention | (S1) 하드코딩 365 | HIGH | config `ohlcv_retention_days`, scheduler가 settings 사용 |
| retention | 730=정확히 2년, 지표 워밍업 버퍼 0 | HIGH | 기본값 **1000**(2년+~270일 버퍼) |
| retention | warmup `days_if_empty=450` → 730 도달 못함 | HIGH | `settings.ohlcv_retention_days`로 시딩 |
| retention | `bulk_delete_old_data`가 interval 무시(전 interval 삭제) | MEDIUM | `interval` 파라미터 추가 + 호출부 `"1d"` |
| retention | `CacheRetentionPolicyDTO` 기본값 여전히 365 | MEDIUM | 기본값 1000 |
| fetch | (S2) date→datetime | HIGH | datetime 전달 |
| fetch | `ohlcv_max_api_days_per_call` `le=365` → KIS 100행 캡 초과 시 무음 절삭 | HIGH | `le=100` |
| fetch | KIS 빈 패딩 행에 `strptime` → 청크 전체 크래시(무음 갭) | HIGH | 빈 `stck_bsop_date` 스킵 |
| fetch | 부분 청크 실패가 caller에 미표면화 → 갭 캐싱 | HIGH | `load_from_api`가 `failed_chunks` 반환, 갭 시 캐시 스킵 |
| fetch | `days_requested==0` → 0회 호출 | LOW | `max(1, ...)` |
| save | (S3) 중복 timestamp CardinalityViolation | HIGH | `load_from_api` dedup + `save_candles_bulk` **방어적 dedup** + `return len(rows)` |
| save | `cache_to_db` NaN 가격/거래량 저장/크래시 | MEDIUM | `df.dropna` 가드 |
| data quality | 팬텀 행 18건(`normalize_timestamp` KST자정→15:00 UTC 밀림) | MEDIUM | normalize를 **KST거래일 UTC자정** 고정 + 기존 18행 삭제 |
| KOSPI | `backfill_kospi.py` 잘못된 path/TR/div/필드 → 항상 실패 | HIGH | 지수 계약(indexchartprice, FHKUP03500100, div U, ISCD 0001, `bstp_nmix_*`)으로 재작성, 50행 캡 대응(60일 청크), UTC자정 저장 |
| bind-param | 32767 초과 우려 | — | 이미 1000행 청크(조치 불요) |

### 문서화(후속 권장) — codex 재평가 대상

- **F1(loader 내부/과거 갭 자가복구)**: 스케줄 경로는 forward-only. 단, 갭 생성 원천(부분 청크 실패)이 Finding 3로 차단되어 **더 이상 갭을 캐싱하지 않음** + 현재 데이터 갭 0(감사 확인). 잔여는 "이미 존재하는 과거 갭 자가복구"로, `get_missing_date_ranges`(구현됨·미사용)를 주간 reconciliation 잡에 연결 권장.
- **F3(force_refresh 의미)**: trailing-edge 갱신만 수행(deep-fetch 아님). 1일 1발급 규칙상 의도적. docstring 명확화 권장.
- **KOSPI 자가유지**: 런타임이 KOSPI를 자동 재적재하지 않음(`MarketDataService`에 지수 메서드 없음). 현재 실 KOSPI 적재됨. warmup 유니버스에 KOSPI 편입 또는 지수 메서드 추가 권장.

## 2. 데이터 적재 결과

- 상위 100종목 + KOSPI + 프록시 5종목: **각 ~506행(2024-07-02 ~ 2026-07-31, ~2년)**.
- KOSPI 실지수 506행(00:00 UTC 정렬, stock과 일치). 갭 4~5건=한국 휴장(감사 확인, 페치 홀 아님).
- 팬텀 행 0, 값 이상 0.

## 3. 2년 백테스트 (운영 함수, 실 OHLCV)

| 시장 소스 | market_days | fear_days | combined_trades | 승률 | 평균수익 |
|-----------|:---:|:---:|:---:|:---:|:---:|
| PROXY(대형주) | 506 | 49 | 66 | 56.1% | +28.8% |
| **KOSPI(실지수)** | 506 | 54 | **58** | **56.9%** | **+32.3%** |

- 1년 창(이전, 데이터 축소 상태)에서는 5%/−12.4%였음 → **결과가 데이터 창에 극도로 민감**(저빈도 전략 특성). 2년 창에서는 양호하나, 표본(58거래)과 단일 2년 구간의 한계를 감안해야 함.

## 4. 검증

- 전체 pytest **527 passed**(신규/갱신 포함, 1건 기존 asyncpg 이벤트루프 격리 flake 무관).
- 저장 end-to-end: 100종목 백필 0 실패, KOSPI 506행, 백테스트 combined>0.

## 5. codex 검토 루프

**Round 1 → 교차검증 → 보완:**

| codex 지적 | 심각도 | 교차검증 | 조치 |
|-----------|--------|----------|------|
| `incremental_update`가 `failed_chunks`를 버림 → 증분 경로에서 갭 캐싱(skip 가드가 full-load만 커버) | High | 유효(유일 호출부=data_loader) | `incremental_update` 4-tuple 전파, data_loader가 언패킹 → 캐시 가드가 증분 경로도 커버 |
| `backfill_2y.py`가 `failed_chunks` 무시하고 부분 데이터 캐싱 | High | 유효 | `failed>0` 시 rollback + 실패 분류 |
| cleanup `symbols_affected` interval-agnostic | Low | 무영향(`get_symbol_stats`/enum 모두 1d 기본, 1d 데이터만 존재) | 유지 |

**Round 2**: codex 확인 — **Zero Critical/High/Medium remaining: YES**. normalize_timestamp KST 앵커·save dedup(keep=last)·retention 1000 마이그레이션 모두 정합 확인.

**최종 상태**: 전체 pytest **527 passed**(기존 asyncpg flake 1건 무관). 103종목 2년치(팬텀 0), KOSPI 실지수 506행. 2년 백테스트(실 KOSPI): 승률 **56.9%**, 평균 **+32.25%**.
