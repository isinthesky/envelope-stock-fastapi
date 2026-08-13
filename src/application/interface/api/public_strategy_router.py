# -*- coding: utf-8 -*-
"""
Public Strategy Router - 공개 전략 포털(/page/) 전용 API

관리자 보호 없이 외부에 노출되는 유일한 전략 API 표면이다.
- 요청으로 조작 가능한 값은 market 하나뿐이며, 한도/동시성/재무 필터는 서버 고정
- rate limit(쿨다운/전역 락)과 fail-closed 정책은 PublicStrategyService가 담당
- 추천은 스케줄러가 생성한 스냅샷 캐시만 반환 (재계산 없음)
"""

from fastapi import APIRouter, Request, status

from src.application.common.dependencies import PublicStrategyServiceDep, get_client_ip
from src.application.common.dto import ResponseDTO
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicGoldenCrossScanRequestDTO,
    PublicRecommendationSnapshotDTO,
    PublicScanCapabilitiesDTO,
)
from src.settings.config import settings

router = APIRouter(
    prefix="/api/v1/public/strategies",
    tags=["Public-Strategy"],
    include_in_schema=False,
)


@router.get(
    "/scan-capabilities",
    response_model=ResponseDTO[PublicScanCapabilitiesDTO],
    status_code=status.HTTP_200_OK,
    summary="공개 스캔 가용 시장 조회",
    description="설정(ETF_UNIVERSE_ENABLED)과 실제 활성 유니버스의 교집합으로 계산한 스캔 가능 시장",
)
async def public_scan_capabilities(
    service: PublicStrategyServiceDep,
) -> ResponseDTO[PublicScanCapabilitiesDTO]:
    """공개 스캔 가용성 조회 - DB count만 수행, 스캔/추천은 실행하지 않음"""
    result = await service.get_scan_capabilities()
    return ResponseDTO.success_response(result, "Public scan capabilities retrieved")


@router.post(
    "/golden-cross-scan",
    response_model=ResponseDTO[PublicGoldenCrossScanDTO],
    status_code=status.HTTP_200_OK,
    summary="공개 골든크로스 스캔 (제한형)",
    description="IP 쿨다운/전역 락/서버 고정 한도가 적용된 공개 스캔",
)
async def public_golden_cross_scan(
    request: Request,
    body: PublicGoldenCrossScanRequestDTO,
    service: PublicStrategyServiceDep,
) -> ResponseDTO[PublicGoldenCrossScanDTO]:
    """공개 골든크로스 스캔 - 정책 적용은 PublicStrategyService가 담당"""
    client_ip = get_client_ip(request, settings.trusted_proxy_ips)
    result = await service.run_public_scan(market=body.market, client_ip=client_ip)
    return ResponseDTO.success_response(result, "Public golden cross scan completed")


@router.get(
    "/recommendations",
    response_model=ResponseDTO[PublicRecommendationSnapshotDTO],
    status_code=status.HTTP_200_OK,
    summary="공개 추천 스냅샷 조회",
    description="스케줄러가 생성한 추천 스냅샷 캐시 조회 (캐시 없으면 available=false)",
)
async def public_recommendations(
    service: PublicStrategyServiceDep,
) -> ResponseDTO[PublicRecommendationSnapshotDTO]:
    """공개 추천 스냅샷 조회 - 캐시 전용, 전략 재계산을 유발하지 않음"""
    result = await service.get_public_recommendations()
    return ResponseDTO.success_response(result, "Public recommendations retrieved")
