# -*- coding: utf-8 -*-
"""
Recommendation Rule Set Validation Service

RecommendationRuleSetDTO의 각 후보(candidate)를 골든크로스 유니버스에 대해
train/test 기간으로 각각 백테스트해 CandidateRule.train_metrics/test_metrics를
채운 뒤, 기존 walk-forward 엔진(backtest/walk_forward.py)에 위임해
frozen_hash/data_snooping_warning이 담긴 WalkForwardValidationResult를 만든다.

이 서비스는 검증 "실행"만 담당한다. DB 저장(recommendation_rule_validations)은
호출자(RecommendationRuleSetService)의 책임이다 - 매 스캔마다 재검증하지 않는다는
설계를 지키기 위함.
"""

from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.dto import MultiSymbolBacktestRequestDTO
from src.application.domain.backtest.service import BacktestService
from src.application.domain.backtest.validation import (
    CandidateRule,
    RuleMetric,
    RuleValue,
    WalkForwardConfig,
    WalkForwardPeriod,
    WalkForwardValidationError,
    WindowMetrics,
)
from src.application.domain.backtest.walk_forward import (
    WalkForwardValidationResult,
    WalkForwardValidationRunner,
)
from src.application.domain.recommendation.dto import RecommendationRuleSetDTO
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

_UNIVERSE_STOCH_THRESHOLD = 30.0
_PREFERRED_GC_STATES = ("OPTIMAL_BUY", "READY_TO_BUY", "BUY_INTEREST", "WAITING_FOR_PULLBACK")


class RecommendationRuleSetValidationService:
    """룰셋 후보들을 walk-forward(train/test 분리) 방식으로 검증한다."""

    def __init__(self, backtest_service: BacktestService, session: AsyncSession) -> None:
        self.backtest_service = backtest_service
        self.session = session

    async def validate(
        self,
        rule_set: RecommendationRuleSetDTO,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        benchmark: str,
        market: str | None = None,
        eligible_only: bool = True,
        limit: int = 20,
        selection_metric: RuleMetric = RuleMetric.CAGR,
    ) -> WalkForwardValidationResult:
        # train_end >= test_start 등 기간 오류는 WalkForwardPeriod의 기존
        # validate_order 검증을 그대로 재사용한다(새 검증 로직 작성 금지).
        period = WalkForwardPeriod(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        )

        symbols = await self._select_universe_symbols(
            market=market, eligible_only=eligible_only, limit=limit
        )
        if not symbols:
            # 유니버스가 비면 모든 후보가 동일한 0.0 지표를 받아 첫 후보가 그대로
            # "선정"되어 버린다 - 검증되지 않은 룰셋이 active로 승격되는 것을 막는다.
            raise WalkForwardValidationError(
                f"no golden-cross universe symbols found for validation "
                f"(market={market!r}, eligible_only={eligible_only}); "
                "refusing to validate/activate a rule set against an empty universe"
            )

        train_start_dt = datetime.combine(period.train_start, time.min)
        train_end_dt = datetime.combine(period.train_end, time.min)
        test_start_dt = datetime.combine(period.test_start, time.min)
        test_end_dt = datetime.combine(period.test_end, time.min)

        train_benchmark_cagr = await self._compute_benchmark_cagr(
            benchmark, train_start_dt, train_end_dt
        )
        test_benchmark_cagr = await self._compute_benchmark_cagr(
            benchmark, test_start_dt, test_end_dt
        )

        candidate_rules: list[CandidateRule] = []
        for candidate in rule_set.candidates:
            train_metrics = await self._run_window(
                candidate.rules, symbols, train_start_dt, train_end_dt, train_benchmark_cagr
            )
            test_metrics = await self._run_window(
                candidate.rules, symbols, test_start_dt, test_end_dt, test_benchmark_cagr
            )
            candidate_rules.append(
                CandidateRule(
                    candidate_id=candidate.candidate_id,
                    name=candidate.name,
                    rules=candidate.rules,
                    train_metrics=train_metrics,
                    test_metrics=test_metrics,
                )
            )

        config = WalkForwardConfig(
            strategy_id=rule_set.rule_id,
            benchmark=benchmark,
            selection_metric=selection_metric,
            period=period,
            candidates=candidate_rules,
        )
        return WalkForwardValidationRunner(config).run()

    async def _select_universe_symbols(
        self, market: str | None, eligible_only: bool, limit: int
    ) -> list[str]:
        """
        룰셋의 모든 후보/윈도우에 공통으로 사용할 유니버스를 한 번만 선정한다
        (backtest_router.run_universe_golden_cross_backtest와 동일한 선정 방식 -
        symbols는 후보마다 재선정하지 않아야 train/test 비교가 공정하다).
        """
        buy_service = BuyStrategyService(session=self.session)
        scan = await buy_service.scan_golden_cross_candidates(
            self.session,
            market=market,
            stoch_threshold=_UNIVERSE_STOCH_THRESHOLD,
            gc_only=False,
            include_etf=False,
            limit=max(limit * 5, limit),
        )

        selected = [
            item for state in _PREFERRED_GC_STATES for item in scan.stocks if item.gc_state == state
        ]
        if eligible_only:
            selected = [item for item in selected if item.screening_score is not None]

        symbols: list[str] = []
        seen: set[str] = set()
        for item in selected:
            if item.symbol in seen:
                continue
            seen.add(item.symbol)
            symbols.append(item.symbol)
            if len(symbols) >= limit:
                break
        return symbols

    async def _run_window(
        self,
        rules: dict[str, RuleValue],
        symbols: list[str],
        start_dt: datetime,
        end_dt: datetime,
        benchmark_cagr: float,
    ) -> WindowMetrics:
        multi_request = MultiSymbolBacktestRequestDTO(
            symbols=symbols,
            start_date=start_dt,
            end_date=end_dt,
            strategy_type="golden_cross",
            strategy_params=rules,
        )
        multi_result = await self.backtest_service.run_multi_symbol_backtest(multi_request)
        results = list(multi_result.results.values())

        if not results:
            # symbols는 있었지만 백테스트가 전부 실패한 경우. 0.0 지표로 조용히
            # 넘어가면 empty-universe와 동일하게 미검증 후보가 선정/활성화될 수 있다.
            raise WalkForwardValidationError(
                f"all backtests failed for {len(symbols)} universe symbols in window "
                f"{start_dt.date()}~{end_dt.date()}; refusing to score this candidate as 0.0"
            )

        return WindowMetrics(
            cagr=self._mean(result.cagr for result in results),
            benchmark_cagr=benchmark_cagr,
            mdd=self._mean(result.mdd for result in results),
            sharpe=self._mean(result.sharpe_ratio for result in results),
            # NOTE: 이 저장소에는 실제 포트폴리오 회전율(거래대금/평잔) 계산에 필요한
            # 데이터가 없다. 심볼당 평균 체결 횟수를 거래 빈도 근사치로 사용한다
            # (진짜 자본 회전율 비율이 아님 - report에서도 이 근사치를 그대로 노출한다).
            turnover=self._mean(float(result.total_trades) for result in results),
        )

    async def _compute_benchmark_cagr(
        self, symbol: str, start_dt: datetime, end_dt: datetime
    ) -> float:
        data, actual_start, actual_end = await self.backtest_service.data_loader.load_ohlcv_data(
            symbol=symbol, start_date=start_dt, end_date=end_dt
        )
        if data.empty:
            return 0.0

        start_price = Decimal(str(data.iloc[0]["close"]))
        end_price = Decimal(str(data.iloc[-1]["close"]))
        years = max((actual_end - actual_start).days / 365, 1 / 365)
        return PerformanceMetrics.calculate_cagr(start_price, end_price, years)

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        collected = list(values)
        return round(sum(collected) / len(collected), 4) if collected else 0.0
