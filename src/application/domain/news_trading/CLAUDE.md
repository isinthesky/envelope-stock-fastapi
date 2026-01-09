# CLAUDE.md - news_trading 도메인 가이드

> 뉴스 기반 단타 전략 도메인: 뉴스 이벤트 분석 → 후보 선별 → 진입/청산 → 리스크 관리 → 백테스트

## ✅ 목적
- 뉴스 이벤트를 정량화해 매수 후보를 선별
- 모멘텀 약화/시간 청산/손절·익절 규칙으로 리스크 관리
- 실거래/백테스트가 동일 규칙을 공유하도록 구성

---

## 📂 구조
```
news_trading/
├── dto.py               # 뉴스/후보/포지션/리스크 DTO
├── news_analyzer.py     # 뉴스 분류/스코어링
├── stock_selector.py    # 후보 필터링 및 랭킹
├── momentum_detector.py # 모멘텀 약화 신호 탐지
├── exit_manager.py      # 청산 규칙 적용
├── safety_guard.py      # 리스크 가드
├── strategy_engine.py   # 실거래 오케스트레이션
├── backtest_engine.py   # 백테스트 전용 엔진
└── CLAUDE.md
```

---

## ✅ 설계/규칙
- **의존성 방향**: Interface → Domain(news_trading) → Adapters
- **DTO 우선**: 입출력은 `dto.py` 기반으로 고정
- **리스크 우선**: `safety_guard` 통과 후에만 진입/추적
- **규칙 공유**: `strategy_engine`과 `backtest_engine`은 동일 규칙을 재사용
- **공통 유틸 사용**: 지표/성과 계산은 `application.common` 모듈 사용
- **통합 위치**: 현재는 독립 도메인으로 유지되며 API 연동 시 Domain 서비스로 호출

---

## 🔗 관련 문서
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
