# CLAUDE.md - news_trading 도메인 가이드

> **뉴스 기반 단타 전략 도메인**: 뉴스 이벤트 분석 → 종목 선별 → 매수/청산 → 리스크 가드 → 백테스트까지의 전 과정 오케스트레이션

## 목적
- 뉴스 이벤트를 정량화(스코어)하고 시세·수급 지표와 결합해 **단타 진입 후보**를 산출
- 모멘텀 둔화·시간 청산·손절/익절 규칙을 자동 집행하여 **리스크 관리**를 강화
- 전략/백테스트 엔진을 통해 **재현 가능한 시뮬레이션**과 실거래 흐름을 공유

---

## 구조
```
news_trading/
├── dto.py              # 뉴스/후보/랭킹/포지션 DTO 및 검증
├── news_analyzer.py    # 뉴스 이벤트 분류·스코어링·종목 매핑
├── stock_selector.py   # 09:00~09:10 필터링 및 랭킹 산출
├── momentum_detector.py# 모멘텀 약화 신호 감지
├── exit_manager.py     # 분할 익절/손절/시간 청산 규칙
├── safety_guard.py     # 일일 손실/포지션 한도 등 리스크 가드
├── strategy_engine.py  # 실거래 전략 오케스트레이션(뉴스→선별→주문/청산)
├── backtest_engine.py  # 뉴스 전략 전용 백테스트 실행기
└── CLAUDE.md           # 본 문서
```

---

## 파일별 역할
- `dto.py`: 뉴스 이벤트 타입/스코어, 종목 후보/랭킹, 포지션·체결·리스크 DTO를 정의해 **입출력 계약**을 고정.
- `news_analyzer.py`: 키워드 사전 기반 이벤트 분류, 영향도/신선도/확산도 스코어 계산, 종목-뉴스 매핑.
- `stock_selector.py`: 거래량·상승률·수급·호가 조건을 적용해 후보를 필터링하고 가중치 기반 랭킹 점수 계산.
- `momentum_detector.py`: 체결 속도, 호가 불균형, 거래량 감소 등 **모멘텀 약화 신호**를 감지하여 조기 청산 트리거 생성.
- `exit_manager.py`: 1·2차 익절, 모멘텀 청산, 시간 청산, 손절 규칙을 적용해 **청산 시그널**을 결정.
- `safety_guard.py`: 일일 손실 한도, 종목/포지션 제한, 연속 손실 차단 등 **보호 규칙**을 집행.
- `strategy_engine.py`: 뉴스 분석→후보 선별→주문/청산→리스크 가드 흐름을 연결하는 **실거래 오케스트레이션** 레이어.
- `backtest_engine.py`: 동일 규칙으로 과거 데이터에 대해 시뮬레이션을 수행하는 **백테스트 러너**.

---

## 설계·규칙
- **의존성 방향**: Interface → Domain(news_trading) → Adapters. FastAPI 요청/응답 객체는 Domain 내부에 두지 않는다.
- **DTO 우선**: 모든 입출력은 `news_trading/dto.py`의 DTO를 사용하여 데이터 계약을 고정한다.
- **리스크 우선**: `safety_guard`에서 한도 검증 후에만 전략 흐름을 진행하고, 모든 예외는 Domain 예외로 변환한다.
- **동일 로직 재사용**: 실거래 `strategy_engine`과 `backtest_engine`은 동일 규칙을 공유해야 하며 지표·성과 계산은 `application.common` 모듈을 사용한다.
- **시간대/세션 고려**: 09:00~09:10 프리필터링, 장중 모니터링, 장 종료 청산 시점 등 **세션별 규칙**을 명시적으로 코드에 반영한다.
- **외부 데이터 검증**: KIS/뉴스 소스 응답은 DTO 검증 및 `validators.py`를 통해 값 범위를 확인하고, Decimal·타임존을 명시한다.

---

## 참고
- 도메인 레이어 개요: `src/application/domain/CLAUDE.md`
- 공통 유틸: `src/application/common/CLAUDE.md`
- 아키텍처/네이밍: `docs/base/ARCHITECTURE.md`, `docs/base/convention.md`
