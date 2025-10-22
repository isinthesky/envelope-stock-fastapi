# -*- coding: utf-8 -*-
"""
Common DTO - 공통 데이터 전송 객체

Base DTO, Pagination, Response 등 재사용 가능한 DTO 정의
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ==================== Base DTO ====================


class BaseDTO(BaseModel):
    """
    Base DTO 클래스

    모든 DTO의 기본 클래스
    """

    model_config = ConfigDict(
        from_attributes=True,  # ORM 모델에서 변환 가능
        populate_by_name=True,  # alias와 실제 이름 모두 사용 가능
        use_enum_values=True,  # Enum을 값으로 직렬화
    )


# ==================== Response DTO ====================


class ResponseDTO(BaseDTO, Generic[T]):
    """
    API 응답 DTO

    Attributes:
        success: 성공 여부
        message: 응답 메시지
        data: 응답 데이터
        error: 에러 정보 (실패 시)
    """

    success: bool = Field(description="성공 여부")
    message: str | None = Field(default=None, description="응답 메시지")
    data: T | None = Field(default=None, description="응답 데이터")
    error: dict[str, Any] | None = Field(default=None, description="에러 정보")

    @classmethod
    def success_response(cls, data: T, message: str = "Success") -> "ResponseDTO[T]":
        """성공 응답 생성"""
        return cls(success=True, message=message, data=data)

    @classmethod
    def error_response(
        cls, message: str = "Error", error: dict[str, Any] | None = None
    ) -> "ResponseDTO[None]":
        """실패 응답 생성"""
        return cls(success=False, message=message, error=error)


# ==================== Pagination DTO ====================


class PaginationDTO(BaseDTO):
    """
    페이지네이션 요청 DTO

    Attributes:
        page: 페이지 번호 (1부터 시작)
        page_size: 페이지 크기
        sort_by: 정렬 기준 필드
        sort_order: 정렬 순서 (asc/desc)
    """

    page: int = Field(default=1, ge=1, description="페이지 번호 (1부터 시작)")
    page_size: int = Field(default=20, ge=1, le=100, description="페이지 크기")
    sort_by: str | None = Field(default=None, description="정렬 기준 필드")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$", description="정렬 순서")

    @property
    def offset(self) -> int:
        """오프셋 계산"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """리밋 반환"""
        return self.page_size


class PaginatedResponseDTO(BaseDTO, Generic[T]):
    """
    페이지네이션 응답 DTO

    Attributes:
        items: 데이터 목록
        total: 전체 레코드 수
        page: 현재 페이지
        page_size: 페이지 크기
        total_pages: 전체 페이지 수
        has_next: 다음 페이지 존재 여부
        has_prev: 이전 페이지 존재 여부
    """

    items: list[T] = Field(description="데이터 목록")
    total: int = Field(description="전체 레코드 수")
    page: int = Field(description="현재 페이지")
    page_size: int = Field(description="페이지 크기")
    total_pages: int = Field(description="전체 페이지 수")

    @property
    def has_next(self) -> bool:
        """다음 페이지 존재 여부"""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """이전 페이지 존재 여부"""
        return self.page > 1


# ==================== Timestamp DTO ====================


class TimestampDTO(BaseDTO):
    """
    타임스탬프 DTO

    Attributes:
        created_at: 생성 시각
        updated_at: 수정 시각
    """

    created_at: datetime = Field(description="생성 시각")
    updated_at: datetime = Field(description="수정 시각")


# ==================== ID DTO ====================


class IdResponseDTO(BaseDTO):
    """
    ID 응답 DTO

    생성/수정 작업 후 ID만 반환할 때 사용

    Attributes:
        id: 레코드 ID
    """

    id: int = Field(description="레코드 ID")


class IdsResponseDTO(BaseDTO):
    """
    다중 ID 응답 DTO

    일괄 작업 후 ID 목록 반환할 때 사용

    Attributes:
        ids: 레코드 ID 목록
        count: 처리된 레코드 수
    """

    ids: list[int] = Field(description="레코드 ID 목록")
    count: int = Field(description="처리된 레코드 수")


# ==================== Message DTO ====================


class MessageDTO(BaseDTO):
    """
    메시지 응답 DTO

    간단한 메시지만 반환할 때 사용

    Attributes:
        message: 메시지
    """

    message: str = Field(description="메시지")


# ==================== Count DTO ====================


class CountDTO(BaseDTO):
    """
    카운트 응답 DTO

    개수만 반환할 때 사용

    Attributes:
        count: 개수
    """

    count: int = Field(description="개수")


# ==================== Status DTO ====================


class StatusDTO(BaseDTO):
    """
    상태 응답 DTO

    상태 확인 응답

    Attributes:
        status: 상태 (healthy, unhealthy, degraded)
        timestamp: 확인 시각
        details: 상세 정보
    """

    status: str = Field(description="상태")
    timestamp: datetime = Field(default_factory=datetime.now, description="확인 시각")
    details: dict[str, Any] | None = Field(default=None, description="상세 정보")


# ==================== Error Detail DTO ====================


class ErrorDetailDTO(BaseDTO):
    """
    에러 상세 DTO

    Attributes:
        code: 에러 코드
        message: 에러 메시지
        field: 에러 발생 필드 (validation error)
        detail: 추가 상세 정보
    """

    code: str = Field(description="에러 코드")
    message: str = Field(description="에러 메시지")
    field: str | None = Field(default=None, description="에러 발생 필드")
    detail: dict[str, Any] | None = Field(default=None, description="추가 상세 정보")
