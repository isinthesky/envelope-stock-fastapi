# -*- coding: utf-8 -*-
"""
DART API 모듈

금융감독원 전자공시시스템(DART) Open API 클라이언트
"""

from src.adapters.external.dart_api.client import (
    DARTAPIClient,
    close_dart_client,
    get_dart_client,
)
from src.adapters.external.dart_api.dto import (
    CompanyInfoDTO,
    CorpCodeDTO,
    FinancialScreeningDTO,
    FinancialStatementDTO,
    FinancialSummaryDTO,
    MajorShareholderDTO,
    OwnershipSummaryDTO,
    PeriodFinancialDTO,
)
from src.adapters.external.dart_api.exceptions import (
    DARTAPIError,
    DARTCorpNotFoundError,
    DARTInvalidKeyError,
    DARTNoDataError,
    DARTRateLimitError,
)

__all__ = [
    # Client
    "DARTAPIClient",
    "get_dart_client",
    "close_dart_client",
    # DTOs
    "CorpCodeDTO",
    "CompanyInfoDTO",
    "FinancialStatementDTO",
    "FinancialSummaryDTO",
    "FinancialScreeningDTO",
    "PeriodFinancialDTO",
    "MajorShareholderDTO",
    "OwnershipSummaryDTO",
    # Exceptions
    "DARTAPIError",
    "DARTRateLimitError",
    "DARTCorpNotFoundError",
    "DARTInvalidKeyError",
    "DARTNoDataError",
]
