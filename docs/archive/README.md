# docs/archive — 작업 완료 계획 문서 보관소

작업이 **코드에 반영 완료**된 계획/개선/리팩토링 문서를 이력 보존용으로 모아둔 곳입니다.
현행 동작의 근거로 삼지 마세요 — 계획 당시 스냅샷이며, 최신 상태는 코드·`README.md`·`CLAUDE.md`가 기준입니다.

> 정리 일자: 2026-08-02

## 보관 문서와 완료 근거

| 문서 | 주제 | 완료 근거(코드 실측) |
|------|------|----------------------|
| `strategy-refactor-plan.md` | strategy 도메인 리팩토링 | 본문 "✅ 진행 상태(완료)" Batch 1~2 커밋 반영 |
| `2026-02-10-strategy-pages-split.md` | 전략 페이지 분리 | `strategy_hub` 3탭 구현됨. (MA5 항목은 이후 제거 — 무효 배너 있음) |
| `2026-07-03-recent-features-page-integration.md` | 추천/백테스트/매도규칙 페이지 연결 | `recommendation_page_router`·`sell_rule_research_router` 존재 |
| `2026-07-04-dead-code-cleanup.md` | 죽은 코드·스크립트 정리 | `scripts/_attic`·`_patches` 부재(정리 완료) |
| `strategy-page-improvement-plan.md` | 전략 페이지 UX 개선 | 마지막 결과 상시출력·쿨다운 `strategy.js` 반영. (MA5 무효 배너 있음) |
| `IMPROVEMENT_PLAN_deadcode.md` | Dead Code 제거 | abandoned 44개 제거(−1054줄) 실행 완료 |
| `IMPROVEMENT_PLAN_ohlcv_storage.md` | OHLCV 저장 개선 | "적용 완료(fix)", 527 passed |
| `IMPROVEMENT_PLAN_strategy_calc.md` | 매수/매도 계산식 blind-spot | 항목 전부 ✅ (Fear Buy 버그 등 수정). 회귀 테스트 `test_strategy_calc_fixes.py` |
| `walk_forward_harness_design.md` | Walk-forward 하네스 설계 | `run_walk_forward.py`·`golden_cross_parity.py` 구현됨 |
| `sell-strategy/claude-plan.md` | 매도 판단 로직 진단(원안) | 점수제로 실현 |
| `sell-strategy/implementation-plan.md` | 매도 점수제 구현 계획 | `sell_score_rules.py`(12규칙)+`sell_score_settings.py` 임계 라이브 |
| `sell-strategy/implementation-review.md` | 점수제 갭 분석 | 당시 "미구현" 지적 → 현재 구현 완료(문서 stale) |

## 아직 진행 중(아카이브 안 함 — `docs/`에 유지)

- `docs/plans/separated-buy-sell-strategy.md` — 매수/매도 완전 재설계(미구현, hybrid 결론)
- `docs/asset-preservation-strategy/WORK_PLAN.md` — PARTIAL_POSITION·DB 마이그레이션 미구현
- `docs/sell_gyun_chim_review.md` — RSI+피크 손절 검토(미채택)
- `docs/backtesting/gc_rsi_mixed_buy_signal_review.md` — GC+RSI 혼합(RSI 게이트 OFF 상태)

## 현행 사용 가이드

매수/매도 실사용법은 → [`docs/buy-sell-usage-guide.md`](../buy-sell-usage-guide.md)
