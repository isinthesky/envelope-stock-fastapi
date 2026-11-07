"""유니버스 백테스트 benchmark_return이 항상 0이던 문제 회귀 테스트(2026-11-07)."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from src.application.domain.backtest.service import BacktestService


def test_benchmark_is_average_buy_and_hold_over_each_symbol_window() -> None:
    service = BacktestService.__new__(BacktestService)
    multi = SimpleNamespace(
        results={
            "A": SimpleNamespace(
                symbol="A",
                benchmark_return=None,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 1, 31),
            ),
            "B": SimpleNamespace(
                symbol="B",
                benchmark_return=None,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 1, 31),
            ),
        }
    )
    prices = {
        "A": {
            date(2023, 12, 29): Decimal("50"),
            date(2024, 1, 2): Decimal("100"),
            date(2024, 1, 31): Decimal("110"),
        },
        "B": {date(2024, 1, 2): Decimal("100"), date(2024, 1, 31): Decimal("90")},
    }

    # A +10%, B −10% → 평균 0, 구간 밖(2023-12-29)은 제외
    assert service._average_benchmark_return(multi, prices) == 0.0
    prices["B"][date(2024, 1, 31)] = Decimal("130")
    assert service._average_benchmark_return(multi, prices) == 20.0


def test_walk_forward_latest_ignores_ab_variant_reports(tmp_path) -> None:
    from src.application.domain.backtest.report_reader import WalkForwardReportReader

    for name in (
        "walk_forward_20260802_050126.json",
        "walk_forward_20260823_154728.json",
        "walk_forward_sector_cap_ab_20260823_154912.json",
        "walk_forward_regime_ab_20260802_071206.json",
    ):
        (tmp_path / name).write_text("{}")
    reader = WalkForwardReportReader(reports_dir=tmp_path)
    assert reader._latest_path().name == "walk_forward_20260823_154728.json"


def test_etf_is_eligible_without_market_cap() -> None:
    from src.adapters.database.models.stock_universe import MarketType, StockUniverseModel

    etf = StockUniverseModel(
        symbol="069500",
        market=MarketType.ETF.value,
        is_active=True,
        is_tradable=True,
        is_excluded=False,
        passed_market_cap=None,
        passed_volume=False,
    )
    stock = StockUniverseModel(
        symbol="005930",
        market=MarketType.KOSPI.value,
        is_active=True,
        is_tradable=True,
        is_excluded=False,
        passed_market_cap=None,
        passed_volume=True,
    )
    assert etf.is_eligible is True
    assert stock.is_eligible is False
