# 포트폴리오 사전 현금화 계획

> 최종 갱신 2026-11-07 (코드 대조 감사). 구현: `src/application/domain/strategy/portfolio_cash_planner.py`(`PortfolioCashPlanner`), 호출: `StrategyService.get_portfolio_cash_plan`.
> ⚠️ 분석·표시 전용(E2 계열)이며 주문을 내지 않는다. 입력이 되는 매도 Stage는 수익 검증되지 않은 값이다(`docs/sell-strategy.md` §4.1).

## 목표
고점/과열 신호가 발생할 때 **전량 손절이 아니라 선제적 비중 축소로 현금 비중을 확보**한다.

## 현재 구현
- API: `GET /api/v1/strategies/portfolio-cash-plan` (관리자 로그인 필요)
- 입력:
  - `target_cash_ratio` (기본 0.30)
  - `current_cash_ratio` (선택)
- 데이터 소스:
  - 활성 추적 중인 `sell` 분석 이력
  - 각 종목을 `SellStrategyService.analyze_sell_signal(..., entry_price, highest_price, force_refresh=True)`로 재분석하고, 새 최고가는 이력의 `highest_price`에 반영
- 화면: `/mypage/sell-strategy`의 `현금화 계획 갱신`, `/ops` 요약(`cash_plan`)
- 응답 핵심 필드: `market_heat_level`, `market_risk_score`, `portfolio_action`, `summary`, `actions[]`(`priority`, `action`, `suggested_sell_ratio`, `urgency_score`)

## 평가 로직
종목별 긴급도 점수(`urgency_score`)는 `final_stage`와 아래 신호를 합산한다.
- `final_stage`: `REDUCE_1` +35 / `REDUCE_2` +60 / `EXIT_ALL` +90
- 데드크로스 +20, 거래량 매도 신호 +15, 거래량 급증(≥1.3배) +10
- 강한 상승 추세로 과매수 매도 차단 −10
- 수익률: ≥15% +25 / ≥8% +18 / >0% +8, 손실 ≤−5% +10
- 수익 종목이면서 REDUCE/EXIT 단계 +15 (현금 확보는 수익 종목 우선)
- ETF/레버리지 계열이면서 REDUCE_1·2 +8

지표 데이터 부족(`INSUFFICIENT_DATA`) 종목은 저장 가격 기준 최고가 대비 −15% 손절선 이하이면 `EXIT_ALL`, 아니면 `분석 보류`로 HOLD와 구분해 표시한다.

## 권장 매도 비중 (`suggested_sell_ratio`)
- 기본값: `dto.CASH_PLAN_BASE_SELL_RATIOS` — REDUCE_1 25% / REDUCE_2 50% / EXIT_ALL 100%
  - 종목 단위 매도 분석 비율(`SELL_STAGE_RATIOS`: REDUCE_1 20~30%, REDUCE_2 30~40%)과 **다른 개념**이다. 현금계획은 포트폴리오 현금 확보 목적이라 더 공격적이다.
- 상향 규칙: 수익 ≥8% REDUCE_1 → ≥30%, 수익 ≥12% REDUCE_2 → ≥60%, ETF 수익 REDUCE_1 → ≥35%, 레버리지 ETF 수익 REDUCE_2 → ≥70%, 점수 ≥90 → ≥70%, 점수 ≥60 → ≥50%

## 액션 규칙
- 비중 100% → 전량 현금화 / ≥50% → 강한 비중 축소 / >0% → 선제 비중 축소 / 0% → 보유 유지
- 포트폴리오 단계(평균 점수): ≥70 `HIGH`(신규 진입 중단) / ≥45 `ELEVATED`(신규 진입 축소) / 그 외 `NORMAL`

## 활용 방식
1. 장 시작 전 `portfolio-cash-plan` 조회
2. 상위 우선순위 종목부터 현금화 검토(수동)
3. 목표 현금 비중 도달 시 신규 진입 제한
4. 장중 재분석으로 단계 상승 시 추가 감축 검토

## 다음 확장 아이디어
- 시장 전체 리스크(코스피/KOSDAQ 지수, 리더 ETF, 레버리지 과열도) 반영
- 실제 보유 수량/평가금액 연동 후 `예상 현금 확보액` 계산
- (완료) sell 전략 페이지 현금화 위젯 — `/mypage/sell-strategy`
