# -*- coding: utf-8 -*-
"""
DART API 예외 모듈

금융감독원 전자공시시스템(DART) Open API 관련 예외 정의
"""


class DARTAPIError(Exception):
    """DART API 기본 예외"""

    def __init__(self, message: str, status_code: str | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DARTRateLimitError(DARTAPIError):
    """DART API 일일 호출 한도 초과"""

    def __init__(self, message: str = "DART API 일일 호출 한도(10,000건) 초과") -> None:
        super().__init__(message, status_code="020")


class DARTCorpNotFoundError(DARTAPIError):
    """기업 고유번호를 찾을 수 없음"""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"종목코드 {symbol}에 해당하는 기업을 찾을 수 없습니다", status_code="013")
        self.symbol = symbol


class DARTInvalidKeyError(DARTAPIError):
    """유효하지 않은 API 키"""

    def __init__(self) -> None:
        super().__init__("DART API 키가 유효하지 않습니다", status_code="010")


class DARTNoDataError(DARTAPIError):
    """조회 데이터 없음"""

    def __init__(self, message: str = "해당 조건에 맞는 데이터가 없습니다") -> None:
        super().__init__(message, status_code="013")
