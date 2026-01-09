# CLAUDE.md - domain 디렉토리 가이드

> **도메인 계층**: 비즈니스 규칙/서비스 로직을 구현하고 Interface와 Adapter 사이를 연결하는 레이어

## ✅ 역할
- 비즈니스 규칙 집행 및 트랜잭션 경계 관리
- DTO 기반 데이터 계약 유지
- DB/Redis/KIS API 호출 조합 및 캐시 정책 결정

---

## 📂 구조
```
domain/
├── account/              # 계좌 잔고/포지션 조회
├── auth/                 # KIS 인증/토큰 관리
├── backtest/             # 백테스트 엔진/데이터 로더
├── market_data/          # 현재가/호가/차트 조회
├── order/                # 주문 생성/조회/취소
├── strategy/             # 전략 관리/스캔/알림
├── news_trading/         # 뉴스 기반 단타 전략
└── websocket_domain/     # WS 도메인 플레이스홀더
```

---

## 🗂️ 도메인별 구성 요약

### account/
- `dto.py`: 계좌/포지션 DTO
- `service.py`: 계좌 데이터 조회, Redis 캐시 활용

### auth/
- `dto.py`: 토큰/승인키 DTO
- `service.py`: KISAuth 기반 토큰 발급/갱신

### market_data/
- `dto.py`: 가격/호가/차트 DTO
- `service.py`: KIS 시세 API 호출, Redis 캐싱

### order/
- `dto.py`: 주문 관련 DTO
- `service.py`: 주문 생성/취소/조회, KIS 주문 API 호출

### backtest/
- `dto.py`: 백테스트 요청/결과 DTO
- `engine.py`: 시뮬레이션 엔진
- `data_loader.py`: OHLCV 수집 + DB 캐시 로더
- `position_manager.py` / `order_manager.py`: 가상 포지션/주문 관리
- `service.py`: 백테스트 퍼사드

### strategy/
- `strategy_service.py`: 전략 CRUD/유니버스/상태 관리
- `buy_strategy_service.py`: 골든크로스 매수 후보 스캔(MA40/MA160)
- `sell_strategy_service.py`: 매도 시그널 분석(MA/Stochastic/RSI)
- `ohlcv_data_loader.py`: DB 캐시 + KIS API OHLCV 로딩
- `scheduler.py`: 전략 실행 스케줄러
- `notification_scheduler.py`: Telegram 알림 스케줄러
- `golden_cross_engine.py`, `state_machine.py`: 골든크로스 실행/상태 관리
- `engine.py`: 레거시 전략 실행 엔진

### news_trading/
- 뉴스 기반 단타 전략 모듈 (상세는 해당 CLAUDE 문서 참고)

### websocket_domain/
- 실시간 도메인 확장 지점(플레이스홀더)

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
- `src/application/domain/news_trading/CLAUDE.md`
- `src/adapters/CLAUDE.md`
