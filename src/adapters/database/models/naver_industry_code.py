# -*- coding: utf-8 -*-
"""Naver industry code mapping model.

- industry_code: 네이버 업종 코드 (숫자 문자열)
- industry_name: 업종명 (사람이 읽는 이름)

참고:
- industry_code는 네이버 모바일(stock) integration API의 industryCode와 동일.
- industry_name은 네이버금융 업종 상세 페이지 title 파싱으로 채움.
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class NaverIndustryCodeModel(Base, BaseModel):
    """업종코드 → 업종명 매핑 테이블"""

    __tablename__ = "naver_industry_codes"

    industry_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="네이버 업종 코드"
    )

    industry_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="업종명"
    )

    source_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="업종명 수집 원본 URL"
    )
