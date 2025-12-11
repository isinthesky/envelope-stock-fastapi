# CLAUDE.md - domain 디렉토리 가이드

> **도메인 계층**: FastAPI Router(Interface)와 Adapter 사이에서 비즈니스 규칙을 집행하는 서비스 레이어

## 🎯 역할
- 도메인 규칙, 트랜잭션 경계, 리스크 관리 책임을 집중
- DTO를 통해 데이터 계약을 명확히 유지하고 ORM/HTTP 세부사항을 차단
- Adapter(KIS API, DB, Redis, 외부 WS) 호출을 조합·검증하며 캐시·재시도 정책을 결정
- Interface 계층이 사용하는 단일 진입점(Service 클래스) 제공

---

## 📂 구조
```
domain/
├── account/              # 계좌 잔고/포지션 조회
├── auth/                 # KIS 인증 및 토큰 관리
├── backtest/             # 백테스트 엔진과 보조 모듈
├── market_data/          # 시세/차트/호가 조회
├── order/                # 주문 생성·취소·상태 관리
├── strategy/             # 전략 설정/실행 엔진
├── news_trading/         # 뉴스 기반 단타 전략 (Phase 1~4)
└── websocket_domain/     # WebSocket 도메인 플레이스홀더
```

---

## 🗂️ 도메인별 파일 요약

### account/
- `account/dto.py`: 계좌 잔고/포지션 요청·응답 DTO 정의(Decimal 정밀도 유지).
- `account/service.py`: KIS API + Redis 캐시를 조합해 잔고/포지션 조회, 합계 계산.

### auth/
- `auth/dto.py`: 액세스 토큰, 상태, WebSocket 승인키 DTO.
- `auth/service.py`: KISAuth를 통해 토큰 발급·갱신·상태 조회, 환경 정보 노출.

### market_data/
- `market_data/dto.py`: 현재가, 호가, 캔들/차트 요청·응답 DTO.
- `market_data/service.py`: KIS 시세/차트 API 호출, 입력 검증, 단위 변환·정규화.

### order/
- `order/dto.py`: 주문 생성/취소/상태/목록 DTO와 값 검증.
- `order/service.py`: 주문 페이싱 락, KIS 주문 호출, 재시도·레이트리밋 처리, DB 저장/조회.

### strategy/
- `strategy/dto.py`: 전략 설정(Bollinger, Envelope, 리스크 관리 등) 및 CRUD 요청/응답 DTO.
- `strategy/engine.py`: 지표 기반 전략 실행 엔진, 시그널 생성과 포지션 관리 로직.
- `strategy/service.py`: 전략 생성·수정·상태 전환, DB 저장소와 엔진 실행 오케스트레이션.

### backtest/
- `backtest/dto.py`: 백테스트 설정, 일별 통계, 거래 로그 DTO.
- `backtest/engine.py`: OHLCV 반복 시뮬레이션, 시그널/체결/성과 집계 핵심 엔진.
- `backtest/data_loader.py`: KIS/DB에서 가격 데이터 로드 및 전처리.
- `backtest/position_manager.py`: 포지션 수량/평단/손익 관리.
- `backtest/order_manager.py`: 가상 주문 생성·체결·수수료/슬리피지 반영.
- `backtest/service.py`: 백테스트 실행 엔드포인트용 퍼사드, 결과 DTO 조립.

### news_trading/ (뉴스 기반 단타 전략)
- `news_trading/dto.py`: 뉴스 이벤트/스코어, 종목 후보, 랭킹·포지션/체결 DTO와 검증 로직.
- `news_trading/news_analyzer.py`: 뉴스 키워드 기반 이벤트 분류, 스코어링, 종목 매핑.
- `news_trading/stock_selector.py`: 거래량·상승률·수급·호가 조건 필터링 및 랭킹 계산.
- `news_trading/momentum_detector.py`: 체결 속도·호가 불균형 등 모멘텀 약화 신호 탐지.
- `news_trading/exit_manager.py`: 분할 익절/손절, 시간 청산 등 청산 규칙 적용.
- `news_trading/safety_guard.py`: 일일 손실 한도, 동시 포지션 제한 등 리스크 가드 레이어.
- `news_trading/strategy_engine.py`: 뉴스 분석→후보 선정→매수/청산 흐름을 오케스트레이션.
- `news_trading/backtest_engine.py`: 뉴스 전략 전용 백테스트 실행기.
- `news_trading/CLAUDE.md`: 뉴스 전략 전용 가이드(이 문서와 별도로 관리).

### websocket_domain/
- `websocket_domain/__init__.py`: 실시간 시세/체결 도메인용 플레이스홀더(추가 확장 지점).

---

## ✅ 설계·의존성 규칙
- **Interface → Domain → Adapters** 방향만 허용. FastAPI/HTTP 객체는 Domain에 두지 않는다.
- **DTO 기반 계약**: Service 입·출력은 `application.common.dto.BaseDTO`를 상속한 DTO만 사용.
- **Adapter 호출 시** 재시도/레이트리밋/캐시 여부를 Service에서 결정하고 예외를 Domain 예외로 변환.
- **트랜잭션 경계**는 `@transaction` 등 공통 데코레이터로 감싸고, DB 세션은 주입받아 사용.
- **시간·금액 단위**는 DTO에서 명시적으로 관리(Decimal 사용)하며 설정 값은 `settings.config`에서 주입.
- **테스트**는 도메인별 독립 픽스처로 성공/실패 경로 모두 검증하고, 외부 연동은 더블/스텁 사용.

---

## 🔗 참고
- 상위 계층 개요: `src/application/CLAUDE.md`
- Adapter 연동 규칙: `src/adapters/CLAUDE.md`
- 아키텍처/네이밍: `docs/base/ARCHITECTURE.md`, `docs/base/convention.md`
