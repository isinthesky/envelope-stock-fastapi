"""entry_guard(SafetyGuard 재현) 판정 단위 테스트."""

from datetime import date

from src.application.domain.backtest.entry_guard import (
    EntryGuardConfig,
    EntryGuardDay,
    check_entry,
)
from src.application.domain.backtest.portfolio_parity_engine import PortfolioExecutionOptions

D = date(2026, 1, 5)


def _ctx(**kw) -> EntryGuardDay:
    base = dict(
        day=D,
        equity_now=100.0,
        equity_history=[100.0] * 25,
        entries_today=0,
        consecutive_losses_today=0,
    )
    base.update(kw)
    return EntryGuardDay(**base)


def test_default_limits_match_live_safety_guard_defaults() -> None:
    from src.application.domain.risk.dto import RiskLimitConfigDTO

    live = RiskLimitConfigDTO()
    cfg = EntryGuardConfig()
    assert cfg.daily_loss_limit == live.daily_loss_limit_ratio
    assert cfg.weekly_loss_limit == live.weekly_loss_limit_ratio
    assert cfg.monthly_loss_limit == live.monthly_loss_limit_ratio
    assert cfg.max_daily_entries == live.max_daily_trades
    assert cfg.max_consecutive_losses_today == live.max_consecutive_losses
    assert cfg.market_crash_threshold == live.market_crash_threshold


def test_each_guard_blocks_and_passes() -> None:
    cfg = EntryGuardConfig(benchmark_returns={D: -0.025})
    assert check_entry(cfg, _ctx(equity_now=95.9)) == "guard_daily_loss"
    hist = [100.0] * 24 + [93.0]  # 5거래일 전 100 → 92는 −8%, 전일 대비는 −1%
    assert check_entry(cfg, _ctx(equity_now=92.0, equity_history=hist)) == "guard_weekly_loss"
    assert check_entry(cfg, _ctx(consecutive_losses_today=3)) == "guard_consecutive_losses"
    assert check_entry(cfg, _ctx()) == "guard_market_crash"
    calm = EntryGuardConfig(benchmark_returns={D: -0.01})
    assert check_entry(calm, _ctx(entries_today=3)) == "guard_max_daily_entries"
    assert check_entry(calm, _ctx()) is None


def test_guard_requires_same_close() -> None:
    import pytest

    with pytest.raises(ValueError):
        PortfolioExecutionOptions(fill_timing="next_open", entry_guard=EntryGuardConfig())
