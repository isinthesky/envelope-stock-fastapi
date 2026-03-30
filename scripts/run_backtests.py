# -*- coding: utf-8 -*-
"""
재무필터 통과 종목 백테스트 실행
"""

import asyncio
import httpx
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

# 재무필터 통과 종목 (골든크로스 스캔 + 재무필터 결과)
STOCKS = [
    {"symbol": "000100", "name": "유한양행", "gc_state": "OPTIMAL_BUY", "status": "PASS"},
    {"symbol": "004370", "name": "농심", "gc_state": "OPTIMAL_BUY", "status": "PASS"},
    {"symbol": "092130", "name": "이크레더블", "gc_state": "OPTIMAL_BUY", "status": "PASS"},
    {"symbol": "083930", "name": "아바코", "gc_state": "OPTIMAL_BUY", "status": "PASS"},
    {"symbol": "036620", "name": "감성코퍼레이션", "gc_state": "OPTIMAL_BUY", "status": "PASS"},
    {"symbol": "036460", "name": "한국가스공사", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "095340", "name": "ISC", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "036810", "name": "에프에스티", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "256840", "name": "한국비엔씨", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "079940", "name": "가비아", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "018260", "name": "삼성에스디에스", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "326030", "name": "SK바이오팜", "gc_state": "BUY_INTEREST", "status": "PASS"},
    {"symbol": "068760", "name": "셀트리온제약", "gc_state": "READY_TO_BUY", "status": "PASS"},
    {"symbol": "084370", "name": "유진테크", "gc_state": "READY_TO_BUY", "status": "PASS"},
    {"symbol": "183300", "name": "코미코", "gc_state": "READY_TO_BUY", "status": "PASS"},
    {"symbol": "086520", "name": "에코프로", "gc_state": "READY_TO_BUY", "status": "TURNAROUND"},
    {"symbol": "033640", "name": "네패스", "gc_state": "READY_TO_BUY", "status": "TURNAROUND"},
]


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
            print(f"  Error: {response.status_code} - {response.text[:200]}")
            return None


async def main():
    print("=" * 90)
    print("📈 재무필터 통과 종목 백테스트")
    print("=" * 90)
    print(f"  기간: 최근 1년")
    print(f"  전략: 골든크로스 (MA55/MA165, Stoch 30/70)")
    print(f"  종목 수: {len(STOCKS)}개")
    print("=" * 90)

    results = []

    for i, stock in enumerate(STOCKS, 1):
        symbol = stock["symbol"]
        name = stock["name"]
        print(f"\n[{i}/{len(STOCKS)}] {symbol} {name} ({stock['gc_state']}/{stock['status']})...", end="", flush=True)

        result = await run_backtest(symbol, name)
        if result:
            results.append({
                **stock,
                "total_return": result.get("total_return", 0),
                "mdd": result.get("mdd", 0),
                "sharpe_ratio": result.get("sharpe_ratio", 0),
                "win_rate": result.get("win_rate", 0),
                "total_trades": result.get("total_trades", 0),
                "avg_holding_days": result.get("avg_holding_days", 0),
            })
            print(f" 수익률:{result.get('total_return', 0):.2f}%, MDD:{result.get('mdd', 0):.2f}%")
        else:
            print(" Failed")

    # 결과 요약
    print("\n" + "=" * 90)
    print("📊 백테스트 결과 요약 (수익률 순)")
    print("=" * 90)

    if results:
        # 수익률 순 정렬
        sorted_results = sorted(results, key=lambda x: x["total_return"], reverse=True)

        print(f"\n{'Symbol':<8} {'Name':<18} {'State':<15} {'Return':>9} {'MDD':>9} {'Sharpe':>8} {'WinRate':>8} {'Trades':>7} {'HoldDays':>9}")
        print("-" * 100)
        for r in sorted_results:
            print(f"{r['symbol']:<8} {r['name'][:16]:<18} {r['gc_state']:<15} {r['total_return']:>8.2f}% {r['mdd']:>8.2f}% {r['sharpe_ratio']:>8.2f} {r['win_rate']:>7.1f}% {r['total_trades']:>7} {r['avg_holding_days']:>9.1f}")

        # 통계
        avg_return = sum(r["total_return"] for r in results) / len(results)
        avg_mdd = sum(r["mdd"] for r in results) / len(results)
        positive = len([r for r in results if r["total_return"] > 0])

        print("\n" + "-" * 100)
        print(f"평균 수익률: {avg_return:.2f}%  |  평균 MDD: {avg_mdd:.2f}%  |  수익 종목: {positive}/{len(results)}개 ({positive/len(results)*100:.1f}%)")

        # 상태별 통계
        print("\n=== 상태별 평균 수익률 ===")
        for state in ["OPTIMAL_BUY", "BUY_INTEREST", "READY_TO_BUY"]:
            state_results = [r for r in results if r["gc_state"] == state]
            if state_results:
                state_avg = sum(r["total_return"] for r in state_results) / len(state_results)
                print(f"  {state}: {state_avg:.2f}% ({len(state_results)}개)")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
