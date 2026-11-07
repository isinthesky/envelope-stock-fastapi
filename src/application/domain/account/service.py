# -*- coding: utf-8 -*-
"""
Account Service - 계좌 관리 서비스
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from src.adapters.cache.redis_client import RedisClient
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.exceptions import KISAPIServiceError
from src.application.domain.account.dto import (
    AccountBalanceResponseDTO,
    PositionListResponseDTO,
    PositionResponseDTO,
)
from src.settings.config import settings


def _to_decimal(value: object) -> Decimal:
    """KIS 숫자 문자열(빈 문자열 포함)을 Decimal로. 해석 불가 값은 0."""
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _to_int(value: object) -> int:
    return int(_to_decimal(value))


def _first_row(output: object) -> dict:
    """KIS output2는 1행짜리 리스트(또는 dict)로 온다."""
    if isinstance(output, list):
        return output[0] if output else {}
    return output if isinstance(output, dict) else {}


class AccountService:
    """
    계좌 서비스

    계좌 잔고, 포지션 조회 및 관리
    """

    def __init__(self, kis_client: KISAPIClient, redis_client: RedisClient) -> None:
        self.kis_client = kis_client
        self.redis_client = redis_client

    # ==================== 계좌 잔고 조회 ====================

    async def get_account_balance(
        self, account_no: str | None = None, use_cache: bool = True
    ) -> AccountBalanceResponseDTO:
        """
        계좌 잔고 조회

        Args:
            account_no: 계좌번호 (없으면 기본 계좌)
            use_cache: 캐시 사용 여부

        Returns:
            AccountBalanceResponseDTO: 계좌 잔고 정보
        """
        account_no = account_no or settings.current_kis_account_no

        # 캐시 조회
        if use_cache:
            cached_data = await self.redis_client.get_account_data(account_no)
            if cached_data:
                return AccountBalanceResponseDTO(**cached_data)

        # API 호출
        # 잔고 합계는 주식잔고조회(TTTC8434R) output2, 주문가능현금만 매수가능조회(TTTC8908R)에서 읽는다.
        # (이전 구현은 TTTC8908R 응답에서 tot_evlu_amt 등 TTTC8434R 전용 필드를 읽어 전부 0이 됐다.)
        try:
            balance_response = await self.kis_client.get(
                "/uapi/domestic-stock/v1/trading/inquire-balance",
                params=self._inquire_balance_params(account_no),
                headers={"tr_id": "VTTC8434R" if settings.is_paper_trading else "TTTC8434R"},
            )
            summary = _first_row(balance_response.get("output2"))
            holdings = [
                item
                for item in balance_response.get("output1") or []
                if _to_int(item.get("hldg_qty")) > 0
            ]

            orderable_response = await self.kis_client.get(
                "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
                params={
                    "CANO": account_no,
                    "ACNT_PRDT_CD": settings.kis_product_code,
                    "PDNO": "",
                    "ORD_UNPR": "",
                    "ORD_DVSN": "01",
                    "CMA_EVLU_AMT_ICLD_YN": "Y",
                    "OVRS_ICLD_YN": "N",
                },
                headers={"tr_id": "VTTC8908R" if settings.is_paper_trading else "TTTC8908R"},
            )
            orderable = orderable_response.get("output") or {}

            purchase_total = _to_decimal(summary.get("pchs_amt_smtl_amt"))
            profit_loss = _to_decimal(summary.get("evlu_pfls_smtl_amt"))
            profit_loss_rate = (
                (profit_loss / purchase_total * 100).quantize(Decimal("0.01"))
                if purchase_total > 0
                else Decimal("0")
            )

            balance_data = AccountBalanceResponseDTO(
                account_no=account_no,
                total_balance=_to_decimal(summary.get("tot_evlu_amt")),
                # D+2 예수금(가수도정산금액): 결제 예정분까지 반영한 현금
                cash_balance=_to_decimal(summary.get("prvs_rcdl_excc_amt")),
                stock_balance=_to_decimal(summary.get("scts_evlu_amt")),
                # 주문가능현금 — 매수 사이징은 이 값을 기준으로 한다
                available_amount=_to_decimal(orderable.get("ord_psbl_cash")),
                total_profit_loss=profit_loss,
                total_profit_loss_rate=profit_loss_rate,
                position_count=len(holdings),
                timestamp=datetime.now(),
            )

            # 캐시 저장
            if use_cache:
                await self.redis_client.cache_account_data(account_no, balance_data.model_dump())

            return balance_data

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get account balance: {e}")

    @staticmethod
    def _inquire_balance_params(account_no: str) -> dict[str, str]:
        return {
            "CANO": account_no,
            "ACNT_PRDT_CD": settings.kis_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

    # ==================== 포지션 조회 ====================

    async def get_position_list(self, account_no: str | None = None) -> PositionListResponseDTO:
        """
        포지션 목록 조회

        Args:
            account_no: 계좌번호

        Returns:
            PositionListResponseDTO: 포지션 목록
        """
        account_no = account_no or settings.current_kis_account_no

        try:
            path = "/uapi/domestic-stock/v1/trading/inquire-balance"
            params = self._inquire_balance_params(account_no)
            headers = {"tr_id": "TTTC8434R" if not settings.is_paper_trading else "VTTC8434R"}

            response = await self.kis_client.get(path, params=params, headers=headers)
            output_list = response.get("output1", [])

            positions = []
            for item in output_list:
                positions.append(
                    PositionResponseDTO(
                        symbol=item.get("pdno", ""),
                        symbol_name=item.get("prdt_name", ""),
                        quantity=int(item.get("hldg_qty", "0")),
                        available_quantity=int(item.get("ord_psbl_qty", "0")),
                        avg_purchase_price=Decimal(item.get("pchs_avg_pric", "0")),
                        current_price=Decimal(item.get("prpr", "0")),
                        purchase_amount=Decimal(item.get("pchs_amt", "0")),
                        evaluated_amount=Decimal(item.get("evlu_amt", "0")),
                        profit_loss=Decimal(item.get("evlu_pfls_amt", "0")),
                        profit_loss_rate=Decimal(item.get("evlu_pfls_rt", "0")),
                    )
                )

            total_purchase = sum(p.purchase_amount for p in positions)
            total_evaluated = sum(p.evaluated_amount for p in positions)
            total_profit_loss = sum(p.profit_loss for p in positions)

            return PositionListResponseDTO(
                account_no=account_no,
                positions=positions,
                total_count=len(positions),
                total_purchase_amount=total_purchase,
                total_evaluated_amount=total_evaluated,
                total_profit_loss=total_profit_loss,
            )

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get position list: {e}")
