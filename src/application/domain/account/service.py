# -*- coding: utf-8 -*-
"""
Account Service - 계좌 관리 서비스
"""

from datetime import datetime
from decimal import Decimal

from src.adapters.cache.redis_client import RedisClient
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.exceptions import KISAPIServiceError
from src.application.domain.account.dto import (
    AccountBalanceResponseDTO,
    PositionListResponseDTO,
    PositionResponseDTO,
)
from src.settings.config import settings


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
        try:
            path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            params = {
                "CANO": account_no,
                "ACNT_PRDT_CD": settings.kis_product_code,
                "PDNO": "",
                "ORD_UNPR": "",
                "ORD_DVSN": "01",
                "CMA_EVLU_AMT_ICLD_YN": "Y",
                "OVRS_ICLD_YN": "N",
            }
            headers = {"tr_id": "TTTC8908R" if not settings.is_paper_trading else "VTTC8908R"}

            response = await self.kis_client.get(path, params=params, headers=headers)
            output = response.get("output", {})

            balance_data = AccountBalanceResponseDTO(
                account_no=account_no,
                total_balance=Decimal(output.get("tot_evlu_amt", "0")),
                cash_balance=Decimal(output.get("nxdy_excc_amt", "0")),
                stock_balance=Decimal(output.get("scts_evlu_amt", "0")),
                available_amount=Decimal(output.get("ord_psbl_cash", "0")),
                total_profit_loss=Decimal(output.get("evlu_pfls_smtl_amt", "0")),
                total_profit_loss_rate=Decimal(output.get("tot_evlu_pfls_rt", "0")),
                position_count=int(output.get("pchs_amt_smtl_amt", "0")),
                timestamp=datetime.now(),
            )

            # 캐시 저장
            if use_cache:
                await self.redis_client.cache_account_data(account_no, balance_data.model_dump())

            return balance_data

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get account balance: {e}")

    # ==================== 포지션 조회 ====================

    async def get_position_list(
        self, account_no: str | None = None
    ) -> PositionListResponseDTO:
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
            params = {
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
