# CLAUDE.md - adapters 디렉토리 가이드

> **Adapter 계층(Infrastructure)**: DB/Redis/KIS/Telegram/WS 등 외부 시스템 연동 담당

## ✅ 역할
- 데이터 저장소, 캐시, 외부 API/WS 통신을 캡슐화
- 도메인 로직 없이 순수 인프라 연동만 담당

---

## 📂 구조
```
adapters/
├── database/               # PostgreSQL + SQLAlchemy(Async)
│   ├── connection.py       # Async Engine/Session 관리
│   ├── models/             # ORM 모델
│   └── repositories/       # Repository 패턴
├── cache/                  # Redis 클라이언트
└── external/               # KIS API / Telegram / WebSocket
```

---

## 🗄️ database/
### 주요 모델
- `account.py`, `position.py`, `order.py`
- `strategy.py`, `strategy_signal.py`, `strategy_symbol_state.py`
- `stock_universe.py`, `ohlcv.py`, `analysis_history.py`

### 주요 Repository
- `order_repository.py`
- `strategy_repository.py`
- `strategy_signal_repository.py`
- `strategy_symbol_state_repository.py`
- `stock_universe_repository.py`
- `ohlcv_repository.py`
- `analysis_history_repository.py`
- `base_repository.py` (CRUD + mixin)

### connection.py
- `create_async_engine` 기반 Async Engine 사용
- `AsyncSessionLocal` 세션 팩토리 제공
- `get_db()`, `get_async_session()` 제너레이터 제공

---

## 🔴 cache/
- `redis_client.py`: Redis 비동기 클라이언트
- 도메인별 캐시 헬퍼(`cache_market_data`, `cache_account_data`, `cache_chart_data`)

---

## 🌐 external/
### kis_api/
- `auth.py`: 토큰 발급/갱신/캐시
- `client.py`: REST 호출, 레이트리밋/재시도
- `exceptions.py`: KIS API 예외

### telegram/
- `notifier.py`: Telegram Bot API 메시지 전송 클라이언트

### websocket/
- `kis_websocket.py`: WS 연결/메시지 송수신
- `websocket_manager.py`: 연결 풀 관리

---

## ✅ 구현 규칙
- Adapter는 비즈니스 로직을 포함하지 않습니다.
- DTO 변환/검증은 Domain에서 수행합니다.
- 모든 I/O는 비동기로 구현합니다.
- DB 세션은 `AsyncSession` 기반으로만 사용합니다.

---

## 🔗 관련 문서
- `src/application/domain/CLAUDE.md`
- `src/settings/CLAUDE.md`
