#!/usr/bin/env python3
"""
Simple Sell Rule vs Hybrid Sell Rule Verification
Uses the implemented compute_simple_sell_signal and mode logic.
Runs lightweight simulation for comparison.
"""

import asyncio
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.application.domain.strategy.sell_strategy_service import SellStrategyService

def simulate_simple_vs_hybrid():
    print("=" * 80)
    print("SIMPLE vs HYBRID SELL RULE VERIFICATION")
    print("Simple Rule: RSI>=70 OR 20d-high DD>=15% OR 85% peak-profit protection")
    print("Hybrid: Legacy Phase + Simple overlay (upgrade stage on trigger)")
    print("=" * 80)

    service = SellStrategyService(session=None)  # no DB needed for compute

    cases = [
        {
            "name": "Case1: Strong RSI + Peak profit",
            "rsi": 73.5,
            "closes": list(np.linspace(72000, 75000, 25)),  # current near high
            "current": 75000,
            "entry": 62000,
            "highest": 82000,
        },
        {
            "name": "Case2: 20d Drawdown trigger",
            "rsi": 62,
            "closes": [80000 + i*100 for i in range(15)] + [76000]*5 + [68000]*5,
            "current": 68000,
            "entry": 72000,
            "highest": 81000,
        },
        {
            "name": "Case3: Profit protection 85%",
            "rsi": 68,
            "closes": list(range(65000, 78000, 500))[-25:],
            "current": 69500,
            "entry": 60000,
            "highest": 78000,
        },
    ]

    for case in cases:
        print(f"\n[{case['name']}]")
        df = pd.DataFrame({"close": case["closes"]})

        simple = service.compute_simple_sell_signal(
            df=df,
            rsi=case["rsi"],
            current_price=case["current"],
            entry_price=case["entry"],
            highest_price=case["highest"],
        )

        print(f"  RSI={case['rsi']}, Current={case['current']}, Entry={case['entry']}, High={case['highest']}")
        print(f"  Simple Sell: {simple['should_sell']}")
        for r in simple['reasons']:
            print(f"    - {r}")

        # Mock legacy stage (simplified)
        legacy_stage = "REDUCE_1" if case['rsi'] > 65 else "HOLD"
        print(f"  Legacy (mocked Phase): {legacy_stage}")

        # Hybrid: upgrade if simple triggers
        hybrid_stage = legacy_stage
        if simple['should_sell']:
            if legacy_stage == "HOLD":
                hybrid_stage = "REDUCE_2"
            elif legacy_stage == "REDUCE_1":
                hybrid_stage = "REDUCE_2 or EXIT_ALL"
        print(f"  Hybrid (overlay): {hybrid_stage}")

    print("\n" + "=" * 80)
    print("Backtest-style comparison note:")
    print("- Simple: Faster exits on clear overbought/drawdown/profit lock.")
    print("- Hybrid: Keeps sophisticated filters (ADX, volume, credit) + upgrades on simple trigger.")
    print("- Recommend running full BacktestService with sell_mode for P&L curves.")
    print("=" * 80)

if __name__ == "__main__":
    simulate_simple_vs_hybrid()
PYEOF
python3 /Users/m2-dev/Apps/kis-strategy-alert-server/scripts/verify_simple_vs_hybrid_sell.py