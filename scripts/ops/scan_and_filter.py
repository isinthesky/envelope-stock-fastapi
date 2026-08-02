# -*- coding: utf-8 -*-
"""
골든크로스 스캔 + 재무필터 적용 + 백테스트 실행
"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"


async def scan_golden_cross(market: str) -> dict | None:
    """골든크로스 스캔"""
    async with httpx.AsyncClient(timeout=300) as client:
        url = f"{BASE_URL}/api/v1/strategies/universe/golden-cross-scan"
        params = {
            "market": market,
            "stoch_threshold": 50,
            "gc_only": "false",
            "include_etf": "false",
        }
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            return data.get("data")
        else:
            print(f"Error scanning {market}: {response.text[:200]}")
            return None


async def apply_financial_filter(scan_result: dict) -> dict | None:
    """재무 필터 적용"""
    async with httpx.AsyncClient(timeout=300) as client:
        url = f"{BASE_URL}/api/v1/strategies/universe/financial-filter"
        response = await client.post(url, json=scan_result)
        if response.status_code == 200:
            data = response.json()
            return data.get("data")
        else:
            print(f"Error applying filter: {response.text[:500]}")
            return None


async def run_backtest(symbol: str, name: str) -> dict | None:
    """백테스트 실행"""
    async with httpx.AsyncClient(timeout=120) as client:
        url = f"{BASE_URL}/api/v1/backtest/run"
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        body = {
            "symbol": symbol,
            "strategy_type": "golden_cross",
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": 10000000,
            "strategy_params": {
                "short_period": 55,
                "long_period": 165,
                "stoch_oversold": 30,
                "stoch_overbought": 70
            }
        }
        response = await client.post(url, json=body)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  Error backtesting {symbol} {name}: {response.text[:200]}")
            return None


def print_scan_summary(scan_result: dict, market: str):
    """스캔 결과 출력"""
    print(f"\n=== {market} Golden Cross Scan ===")
    print(f"  Total scanned: {scan_result.get('total_scanned', 0)}")
    print(f"  GC Active: {scan_result.get('gc_active_count', 0)}")
    print(f"  Optimal Buy: {scan_result.get('optimal_buy_count', 0)}")
    print(f"  Ready to Buy: {scan_result.get('ready_to_buy_count', 0)}")
    print(f"  Buy Interest: {scan_result.get('buy_interest_count', 0)}")


def print_filter_summary(filter_result: dict):
    """필터 결과 출력"""
    print(f"\n=== Financial Filter Result ===")
    print(f"  Total: {filter_result.get('total_scanned', 0)}")
    print(f"  Pass: {filter_result.get('financial_pass_count', 0)}")
    print(f"  Fail: {filter_result.get('financial_fail_count', 0)}")
    print(f"  Turnaround: {filter_result.get('turnaround_count', 0)}")
    print(f"  Error: {filter_result.get('financial_error_count', 0)}")
    print(f"  Pending: {filter_result.get('financial_pending_count', 0)}")


async def main():
    print("=" * 80)
    print("📊 골든크로스 + 재무필터 스캔 & 백테스트")
    print("=" * 80)

    # 1. 골든크로스 스캔 (KOSPI + KOSDAQ)
    all_stocks = []

    for market in ["KOSPI", "KOSDAQ"]:
        scan_result = await scan_golden_cross(market)
        if scan_result:
            print_scan_summary(scan_result, market)
            all_stocks.extend(scan_result.get("stocks", []))

    print(f"\n총 스캔 종목: {len(all_stocks)}개")

    # 2. 매수 후보만 필터링 (OPTIMAL_BUY, READY_TO_BUY, BUY_INTEREST)
    buy_states = ["OPTIMAL_BUY", "READY_TO_BUY", "BUY_INTEREST"]
    buy_candidates = [s for s in all_stocks if s.get("gc_state") in buy_states]
    print(f"매수 후보: {len(buy_candidates)}개")

    if not buy_candidates:
        print("매수 후보가 없습니다.")
        return

    # 3. 재무 필터 적용 (매수 후보만 포함한 스캔 결과 생성)
    scan_for_filter = {
        "stocks": buy_candidates,
        "total_scanned": len(buy_candidates),
        "gc_active_count": len([s for s in buy_candidates if s.get("gc_state") == "GC_ACTIVE"]),
        "pullback_waiting_count": len([s for s in buy_candidates if s.get("gc_state") == "WAITING_FOR_PULLBACK"]),
        "buy_interest_count": len([s for s in buy_candidates if s.get("gc_state") == "BUY_INTEREST"]),
        "ready_to_buy_count": len([s for s in buy_candidates if s.get("gc_state") == "READY_TO_BUY"]),
        "optimal_buy_count": len([s for s in buy_candidates if s.get("gc_state") == "OPTIMAL_BUY"]),
        "scan_time": datetime.now().isoformat(),
        "errors": [],
        "financial_pass_count": 0,
        "financial_fail_count": 0,
        "financial_error_count": 0,
        "turnaround_count": 0,
        "financial_pending_count": 0,
    }

    filter_result = await apply_financial_filter(scan_for_filter)
    if filter_result:
        print_filter_summary(filter_result)

        # 재무 필터 통과 + 턴어라운드 종목
        passed_stocks = [s for s in filter_result.get("stocks", [])
                        if s.get("financial_filter_status") in ["PASS", "TURNAROUND"]]

        print(f"\n=== 재무필터 통과 종목 ({len(passed_stocks)}개) ===")
        for s in passed_stocks:
            status = s.get("financial_filter_status", "N/A")
            rev_yoy = s.get("revenue_yoy")
            margin = s.get("operating_margin")
            print(f"  {s['symbol']} {s['name']}: {s['gc_state']} [{status}] "
                  f"(rev:{rev_yoy:.1f}% margin:{margin:.1f}%)" if rev_yoy else
                  f"  {s['symbol']} {s['name']}: {s['gc_state']} [{status}]")

        # 4. 백테스트 실행
        if passed_stocks:
            print(f"\n{'='*80}")
            print(f"📈 백테스트 실행 ({len(passed_stocks)}개 종목)")
            print(f"{'='*80}")

            backtest_results = []
            for stock in passed_stocks:
                symbol = stock["symbol"]
                name = stock["name"]
                print(f"\n▶ {symbol} {name} 백테스트 중...")

                result = await run_backtest(symbol, name)
                if result:
                    backtest_results.append({
                        "symbol": symbol,
                        "name": name,
                        "gc_state": stock["gc_state"],
                        "financial_status": stock.get("financial_filter_status"),
                        "result": result
                    })

                    # 결과 출력
                    if "data" in result:
                        data = result["data"]
                        print(f"  총 수익률: {data.get('total_return', 0):.2f}%")
                        print(f"  MDD: {data.get('mdd', 0):.2f}%")
                        print(f"  Sharpe: {data.get('sharpe_ratio', 0):.2f}")
                        print(f"  승률: {data.get('win_rate', 0):.1f}%")
                        print(f"  거래 횟수: {data.get('total_trades', 0)}")
                    elif "error" in result:
                        print(f"  Error: {result.get('error')}")

            # 최종 결과 요약
            print(f"\n{'='*80}")
            print(f"📊 백테스트 결과 요약")
            print(f"{'='*80}")

            # 수익률 순 정렬
            valid_results = [r for r in backtest_results if r.get("result", {}).get("data")]
            if valid_results:
                sorted_results = sorted(
                    valid_results,
                    key=lambda x: x["result"]["data"].get("total_return", 0),
                    reverse=True
                )

                print(f"\n{'Symbol':<10} {'Name':<20} {'Return':>10} {'MDD':>8} {'Sharpe':>8} {'WinRate':>8} {'Trades':>7}")
                print("-" * 80)
                for r in sorted_results:
                    d = r["result"]["data"]
                    print(f"{r['symbol']:<10} {r['name'][:18]:<20} {d.get('total_return',0):>9.2f}% "
                          f"{d.get('mdd',0):>7.2f}% {d.get('sharpe_ratio',0):>8.2f} "
                          f"{d.get('win_rate',0):>7.1f}% {d.get('total_trades',0):>7}")

    else:
        print("재무 필터 적용 실패")


if __name__ == "__main__":
    asyncio.run(main())
