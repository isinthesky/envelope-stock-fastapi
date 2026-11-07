# -*- coding: utf-8 -*-
"""
Admin Auth DTO - 관리자 로그인/세션 데이터 전송 객체
"""

from datetime import datetime

from pydantic import Field

from src.application.common.dto import BaseDTO


class AdminLoginRequestDTO(BaseDTO):
    """관리자 로그인 요청"""

    username: str = Field(min_length=1, max_length=64, description="아이디")
    password: str = Field(min_length=1, max_length=256, description="비밀번호")


class AdminSessionDTO(BaseDTO):
    """관리자 세션 정보 (토큰 자체는 포함하지 않는다)"""

    username: str = Field(description="로그인 아이디")
    created_at: datetime = Field(description="세션 생성 시각(UTC)")
    expires_at: datetime = Field(description="세션 만료 시각(UTC)")


class AdminLoginResultDTO(BaseDTO):
    """로그인 결과 - token은 쿠키로만 내려가고 응답 본문에는 싣지 않는다"""

    token: str = Field(description="세션 토큰(원문)")
    session: AdminSessionDTO = Field(description="세션 정보")
