# -*- coding: utf-8 -*-
"""
Access Log Model - 페이지 접근 로그 모델

외부 사용자의 페이지 접근 기록을 저장합니다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class AccessLogModel(Base, BaseModel):
    """
    페이지 접근 로그 모델

    외부 사용자의 접근 정보를 기록합니다.
    """

    __tablename__ = "access_logs"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 요청 정보 ====================
    method: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="HTTP 메서드 (GET, POST 등)"
    )

    path: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True, comment="요청 경로"
    )

    query_string: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="쿼리 스트링"
    )

    # ==================== 클라이언트 정보 ====================
    ip_address: Mapped[str] = mapped_column(
        String(45), nullable=False, index=True, comment="클라이언트 IP (IPv4/IPv6)"
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="User-Agent 헤더"
    )

    referer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Referer 헤더"
    )

    # ==================== 응답 정보 ====================
    status_code: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="HTTP 상태 코드"
    )

    response_time_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="응답 시간 (밀리초)"
    )

    # ==================== 메타데이터 ====================
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, comment="접근 시각"
    )

    # ==================== GeoIP 정보 (선택) ====================
    country: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="접속 국가"
    )

    city: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="접속 도시"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_access_logs_path_accessed", "path", "accessed_at"),
        Index("ix_access_logs_ip_accessed", "ip_address", "accessed_at"),
        Index("ix_access_logs_accessed_at_desc", "accessed_at", postgresql_using="btree"),
    )
