# -*- coding: utf-8 -*-
"""
Base Repository - 공통 Repository 및 Mixin 패턴

40% 코드 감소를 위한 재사용 가능한 CRUD 로직

세션 계약 (2026-01-14 업데이트):
- 새 패턴: 생성자에서 session 받지 않고, 메서드 파라미터로 전달
- 기존 패턴: 하위 호환을 위해 생성자에서 session 받는 것도 지원
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

    세션 계약:
    - 새 패턴: __init__에서 session 없이 생성, 메서드에서 session 파라미터로 전달
    - 기존 패턴: __init__에서 session 전달 (하위 호환)
    """

    def __init__(self, model: type[ModelType], session: AsyncSession | None = None) -> None:
        """
        Args:
            model: SQLAlchemy 모델 클래스
            session: AsyncSession 인스턴스 (선택적, 새 패턴에서는 None)
        """
        self.model = model
        self._session = session

    def _get_session(self, session: AsyncSession | None = None) -> AsyncSession:
        """
        세션 획득 헬퍼

        Args:
            session: 메서드 파라미터로 전달된 세션

        Returns:
            AsyncSession: 사용할 세션

        Raises:
            ValueError: 세션이 없는 경우
        """
        resolved_session = session or self._session
        if resolved_session is None:
            raise ValueError(
                "Session required: pass session parameter or initialize with session"
            )
        return resolved_session

    # 하위 호환을 위한 session property
    @property
    def session(self) -> AsyncSession:
        """기존 코드 호환을 위한 session 접근자 (deprecated)"""
        if self._session is None:
            raise ValueError("Session not initialized. Use new pattern with session parameter.")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        """session 설정 (deprecated)"""
        self._session = value

    # ==================== Create ====================

    async def create(
        self, session: AsyncSession | None = None, **kwargs: Any
    ) -> ModelType:
        """
        단일 레코드 생성

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **kwargs: 모델 필드 값

        Returns:
            ModelType: 생성된 모델 인스턴스
        """
        db = self._get_session(session)
        instance = self.model(**kwargs)
        db.add(instance)
        await db.flush()
        await db.refresh(instance)
        return instance

    async def create_many(
        self, items: list[dict[str, Any]], session: AsyncSession | None = None
    ) -> list[ModelType]:
        """
        다중 레코드 생성

        Args:
            items: 모델 필드 딕셔너리 리스트
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            list[ModelType]: 생성된 모델 인스턴스 리스트
        """
        db = self._get_session(session)
        instances = [self.model(**item) for item in items]
        db.add_all(instances)
        await db.flush()
        for instance in instances:
            await db.refresh(instance)
        return instances

    # ==================== Read ====================

    async def get_by_id(
        self, id: int, session: AsyncSession | None = None
    ) -> ModelType | None:
        """
        ID로 단일 레코드 조회

        Args:
            id: Primary Key
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            ModelType | None: 조회된 모델 인스턴스 또는 None
        """
        db = self._get_session(session)
        return await db.get(self.model, id)

    async def get_one(
        self, session: AsyncSession | None = None, **filters: Any
    ) -> ModelType | None:
        """
        조건에 맞는 단일 레코드 조회

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            ModelType | None: 조회된 모델 인스턴스 또는 None
        """
        db = self._get_session(session)
        stmt = select(self.model).filter_by(**filters)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many(
        self,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
        **filters: Any,
    ) -> Sequence[ModelType]:
        """
        조건에 맞는 다중 레코드 조회

        Args:
            limit: 최대 레코드 수
            offset: 시작 위치
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            Sequence[ModelType]: 조회된 모델 인스턴스 리스트
        """
        db = self._get_session(session)
        stmt = select(self.model).filter_by(**filters).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_all(self, session: AsyncSession | None = None) -> Sequence[ModelType]:
        """
        전체 레코드 조회

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            Sequence[ModelType]: 전체 모델 인스턴스 리스트
        """
        db = self._get_session(session)
        stmt = select(self.model)
        result = await db.execute(stmt)
        return result.scalars().all()

    # ==================== Update ====================

    async def update_by_id(
        self, id: int, session: AsyncSession | None = None, **kwargs: Any
    ) -> ModelType | None:
        """
        ID로 레코드 업데이트

        Args:
            id: Primary Key
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **kwargs: 업데이트할 필드 값

        Returns:
            ModelType | None: 업데이트된 모델 인스턴스 또는 None
        """
        db = self._get_session(session)
        instance = await self.get_by_id(id, session=db)
        if instance:
            for key, value in kwargs.items():
                setattr(instance, key, value)
            await db.flush()
            await db.refresh(instance)
        return instance

    async def update_many(
        self,
        filters: dict[str, Any],
        session: AsyncSession | None = None,
        **kwargs: Any,
    ) -> int:
        """
        조건에 맞는 다중 레코드 업데이트

        Args:
            filters: 필터 조건
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **kwargs: 업데이트할 필드 값

        Returns:
            int: 업데이트된 레코드 수
        """
        db = self._get_session(session)
        stmt = update(self.model).filter_by(**filters).values(**kwargs)
        result = await db.execute(stmt)
        return result.rowcount

    # ==================== Delete ====================

    async def delete_by_id(
        self, id: int, session: AsyncSession | None = None
    ) -> bool:
        """
        ID로 레코드 삭제

        Args:
            id: Primary Key
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            bool: 삭제 성공 여부
        """
        db = self._get_session(session)
        instance = await self.get_by_id(id, session=db)
        if instance:
            await db.delete(instance)
            await db.flush()
            return True
        return False

    async def delete_many(
        self, session: AsyncSession | None = None, **filters: Any
    ) -> int:
        """
        조건에 맞는 다중 레코드 삭제

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            int: 삭제된 레코드 수
        """
        db = self._get_session(session)
        stmt = delete(self.model).filter_by(**filters)
        result = await db.execute(stmt)
        return result.rowcount

    # ==================== Count ====================

    async def count(self, session: AsyncSession | None = None, **filters: Any) -> int:
        """
        조건에 맞는 레코드 수 카운트

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            int: 레코드 수
        """
        db = self._get_session(session)
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        result = await db.execute(stmt)
        return result.scalar_one()

    # ==================== Exists ====================

    async def exists(
        self, session: AsyncSession | None = None, **filters: Any
    ) -> bool:
        """
        조건에 맞는 레코드 존재 여부

        Args:
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            bool: 존재 여부
        """
        cnt = await self.count(session=session, **filters)
        return cnt > 0


# ==================== Mixin Classes ====================


class SearchableMixin:
    """검색 기능 Mixin"""

    async def search(
        self: BaseRepository[ModelType],
        query_stmt: Select[tuple[ModelType]],
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[ModelType]:
        """
        커스텀 쿼리 실행

        Args:
            query_stmt: SQLAlchemy Select 문
            limit: 최대 레코드 수
            offset: 시작 위치
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            Sequence[ModelType]: 조회된 모델 인스턴스 리스트
        """
        db = self._get_session(session)
        stmt = query_stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()


class PaginationMixin:
    """페이지네이션 Mixin"""

    async def paginate(
        self: BaseRepository[ModelType],
        page: int = 1,
        page_size: int = 20,
        session: AsyncSession | None = None,
        **filters: Any,
    ) -> dict[str, Any]:
        """
        페이지네이션 조회

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 크기
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
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
        items = await self.get_many(limit=page_size, offset=offset, session=session, **filters)
        total = await self.count(session=session, **filters)
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
        self: BaseRepository[ModelType],
        column: str,
        func_name: str = "sum",
        session: AsyncSession | None = None,
        **filters: Any,
    ) -> Any:
        """
        집계 함수 실행

        Args:
            column: 집계할 컬럼명
            func_name: 집계 함수 ('sum', 'avg', 'min', 'max', 'count')
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)
            **filters: 필터 조건

        Returns:
            Any: 집계 결과
        """
        db = self._get_session(session)
        agg_func = getattr(func, func_name)
        col = getattr(self.model, column)
        stmt = select(agg_func(col)).filter_by(**filters)
        result = await db.execute(stmt)
        return result.scalar_one()
