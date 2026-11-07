# CLAUDE.md - domain 디렉토리 가이드

> 도메인 계층: 비즈니스 규칙/서비스 로직을 구현하고 Interface와 Adapter 사이를 연결하는 레이어

## ✅ 역할
- 비즈니스 규칙 집행 및 트랜잭션 경계 관리
- DTO 기반 데이터 계약 유지
- DB/Redis/KIS API 호출 조합 및 캐시 정책 결정

---

## 📂 구조
```
domain/
├── access_log/           # 접근 로그 조회/통계/정리
├── admin_auth/           # 관리자 ID/PW 로그인·Redis 세션·실패 잠금 (주문 경로 게이트)
├── account/              # 계좌 잔고/포지션 조회
├── auth/                 # KIS 인증/토큰/승인키 관리
├── backtest/             # 백테스트 엔진/데이터 로더/walk-forward/라이브 패리티 리플레이
├── market_data/          # 현재가/호가/차트 조회
├── ohlcv/                # OHLCV 캐시 매니저/워밍업/스케줄러
├── order/                # 주문 생성/조회/취소/정정
├── paper_trade/          # 페이퍼 트레이딩 원장/브리지(라이브 스케줄러에 미배선)
├── recommendation/       # 추천 후보/룰셋/walk-forward 검증
├── risk/                 # 리스크 가드(예: SafetyGuard)
├── screener/             # 네이버 기반 가치주 스크리닝
└── strategy/             # 전략 관리/스캔/알림/스케줄러
```

---

## 🗂️ 도메인별 구성 요약

### access_log/
- `dto.py`: 접근 로그 목록/통계/고유 IP/정리 결과 DTO (프론트 `templates/page/access_logs.html` 응답 계약)
- `service.py`: `AccessLogRepository` 호출, `@transaction`으로 세션/트랜잭션 경계 소유

### admin_auth/
- `dto.py`: 로그인 요청/세션/로그인 결과 DTO
- `service.py`: `AdminAuthService` — scrypt 검증(`common/password_hash.py`), 세션 토큰은 SHA-256만 Redis 키로 저장, IP별 실패 잠금, 자격증명 교체 시 세션 무효화. 미설정·Redis 장애는 fail-closed

### account/
- `dto.py`: 계좌/포지션 DTO
- `service.py`: 계좌 데이터 조회, Redis 캐시 활용

### auth/
- `dto.py`: 토큰/승인키 DTO
- `service.py`: KISAuth 기반 토큰 발급/갱신/승인키 발급

### market_data/
- `dto.py`: 가격/호가/차트 DTO
- `service.py`: KIS 시세 API 호출, Redis 캐싱

### order/
- `dto.py`: 주문 관련 DTO
- `service.py`: 주문 생성/취소/정정/조회 + DB 저장

### backtest/
- `dto.py`: 백테스트 요청/결과 DTO
- `engine.py`: 시뮬레이션 엔진
- `data_loader.py`: OHLCV 로더
- `position_manager.py` / `order_manager.py`: 가상 포지션/주문 관리
- `service.py`: 백테스트 퍼사드
- 연구/검증용: `golden_cross_parity.py`(라이브 FSM 리플레이 `GoldenCrossParityReplay`), `portfolio_parity_engine.py`(공유 현금북 포트폴리오), `walk_forward*.py`, `regime_filter.py`(ADX `wilder_adx_series`), `entry_guard.py`(SafetyGuard 백테스트 재현), `state_overlay.py`/`leverage_overlay.py`/`exit_overlay.py`, `cost_schedule.py`, `statistics.py`

### risk/
- 재사용되는 리스크 가드 모듈
- `safety_guard.py`: GoldenCross 엔진의 신규 매수 사전 점검. 실효 가드는 **시장 급락**(벤치 당일 수익률 ≤ −2%, 엔진 `_benchmark_change_today`)과 **일 신규 진입 3건 상한**(`record_entry`)뿐이다. 일·주·월 손실/연속 손실 가드와 자체 `max_concurrent_positions`(3)·투자비중 한도는 계좌 상태를 채우지 않아 사실상 비활성 — 최대 보유는 전략 config `position.max_position_count`(5)를 엔진이 직접 적용한다(근거 `reports/entry_guard_eval_20261107.json`). 매도(위험 축소)는 막지 않는다.

### strategy/
- `dto.py`: 전략/유니버스/시그널 DTO
- `strategy_contract.py`: GoldenCross 상태/파라미터 canonical 계약(enum·순서 상수·SELL_STAGE_ORDER)
- `strategy_service.py`: **facade** — 전략 CRUD/분석 이력 + 아래 협력자에 위임
  - `universe_service.py`: 유니버스 갱신(ETF 시딩 + KRX 시딩 + 워커풀 + 재집계)
  - `recommendation_service.py`: 골든크로스 추천 스코어링/랭킹(`RecommendationScorer`)
  - `portfolio_cash_planner.py`: 포트폴리오 현금계획 정책(순수 policy)
- `buy_strategy_service.py`: 골든크로스 매수 스캔(`_run_scan_workers`/`_evaluate_gc_row` 공용화)
- `sell_strategy_service.py`: 매도 시그널 분석(`analyze_sell_signal` 4단 분해)
- `sell_score_rules.py`: 매도 점수 `ScoreRule` 파이프라인(points+max 단일 소스)
- `sell_rule_research_service.py` / `sell_rule_preregistration_config.py` / `sell_risk_backfill_service.py`: 매도 룰 연구/사전등록/리스크 백필
- `stock_screener.py`: 종목 스크리닝 기준
- `signal_evaluator.py` / `presets.py` / `symbol_validation.py`: 시그널 평가/프리셋/심볼 검증
- `ohlcv_data_loader.py`: DB 캐시 + KIS API OHLCV 로딩
- `golden_cross_engine.py`, `state_machine.py`: 골든크로스 실행/상태 관리. 엔진은 kill-switch(`STRATEGY_LIVE_TRADING_ENABLED`) → 직전 주문 대사 → MA drift 점검 → 레짐 게이트(실주문 fail-closed) → 후보(ETF 모드면 활성 ETF 전체, 보유 종목 먼저·종목코드 순) 처리 순이며, 주문은 기본 장후 시간외 종가(`ORD_DVSN 06`)로 접수해 `PENDING`+`order_no`로 남기고 `reconcile_open_orders`(16:10 job)가 `EXECUTED`/`CANCELLED`로 확정한다
- `market_regime.py`: 시장 국면(ADX) 게이트 공용 모듈 `build_regime_filter`/`market_regime_ok` — 스캔/알림 fail-open, 실주문 fail-closed
- `risk_contract.py`: 고점 대비 낙폭 손절 계약(`peak_drawdown_ratio` 등) 공용 함수
- `public_strategy_service.py` / `public_dto.py`: 공개 포털(`/page`, `/api/v1/public/strategies`) 제한형 스캔·매도분석(쿨다운·전역 락)
- `analysis_history_validation.py`: 분석 이력 검증
- `scheduler.py`: 전략 실행 스케줄러(`create_async_scheduler`/`register_cron_job` 공용 팩토리)
- `notification_scheduler.py`: Telegram 알림 스케줄러(wiring) — `alert_builders.py`(payload 조립)·`notification_dedupe.py`(freshness/dedupe)로 분리

> ⚠️ 레거시 볼린저 `engine.py`는 제거됨(실주문 가드 없는 이중 엔진). 이제 `golden_cross` 타입만 스케줄러로 실행된다.

---

## ✅ 설계/의존성 규칙
- Interface → Domain → Adapters 의존 방향 유지
- FastAPI Request/Response 객체를 Domain에 두지 않음
- DB 세션은 DI 또는 `@transaction`을 통해 주입
- 외부 예외는 도메인 예외로 변환해 일관된 에러 처리 유지
- 캐시 사용 여부/TTL 등 정책은 Service에서 결정

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/adapters/CLAUDE.md`
