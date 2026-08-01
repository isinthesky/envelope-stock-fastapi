# -*- coding: utf-8 -*-
"""
DART API Client - 금융감독원 전자공시시스템 API 클라이언트

DART Open API를 통한 기업정보, 재무제표, 지분현황 조회

캐싱 정책:
- 재무 스크리닝 데이터: Redis 7일 캐싱 (재무제표는 분기별 갱신)
- 기업개황: Redis 30일 캐싱 (거의 변경 없음)
- 고유번호: 메모리 캐싱 (세션 유지)
"""

import asyncio
import io
import logging
import zipfile
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.adapters.external.dart_api.dto import (
    CompanyInfoDTO,
    CorpCodeDTO,
    FinancialScreeningDTO,
    FinancialStatementDTO,
    MajorShareholderDTO,
    PeriodFinancialDTO,
)
from src.adapters.external.dart_api.exceptions import (
    DARTAPIError,
    DARTCorpNotFoundError,
    DARTInvalidKeyError,
    DARTNoDataError,
    DARTRateLimitError,
)
from src.settings.config import settings

logger = logging.getLogger(__name__)

# 캐시 TTL 설정 (초)
CACHE_TTL_FINANCIAL_SCREENING = 7 * 24 * 60 * 60  # 7일 (재무제표는 분기별 갱신)
CACHE_TTL_COMPANY_INFO = 30 * 24 * 60 * 60  # 30일 (거의 변경 없음)


# DART API 응답 상태 코드
DART_STATUS_CODES = {
    "000": "정상",
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "013": "조회된 데이터 없음",
    "020": "일일 요청 한도 초과",
    "100": "필수 파라미터 누락",
    "800": "원하지 않는 데이터",
    "900": "시스템 에러",
}


class DARTAPIClient:
    """
    DART Open API REST 클라이언트

    기업 고유번호 매핑, 기업개황, 재무제표, 지분현황 조회 기능 제공
    """

    def __init__(self) -> None:
        self.api_key = settings.dart_open_api_key
        self.base_url = settings.dart_api_base_url
        self.timeout = settings.dart_api_timeout

        # 고유번호 캐시 (stock_code -> corp_code)
        self._corp_code_cache: dict[str, CorpCodeDTO] = {}
        self._cache_loaded = False
        self._cache_lock = asyncio.Lock()

        # HTTP 클라이언트
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """httpx.AsyncClient 인스턴스 반환 (Lazy 초기화)"""
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=self.timeout,
                        limits=httpx.Limits(
                            max_keepalive_connections=10,
                            max_connections=20,
                            keepalive_expiry=30.0,
                        ),
                    )
        return self._client

    async def aclose(self) -> None:
        """HTTP 클라이언트 리소스 정리"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _check_response_status(self, data: dict, allow_no_data: bool = False) -> None:
        """API 응답 상태 코드 확인"""
        status = data.get("status", "")

        if status == "000":
            return

        if status == "010" or status == "011":
            raise DARTInvalidKeyError()

        if status == "013":
            if allow_no_data:
                return
            raise DARTNoDataError()

        if status == "020":
            raise DARTRateLimitError()

        message = DART_STATUS_CODES.get(status, f"알 수 없는 오류 (코드: {status})")
        raise DARTAPIError(message, status_code=status)

    # ==================== 고유번호 조회 ====================

    async def load_corp_codes(self) -> None:
        """
        전체 기업 고유번호 목록 로드 (ZIP 파일 다운로드)

        DART API에서 제공하는 고유번호 ZIP 파일을 다운로드하여 파싱
        """
        async with self._cache_lock:
            if self._cache_loaded:
                return

            logger.info("DART 고유번호 목록 로드 시작")
            client = await self._get_client()

            url = f"{self.base_url}/api/corpCode.xml"
            params = {"crtfc_key": self.api_key}

            response = await client.get(url, params=params)
            response.raise_for_status()

            # Content-Type 확인: JSON이면 에러 응답
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    data = response.json()
                    self._check_response_status(data)
                except Exception as e:
                    raise DARTAPIError(f"고유번호 목록 조회 실패: {e}")

            # ZIP 파일인지 확인
            if not response.content.startswith(b"PK"):
                raise DARTAPIError("고유번호 목록 응답이 ZIP 파일이 아닙니다")

            # ZIP 파일 파싱
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                xml_filename = zf.namelist()[0]
                with zf.open(xml_filename) as xml_file:
                    tree = ElementTree.parse(xml_file)
                    root = tree.getroot()

                    for corp in root.findall("list"):
                        corp_code = corp.findtext("corp_code", "")
                        corp_name = corp.findtext("corp_name", "")
                        stock_code = corp.findtext("stock_code", "")
                        modify_date = corp.findtext("modify_date", "")

                        if stock_code:  # 상장사만 캐시
                            dto = CorpCodeDTO.from_xml(
                                corp_code=corp_code,
                                corp_name=corp_name,
                                stock_code=stock_code,
                                modify_date=modify_date,
                            )
                            self._corp_code_cache[stock_code] = dto

            self._cache_loaded = True
            logger.info(f"DART 고유번호 {len(self._corp_code_cache)}개 로드 완료")

    async def get_corp_code(self, stock_code: str) -> str:
        """
        종목코드로 DART 고유번호 조회

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            DART 고유번호 (8자리)

        Raises:
            DARTCorpNotFoundError: 종목코드에 해당하는 기업이 없을 경우
        """
        if not self._cache_loaded:
            await self.load_corp_codes()

        dto = self._corp_code_cache.get(stock_code)
        if not dto:
            raise DARTCorpNotFoundError(stock_code)

        return dto.corp_code

    # ==================== 기업개황 조회 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get_company_info(self, corp_code: str) -> CompanyInfoDTO:
        """
        기업개황 조회

        Args:
            corp_code: DART 고유번호

        Returns:
            CompanyInfoDTO: 기업개황 정보
        """
        client = await self._get_client()

        url = f"{self.base_url}/api/company.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
        }

        response = await client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        self._check_response_status(data)

        return CompanyInfoDTO.from_api_response(data)

    # ==================== 재무제표 조회 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
        fs_div: str = "CFS",
    ) -> Sequence[FinancialStatementDTO]:
        """
        재무제표 전체 계정 조회

        Args:
            corp_code: DART 고유번호
            bsns_year: 사업연도 (예: "2024")
            reprt_code: 보고서 코드
                - 11013: 1분기보고서
                - 11012: 반기보고서
                - 11014: 3분기보고서
                - 11011: 사업보고서 (연간)
            fs_div: 재무제표 구분
                - CFS: 연결재무제표
                - OFS: 개별재무제표

        Returns:
            재무제표 항목 리스트
        """
        client = await self._get_client()

        url = f"{self.base_url}/api/fnlttSinglAcntAll.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }

        response = await client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        self._check_response_status(data, allow_no_data=True)

        items = data.get("list", [])
        if not items:
            return []

        return [FinancialStatementDTO.from_api_response(item) for item in items]

    # ==================== 지분현황 조회 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get_major_shareholders(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
    ) -> Sequence[MajorShareholderDTO]:
        """
        최대주주 현황 조회

        Args:
            corp_code: DART 고유번호
            bsns_year: 사업연도
            reprt_code: 보고서 코드

        Returns:
            최대주주 현황 리스트
        """
        client = await self._get_client()

        url = f"{self.base_url}/api/hyslrSttus.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }

        response = await client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        self._check_response_status(data, allow_no_data=True)

        items = data.get("list", [])
        if not items:
            return []

        return [MajorShareholderDTO.from_api_response(item) for item in items]

    # ==================== 재무 스크리닝 (2차 필터) ====================

    async def get_financial_screening(
        self,
        stock_code: str,
        use_cache: bool = True,
    ) -> FinancialScreeningDTO | None:
        """
        재무 스크리닝 (2차 필터용)

        최근 2년간 반기/연간 데이터를 조회하여 스크리닝
        - 매출 YoY ≥ 0%
        - 영업이익 2년 연속 흑자
        - 적자→흑자 전환 여부

        캐싱: Redis 7일 TTL

        Args:
            stock_code: 종목코드
            use_cache: 캐시 사용 여부 (기본 True)

        Returns:
            FinancialScreeningDTO 또는 None
        """
        # 캐시 조회
        if use_cache:
            cached = await self._get_cached_financial_screening(stock_code)
            if cached is not None:
                logger.debug(f"[DART] {stock_code}: 캐시 히트")
                return cached

        try:
            corp_code = await self.get_corp_code(stock_code)
        except DARTCorpNotFoundError:
            logger.debug(f"[DART] {stock_code}: 고유번호 없음")
            return None

        # 기업개황에서 업종코드 조회
        try:
            company_info = await self.get_company_info(corp_code)
            corp_name = company_info.corp_name
            induty_code = company_info.induty_code
        except Exception:
            corp_name = ""
            induty_code = ""

        current_year = datetime.now().year
        periods: list[PeriodFinancialDTO] = []

        # 보고서 코드: 11011(사업보고서/연간), 11012(반기)
        # 최근 2년 데이터 조회 (반기 단위 우선, 없으면 연간)
        report_configs = [
            # (연도, 보고서코드, 기간유형)
            (current_year - 1, "11012", "H1"),  # 전년 상반기
            (current_year - 1, "11011", "ANNUAL"),  # 전년 연간
            (current_year - 2, "11012", "H1"),  # 전전년 상반기
            (current_year - 2, "11011", "ANNUAL"),  # 전전년 연간
        ]

        used_fs_type = "CFS"  # 사용된 재무제표 유형 추적

        for bsns_year, reprt_code, period_type in report_configs:
            try:
                # CFS(연결재무제표) 먼저 시도
                statements = await self.get_financial_statements(
                    corp_code=corp_code,
                    bsns_year=str(bsns_year),
                    reprt_code=reprt_code,
                    fs_div="CFS",
                )

                # CFS에 데이터 없으면 OFS(개별재무제표)로 fallback
                if not statements:
                    statements = await self.get_financial_statements(
                        corp_code=corp_code,
                        bsns_year=str(bsns_year),
                        reprt_code=reprt_code,
                        fs_div="OFS",
                    )
                    if statements:
                        used_fs_type = "OFS"
                        logger.debug(f"[DART] {stock_code} {bsns_year}: OFS로 fallback")

                if not statements:
                    continue

                # 매출액, 영업이익 추출
                revenue = Decimal("0")
                operating_profit = Decimal("0")
                net_income = Decimal("0")

                for stmt in statements:
                    account_nm = stmt.account_nm
                    if "매출액" in account_nm or "수익(매출액)" in account_nm:
                        if stmt.thstrm_amount > 0:
                            revenue = stmt.thstrm_amount
                    elif account_nm == "영업이익" or account_nm == "영업이익(손실)":
                        operating_profit = stmt.thstrm_amount
                    elif "당기순이익" in account_nm:
                        if stmt.thstrm_amount != 0 and net_income == 0:
                            net_income = stmt.thstrm_amount

                # 영업이익률 계산
                operating_margin = Decimal("0")
                if revenue > 0:
                    operating_margin = (operating_profit / revenue) * 100

                period_label = f"{bsns_year}{period_type}"
                periods.append(PeriodFinancialDTO(
                    period=period_label,
                    period_type=period_type,
                    revenue=revenue,
                    operating_profit=operating_profit,
                    operating_margin=operating_margin,
                    net_income=net_income,
                ))

            except DARTNoDataError:
                continue
            except DARTAPIError as e:
                logger.debug(f"[DART] {stock_code} {bsns_year} {reprt_code}: {e.message}")
                continue

        if len(periods) < 2:
            logger.debug(f"[DART] {stock_code}: 재무 데이터 부족 ({len(periods)}개)")
            return None

        # 연간 데이터만 필터링 (비교 기준)
        annual_periods = [p for p in periods if p.period_type == "ANNUAL"]

        if len(annual_periods) < 2:
            # 연간이 부족하면 반기로 대체
            annual_periods = sorted(periods, key=lambda x: x.period, reverse=True)[:2]

        if len(annual_periods) < 2:
            return None

        latest = annual_periods[0]
        previous = annual_periods[1]

        # 매출 데이터 가용성 확인 (매출액이 0이면 데이터 부족으로 간주)
        has_revenue_data = latest.revenue > 0 and previous.revenue > 0

        # 매출 YoY 계산 (데이터 부족 시 None)
        revenue_yoy: Decimal | None = None
        if has_revenue_data:
            revenue_yoy = ((latest.revenue - previous.revenue) / previous.revenue) * 100

        # 2년 연속 흑자 여부
        is_consecutive_profit = (
            latest.operating_profit > 0 and previous.operating_profit > 0
        )

        # 적자→흑자 전환 여부
        is_turnaround = (
            previous.operating_profit <= 0 and latest.operating_profit > 0
        )

        # 필터 통과 여부 (매출 데이터 없으면 통과 불가)
        passes_revenue_filter = has_revenue_data and revenue_yoy is not None and revenue_yoy >= Decimal("0")
        passes_profit_filter = is_consecutive_profit

        result = FinancialScreeningDTO(
            stock_code=stock_code,
            corp_code=corp_code,
            corp_name=corp_name,
            induty_code=induty_code,
            periods=periods,
            revenue_yoy=revenue_yoy,
            latest_operating_margin=latest.operating_margin,
            is_consecutive_profit=is_consecutive_profit,
            is_turnaround=is_turnaround,
            has_revenue_data=has_revenue_data,
            fs_type=used_fs_type,
            passes_revenue_filter=passes_revenue_filter,
            passes_profit_filter=passes_profit_filter,
        )

        # 결과 캐싱
        await self._cache_financial_screening(stock_code, result)

        return result

    # ==================== 캐싱 헬퍼 메서드 ====================

    async def _get_redis_client(self):
        """Redis 클라이언트 가져오기 (lazy import)"""
        try:
            from src.adapters.cache.redis_client import get_redis_client
            return await get_redis_client()
        except Exception:
            return None

    async def _get_cached_financial_screening(
        self, stock_code: str
    ) -> FinancialScreeningDTO | None:
        """캐시에서 재무 스크리닝 결과 조회"""
        try:
            redis = await self._get_redis_client()
            if redis is None:
                return None

            cache_key = f"dart:financial:{stock_code}"
            cached_data = await redis.get(cache_key)

            if cached_data is None:
                return None

            # JSON -> DTO 변환
            return self._deserialize_financial_screening(cached_data)
        except Exception as e:
            logger.debug(f"[DART] 캐시 조회 실패 {stock_code}: {e}")
            return None

    async def _cache_financial_screening(
        self, stock_code: str, dto: FinancialScreeningDTO
    ) -> None:
        """재무 스크리닝 결과 캐싱"""
        try:
            redis = await self._get_redis_client()
            if redis is None:
                return

            cache_key = f"dart:financial:{stock_code}"
            cache_data = self._serialize_financial_screening(dto)
            await redis.set(cache_key, cache_data, ttl=CACHE_TTL_FINANCIAL_SCREENING)
            logger.debug(f"[DART] {stock_code}: 캐시 저장 (TTL: 7일)")
        except Exception as e:
            logger.debug(f"[DART] 캐시 저장 실패 {stock_code}: {e}")

    def _serialize_financial_screening(self, dto: FinancialScreeningDTO) -> dict:
        """FinancialScreeningDTO -> JSON 직렬화"""
        return {
            "stock_code": dto.stock_code,
            "corp_code": dto.corp_code,
            "corp_name": dto.corp_name,
            "induty_code": dto.induty_code,
            "periods": [
                {
                    "period": p.period,
                    "period_type": p.period_type,
                    "revenue": str(p.revenue),
                    "operating_profit": str(p.operating_profit),
                    "operating_margin": str(p.operating_margin),
                    "net_income": str(p.net_income),
                }
                for p in dto.periods
            ],
            "revenue_yoy": str(dto.revenue_yoy) if dto.revenue_yoy is not None else None,
            "latest_operating_margin": str(dto.latest_operating_margin),
            "is_consecutive_profit": dto.is_consecutive_profit,
            "is_turnaround": dto.is_turnaround,
            "has_revenue_data": dto.has_revenue_data,
            "fs_type": dto.fs_type,
            "passes_revenue_filter": dto.passes_revenue_filter,
            "passes_profit_filter": dto.passes_profit_filter,
        }

    def _deserialize_financial_screening(self, data: dict) -> FinancialScreeningDTO:
        """JSON -> FinancialScreeningDTO 역직렬화"""
        periods = [
            PeriodFinancialDTO(
                period=p["period"],
                period_type=p["period_type"],
                revenue=Decimal(p["revenue"]),
                operating_profit=Decimal(p["operating_profit"]),
                operating_margin=Decimal(p["operating_margin"]),
                net_income=Decimal(p["net_income"]),
            )
            for p in data.get("periods", [])
        ]

        revenue_yoy = Decimal(data["revenue_yoy"]) if data.get("revenue_yoy") else None

        return FinancialScreeningDTO(
            stock_code=data["stock_code"],
            corp_code=data["corp_code"],
            corp_name=data["corp_name"],
            induty_code=data["induty_code"],
            periods=periods,
            revenue_yoy=revenue_yoy,
            latest_operating_margin=Decimal(data["latest_operating_margin"]),
            is_consecutive_profit=data["is_consecutive_profit"],
            is_turnaround=data["is_turnaround"],
            has_revenue_data=data.get("has_revenue_data", True),
            fs_type=data.get("fs_type", "CFS"),
            passes_revenue_filter=data["passes_revenue_filter"],
            passes_profit_filter=data["passes_profit_filter"],
        )

# 싱글톤 인스턴스
_dart_client: DARTAPIClient | None = None
_dart_client_lock = asyncio.Lock()


async def get_dart_client() -> DARTAPIClient:
    """DART API 클라이언트 싱글톤 반환"""
    global _dart_client
    if _dart_client is None:
        async with _dart_client_lock:
            if _dart_client is None:
                _dart_client = DARTAPIClient()
    return _dart_client


async def close_dart_client() -> None:
    """DART API 클라이언트 정리"""
    global _dart_client
    if _dart_client is not None:
        await _dart_client.aclose()
        _dart_client = None
