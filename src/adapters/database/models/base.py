# -*- coding: utf-8 -*-
"""
Base Model - 공통 모델 Base 클래스 및 Mixin
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class TimestampMixin:
    """생성/수정 타임스탬프 Mixin"""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        """생성 시각"""
        return mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        """수정 시각"""
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )


class SoftDeleteMixin:
    """소프트 삭제 Mixin"""

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        """삭제 시각 (NULL = 미삭제)"""
        return mapped_column(DateTime(timezone=True), nullable=True, default=None)

    @property
    def is_deleted(self) -> bool:
        """삭제 여부"""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """소프트 삭제 실행"""
        self.deleted_at = datetime.now()

    def restore(self) -> None:
        """삭제 복원"""
        self.deleted_at = None


class BaseModel(TimestampMixin):
    """
    Base Model for all database models

    모든 모델은 이 클래스를 상속받아 created_at, updated_at 자동 포함
    """

    def to_dict(self) -> dict[str, Any]:
        """모델을 딕셔너리로 변환"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self) -> str:
        """모델 문자열 표현"""
        class_name = self.__class__.__name__
        attrs = ", ".join(
            f"{k}={v!r}"
            for k, v in self.to_dict().items()
            if k not in ("created_at", "updated_at")
        )
        return f"{class_name}({attrs})"
