# -*- coding: utf-8 -*-
"""
볼린저 밴드(20,2) + 엔벨로프 차트 매매 전략 예제

이 예제는 볼린저 밴드와 엔벨로프를 결합하여
더 신뢰도 높은 매매 시그널을 생성하는 전략입니다.

매매 전략:
1. 매수 조건: 가격이 볼린저 밴드 하단 AND 엔벨로프 하단을 동시에 돌파 (과매도)
2. 매도 조건: 가격이 볼린저 밴드 상단 AND 엔벨로프 상단을 동시에 돌파 (과매수)
3. 리스크 관리: 손절 -3%, 익절 +5% 설정
"""

import asyncio

import httpx

# ==================== 설정 ====================

API_BASE_URL = "http://localhost:8000"

# 전략 설정
STRATEGY_CONFIG = {
    "name": "볼린저밴드+엔벨로프 전략",
    "description": "볼린저 밴드(20,2)와 엔벨로프(20,2%)를 결합한 평균 회귀 전략",
    "strategy_type": "mean_reversion",
    "symbols": [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "035420",  # NAVER
    ],
    "config": {
        # 볼린저 밴드 설정 (20일, 표준편차 2배)
        "bollinger_band": {"period": 20, "std_multiplier": 2.0},
        # 엔벨로프 설정 (20일, 2% 채널)
        "envelope": {"period": 20, "percentage": 2.0},
        # 포지션 관리
        "position": {
            "allocation_ratio": 0.1,  # 계좌 자산의 10%씩 배분
            "max_position_count": 3,  # 최대 3개 종목 동시 보유
        },
        # 리스크 관리
        "risk_management": {
            "use_stop_loss": True,
            "stop_loss_ratio": -0.03,  # -3% 손절
            "use_take_profit": True,
            "take_profit_ratio": 0.05,  # +5% 익절
            "use_trailing_stop": False,
            "use_reverse_signal_exit": True,  # 반대 시그널 발생 시 청산
        },
        # 체크 주기 (60초마다)
        "check_interval": 60,
    },
}


# ==================== API 함수 ====================


async def create_strategy(config: dict) -> dict:
    """전략 생성"""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE_URL}/api/v1/strategies", json=config, timeout=30.0)
        response.raise_for_status()
        return response.json()


async def get_strategy(strategy_id: int) -> dict:
    """전략 상세 조회"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE_URL}/api/v1/strategies/{strategy_id}", timeout=30.0)
        response.raise_for_status()
        return response.json()


async def get_strategy_list() -> dict:
    """전략 목록 조회"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE_URL}/api/v1/strategies", timeout=30.0)
        response.raise_for_status()
        return response.json()


async def start_strategy(strategy_id: int) -> dict:
    """전략 시작"""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE_URL}/api/v1/strategies/{strategy_id}/start", timeout=30.0)
        response.raise_for_status()
        return response.json()


async def pause_strategy(strategy_id: int) -> dict:
    """전략 일시정지"""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE_URL}/api/v1/strategies/{strategy_id}/pause", timeout=30.0)
        response.raise_for_status()
        return response.json()


async def stop_strategy(strategy_id: int) -> dict:
    """전략 중지"""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE_URL}/api/v1/strategies/{strategy_id}/stop", timeout=30.0)
        response.raise_for_status()
        return response.json()


async def delete_strategy(strategy_id: int) -> None:
    """전략 삭제"""
    async with httpx.AsyncClient() as client:
        response = await client.delete(f"{API_BASE_URL}/api/v1/strategies/{strategy_id}", timeout=30.0)
        response.raise_for_status()


async def update_strategy(strategy_id: int, update_data: dict) -> dict:
    """전략 수정"""
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{API_BASE_URL}/api/v1/strategies/{strategy_id}", json=update_data, timeout=30.0
        )
        response.raise_for_status()
        return response.json()


# ==================== 예제 실행 ====================


async def example_create_and_start_strategy():
    """예제 1: 전략 생성 및 시작"""
    print("\n" + "=" * 60)
    print("예제 1: 볼린저 밴드 + 엔벨로프 전략 생성 및 시작")
    print("=" * 60)

    try:
        # 1. 전략 생성
        print("\n1. 전략 생성 중...")
        result = await create_strategy(STRATEGY_CONFIG)
        strategy_id = result["id"]
        print(f"✅ 전략 생성 완료: ID={strategy_id}, 이름={result['name']}")
        print(f"   - 대상 종목: {', '.join(result['symbols'])}")
        print(f"   - 볼린저 밴드: {result['config']['bollinger_band']}")
        print(f"   - 엔벨로프: {result['config']['envelope']}")
        print(f"   - 상태: {result['status']}")

        # 2. 전략 시작
        print(f"\n2. 전략 시작 중... (ID: {strategy_id})")
        result = await start_strategy(strategy_id)
        print(f"✅ 전략 시작 완료: 상태={result['status']}")
        print(f"   - 시작 시각: {result['started_at']}")

        print("\n💡 전략이 백그라운드에서 실행됩니다.")
        print("   - 60초마다 차트를 분석하여 자동 매매를 수행합니다.")
        print(f"   - 서버 로그를 확인하여 실행 상태를 모니터링하세요.")

        return strategy_id

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


async def example_view_strategy_status(strategy_id: int):
    """예제 2: 전략 상태 조회"""
    print("\n" + "=" * 60)
    print("예제 2: 전략 상태 조회")
    print("=" * 60)

    try:
        result = await get_strategy(strategy_id)

        print(f"\n전략 ID: {result['id']}")
        print(f"전략명: {result['name']}")
        print(f"상태: {result['status']}")
        print(f"대상 종목: {', '.join(result['symbols'])}")
        print(f"\n실행 통계:")
        print(f"  - 총 실행: {result['total_executions']}회")
        print(f"  - 성공: {result['successful_executions']}회")
        print(f"  - 실패: {result['failed_executions']}회")
        print(f"  - 성공률: {result['success_rate']:.1f}%")

        if result["last_executed_at"]:
            print(f"\n마지막 실행: {result['last_executed_at']}")

        return result

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


async def example_list_all_strategies():
    """예제 3: 전체 전략 목록 조회"""
    print("\n" + "=" * 60)
    print("예제 3: 전체 전략 목록 조회")
    print("=" * 60)

    try:
        result = await get_strategy_list()

        print(f"\n총 {result['total_count']}개의 전략이 있습니다.\n")

        for strategy in result["strategies"]:
            status_emoji = "🟢" if strategy["status"] == "active" else "🟡" if strategy["status"] == "paused" else "⚪"
            print(f"{status_emoji} ID: {strategy['id']} | {strategy['name']}")
            print(f"   상태: {strategy['status']} | 종목: {', '.join(strategy['symbols'])}")
            print(f"   성공률: {strategy['success_rate']:.1f}% ({strategy['successful_executions']}/{strategy['total_executions']})")
            print()

        return result

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


async def example_pause_and_restart(strategy_id: int):
    """예제 4: 전략 일시정지 및 재시작"""
    print("\n" + "=" * 60)
    print("예제 4: 전략 일시정지 및 재시작")
    print("=" * 60)

    try:
        # 1. 일시정지
        print(f"\n1. 전략 일시정지 중... (ID: {strategy_id})")
        result = await pause_strategy(strategy_id)
        print(f"✅ 전략 일시정지 완료: 상태={result['status']}")

        # 2. 잠시 대기
        print("\n2. 5초 대기...")
        await asyncio.sleep(5)

        # 3. 재시작
        print(f"\n3. 전략 재시작 중... (ID: {strategy_id})")
        result = await start_strategy(strategy_id)
        print(f"✅ 전략 재시작 완료: 상태={result['status']}")

        return result

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


async def example_update_strategy_config(strategy_id: int):
    """예제 5: 전략 설정 수정"""
    print("\n" + "=" * 60)
    print("예제 5: 전략 설정 수정 (손절/익절 비율 변경)")
    print("=" * 60)

    try:
        # 먼저 일시정지
        print(f"\n1. 전략 일시정지 중...")
        await pause_strategy(strategy_id)

        # 설정 수정
        print(f"\n2. 설정 수정 중...")
        update_data = {
            "config": {
                "bollinger_band": {"period": 20, "std_multiplier": 2.0},
                "envelope": {"period": 20, "percentage": 2.5},  # 2.5%로 변경
                "position": {"allocation_ratio": 0.15, "max_position_count": 3},  # 15%로 증가
                "risk_management": {
                    "use_stop_loss": True,
                    "stop_loss_ratio": -0.05,  # -5%로 변경
                    "use_take_profit": True,
                    "take_profit_ratio": 0.08,  # +8%로 변경
                    "use_trailing_stop": False,
                    "use_reverse_signal_exit": True,
                },
                "check_interval": 60,
            }
        }

        result = await update_strategy(strategy_id, update_data)
        print(f"✅ 설정 수정 완료")
        print(f"   - 엔벨로프: {result['config']['envelope']}")
        print(f"   - 손절: {result['config']['risk_management']['stop_loss_ratio']*100:.1f}%")
        print(f"   - 익절: {result['config']['risk_management']['take_profit_ratio']*100:.1f}%")

        return result

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


async def example_stop_and_delete(strategy_id: int):
    """예제 6: 전략 중지 및 삭제"""
    print("\n" + "=" * 60)
    print("예제 6: 전략 중지 및 삭제")
    print("=" * 60)

    try:
        # 1. 전략 중지
        print(f"\n1. 전략 중지 중... (ID: {strategy_id})")
        result = await stop_strategy(strategy_id)
        print(f"✅ 전략 중지 완료: 상태={result['status']}")

        # 2. 전략 삭제
        print(f"\n2. 전략 삭제 중... (ID: {strategy_id})")
        await delete_strategy(strategy_id)
        print(f"✅ 전략 삭제 완료")

    except httpx.HTTPStatusError as e:
        print(f"❌ API 오류: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise


# ==================== 메인 실행 ====================


async def main():
    """메인 실행 함수"""
    print("\n" + "=" * 60)
    print("볼린저 밴드 + 엔벨로프 차트 매매 전략 예제")
    print("=" * 60)
    print("\n⚠️  주의사항:")
    print("1. 이 예제를 실행하기 전에 FastAPI 서버가 실행 중이어야 합니다.")
    print("2. .env 파일에 KIS API 인증 정보가 설정되어 있어야 합니다.")
    print("3. 실제 매매가 실행되므로 주의하세요!")

    input("\n계속하려면 Enter를 누르세요...")

    strategy_id = None

    try:
        # 1. 전략 생성 및 시작
        strategy_id = await example_create_and_start_strategy()

        # 2. 전략 상태 조회
        await asyncio.sleep(2)
        await example_view_strategy_status(strategy_id)

        # 3. 전체 전략 목록 조회
        await asyncio.sleep(2)
        await example_list_all_strategies()

        # 4. 일시정지 및 재시작 (선택사항)
        # await asyncio.sleep(2)
        # await example_pause_and_restart(strategy_id)

        # 5. 설정 수정 (선택사항)
        # await asyncio.sleep(2)
        # await example_update_strategy_config(strategy_id)

        print("\n" + "=" * 60)
        print("✅ 모든 예제 실행 완료")
        print("=" * 60)
        print(f"\n전략 ID: {strategy_id}")
        print("전략이 백그라운드에서 계속 실행됩니다.")
        print("중지하려면 아래 명령을 사용하세요:")
        print(f"  - 일시정지: pause_strategy({strategy_id})")
        print(f"  - 중지: stop_strategy({strategy_id})")
        print(f"  - 삭제: stop_strategy({strategy_id}) 후 delete_strategy({strategy_id})")

    except Exception as e:
        print(f"\n❌ 예제 실행 중 오류 발생: {e}")

        if strategy_id:
            print(f"\n정리 작업 중... (전략 ID: {strategy_id})")
            try:
                await example_stop_and_delete(strategy_id)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
