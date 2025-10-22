# -*- coding: utf-8 -*-
"""
Base Repository - 공통 Repository 및 Mixin 패턴

40% 코드 감소를 위한 재사용 가능한 CRUD 로직
"""

from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.connection import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Base Repository 클래스

    모든 Repository의 기본 CRUD 기능 제공
    """

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        """
        Args:
            model: SQLAlchemy 모델 클래스
            session: AsyncSession 인스턴스
        """
        self.model = model
        self.session = session

    # ==================== Create ====================

    async def create(self, **kwargs: Any) -> ModelType:
        """
        단일 레코드 생성

        Args:
            **kwargs: 모델 필드 값

        Returns:
            ModelType: 생성된 모델 인스턴스
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def create_many(self, items: list[dict[str, Any]]) -> list[ModelType]:
        """
        다중 레코드 생성

        Args:
            items: 모델 필드 딕셔너리 리스트

        Returns:
            list[ModelType]: 생성된 모델 인스턴스 리스트
        """
        instances = [self.model(**item) for item in items]
        self.session.add_all(instances)
        await self.session.flush()
        for instance in instances:
            await self.session.refresh(instance)
        return instances

    # ==================== Read ====================

    async def get_by_id(self, id: int) -> ModelType | None:
        """
        ID로 단일 레코드 조회

        Args:
            id: Primary Key

        Returns:
            ModelType | None: 조회된 모델 인스턴스 또는 None
        """
        return await self.session.get(self.model, id)

    async def get_one(self, **filters: Any) -> ModelType | None:
        """
        조건에 맞는 단일 레코드 조회

        Args:
            **filters: 필터 조건

        Returns:
            ModelType | None: 조회된 모델 인스턴스 또는 None
        """
        stmt = select(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many(
        self, limit: int = 100, offset: int = 0, **filters: Any
    ) -> Sequence[ModelType]:
        """
        조건에 맞는 다중 레코드 조회

        Args:
            limit: 최대 레코드 수
            offset: 시작 위치
            **filters: 필터 조건

        Returns:
            Sequence[ModelType]: 조회된 모델 인스턴스 리스트
        """
        stmt = select(self.model).filter_by(**filters).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_all(self) -> Sequence[ModelType]:
        """
        전체 레코드 조회

        Returns:
            Sequence[ModelType]: 전체 모델 인스턴스 리스트
        """
        stmt = select(self.model)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ==================== Update ====================

    async def update_by_id(self, id: int, **kwargs: Any) -> ModelType | None:
        """
        ID로 레코드 업데이트

        Args:
            id: Primary Key
            **kwargs: 업데이트할 필드 값

        Returns:
            ModelType | None: 업데이트된 모델 인스턴스 또는 None
        """
        instance = await self.get_by_id(id)
        if instance:
            for key, value in kwargs.items():
                setattr(instance, key, value)
            await self.session.flush()
            await self.session.refresh(instance)
        return instance

    async def update_many(self, filters: dict[str, Any], **kwargs: Any) -> int:
        """
        조건에 맞는 다중 레코드 업데이트

        Args:
            filters: 필터 조건
            **kwargs: 업데이트할 필드 값

        Returns:
            int: 업데이트된 레코드 수
        """
        stmt = update(self.model).filter_by(**filters).values(**kwargs)
        result = await self.session.execute(stmt)
        return result.rowcount

    # ==================== Delete ====================

    async def delete_by_id(self, id: int) -> bool:
        """
        ID로 레코드 삭제

        Args:
            id: Primary Key

        Returns:
            bool: 삭제 성공 여부
        """
        instance = await self.get_by_id(id)
        if instance:
            await self.session.delete(instance)
            await self.session.flush()
            return True
        return False

    async def delete_many(self, **filters: Any) -> int:
        """
        조건에 맞는 다중 레코드 삭제

        Args:
            **filters: 필터 조건

        Returns:
            int: 삭제된 레코드 수
        """
        stmt = delete(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.rowcount

    # ==================== Count ====================

    async def count(self, **filters: Any) -> int:
        """
        조건에 맞는 레코드 수 카운트

        Args:
            **filters: 필터 조건

        Returns:
            int: 레코드 수
        """
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ==================== Exists ====================

    async def exists(self, **filters: Any) -> bool:
        """
        조건에 맞는 레코드 존재 여부

        Args:
            **filters: 필터 조건

        Returns:
            bool: 존재 여부
        """
        count = await self.count(**filters)
        return count > 0


# ==================== Mixin Classes ====================


class SearchableMixin:
    """검색 기능 Mixin"""

    async def search(
        self: BaseRepository[ModelType],
        query_stmt: Select[tuple[ModelType]],
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelType]:
        """
        커스텀 쿼리 실행

        Args:
            query_stmt: SQLAlchemy Select 문
            limit: 최대 레코드 수
            offset: 시작 위치

        Returns:
            Sequence[ModelType]: 조회된 모델 인스턴스 리스트
        """
        stmt = query_stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PaginationMixin:
    """페이지네이션 Mixin"""

    async def paginate(
        self: BaseRepository[ModelType],
        page: int = 1,
        page_size: int = 20,
        **filters: Any,
    ) -> dict[str, Any]:
        """
        페이지네이션 조회

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 크기
            **filters: 필터 조건

        Returns:
            dict: 페이지네이션 결과
                - items: 조회된 데이터
                - total: 전체 레코드 수
                - page: 현재 페이지
                - page_size: 페이지 크기
                - total_pages: 전체 페이지 수
        """
        offset = (page - 1) * page_size
        items = await self.get_many(limit=page_size, offset=offset, **filters)
        total = await self.count(**filters)
        total_pages = (total + page_size - 1) // page_size

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }


class StatsMixin:
    """통계 기능 Mixin"""

    async def aggregate(
        self: BaseRepository[ModelType], column: str, func_name: str = "sum", **filters: Any
    ) -> Any:
        """
        집계 함수 실행

        Args:
            column: 집계할 컬럼명
            func_name: 집계 함수 ('sum', 'avg', 'min', 'max', 'count')
            **filters: 필터 조건

        Returns:
            Any: 집계 결과
        """
        agg_func = getattr(func, func_name)
        col = getattr(self.model, column)
        stmt = select(agg_func(col)).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one()
