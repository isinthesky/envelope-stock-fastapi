# CLAUDE.md - `domain/news_trading/` 서브도메인 가이드

> 뉴스 이벤트 기반 단타 전략(분석 → 후보 선별 → 진입/추적/청산 → 리스크 가드 → 백테스트)을 구현합니다. **현재 코드베이스에서는 독립 모듈**이며, API로 노출하거나 스케줄링에 연결할 때 `domain` 서비스로 감싸서 `interface`에서 호출합니다.

## 구성(현재 파일 기준)

```text
news_trading/
  dto.py               # 뉴스/후보/포지션/리스크 DTO
  news_analyzer.py     # 뉴스 분류/스코어링
  stock_selector.py    # 후보 필터링/랭킹
  momentum_detector.py # 모멘텀 약화 신호 탐지
  safety_guard.py      # 진입 전 리스크 가드(손절/노출/금지조건 등)
  exit_manager.py      # 청산 규칙 적용(시간/손절/익절 등)
  strategy_engine.py   # 실거래 오케스트레이션(연동 지점)
  backtest_engine.py   # 백테스트 전용 오케스트레이션
```

## 규칙/가드레일
- **의존성 방향**: `interface → domain(news_trading) → adapters`
- **DTO 우선**: 외부 입출력 계약은 `dto.py`에서 고정하고, 내부 로직은 DTO 기준으로 조합
- **리스크 우선**: `safety_guard` 통과 전에는 진입/추적 로직이 실행되지 않도록 구성
- **규칙 공유**: 실거래/백테스트는 가능한 한 동일 규칙(청산/리스크)을 재사용
- **공통 유틸 사용**: 지표/성과 계산은 `application.common`의 유틸을 재사용

## 통합 시 권장 방식
- API로 노출 시: `domain/news_trading/service.py`(퍼사드) 추가 → `interface/api/news_trading_router.py`로 라우팅
- 스케줄링 시: `src/main.py` lifespan에서 시작/정리되는 스케줄러 패턴(`domain.strategy.*`)을 참고

## 관련 문서
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`

