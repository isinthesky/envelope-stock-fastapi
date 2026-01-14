# CLAUDE.md - `application/domain/` (Domain) 가이드

> 비즈니스 규칙/정책을 구현하는 레이어입니다. 외부 I/O(DB/Redis/KIS/Naver/Telegram/WS)는 **항상 adapters를 통해** 수행하고, interface는 domain 서비스를 호출만 합니다.

## 이 레이어의 역할
- 유즈케이스 조합(예: “차트 조회 + 캐시 + 저장”, “전략 실행 + 알림”)
- 트랜잭션/세션 경계 정의(직접 세션 주입 또는 `@transaction` 사용)
- 캐시 정책(키/TTL/우선순위) 결정
- 외부 예외를 도메인 예외/응답 계약으로 변환

## 서브도메인 구조(현재 폴더 기준)

```text
domain/
  account/        # 계좌/포지션 조회
  auth/           # KIS 인증/토큰/승인키
  market_data/    # 시세/호가/차트
  order/          # 주문 생성/취소/정정/조회
  strategy/       # 전략 실행/스케줄링/알림/유니버스/시그널
  backtest/       # 백테스트 엔진/데이터 로더/퍼사드 서비스
  ohlcv/          # OHLCV DB 캐시(통계/워밍업/정리/스케줄러)
  screener/       # 가치주 스크리닝(네이버 금융 연동)
  news_trading/   # 뉴스 기반 단타 전략(별도 가이드 존재)
  websocket_domain/  # 실시간 도메인 확장 지점(플레이스홀더)
```

## 도메인 공통 규칙 (Do / Don't)
- **Do**
  - 입력/출력 계약은 `dto.py`에 명시(Pydantic DTO 중심)
  - 외부 연동 객체는 생성/주입 지점을 고정(DI 또는 팩토리 함수)
  - 캐시/트랜잭션 경계를 “서비스 레벨”에서 관리
- **Don't**
  - FastAPI/Starlette 객체를 domain으로 끌어오지 않기
  - Repository/Redis/HTTP 호출을 interface에서 직접 하지 않기
  - adapter 결과를 그대로 API 응답 스키마로 누수시키지 않기(필요 시 DTO로 변환)

## 라이프사이클 연계(현재 코드 기준)
- `src/main.py`의 lifespan에서 아래가 시작/종료됩니다.
  - KIS 토큰 자동갱신 태스크(`application.common.background_tasks`)
  - 전략 엔진/스케줄러/알림(`domain.strategy.*`)
  - OHLCV 캐시 스케줄러(`domain.ohlcv.scheduler`)

## 관련 문서
- `src/application/common/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/application/domain/news_trading/CLAUDE.md`
- `src/adapters/CLAUDE.md`

