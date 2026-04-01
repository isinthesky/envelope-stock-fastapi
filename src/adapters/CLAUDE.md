# CLAUDE.md - `src/adapters/` (Infrastructure / Outbound) 가이드

> 외부 시스템 연동을 캡슐화합니다(DB/Redis/KIS/Naver/Telegram/WS). 도메인은 adapters를 통해서만 I/O를 수행합니다.

## 폴더 구조(현재 코드 기준)

```text
adapters/
  database/
    connection.py        # Async engine/session, get_db/close_db
    models/              # SQLAlchemy ORM models
    repositories/        # Repository 패턴
  cache/
    redis_client.py      # RedisClient + factory(get_redis_client)
  external/
    kis_api/             # KIS 인증/REST 호출/예외
    websocket/           # KIS WebSocket 연결/구독 관리
    telegram/            # Telegram notifier
    naver/               # Naver 금융 스크리닝용 client
```

## database/
- **connection**: `create_async_engine` 기반, `AsyncSessionLocal` 제공, `get_db()`로 세션 yield
- **models**(주요):
  - `account.py`, `position.py`, `order.py`
  - `strategy.py`, `strategy_signal.py`, `strategy_symbol_state.py`
  - `stock_universe.py`, `ohlcv.py`, `analysis_history.py`
- **repositories**(주요):
  - `base_repository.py` (공통 CRUD)
  - `order_repository.py`, `strategy_repository.py`
  - `strategy_signal_repository.py`, `strategy_symbol_state_repository.py`
  - `stock_universe_repository.py`, `ohlcv_repository.py`, `analysis_history_repository.py`

## cache/
- `redis_client.py`는 애플리케이션 전역에서 재사용되는 Redis 연결/명령 래퍼를 제공합니다.
- TTL/키 정책은 domain(service)에서 결정합니다.

## external/
- **kis_api/**
  - `auth.py`: 토큰 발급/갱신/캐시(환경(prod/vps)은 `settings`로 결정)
  - `client.py`: REST 호출(타임아웃/레이트리밋/재시도/백오프)
  - `exceptions.py`: KIS 연동 예외 정의
- **websocket/**
  - `kis_websocket.py`: WS 연결/송수신
  - `websocket_manager.py`: 연결 풀/구독 관리
- **telegram/**
  - `notifier.py`: Bot API 메시지 전송
- **naver/**
  - `stock_client.py`: 재무/지표 조회(스크리너 도메인에서 사용)

## 구현 규칙
- adapters는 **비즈니스 정책을 결정하지 않습니다**.
  - 예: “캐시를 언제/얼마나 저장할지”, “리스크 한도”는 domain 책임
- domain DTO에 맞춘 변환은 domain에서 수행합니다(어댑터는 원천 데이터/ORM을 제공해도 됨).
- 네트워크 I/O는 비동기 구현을 기본으로 합니다(HTTP/DB/Redis/WS).

## 관련 문서
- `src/settings/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`

