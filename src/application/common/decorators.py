# -*- coding: utf-8 -*-
"""
Decorators - 공통 데코레이터

@transaction, @cache, @retry 등 재사용 가능한 데코레이터
"""

import functools
import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.connection import AsyncSessionLocal

P = ParamSpec("P")
T = TypeVar("T")

logger = logging.getLogger(__name__)


# ==================== @transaction 데코레이터 ====================


def transaction(func: Callable[P, T]) -> Callable[P, T]:
    """
    트랜잭션 데코레이터

    Service Layer 메서드에 적용하여 자동 트랜잭션 관리
    - 성공 시: commit
    - 실패 시: rollback

    사용 예시:
        @transaction
        async def create_order(self, order_data: dict) -> Order:
            # 비즈니스 로직
            pass

    주의:
        - 외부 호출 메서드에만 적용 (내부 헬퍼 메서드는 제외)
        - Service Layer에서만 사용 (Repository는 제외)
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        async with AsyncSessionLocal() as session:
            try:
                # Service 메서드의 첫 번째 인자를 session으로 교체
                # 일반적으로 self, session, ... 형태
                if len(args) > 1 and isinstance(args[1], AsyncSession):
                    # 이미 session이 전달된 경우 (내부 호출)
                    result = await func(*args, **kwargs)
                else:
                    # 새로운 session 주입 (외부 호출)
                    new_args = (args[0], session) + args[1:]
                    result = await func(*new_args, **kwargs)

                await session.commit()
                return result

            except Exception as e:
                await session.rollback()
                logger.error(f"Transaction failed in {func.__name__}: {e}")
                raise

    return wrapper


# ==================== @retry 데코레이터 ====================


def retry(
    max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    재시도 데코레이터

    Args:
        max_attempts: 최대 시도 횟수
        delay: 초기 지연 시간 (초)
        backoff: 지연 시간 배율

    사용 예시:
        @retry(max_attempts=3, delay=1.0, backoff=2.0)
        async def call_external_api():
            # 외부 API 호출
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            import asyncio

            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"Max retry attempts ({max_attempts}) reached for {func.__name__}"
                        )
                        raise

                    logger.warning(
                        f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception

        return wrapper

    return decorator


# ==================== @cache 데코레이터 ====================


def cache(ttl: int = 60, key_prefix: str = "") -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    캐시 데코레이터

    Args:
        ttl: Time-To-Live (초)
        key_prefix: 캐시 키 접두사

    사용 예시:
        @cache(ttl=300, key_prefix="market")
        async def get_market_price(symbol: str) -> dict:
            # 시세 조회
            pass

    Note:
        - Redis 의존성 필요
        - 함수 인자를 기반으로 캐시 키 생성
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            from src.adapters.cache.redis_client import get_redis_client

            # 캐시 키 생성
            cache_key = f"{key_prefix}:{func.__name__}:"
            cache_key += ":".join(str(arg) for arg in args[1:])  # self 제외
            cache_key += ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))

            redis = await get_redis_client()

            # 캐시 조회
            cached = await redis.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

            # 함수 실행 및 캐시 저장
            logger.debug(f"Cache miss for {cache_key}")
            result = await func(*args, **kwargs)
            await redis.set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorator


# ==================== @log_execution 데코레이터 ====================


def log_execution(func: Callable[P, T]) -> Callable[P, T]:
    """
    실행 로깅 데코레이터

    함수 실행 시작/종료 및 실행 시간 로깅

    사용 예시:
        @log_execution
        async def complex_calculation():
            # 복잡한 계산
            pass
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        import time

        func_name = func.__name__
        logger.info(f"[START] {func_name}")

        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"[END] {func_name} (took {elapsed:.3f}s)")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[ERROR] {func_name} failed after {elapsed:.3f}s: {e}")
            raise

    return wrapper


# ==================== @validate_input 데코레이터 ====================


def validate_input(
    validator: Callable[[Any], bool], error_message: str = "Invalid input"
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    입력 검증 데코레이터

    Args:
        validator: 검증 함수 (True: 통과, False: 실패)
        error_message: 검증 실패 시 에러 메시지

    사용 예시:
        @validate_input(lambda x: x > 0, "Value must be positive")
        async def process_value(value: int):
            # 처리
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # 첫 번째 인자 검증 (self 제외)
            if len(args) > 1:
                if not validator(args[1]):
                    raise ValueError(error_message)

            return await func(*args, **kwargs)

        return wrapper

    return decorator
