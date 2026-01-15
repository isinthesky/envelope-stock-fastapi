# -*- coding: utf-8 -*-
"""
Access Logging Middleware - 페이지 접근 로깅 미들웨어

/page/ 경로에 대한 외부 접근을 로깅합니다.
"""

import logging
import time
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.models.access_log import AccessLogModel

logger = logging.getLogger(__name__)


class AccessLoggingMiddleware(BaseHTTPMiddleware):
    """
    페이지 접근 로깅 미들웨어

    /page/ 경로에 대한 접근을 DB에 기록합니다.
    내부 요청 (health check 등)은 제외합니다.
    """

    # 로깅 대상 경로 패턴
    LOG_PATHS = ["/page"]

    # 제외할 경로 패턴
    EXCLUDE_PATHS = ["/health", "/api/", "/mypage/", "/static/", "/favicon.ico"]

    # 제외할 User-Agent 패턴 (봇, 내부 요청 등)
    EXCLUDE_USER_AGENTS = ["health", "kube-probe", "ELB-HealthChecker"]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """요청 처리 및 로깅"""
        path = request.url.path

        # 로깅 대상 여부 확인
        should_log = self._should_log(request)

        # 요청 시작 시간
        start_time = time.time()

        # 요청 처리
        response = await call_next(request)

        # 로깅 대상인 경우에만 기록
        if should_log:
            try:
                await self._log_access(request, response, start_time)
            except Exception as e:
                logger.warning(f"Failed to log access: {e}")

        return response

    def _should_log(self, request: Request) -> bool:
        """로깅 대상 여부 확인"""
        path = request.url.path

        # 제외 경로 확인
        for exclude in self.EXCLUDE_PATHS:
            if path.startswith(exclude):
                return False

        # 로깅 대상 경로 확인
        for log_path in self.LOG_PATHS:
            if path.startswith(log_path):
                # User-Agent 확인
                user_agent = request.headers.get("user-agent", "")
                for exclude_ua in self.EXCLUDE_USER_AGENTS:
                    if exclude_ua.lower() in user_agent.lower():
                        return False
                return True

        return False

    async def _log_access(
        self, request: Request, response: Response, start_time: float
    ) -> None:
        """접근 로그 DB 저장"""
        # 응답 시간 계산
        response_time_ms = int((time.time() - start_time) * 1000)

        # 클라이언트 IP 추출 (프록시 뒤에 있는 경우 X-Forwarded-For 헤더 확인)
        ip_address = self._get_client_ip(request)

        # 로그 데이터 생성
        log_data = AccessLogModel(
            method=request.method,
            path=request.url.path,
            query_string=str(request.url.query) if request.url.query else None,
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
            status_code=response.status_code,
            response_time_ms=response_time_ms,
            accessed_at=datetime.now(),
        )

        # DB 저장
        async with AsyncSessionLocal() as session:
            session.add(log_data)
            await session.commit()

        logger.debug(
            f"Access logged: {request.method} {request.url.path} "
            f"from {ip_address} - {response.status_code} ({response_time_ms}ms)"
        )

    def _get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 추출"""
        # X-Forwarded-For 헤더 확인 (프록시/로드밸런서 뒤에 있는 경우)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # 첫 번째 IP가 실제 클라이언트 IP
            return forwarded_for.split(",")[0].strip()

        # X-Real-IP 헤더 확인
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # 직접 연결된 경우
        if request.client:
            return request.client.host

        return "unknown"
