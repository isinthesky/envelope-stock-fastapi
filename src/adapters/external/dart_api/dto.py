# -*- coding: utf-8 -*-
"""
DART API DTO 모듈

금융감독원 전자공시시스템(DART) Open API 응답 데이터 구조
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CorpCodeDTO:
    """기업 고유번호 정보"""

    corp_code: str  # DART 고유번호 (8자리)
    corp_name: str  # 정식 회사명
    stock_code: str  # 종목코드 (6자리, 상장사만)
    modify_date: str  # 최종변경일

    @classmethod
    def from_xml(cls, corp_code: str, corp_name: str, stock_code: str, modify_date: str) -> "CorpCodeDTO":
        """XML 파싱 결과로부터 생성"""
        return cls(
            corp_code=corp_code.strip(),
            corp_name=corp_name.strip(),
            stock_code=stock_code.strip() if stock_code else "",
            modify_date=modify_date.strip() if modify_date else "",
        )


@dataclass
class CompanyInfoDTO:
    """기업개황 정보"""

    corp_code: str  # 고유번호
    corp_name: str  # 정식명칭
    corp_name_eng: str  # 영문명칭
    stock_name: str  # 종목명
    stock_code: str  # 종목코드
    ceo_nm: str  # 대표자명
    corp_cls: str  # 법인구분 (Y:유가, K:코스닥, N:코넥스, E:기타)
    jurir_no: str  # 법인등록번호
    bizr_no: str  # 사업자등록번호
    adres: str  # 주소
    hm_url: str  # 홈페이지
    ir_url: str  # IR 홈페이지
    phn_no: str  # 전화번호
    fax_no: str  # 팩스번호
    induty_code: str  # 업종코드
    est_dt: str  # 설립일 (YYYYMMDD)
    acc_mt: str  # 결산월 (MM)

    @classmethod
    def from_api_response(cls, data: dict) -> "CompanyInfoDTO":
        """API 응답으로부터 생성"""
        return cls(
            corp_code=data.get("corp_code", ""),
            corp_name=data.get("corp_name", ""),
            corp_name_eng=data.get("corp_name_eng", ""),
            stock_name=data.get("stock_name", ""),
            stock_code=data.get("stock_code", ""),
            ceo_nm=data.get("ceo_nm", ""),
            corp_cls=data.get("corp_cls", ""),
            jurir_no=data.get("jurir_no", ""),
            bizr_no=data.get("bizr_no", ""),
            adres=data.get("adres", ""),
            hm_url=data.get("hm_url", ""),
            ir_url=data.get("ir_url", ""),
            phn_no=data.get("phn_no", ""),
            fax_no=data.get("fax_no", ""),
            induty_code=data.get("induty_code", ""),
            est_dt=data.get("est_dt", ""),
            acc_mt=data.get("acc_mt", ""),
        )

@dataclass
class FinancialStatementDTO:
    """재무제표 항목"""

    rcept_no: str  # 접수번호
    reprt_code: str  # 보고서 코드 (11013: 1분기, 11012: 반기, 11014: 3분기, 11011: 사업)
    bsns_year: str  # 사업연도
    corp_code: str  # 고유번호
    sj_div: str  # 재무제표 구분 (BS: 재무상태표, IS: 손익계산서, CIS: 포괄손익계산서, CF: 현금흐름표)
    sj_nm: str  # 재무제표명
    account_id: str  # 계정ID
    account_nm: str  # 계정명
    account_detail: str  # 계정상세
    thstrm_nm: str  # 당기명
    thstrm_amount: Decimal  # 당기금액
    frmtrm_nm: str  # 전기명
    frmtrm_amount: Decimal  # 전기금액
    bfefrmtrm_nm: str  # 전전기명
    bfefrmtrm_amount: Decimal  # 전전기금액
    ord: int  # 계정과목 정렬순서
    currency: str  # 통화 단위

    @classmethod
    def from_api_response(cls, data: dict) -> "FinancialStatementDTO":
        """API 응답으로부터 생성"""

        def parse_amount(value: str | None) -> Decimal:
            if not value:
                return Decimal("0")
            try:
                return Decimal(value.replace(",", ""))
            except Exception:
                return Decimal("0")

        return cls(
            rcept_no=data.get("rcept_no", ""),
            reprt_code=data.get("reprt_code", ""),
            bsns_year=data.get("bsns_year", ""),
            corp_code=data.get("corp_code", ""),
            sj_div=data.get("sj_div", ""),
            sj_nm=data.get("sj_nm", ""),
            account_id=data.get("account_id", ""),
            account_nm=data.get("account_nm", ""),
            account_detail=data.get("account_detail", ""),
            thstrm_nm=data.get("thstrm_nm", ""),
            thstrm_amount=parse_amount(data.get("thstrm_amount")),
            frmtrm_nm=data.get("frmtrm_nm", ""),
            frmtrm_amount=parse_amount(data.get("frmtrm_amount")),
            bfefrmtrm_nm=data.get("bfefrmtrm_nm", ""),
            bfefrmtrm_amount=parse_amount(data.get("bfefrmtrm_amount")),
            ord=int(data.get("ord", 0)),
            currency=data.get("currency", "KRW"),
        )


@dataclass
class MajorShareholderDTO:
    """최대주주 현황"""

    rcept_no: str  # 접수번호
    corp_cls: str  # 법인구분
    corp_code: str  # 고유번호
    corp_name: str  # 법인명
    nm: str  # 성명 (최대주주명)
    relate: str  # 관계 (본인, 친인척 등)
    stock_knd: str  # 주식종류 (보통주, 우선주 등)
    bsis_posesn_stock_co: int  # 기초 소유 주식수
    bsis_posesn_stock_qota_rt: Decimal  # 기초 소유 지분율
    trmend_posesn_stock_co: int  # 기말 소유 주식수
    trmend_posesn_stock_qota_rt: Decimal  # 기말 소유 지분율
    rm: str  # 비고

    @classmethod
    def from_api_response(cls, data: dict) -> "MajorShareholderDTO":
        """API 응답으로부터 생성"""

        def parse_int(value: str | None) -> int:
            if not value:
                return 0
            try:
                return int(value.replace(",", ""))
            except Exception:
                return 0

        def parse_rate(value: str | None) -> Decimal:
            if not value:
                return Decimal("0")
            try:
                return Decimal(value.replace(",", ""))
            except Exception:
                return Decimal("0")

        return cls(
            rcept_no=data.get("rcept_no", ""),
            corp_cls=data.get("corp_cls", ""),
            corp_code=data.get("corp_code", ""),
            corp_name=data.get("corp_name", ""),
            nm=data.get("nm", ""),
            relate=data.get("relate", ""),
            stock_knd=data.get("stock_knd", ""),
            bsis_posesn_stock_co=parse_int(data.get("bsis_posesn_stock_co")),
            bsis_posesn_stock_qota_rt=parse_rate(data.get("bsis_posesn_stock_qota_rt")),
            trmend_posesn_stock_co=parse_int(data.get("trmend_posesn_stock_co")),
            trmend_posesn_stock_qota_rt=parse_rate(data.get("trmend_posesn_stock_qota_rt")),
            rm=data.get("rm", ""),
        )


@dataclass
class FinancialSummaryDTO:
    """재무 요약 정보 (2차 필터링용)"""

    corp_code: str
    bsns_year: str
    revenue: Decimal  # 매출액
    revenue_yoy: Decimal  # 매출액 YoY 증가율
    operating_profit: Decimal  # 영업이익
    net_income: Decimal  # 당기순이익
    is_profitable: bool  # 흑자 여부

    @property
    def passes_filter(self) -> bool:
        """2차 필터 통과 여부 (매출 YoY≥0%, 흑자)"""
        return self.revenue_yoy >= Decimal("0") and self.is_profitable


@dataclass
class OwnershipSummaryDTO:
    """지분 요약 정보 (3차 필터링용)"""

    corp_code: str
    major_shareholder_name: str  # 최대주주명
    major_shareholder_rate: Decimal  # 최대주주 지분율

    @property
    def passes_filter(self, min_rate: Decimal = Decimal("15")) -> bool:
        """3차 필터 통과 여부 (최대주주 지분율 ≥15%)"""
        return self.major_shareholder_rate >= min_rate


@dataclass
class PeriodFinancialDTO:
    """기간별 재무 데이터"""

    period: str  # 기간 (예: "2024Q1", "2024H1", "2024")
    period_type: str  # 기간 유형 (Q1, Q2, Q3, Q4, H1, H2, ANNUAL)
    revenue: Decimal  # 매출액
    operating_profit: Decimal  # 영업이익
    operating_margin: Decimal  # 영업이익률 (%)
    net_income: Decimal  # 당기순이익


@dataclass
class FinancialScreeningDTO:
    """
    재무 스크리닝 결과 (2차 필터용)

    조건:
    - 매출 YoY ≥ 0% (구조적 성장/유지)
    - 영업이익 2년 연속 흑자 (턴어라운드 제외)
    - 영업이익률 업종 하위 30% 제외 (품질 필터)
    """

    stock_code: str
    corp_code: str
    corp_name: str
    induty_code: str  # 업종코드

    # 최근 기간 재무 데이터
    periods: list[PeriodFinancialDTO]

    # 계산된 지표
    revenue_yoy: Decimal | None  # 매출 YoY 증가율 (%), None=데이터 부족
    latest_operating_margin: Decimal  # 최근 영업이익률 (%)
    is_consecutive_profit: bool  # 2년 연속 영업흑자 여부
    is_turnaround: bool  # 적자→흑자 전환 여부

    # 데이터 가용성 플래그
    has_revenue_data: bool = True  # 매출액 데이터 존재 여부
    fs_type: str = "CFS"  # 사용된 재무제표 유형 (CFS: 연결, OFS: 개별)

    # 필터 통과 여부
    passes_revenue_filter: bool = False  # 매출 YoY ≥ 0%
    passes_profit_filter: bool = False  # 2년 연속 흑자

    @property
    def filter_status(self) -> str:
        """필터 상태"""
        # 매출 데이터 부족 시 FAIL
        if not self.has_revenue_data:
            return "FAIL"
        if self.is_turnaround:
            return "TURNAROUND"  # 적자→흑자 전환 (별도 버킷)
        if self.passes_revenue_filter and self.passes_profit_filter:
            return "PASS"
        return "FAIL"

    @property
    def passes_filter(self) -> bool:
        """2차 필터 통과 여부 (턴어라운드 제외)"""
        return self.passes_revenue_filter and self.passes_profit_filter and not self.is_turnaround

    def to_dict(self) -> dict:
        """딕셔너리 변환"""
        return {
            "stock_code": self.stock_code,
            "corp_name": self.corp_name,
            "revenue_yoy": float(self.revenue_yoy) if self.revenue_yoy is not None else None,
            "operating_margin": float(self.latest_operating_margin),
            "is_consecutive_profit": self.is_consecutive_profit,
            "is_turnaround": self.is_turnaround,
            "has_revenue_data": self.has_revenue_data,
            "fs_type": self.fs_type,
            "filter_status": self.filter_status,
            "passes_filter": self.passes_filter,
        }
