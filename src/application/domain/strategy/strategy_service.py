# -*- coding: utf-8 -*-
"""
Strategy Service - 전략 관리 서비스

전략 CRUD, 상태 관리, 유니버스 관리 등 핵심 기능 제공
매수/매도 분석은 별도 서비스로 위임

세션 계약 (2026-01-14 업데이트):
- Repository는 DI로 주입받고, session은 @transaction 데코레이터가 메서드에 주입
- 새 패턴: 생성자에서 Repository만 받고 session 받지 않음
- 기존 패턴: 하위 호환을 위해 생성자에서 session 받는 것도 지원
"""

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyStatus
from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.database.repositories.strategy_signal_repository import (
    StrategySignalRepository,
)
from src.adapters.database.repositories.strategy_symbol_state_repository import (
    StrategySymbolStateRepository,
)
from src.adapters.external.kis_api.client import get_kis_client
from src.application.common.decorators import transaction
from src.application.common.exceptions import NotFoundError, StrategyError
from src.application.domain.strategy.dto import (
    AnalysisHistoryCreateDTO,
    AnalysisHistoryDTO,
    AnalysisHistoryListDTO,
    AnalysisHistoryRefreshResultDTO,
    GoldenCrossConfigDTO,
    PortfolioCashActionDTO,
    PortfolioCashPlanDTO,
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
    GoldenCrossRecommendationDTO,
    IndustrySummaryDTO,
    PresetActivateRequestDTO,
    SELL_PHASE_INFO,
    SELL_STAGE_INFO,
    SellSignalAnalysisDTO,
    SignalListDTO,
    SignalStatisticsDTO,
    StrategyPresetDTO,
    StrategyPresetListDTO,
    StockUniverseItemDTO,
    StockUniverseListDTO,
    StrategyConfigDTO,
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyExecuteResultDTO,
    StrategyListResponseDTO,
    StrategySignalDTO,
    StrategyUpdateRequestDTO,
    SymbolStateDTO,
    SymbolStateListDTO,
)
from src.application.domain.strategy.symbol_validation import split_valid_symbol_pairs
from src.settings.config import settings

if TYPE_CHECKING:
    from src.adapters.database.repositories.analysis_history_repository import (
        AnalysisHistoryRepository,
    )


class StrategyService:
    """
    전략 서비스

    전략 생성, 조회, 수정, 삭제 및 실행 관리

    세션 계약:
    - 새 패턴: Repository를 DI로 주입, @transaction이 session 주입
    - 기존 패턴: session을 생성자에 전달 (하위 호환)
    """

    def __init__(
        self,
        strategy_repo: StrategyRepository | None = None,
        analysis_repo: "AnalysisHistoryRepository | None" = None,
        session: AsyncSession | None = None,
    ) -> None:
        """
        Args:
            strategy_repo: Strategy Repository (새 패턴: DI 주입)
            analysis_repo: Analysis History Repository (새 패턴: DI 주입)
            session: AsyncSession (기존 패턴: 하위 호환)
        """
        # 새 패턴: Repository가 DI로 주입된 경우
        if strategy_repo is not None:
            self.strategy_repo = strategy_repo
            self.analysis_repo = analysis_repo
            self._session = None
        # 기존 패턴: session으로 Repository 생성 (하위 호환)
        elif session is not None:
            self.strategy_repo = StrategyRepository(session)
            self.analysis_repo = None
            self._session = session
        else:
            # session 없이 생성 (나중에 @transaction으로 주입)
            self.strategy_repo = StrategyRepository()
            self.analysis_repo = None
            self._session = None

    # 하위 호환을 위한 session property
    @property
    def session(self) -> AsyncSession | None:
        """기존 코드 호환을 위한 session 접근자"""
        return self._session

    @session.setter
    def session(self, value: AsyncSession | None) -> None:
        """session 설정"""
        self._session = value

    # ==================== 프리셋 ====================

    def get_preset_list(self) -> StrategyPresetListDTO:
        """프리셋 목록 조회 (DB 불필요, 동기 메서드)"""
        from src.application.domain.strategy.presets import list_presets

        presets = list_presets()
        preset_dtos = [
            StrategyPresetDTO(
                preset_id=p.preset_id,
                name=p.name,
                description=p.description,
                strategy_type=p.strategy_type,
                tags=p.tags,
                risk_level=p.risk_level,
            )
            for p in presets
        ]
        return StrategyPresetListDTO(presets=preset_dtos, total_count=len(preset_dtos))

    async def activate_preset(
        self,
        preset_id: str,
        request: PresetActivateRequestDTO,
    ) -> StrategyDetailResponseDTO:
        """프리셋으로 전략 생성 (기존 create_strategy 재사용)"""
        from src.application.domain.strategy.presets import get_preset

        preset = get_preset(preset_id)
        if not preset:
            raise StrategyError(f"Preset not found: {preset_id}")

        # 심볼 결정: 요청에 없으면 유니버스 상위 eligible 종목 사용
        symbols = request.symbols
        if not symbols:
            universe = await self.get_stock_universe(eligible_only=True, limit=50)
            symbols = [s.symbol for s in universe.stocks]
            if not symbols:
                raise StrategyError("No eligible symbols found in universe")

        name = request.name_override or f"{preset.name} ({preset_id})"

        create_request = StrategyCreateRequestDTO(
            name=name,
            description=preset.description,
            strategy_type=preset.strategy_type,
            symbols=symbols,
            config=preset.config,
        )

        return await self.create_strategy(create_request)

    # ==================== 전략 생성 ====================

    @transaction
    async def create_strategy(
        self, session: AsyncSession, request: StrategyCreateRequestDTO
    ) -> StrategyDetailResponseDTO:
        """
        전략 생성

        Args:
            session: Database Session (@transaction이 주입)
            request: 전략 생성 요청

        Returns:
            StrategyDetailResponseDTO: 생성된 전략 정보
        """
        account_no = request.account_no or settings.current_kis_account_no

        # 전략명 중복 체크 (session을 메서드 파라미터로 전달)
        existing = await self.strategy_repo.get_by_name(
            request.name,
            account_no=account_no,
            session=session,
        )
        if existing:
            raise StrategyError(
                f"Strategy with name '{request.name}' already exists for account '{account_no}'"
            )

        # 종목 리스트 문자열 변환
        symbols_str = ",".join(request.symbols)

        # 설정 JSON 변환 (전략 유형에 따라 적절한 config 사용)
        if request.strategy_type == "golden_cross" and request.golden_cross_config:
            config_json = request.golden_cross_config.model_dump_json()
        elif request.config:
            config_json = request.config.model_dump_json()
        elif request.strategy_type == "golden_cross":
            # golden_cross인데 config가 없으면 기본값 사용
            config_json = GoldenCrossConfigDTO().model_dump_json()
        else:
            config_json = StrategyConfigDTO().model_dump_json()

        # 전략 생성 (session을 메서드 파라미터로 전달)
        strategy = await self.strategy_repo.create(
            session=session,
            name=request.name,
            description=request.description or "",
            strategy_type=request.strategy_type,
            account_no=account_no,
            symbols=symbols_str,
            config_json=config_json,
            status=StrategyStatus.PAUSED.value,
        )

        return self._to_detail_dto(strategy)

    # ==================== 전략 조회 ====================

    @transaction
    async def get_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """
        전략 상세 조회

        Args:
            session: Database Session (@transaction이 주입)
            strategy_id: 전략 ID

        Returns:
            StrategyDetailResponseDTO: 전략 상세 정보
        """
        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        return self._to_detail_dto(strategy)

    @transaction
    async def get_strategy_list(
        self,
        session: AsyncSession,
        account_no: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StrategyListResponseDTO:
        """
        전략 목록 조회

        Args:
            session: Database Session (@transaction이 주입)
            account_no: 계좌번호
            status: 전략 상태 필터
            limit: 조회 개수
            offset: 오프셋

        Returns:
            StrategyListResponseDTO: 전략 목록
        """
        account_no = account_no or settings.current_kis_account_no

        if status:
            try:
                status_enum = StrategyStatus(status)
            except ValueError:
                raise StrategyError(f"유효하지 않은 전략 상태: {status}")
            strategies = await self.strategy_repo.get_by_status(
                status_enum, account_no=account_no, limit=limit, offset=offset, session=session
            )
        else:
            strategies = await self.strategy_repo.get_by_account(
                account_no, limit=limit, offset=offset, session=session
            )

        strategy_list = [self._to_detail_dto(s) for s in strategies]

        total_count = await self.strategy_repo.count_by_account(
            account_no, status=StrategyStatus(status) if status else None, session=session
        )

        return StrategyListResponseDTO(strategies=strategy_list, total_count=total_count)

    # ==================== 전략 수정 ====================

    @transaction
    async def update_strategy(
        self, session: AsyncSession, strategy_id: int, request: StrategyUpdateRequestDTO
    ) -> StrategyDetailResponseDTO:
        """
        전략 수정

        Args:
            session: Database Session (@transaction이 주입)
            strategy_id: 전략 ID
            request: 전략 수정 요청

        Returns:
            StrategyDetailResponseDTO: 수정된 전략 정보
        """
        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        # 수정할 필드 준비
        update_data = {}
        if request.name:
            duplicate = await self.strategy_repo.get_by_name(
                request.name,
                account_no=strategy.account_no,
                session=session,
            )
            if duplicate and duplicate.id != strategy_id:
                raise StrategyError(
                    f"Strategy with name '{request.name}' already exists for account '{strategy.account_no}'"
                )
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.symbols:
            update_data["symbols"] = ",".join(request.symbols)
        # 전략 유형에 따라 적절한 config 사용
        if request.golden_cross_config:
            update_data["config_json"] = request.golden_cross_config.model_dump_json()
        elif request.config:
            update_data["config_json"] = request.config.model_dump_json()
        if request.status:
            update_data["status"] = request.status

        # 전략 업데이트 (session을 메서드 파라미터로 전달)
        await self.strategy_repo.update_by_id(strategy_id, session=session, **update_data)

        # 업데이트된 전략 조회
        updated_strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)
        if not updated_strategy:
            raise StrategyError("Failed to retrieve updated strategy")

        return self._to_detail_dto(updated_strategy)

    # ==================== 전략 삭제 ====================

    @transaction
    async def delete_strategy(self, session: AsyncSession, strategy_id: int) -> None:
        """
        전략 삭제 (Soft Delete)

        Args:
            session: Database Session (@transaction이 주입)
            strategy_id: 전략 ID
        """
        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        # 활성 상태 전략은 삭제 불가
        if strategy.is_active:
            raise StrategyError("Cannot delete active strategy. Stop it first.")

        await self.strategy_repo.soft_delete_by_id(strategy_id, session=session)

    # ==================== 전략 상태 관리 ====================

    @transaction
    async def start_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 시작 (활성화)"""
        await self.strategy_repo.activate_strategy(strategy_id, session=session)

        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    @transaction
    async def pause_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 일시정지"""
        await self.strategy_repo.pause_strategy(strategy_id, session=session)

        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    @transaction
    async def stop_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 중지"""
        await self.strategy_repo.stop_strategy(strategy_id, session=session)

        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    # ==================== Helper Methods ====================

    def _to_detail_dto(self, strategy) -> StrategyDetailResponseDTO:
        """Strategy Model을 DetailResponseDTO로 변환"""
        config_dict = json.loads(strategy.config_json)

        # 전략 유형에 따라 적절한 config 파싱
        config = None
        golden_cross_config = None

        if strategy.strategy_type == "golden_cross":
            try:
                golden_cross_config = GoldenCrossConfigDTO(**config_dict)
            except Exception:
                # 파싱 실패 시 기본값 사용
                golden_cross_config = GoldenCrossConfigDTO()
        else:
            try:
                config = StrategyConfigDTO(**config_dict)
            except Exception:
                config = StrategyConfigDTO()

        return StrategyDetailResponseDTO(
            id=strategy.id,
            name=strategy.name,
            description=strategy.description,
            strategy_type=strategy.strategy_type,
            account_no=strategy.account_no,
            symbols=strategy.symbol_list,
            status=strategy.status,
            config=config,
            golden_cross_config=golden_cross_config,
            total_executions=strategy.total_executions,
            successful_executions=strategy.successful_executions,
            failed_executions=strategy.failed_executions,
            success_rate=strategy.success_rate,
            last_executed_at=strategy.last_executed_at,
            started_at=strategy.started_at,
            stopped_at=strategy.stopped_at,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
        )

    # ==================== Golden Cross Strategy Methods ====================

    @transaction
    async def get_golden_cross_config(
        self, session: AsyncSession, strategy_id: int
    ) -> GoldenCrossConfigDTO:
        """골든크로스 전략 설정 조회"""
        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        try:
            config_dict = json.loads(strategy.config_json)
            return GoldenCrossConfigDTO(**config_dict)
        except Exception:
            return GoldenCrossConfigDTO()

    @transaction
    async def update_golden_cross_config(
        self,
        session: AsyncSession,
        strategy_id: int,
        config: GoldenCrossConfigDTO,
    ) -> GoldenCrossConfigDTO:
        """골든크로스 전략 설정 수정"""
        strategy = await self.strategy_repo.get_by_id(strategy_id, session=session)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        config_json = config.model_dump_json()
        await self.strategy_repo.update_by_id(strategy_id, session=session, config_json=config_json)

        return config

    @transaction
    async def get_symbol_states(
        self, session: AsyncSession, strategy_id: int
    ) -> SymbolStateListDTO:
        """종목별 상태 조회"""
        state_repo = StrategySymbolStateRepository(session)
        states = await state_repo.get_all_by_strategy(strategy_id)
        state_counts = await state_repo.count_by_state(strategy_id)

        state_dtos = [
            SymbolStateDTO(
                strategy_id=s.strategy_id,
                symbol=s.symbol,
                state=s.state,
                gc_date=s.gc_date,
                pullback_date=s.pullback_date,
                entry_date=s.entry_date,
                entry_price=s.entry_price,
                quantity=s.quantity,
                last_ma_short=s.last_ma_short,
                last_ma_long=s.last_ma_long,
                last_stoch_k=s.last_stoch_k,
                last_stoch_d=s.last_stoch_d,
                last_close=s.last_close,
                unrealized_pnl_ratio=s.unrealized_pnl_ratio,
                days_since_entry=s.days_since_entry,
                last_checked_at=s.last_checked_at,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in states
        ]

        return SymbolStateListDTO(
            states=state_dtos,
            total_count=len(state_dtos),
            state_counts=state_counts,
        )

    @transaction
    async def get_signals(
        self, session: AsyncSession, strategy_id: int, limit: int = 50, offset: int = 0
    ) -> SignalListDTO:
        """시그널 이력 조회"""
        signal_repo = StrategySignalRepository(session)
        signals = await signal_repo.get_by_strategy(strategy_id, limit, offset)

        signal_dtos = [
            StrategySignalDTO(
                id=s.id,
                strategy_id=s.strategy_id,
                symbol=s.symbol,
                signal_type=s.signal_type,
                signal_status=s.signal_status,
                signal_price=s.signal_price,
                target_quantity=s.target_quantity,
                executed_price=s.executed_price,
                executed_quantity=s.executed_quantity,
                exit_reason=s.exit_reason,
                realized_pnl=s.realized_pnl,
                realized_pnl_ratio=s.realized_pnl_ratio,
                ma_short=s.ma_short,
                ma_long=s.ma_long,
                stoch_k=s.stoch_k,
                stoch_d=s.stoch_d,
                prev_state=s.prev_state,
                new_state=s.new_state,
                note=s.note,
                signal_at=s.signal_at,
                executed_at=s.executed_at,
                created_at=s.created_at,
            )
            for s in signals
        ]

        return SignalListDTO(
            signals=signal_dtos,
            total_count=len(signal_dtos),
        )

    @transaction
    async def get_signal_statistics(
        self, session: AsyncSession, strategy_id: int, days: int = 30
    ) -> SignalStatisticsDTO:
        """시그널 통계 조회"""
        signal_repo = StrategySignalRepository(session)
        stats = await signal_repo.get_statistics(strategy_id, days)

        return SignalStatisticsDTO(**stats)

    async def execute_golden_cross(
        self, strategy_id: int, dry_run: bool = True, force: bool = False
    ) -> StrategyExecuteResultDTO:
        """골든크로스 전략 수동 실행 (스케줄러 사용, 별도 세션)"""
        from src.application.domain.strategy.scheduler import get_strategy_scheduler

        scheduler = get_strategy_scheduler()
        execution = await scheduler.execute_now(strategy_id, dry_run=dry_run, force=force)

        if not execution.get("success"):
            raise StrategyError(execution.get("error", "Execution failed"))

        return StrategyExecuteResultDTO(**execution["result"])

    # ==================== Stock Universe Methods ====================

    @transaction
    async def get_stock_universe(
        self,
        session: AsyncSession,
        market: str | None = None,
        eligible_only: bool = True,
        limit: int = 1000,
    ) -> StockUniverseListDTO:
        """종목 유니버스 조회"""
        universe_repo = StockUniverseRepository(session)

        market_type = MarketType(market) if market else None

        if eligible_only:
            stocks = await universe_repo.get_eligible_stocks(market=market_type, limit=limit)
        else:
            if market_type:
                stocks = await universe_repo.get_many(market=market_type.value, limit=limit)
            else:
                stocks = await universe_repo.get_many(limit=limit)

        stock_dtos = [
            StockUniverseItemDTO(
                symbol=s.symbol,
                name=s.name,
                market=s.market,
                sector=s.sector,
                market_cap=s.market_cap,
                avg_volume_20d=s.avg_volume_20d,
                current_price=s.current_price,
                is_eligible=s.is_eligible,
                screening_score=s.screening_score,
            )
            for s in stocks
        ]

        eligible_count = sum(1 for s in stocks if s.is_eligible)

        return StockUniverseListDTO(
            stocks=stock_dtos,
            total_count=len(stock_dtos),
            eligible_count=eligible_count,
        )

    @transaction
    async def refresh_universe(self, session: AsyncSession) -> dict:
        """유니버스 갱신 (B-1)

        - B-1: 기존 stock_universe에 존재하는 종목들을 대상으로
          (1) 현재가/거래량/시총 등 기본 데이터를 갱신하고
          (2) 스크리닝 재적용(passed_* / screening_score)까지 수행합니다.

        B-2는 "대상 종목 수 확대"로 대체: 상위 500개까지 갱신/스캔 대상으로 사용.
        """
        import asyncio
        from datetime import datetime
        from decimal import Decimal

        from src.adapters.cache.redis_client import get_redis_client
        from src.adapters.database.connection import AsyncSessionLocal
        from src.adapters.database.repositories.stock_universe_repository import (
            StockUniverseRepository,
        )
        from src.adapters.external.kis_api.client import get_kis_client
        from src.adapters.external.naver.stock_client import get_naver_stock_client
        from src.application.domain.market_data.service import MarketDataService
        from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader
        from src.application.domain.strategy.stock_screener import StockScreener
        from src.settings.config import settings

        universe_repo = StockUniverseRepository(session)

        # (B-2) 유니버스가 500 미만이면, KRX KIND 상장 목록에서 종목을 채워 넣어 500개까지 확장
        # - 최소 필드(symbol/name/market)만 채우고, 이후 아래 갱신 로직에서 시총/거래량/스크리닝을 업데이트
        from sqlalchemy import func, select
        from src.adapters.database.models.stock_universe import StockUniverseModel

        target_universe_size = 500
        seeded = 0

        count_res = await session.execute(
            select(func.count())
            .select_from(StockUniverseModel)
            .where(
                StockUniverseModel.is_active == True,
                StockUniverseModel.is_excluded == False,
            )
        )
        universe_size_before = int(count_res.scalar() or 0)

        if universe_size_before < target_universe_size:
            import re

            import httpx

            async def fetch_kind_corp_list(market_type: str) -> list[tuple[str, str]]:
                url = (
                    "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
                    f"&marketType={market_type}"
                )
                async with httpx.AsyncClient(
                    timeout=20.0,
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    html = resp.content.decode("euc-kr", errors="ignore")

                # <tr><td>회사명</td><td>종목코드</td> ... 형태
                pairs = re.findall(
                    r"<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>",
                    html,
                    flags=re.IGNORECASE,
                )

                items: list[tuple[str, str]] = []
                for name, code in pairs:
                    code = re.sub(r"\D", "", code or "")
                    if not code:
                        continue
                    items.append((code.zfill(6), (name or "").strip()))
                return items

            # 기존 심볼 set
            sym_res = await session.execute(select(StockUniverseModel.symbol))
            existing_symbols = set(sym_res.scalars().all())

            need = target_universe_size - universe_size_before
            rows: list[dict] = []

            # KOSPI 먼저 채우고, 부족하면 KOSDAQ로 채움
            for symbol, name in await fetch_kind_corp_list("stockMkt"):
                if symbol in existing_symbols:
                    continue
                rows.append({"symbol": symbol, "name": name, "market": MarketType.KOSPI.value})
                existing_symbols.add(symbol)
                if len(rows) >= need:
                    break

            if len(rows) < need:
                for symbol, name in await fetch_kind_corp_list("kosdaqMkt"):
                    if symbol in existing_symbols:
                        continue

                    rows.append({"symbol": symbol, "name": name, "market": MarketType.KOSDAQ.value})
                    existing_symbols.add(symbol)
                    if len(rows) >= need:
                        break

            if rows:
                # seed는 별도 세션에서 커밋해서 worker 세션에서도 즉시 보이게 함
                async with AsyncSessionLocal() as seed_session:
                    seed_repo = StockUniverseRepository(seed_session)
                    await seed_repo.create_many(rows, session=seed_session)
                    await seed_session.commit()
                seeded = len(rows)

                # 현재 세션에서 이후 조회가 최신 커밋을 볼 수 있도록 트랜잭션 스냅샷을 갱신
                # (refresh_universe는 이 시점에 쓰기 작업이 없으므로 rollback은 안전)
                await session.rollback()

        # 현재는 "활성 + 제외 아님" 종목 중 상위 500개를 갱신 대상으로 사용
        target_stocks = await universe_repo.get_active_stocks(limit=500, session=session)
        if not target_stocks:
            return {
                "success": False,
                "target": 0,
                "updated": 0,
                "screened": 0,
                "errors": ["No active stocks found in universe"],
                "refreshed_at": datetime.now().isoformat(),
            }

        kis_client = get_kis_client()
        redis_client = await get_redis_client()
        market_data_service = MarketDataService(kis_client, redis_client)
        naver_client = get_naver_stock_client()

        import logging, time

        logger = logging.getLogger(__name__)
        started_at = time.monotonic()

        # timeout은 대기 무한을 피하기 위한 운영 안전장치
        kis_timeout = float(getattr(settings, "kis_api_timeout", 10))
        naver_timeout = 10.0
        ohlcv_timeout = max(20.0, kis_timeout * 3)

        MAX_ERRORS = int(getattr(settings, "universe_refresh_error_list_limit", 50))
        warn_budget = int(getattr(settings, "universe_refresh_warn_budget", 50))
        overall_timeout = float(getattr(settings, "universe_refresh_timeout_seconds", 300))

        warning_counts = {"price": 0, "naver": 0, "ohlcv": 0}
        warning_suppressed = {"price": False, "naver": False, "ohlcv": False}

        def warn(category: str, msg: str) -> None:
            warning_counts[category] = warning_counts.get(category, 0) + 1
            if warn_budget <= 0:
                return
            if warning_counts[category] <= warn_budget:
                logger.warning(msg)
                return
            if not warning_suppressed.get(category, False):
                warning_suppressed[category] = True
                logger.warning(
                    f"[universe.refresh] {category} warnings suppressed (>{warn_budget})"
                )

        concurrency = max(1, min(settings.scan_concurrency_limit, 20))
        logger.info(
            f"[universe.refresh] start: target={len(target_stocks)} seeded={seeded} concurrency={concurrency}"
        )

        work_queue: asyncio.Queue[tuple[int, object]] = asyncio.Queue()
        for idx, stock in enumerate(target_stocks):
            work_queue.put_nowait((idx, stock))

        async def worker() -> tuple[int, int, int, list[str]]:
            updated = 0
            screened = 0
            error_count = 0
            errors: list[str] = []

            async with AsyncSessionLocal() as worker_session:
                screener = StockScreener(worker_session, kis_client)
                data_loader = OHLCVDataLoader(worker_session)

                while True:
                    try:
                        _idx, stock = work_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    symbol = getattr(stock, "symbol", None)
                    if not symbol:
                        work_queue.task_done()
                        continue

                    try:
                        # 1) 현재가/누적거래량
                        price = None
                        try:
                            price = await asyncio.wait_for(
                                market_data_service.get_current_price(symbol, use_cache=True),
                                timeout=kis_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("price", f"[universe.refresh] price fetch failed: {symbol}: {e}")

                        # 2) 시총/종목명 (네이버) — 실패해도 진행
                        fin = None
                        try:
                            fin = await asyncio.wait_for(
                                naver_client.get_stock_financial_data(symbol),
                                timeout=naver_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("naver", f"[universe.refresh] naver fetch failed: {symbol}: {e}")

                        # 3) OHLCV 캐시 최신화 + 20일 평균 거래량 계산
                        load = None
                        try:
                            load = await asyncio.wait_for(
                                data_loader.load_ohlcv_with_stats(
                                    symbol=symbol,
                                    days=60,
                                    interval="1d",
                                    min_candles=30,
                                    cache_freshness_days=3,
                                    force_refresh=False,
                                ),
                                timeout=ohlcv_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("ohlcv", f"[universe.refresh] ohlcv load failed: {symbol}: {e}")
                        df = load.df if load is not None else None

                        avg_vol_20d = None
                        if df is not None and not df.empty and len(df) >= 20:
                            avg_vol_20d = int(df["volume"].tail(20).mean())

                        # 4) stock_universe 기본 필드 업데이트
                        await screener.update_stock_data(
                            symbol=symbol,
                            name=(fin.name if fin and fin.name else getattr(stock, "name", None)),
                            market=getattr(stock, "market", None),
                            sector=getattr(stock, "sector", None),
                            industry=(
                                fin.industry_code
                                if fin and fin.industry_code
                                else getattr(stock, "industry", None)
                            ),
                            market_cap=(
                                Decimal(fin.market_cap)
                                if fin and fin.market_cap
                                else getattr(stock, "market_cap", None)
                            ),
                            avg_volume_20d=(
                                Decimal(avg_vol_20d)
                                if avg_vol_20d is not None
                                else getattr(stock, "avg_volume_20d", None)
                            ),
                            current_price=(
                                price.current_price
                                if price
                                else getattr(stock, "current_price", None)
                            ),
                        )
                        updated += 1

                        # 5) 스크리닝 재적용
                        passed = await screener.apply_screening(symbol)
                        if passed:
                            screened += 1

                        # commit (OHLCV 캐시 + stock_universe 업데이트 반영)
                        await worker_session.commit()

                    except asyncio.CancelledError:
                        await worker_session.rollback()
                        raise

                    except Exception as e:
                        await worker_session.rollback()
                        error_count += 1
                        logger.exception(f"[universe.refresh] worker failed: {symbol}")
                        if len(errors) < MAX_ERRORS:
                            errors.append(f"{symbol}: {type(e).__name__}: {e}")
                    finally:
                        work_queue.task_done()

            return updated, screened, error_count, errors

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]

        timed_out = False
        message = None
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*workers, return_exceptions=True),
                timeout=overall_timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            message = f"Global timeout after {overall_timeout}s"
            for t in workers:
                t.cancel()
            results = await asyncio.gather(*workers, return_exceptions=True)

        total_updated = 0
        total_screened = 0
        total_error_count = 0
        errors: list[str] = []
        for item in results:
            if isinstance(item, BaseException):
                total_error_count += 1
                logger.error("[universe.refresh] worker task crashed", exc_info=item)
                if len(errors) < MAX_ERRORS:
                    errors.append(str(item))
                continue
            u, s, ec, e = item
            total_updated += u
            total_screened += s
            total_error_count += ec
            if len(errors) < MAX_ERRORS:
                errors.extend(e[: max(0, MAX_ERRORS - len(errors))])

        elapsed = time.monotonic() - started_at
        logger.info(
            f"[universe.refresh] done: target={len(target_stocks)} updated={total_updated} screened={total_screened} errors={total_error_count} warnings={warning_counts} timed_out={timed_out} elapsed={elapsed:.1f}s"
        )

        return {
            "success": (not timed_out),
            "message": message,
            "timed_out": timed_out,
            "target": len(target_stocks),
            "updated": total_updated,
            "screened": total_screened,
            "seeded": seeded,
            "universe_size_before": universe_size_before,
            "universe_size_after": universe_size_before + seeded,
            "concurrency": concurrency,
            "error_count": total_error_count,
            "errors_truncated": total_error_count > len(errors),
            "errors": errors,
            "warning_counts": warning_counts,
            "refreshed_at": datetime.now().isoformat(),
        }

    # ==================== Buy/Sell Strategy Delegation ====================

    @transaction
    async def scan_golden_cross_candidates(
        self,
        session: AsyncSession,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        max_concurrent: int | None = None,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔 (BuyStrategyService로 위임)

        Args:
            session: Database Session (@transaction이 주입)
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            stoch_threshold: Stochastic 과매도 임계값
            gc_only: 골든크로스 활성 종목만 반환
            include_etf: ETF 종목 포함 여부 (기본 True)
            max_concurrent: 스캔 동시 처리 수 (None이면 설정값 사용)
        """
        from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

        buy_service = BuyStrategyService(session=session)
        return await buy_service.scan_golden_cross_candidates(
            market=market,
            stoch_threshold=stoch_threshold,
            gc_only=gc_only,
            include_etf=include_etf,
            limit=limit,
            max_concurrent=max_concurrent,
        )

    @transaction
    async def get_golden_cross_recommendations(
        self,
        session: AsyncSession,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        max_concurrent: int | None = None,
        top_n: int = 5,
        top_industries_n: int = 3,
        target_states: list[str] | None = None,
        min_recommendation_score: float = 0.0,
        apply_financial_filter: bool = False,
        financial_filter_max_concurrent: int = 3,
    ) -> GoldenCrossRecommendationDTO:
        """골든크로스 추천 요약 (Top 종목 + Top 업종)

        - Top 종목: 대상 상태 후보 중 추천 점수 상위 N개
        - Top 업종: 대상 상태 후보에서 업종별 count 상위 N개
        """
        from collections import Counter

        from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

        buy_service = BuyStrategyService(session=session)
        if target_states is None:
            target_states = ["OPTIMAL_BUY"]
            # [#2/#3] fear-buy 알림 opt-in: 켜져 있으면 FEAR_BUY 후보도 추천/알림에 포함
            if getattr(settings, "fear_buy_notify_enabled", False) and getattr(
                settings, "fear_buy_window_enabled", False
            ):
                target_states = target_states + ["FEAR_BUY"]
        target_states = self._validate_recommendation_target_states(target_states)
        target_state_set = set(target_states)

        scan = await buy_service.scan_golden_cross_candidates(
            market=market,
            stoch_threshold=stoch_threshold,
            gc_only=gc_only,
            include_etf=include_etf,
            limit=limit,
            max_concurrent=max_concurrent,
        )
        financial_filter_applied = False
        if apply_financial_filter:
            scan_before_financial_filter = scan
            try:
                scan = await buy_service.apply_financial_filter(
                    scan,
                    target_states=target_states,
                    max_concurrent=financial_filter_max_concurrent,
                )
                if self._financial_filter_has_any_success(scan, target_state_set):
                    financial_filter_applied = True
                else:
                    errors = list(scan_before_financial_filter.errors)
                    errors.append(
                        "Financial filter skipped: all target financial screenings failed"
                    )
                    scan = scan_before_financial_filter.model_copy(update={"errors": errors})
            except Exception as exc:
                errors = list(scan_before_financial_filter.errors)
                errors.append(f"Financial filter skipped: {exc}")
                scan = scan_before_financial_filter.model_copy(update={"errors": errors})

        explained_stocks = [
            self._attach_recommendation_explainability(
                stock,
                target_state_set=target_state_set,
                min_recommendation_score=min_recommendation_score,
                financial_filter_applied=financial_filter_applied,
            )
            for stock in scan.stocks
        ]
        candidates = [
            stock
            for stock in explained_stocks
            if stock.gc_state in target_state_set
            and float(stock.recommendation_score or 0) >= min_recommendation_score
            and self._passes_recommendation_financial_filter(
                stock,
                financial_filter_applied=financial_filter_applied,
            )
        ]
        candidates.sort(
            key=lambda s: (
                -float(s.recommendation_score or 0),
                self._recommendation_state_rank(s.gc_state),
                s.symbol,
            )
        )
        top_stocks = candidates[:top_n]

        counter: Counter[str] = Counter([s.industry_code for s in candidates if s.industry_code])

        # code -> name (이미 scan 단계에서 industry_name attach 됨)
        code_to_name: dict[str, str | None] = {}
        for s in candidates:
            if s.industry_code and s.industry_code not in code_to_name:
                code_to_name[s.industry_code] = s.industry_name

        top_industries: list[IndustrySummaryDTO] = []
        for code, cnt in counter.most_common(top_industries_n):
            top_industries.append(
                IndustrySummaryDTO(
                    industry_code=code,
                    industry_name=code_to_name.get(code),
                    count=cnt,
                )
            )

        return GoldenCrossRecommendationDTO(
            top_stocks=top_stocks,
            top_industries=top_industries,
            buy_candidate_count=len(candidates),
            scan_time=scan.scan_time,
            errors=scan.errors,
            candidate_state_counts=dict(Counter(stock.gc_state for stock in candidates)),
            selected_state_counts=dict(Counter(stock.gc_state for stock in top_stocks)),
            financial_status_counts=dict(
                Counter(str(stock.financial_filter_status or "NOT_CHECKED") for stock in candidates)
            ),
            excluded_count=len(explained_stocks) - len(candidates),
            selection_criteria=[
                f"target_states={','.join(target_states)}",
                f"min_recommendation_score={min_recommendation_score:.1f}",
                (
                    "score = signal stage + screening score + MA gap health + "
                    "Stoch recovery + financial status"
                ),
                (
                    "financial_filter="
                    f"{'applied' if financial_filter_applied else 'requested_failed' if apply_financial_filter else 'disabled'}"
                ),
            ],
        )

    @staticmethod
    def _validate_recommendation_target_states(target_states: list[str]) -> list[str]:
        allowed_states = {
            "OPTIMAL_BUY",
            "BUY_INTEREST",
            "READY_TO_BUY",
            "WAITING_FOR_PULLBACK",
            "GC_ACTIVE",
            "NOT_GC",
            "FEAR_BUY",
        }
        invalid = sorted(set(target_states) - allowed_states)
        if invalid:
            raise StrategyError(
                "Invalid target_states: "
                f"{', '.join(invalid)}. Allowed: {', '.join(sorted(allowed_states))}"
            )
        return target_states

    @staticmethod
    def _recommendation_state_rank(gc_state: str) -> int:
        return {
            "OPTIMAL_BUY": 0,
            "FEAR_BUY": 1,
            "BUY_INTEREST": 2,
            "READY_TO_BUY": 3,
            "WAITING_FOR_PULLBACK": 4,
            "GC_ACTIVE": 5,
            "NOT_GC": 6,
        }.get(gc_state, 99)

    @staticmethod
    def _passes_recommendation_financial_filter(
        stock: GoldenCrossScanItemDTO,
        *,
        financial_filter_applied: bool,
    ) -> bool:
        if not financial_filter_applied:
            return True
        return stock.financial_filter_status in {"PASS", "TURNAROUND"}

    @staticmethod
    def _financial_filter_has_any_success(
        scan: GoldenCrossScanListDTO,
        target_state_set: set[str],
    ) -> bool:
        return any(
            stock.gc_state in target_state_set
            and stock.financial_filter_status in {"PASS", "TURNAROUND", "FAIL"}
            for stock in scan.stocks
        )

    def _attach_recommendation_explainability(
        self,
        stock: GoldenCrossScanItemDTO,
        *,
        target_state_set: set[str],
        min_recommendation_score: float,
        financial_filter_applied: bool = False,
    ) -> GoldenCrossScanItemDTO:
        score, reasons, filter_reasons = self._score_recommendation_candidate(stock)
        if stock.gc_state not in target_state_set:
            filter_reasons.append(f"대상 상태 제외 ({stock.gc_state})")
        if score < min_recommendation_score:
            filter_reasons.append(f"추천 점수 미달 ({score:.1f} < {min_recommendation_score:.1f})")
        if financial_filter_applied and stock.financial_filter_status not in {"PASS", "TURNAROUND"}:
            status = stock.financial_filter_status or "NOT_CHECKED"
            reason = f"재무 필터 제외 ({status})"
            if reason not in filter_reasons:
                filter_reasons.append(reason)
        return stock.model_copy(
            update={
                "recommendation_score": round(score, 2),
                "recommendation_reasons": reasons,
                "filter_reasons": filter_reasons,
            }
        )

    def _score_recommendation_candidate(
        self,
        stock: GoldenCrossScanItemDTO,
    ) -> tuple[float, list[str], list[str]]:
        reasons: list[str] = []
        filter_reasons: list[str] = []
        score = 0.0

        state_score = {
            "OPTIMAL_BUY": 55.0,
            "BUY_INTEREST": 42.0,
            "READY_TO_BUY": 32.0,
            "WAITING_FOR_PULLBACK": 16.0,
            "GC_ACTIVE": 8.0,
        }.get(stock.gc_state, 0.0)
        score += state_score
        if state_score:
            reasons.append(f"{stock.gc_state} 신호 단계 ({state_score:.0f}점)")

        screening = float(stock.screening_score or 0)
        screening_score = min(max(screening, 0.0), 100.0) * 0.2
        score += screening_score
        if screening_score:
            reasons.append(f"스크리닝 점수 반영 ({screening:.1f})")

        if 0 <= stock.ma_gap_ratio <= 8:
            score += 10.0
            reasons.append(f"MA 갭 건강 ({stock.ma_gap_ratio:.1f}%)")
        elif stock.ma_gap_ratio > 12:
            filter_reasons.append(f"MA 갭 과대 ({stock.ma_gap_ratio:.1f}%)")

        if stock.stoch_k >= 30 and stock.stoch_k > stock.stoch_d:
            score += 10.0
            reasons.append(f"Stoch 회복 우위 (K={stock.stoch_k:.1f} > D={stock.stoch_d:.1f})")
        elif stock.stoch_k < 30:
            reasons.append(f"과매도 관찰 구간 (K={stock.stoch_k:.1f})")

        financial_status = stock.financial_filter_status
        if financial_status == "PASS":
            score += 8.0
            reasons.append("재무 필터 통과")
        elif financial_status == "TURNAROUND":
            score += 5.0
            reasons.append("턴어라운드 후보")
        elif financial_status == "FAIL":
            score -= 12.0
            filter_reasons.append("재무 필터 미통과")
        elif financial_status == "ERROR":
            score -= 4.0
            filter_reasons.append("재무 데이터 확인 실패")
        elif financial_status == "PENDING":
            filter_reasons.append("재무 필터 미조회")

        return max(score, 0.0), reasons, filter_reasons

    @transaction
    async def analyze_sell_signal(
        self,
        session: AsyncSession,
        symbol: str,
        stoch_overbought: float = 70.0,
        rsi_overbought: float = 70.0,
        entry_price: float | None = None,
        highest_price: float | None = None,
        trailing_stop_activated: bool = False,
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석 (SellStrategyService로 위임)

        Args:
            session: Database Session (@transaction이 주입)
            symbol: 종목코드
            stoch_overbought: Stochastic 과매수 임계값
            rsi_overbought: RSI 과매수 임계값
            entry_price: 진입가 (수익률 기반 동적 임계값 적용)
            highest_price: 포지션 최고가 (트레일링 스탑용)
            trailing_stop_activated: 트레일링 스탑 활성화 여부
        """
        from src.application.domain.strategy.sell_strategy_service import SellStrategyService

        sell_service = SellStrategyService(session)
        return await sell_service.analyze_sell_signal(
            symbol=symbol,
            stoch_overbought=stoch_overbought,
            rsi_overbought=rsi_overbought,
            entry_price=entry_price,
            highest_price=highest_price,
            trailing_stop_activated=trailing_stop_activated,
        )

    # ==================== Analysis History Methods ====================

    @transaction
    async def save_analysis_history(
        self, session: AsyncSession, dto: AnalysisHistoryCreateDTO
    ) -> AnalysisHistoryDTO:
        """분석 이력 저장"""
        history_repo = self._get_analysis_repo(session)

        # sell_reasons를 JSON 문자열로 변환
        sell_reasons_json = None
        if dto.sell_reasons:
            sell_reasons_json = json.dumps(dto.sell_reasons, ensure_ascii=False)

        model = await history_repo.create(
            session=session,
            analysis_type=dto.analysis_type,
            symbol=dto.symbol,
            name=dto.name,
            current_price=dto.current_price,
            ma_short=dto.ma_short,
            ma_long=dto.ma_long,
            ma_gap_ratio=dto.ma_gap_ratio,
            stoch_k=dto.stoch_k,
            stoch_d=dto.stoch_d,
            gc_state=dto.gc_state,
            is_gc_active=dto.is_gc_active,
            rsi=dto.rsi,
            is_death_cross=dto.is_death_cross,
            is_stoch_overbought=dto.is_stoch_overbought,
            is_rsi_overbought=dto.is_rsi_overbought,
            sell_phase=dto.sell_phase,
            sell_reasons=sell_reasons_json,
            analyzed_at=datetime.now(),
            entry_price=dto.entry_price,
            note=dto.note,
            is_active=dto.is_active if dto.is_active is not None else True,
            candle_count=dto.candle_count,
        )

        return self._history_to_dto(model)

    @transaction
    async def get_analysis_history(
        self, session: AsyncSession, history_id: int
    ) -> AnalysisHistoryDTO:
        """분석 이력 상세 조회"""
        history_repo = self._get_analysis_repo(session)
        model = await history_repo.get_by_id(history_id, session=session)

        if not model:
            raise NotFoundError(f"Analysis history not found: {history_id}")

        return self._history_to_dto(model)

    @transaction
    async def list_analysis_history(
        self,
        session: AsyncSession,
        analysis_type: str,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnalysisHistoryListDTO:
        """분석 이력 목록 조회"""
        history_repo = self._get_analysis_repo(session)
        histories = await history_repo.get_by_type(
            analysis_type=analysis_type,
            is_active=is_active,
            limit=limit,
            offset=offset,
            session=session,
        )
        total_count = await history_repo.count_by_type(analysis_type, is_active, session=session)

        items = [self._history_to_dto(h) for h in histories]

        return AnalysisHistoryListDTO(
            items=items,
            total_count=total_count,
        )

    @transaction
    async def delete_analysis_history(self, session: AsyncSession, history_id: int) -> bool:
        """분석 이력 삭제"""
        history_repo = self._get_analysis_repo(session)
        return await history_repo.delete_by_id(history_id, session=session)

    @transaction
    async def set_analysis_history_active(
        self, session: AsyncSession, history_id: int, is_active: bool
    ) -> AnalysisHistoryDTO:
        """분석 이력 활성 추적 상태 변경"""
        history_repo = self._get_analysis_repo(session)
        updated = await history_repo.set_active(history_id, is_active, session=session)
        if not updated:
            raise NotFoundError(f"Analysis history not found: {history_id}")
        return self._history_to_dto(updated)

    @transaction
    async def update_analysis_history(
        self,
        session: AsyncSession,
        history_id: int,
        entry_price: Decimal | None = None,
        note: str | None = None,
    ) -> AnalysisHistoryDTO:
        """분석 이력 업데이트 (진입가, 메모)"""
        history_repo = self._get_analysis_repo(session)

        # 기존 레코드 확인
        existing = await history_repo.get_by_id(history_id, session=session)
        if not existing:
            raise NotFoundError(f"Analysis history not found: {history_id}")

        # 업데이트할 필드 준비
        update_kwargs = {}
        if entry_price is not None:
            update_kwargs["entry_price"] = entry_price
        if note is not None:
            update_kwargs["note"] = note

        if update_kwargs:
            await history_repo.update_by_id(history_id, session=session, **update_kwargs)

        # 업데이트된 레코드 반환
        updated = await history_repo.get_by_id(history_id, session=session)
        return self._history_to_dto(updated)

    def _get_analysis_repo(self, session: AsyncSession):
        """Analysis History Repository 획득 헬퍼"""
        if self.analysis_repo is not None:
            return self.analysis_repo
        # DI로 주입되지 않은 경우 임시 생성
        from src.adapters.database.repositories.analysis_history_repository import (
            AnalysisHistoryRepository,
        )

        return AnalysisHistoryRepository(session)

    def build_portfolio_cash_plan(
        self,
        histories: list,
        *,
        target_cash_ratio: float = 0.30,
        current_cash_ratio: float | None = None,
    ) -> PortfolioCashPlanDTO:
        """활성 매도 분석 이력 기준 사전 현금화 계획 생성"""
        from src.application.domain.strategy.sell_strategy_service import SellStrategyService

        scored_actions: list[PortfolioCashActionDTO] = []
        total_score = 0.0
        winner_priority_count = 0

        for item in histories:
            sell_stage = getattr(item, "sell_stage", None) or "HOLD"
            final_stage = getattr(item, "final_stage", None) or sell_stage
            if hasattr(final_stage, "value"):
                final_stage = final_stage.value
            sell_reasons = getattr(item, "sell_reasons", None) or []
            if isinstance(sell_reasons, str):
                try:
                    sell_reasons = json.loads(sell_reasons)
                except json.JSONDecodeError:
                    sell_reasons = [sell_reasons]

            volume_ratio = float(getattr(item, "volume_ratio", 0.0) or 0.0)
            market = getattr(item, "market", None)
            instrument_profile = SellStrategyService.infer_instrument_profile(
                getattr(item, "symbol", ""),
                name=getattr(item, "name", None),
                market=market,
            )
            profit_ratio = None
            entry_price = getattr(item, "entry_price", None)
            current_price = getattr(item, "current_price", None)
            if entry_price and current_price:
                try:
                    profit_ratio = float((current_price - entry_price) / entry_price)
                except Exception:
                    profit_ratio = None

            score = 0.0
            reasons = list(sell_reasons)
            if final_stage == "REDUCE_1":
                score += 35
            elif final_stage == "REDUCE_2":
                score += 60
            elif final_stage == "EXIT_ALL":
                score += 90

            if getattr(item, "is_death_cross", False):
                score += 20
                reasons.append("데드크로스 진행")
            if getattr(item, "is_volume_sell_signal", False):
                score += 15
                reasons.append("거래량 매도 신호")
            if getattr(item, "is_volume_spike", False) and volume_ratio >= 1.3:
                score += 10
                reasons.append(f"거래량 급증 {volume_ratio:.2f}배")
            if getattr(item, "overbought_sell_blocked", False):
                score -= 10
                reasons.append("강한 상승 추세로 과매수 매도 차단")
            if profit_ratio is not None and profit_ratio >= 0.15:
                score += 25
                reasons.append("수익 보호 우선 현금화 구간 (+15%)")
            elif profit_ratio is not None and profit_ratio >= 0.08:
                score += 18
                reasons.append("수익 구간에서 선제 현금화 유리")
            elif profit_ratio is not None and profit_ratio > 0:
                score += 8
                reasons.append("소폭 수익 구간")
            if profit_ratio is not None and profit_ratio <= -0.05:
                score += 10
                reasons.append("손실 확대 전 리스크 축소 필요")
            if (
                profit_ratio is not None
                and profit_ratio > 0
                and final_stage in {"REDUCE_1", "REDUCE_2", "EXIT_ALL"}
            ):
                winner_priority_count += 1
                score += 15
                reasons.append("현금 확보는 수익 종목 우선")
            if instrument_profile["is_etf_like"] and final_stage in {"REDUCE_1", "REDUCE_2"}:
                score += 8
                reasons.append("ETF/레버리지 계열은 회전이 빨라 선제 축소")

            suggested_ratio = {
                "HOLD": 0.0,
                "REDUCE_1": 0.25,
                "REDUCE_2": 0.50,
                "EXIT_ALL": 1.0,
            }.get(final_stage, 0.0)
            if profit_ratio is not None and profit_ratio >= 0.08 and final_stage == "REDUCE_1":
                suggested_ratio = max(suggested_ratio, 0.30)
            if profit_ratio is not None and profit_ratio >= 0.12 and final_stage == "REDUCE_2":
                suggested_ratio = max(suggested_ratio, 0.60)
            if (
                instrument_profile["is_etf_like"]
                and profit_ratio is not None
                and profit_ratio > 0
                and final_stage == "REDUCE_1"
            ):
                suggested_ratio = max(suggested_ratio, 0.35)
            if (
                instrument_profile["is_leveraged_etf_like"]
                and profit_ratio is not None
                and profit_ratio > 0
                and final_stage == "REDUCE_2"
            ):
                suggested_ratio = max(suggested_ratio, 0.70)
            if score >= 90 and suggested_ratio < 1.0:
                suggested_ratio = max(suggested_ratio, 0.70)
            elif score >= 60 and suggested_ratio < 0.50:
                suggested_ratio = max(suggested_ratio, 0.50)

            action = "보유 유지"
            if suggested_ratio >= 1.0:
                action = "전량 현금화"
            elif suggested_ratio >= 0.50:
                action = "강한 비중 축소"
            elif suggested_ratio > 0:
                action = "선제 비중 축소"

            note = None
            if profit_ratio is not None and profit_ratio >= 0.15:
                note = "수익 종목은 고점 경고 시 현금 창출원으로 우선 활용"
            elif profit_ratio is not None and profit_ratio >= 0.08:
                note = "수익 보호 단계: 현금이 필요하면 먼저 줄일 후보"
            elif profit_ratio is not None and profit_ratio <= -0.08:
                note = "기존 손실 보전 기대보다 자본 보전 우선"
            elif instrument_profile["is_leveraged_etf_like"] and final_stage in {
                "REDUCE_1",
                "REDUCE_2",
            }:
                note = "레버리지/인버스 계열은 일반 종목보다 더 빠르게 이익 보호"
            elif instrument_profile["is_etf_like"] and final_stage in {"REDUCE_1", "REDUCE_2"}:
                note = "ETF 계열은 수익 구간에서 선제 현금화 기준을 강화"

            non_negative_score = max(score, 0.0)
            scored_actions.append(
                PortfolioCashActionDTO(
                    symbol=getattr(item, "symbol"),
                    name=getattr(item, "name", None),
                    priority=0,
                    action=action,
                    sell_stage=final_stage,
                    suggested_sell_ratio=round(suggested_ratio, 2),
                    urgency_score=round(non_negative_score, 2),
                    profit_ratio=round(profit_ratio, 4) if profit_ratio is not None else None,
                    reasons=list(dict.fromkeys(reasons))[:6],
                    note=note,
                )
            )
            total_score += non_negative_score

        scored_actions.sort(key=lambda x: x.urgency_score, reverse=True)
        for idx, action in enumerate(scored_actions, start=1):
            action.priority = idx

        active_count = len(scored_actions)
        avg_score = round(total_score / active_count, 2) if active_count else 0.0
        cash_gap_ratio = None
        if avg_score >= 70:
            heat_level = "HIGH"
            portfolio_action = "신규 진입 중단 + 상위 위험 종목 중심 현금화"
        elif avg_score >= 45:
            heat_level = "ELEVATED"
            portfolio_action = "신규 진입 축소 + REDUCE 단계 종목 우선 정리"
        else:
            heat_level = "NORMAL"
            portfolio_action = "보유 유지 가능, 다만 경고 종목은 선별 감축"

        summary = [
            f"활성 추적 종목 {active_count}개 기준 포트폴리오 위험 점수는 {avg_score:.1f}점",
            f"시장 과열 단계는 {heat_level}로 판단",
            f"목표 현금 비중은 {target_cash_ratio * 100:.0f}%",
        ]
        if current_cash_ratio is not None:
            cash_gap_ratio = round(target_cash_ratio - current_cash_ratio, 4)
            if cash_gap_ratio > 0:
                summary.append(
                    f"현재 현금 비중이 목표보다 {cash_gap_ratio * 100:.1f}%p 낮아 선제 현금화 필요"
                )
            else:
                summary.append("현재 현금 비중은 목표 이상으로 방어 가능")
        if winner_priority_count > 0:
            summary.append(
                f"현금 확보는 수익 구간 종목 {winner_priority_count}개를 " f"우선 활용하도록 정렬"
            )
        if scored_actions:
            top = scored_actions[0]
            summary.append(f"최우선 정리 후보는 {top.symbol}{' ' + top.name if top.name else ''}")

        return PortfolioCashPlanDTO(
            analyzed_at=datetime.now(),
            active_sell_count=active_count,
            target_cash_ratio=target_cash_ratio,
            current_cash_ratio=current_cash_ratio,
            cash_gap_ratio=cash_gap_ratio,
            market_heat_level=heat_level,
            market_risk_score=avg_score,
            portfolio_action=portfolio_action,
            summary=summary,
            actions=scored_actions,
        )

    @transaction
    async def get_portfolio_cash_plan(
        self,
        session: AsyncSession,
        target_cash_ratio: float = 0.30,
        current_cash_ratio: float | None = None,
    ) -> PortfolioCashPlanDTO:
        """활성 매도 분석 이력 기반 포트폴리오 사전 현금화 계획"""
        history_repo = self._get_analysis_repo(session)
        histories = list(
            await history_repo.get_by_type(
                "sell", is_active=True, limit=200, offset=0, session=session
            )
        )
        enriched_histories = []

        from src.application.domain.strategy.sell_strategy_service import SellStrategyService

        sell_service = SellStrategyService(session)
        universe_repo = StockUniverseRepository(session)
        for model in histories:
            universe_stock = await universe_repo.get_by_symbol(model.symbol, session=session)
            resolved_name = model.name or (universe_stock.name if universe_stock else None)
            resolved_market = universe_stock.market if universe_stock else None
            try:
                live = await sell_service.analyze_sell_signal(
                    symbol=model.symbol,
                    entry_price=float(model.entry_price) if model.entry_price is not None else None,
                    force_refresh=True,
                    name=resolved_name,
                    market=resolved_market,
                )
                enriched_histories.append(
                    SimpleNamespace(
                        symbol=live.symbol,
                        name=live.name or resolved_name,
                        market=resolved_market,
                        sell_stage=(
                            live.final_stage.value
                            if hasattr(live.final_stage, "value")
                            else live.final_stage or live.sell_stage
                        ),
                        final_stage=live.final_stage,
                        sell_reasons=live.sell_stage_reasons or live.sell_reasons,
                        entry_price=live.entry_price,
                        current_price=live.current_price,
                        is_death_cross=live.is_death_cross,
                        is_volume_sell_signal=live.is_volume_sell_signal,
                        is_volume_spike=live.is_volume_spike,
                        is_volume_peak=live.is_volume_peak,
                        overbought_sell_blocked=live.overbought_sell_blocked,
                        volume_ratio=live.volume_ratio,
                    )
                )
            except Exception:
                enriched_histories.append(
                    SimpleNamespace(
                        symbol=model.symbol,
                        name=resolved_name,
                        market=resolved_market,
                        sell_stage="HOLD",
                        sell_reasons=json.loads(model.sell_reasons) if model.sell_reasons else [],
                        entry_price=model.entry_price,
                        current_price=model.current_price,
                        is_death_cross=model.is_death_cross,
                        is_volume_sell_signal=False,
                        is_volume_spike=False,
                        is_volume_peak=False,
                        overbought_sell_blocked=False,
                        volume_ratio=None,
                    )
                )
        return self.build_portfolio_cash_plan(
            enriched_histories,
            target_cash_ratio=target_cash_ratio,
            current_cash_ratio=current_cash_ratio,
        )

    @transaction
    async def refresh_analysis_history(
        self, session: AsyncSession, analysis_type: str, market_data_service=None
    ) -> AnalysisHistoryRefreshResultDTO:
        """활성 추적 종목 분석 갱신"""
        import logging

        logger = logging.getLogger(__name__)
        errors: list[str] = []
        updated_items: list[AnalysisHistoryDTO] = []

        history_repo = self._get_analysis_repo(session)
        raw_active_symbols = await history_repo.get_active_symbols(analysis_type, session=session)

        # 메모 행(MEMO-BROADCAST-* 등) 등 종목코드 형식이 아닌 값은 분석 대상에서 제외.
        # 공백만 다른 원본 행이 공존해도 각 행을 개별 조회/갱신할 수 있도록
        # (raw, stripped) 쌍을 보존한다. DB 행 조회/갱신=raw, 외부 조회=stripped.
        symbol_pairs, skipped_symbols = split_valid_symbol_pairs(raw_active_symbols)
        if skipped_symbols:
            logger.info(
                f"[Refresh] Skipping non-symbol rows (memo etc.): {', '.join(skipped_symbols)}"
            )

        if not symbol_pairs:
            return AnalysisHistoryRefreshResultDTO(
                updated_count=0,
                items=[],
                errors=["No active tracking items found"],
            )

        logger.info(f"[Refresh] Refreshing {len(symbol_pairs)} {analysis_type} items")

        # 종목명 조회를 위한 유니버스 레포지토리
        universe_repo = StockUniverseRepository(session)

        for db_symbol, symbol in symbol_pairs:
            # DB 행 조회/갱신에는 원본(raw) 값, KIS/유니버스 등 외부·정규화 조회에는
            # stripped 값(symbol)을 사용한다.
            try:
                # 종목명 조회 (DB에 없는 경우)
                stock_name = None
                latest = await history_repo.get_latest_by_symbol(
                    db_symbol, analysis_type, is_active=True, session=session
                )
                if latest and not latest.name:
                    # DB 유니버스에서 조회
                    universe_stock = await universe_repo.get_by_symbol(symbol, session=session)
                    if universe_stock and universe_stock.name:
                        stock_name = universe_stock.name
                    elif market_data_service:
                        # API 폴백 (일반주식 + ETF 지원)
                        try:
                            stock_name = await market_data_service.get_stock_name(symbol)
                        except Exception:
                            pass

                if analysis_type == "sell":
                    # SellStrategyService는 별도 세션 사용 (내부에서 처리)
                    from src.application.domain.strategy.sell_strategy_service import (
                        SellStrategyService,
                    )

                    sell_service = SellStrategyService(session)
                    # force_refresh=True로 최신 데이터 요청
                    sell_result = await sell_service.analyze_sell_signal(
                        symbol=symbol, force_refresh=True
                    )
                    sell_reasons_json = json.dumps(sell_result.sell_reasons, ensure_ascii=False)

                    if latest:
                        update_kwargs = {
                            "current_price": sell_result.current_price,
                            "ma_short": sell_result.ma_short,
                            "ma_long": sell_result.ma_long,
                            "ma_gap_ratio": sell_result.ma_gap_ratio,
                            "stoch_k": sell_result.stoch_k,
                            "stoch_d": sell_result.stoch_d,
                            "rsi": sell_result.rsi,
                            "is_death_cross": sell_result.is_death_cross,
                            "is_stoch_overbought": sell_result.is_stoch_overbought,
                            "is_rsi_overbought": sell_result.is_rsi_overbought,
                            "sell_phase": sell_result.sell_phase,
                            "sell_reasons": sell_reasons_json,
                            "analyzed_at": datetime.now(),
                        }
                        if stock_name:
                            update_kwargs["name"] = stock_name

                        await history_repo.update_by_id(latest.id, session=session, **update_kwargs)
                        updated = await history_repo.get_by_id(latest.id, session=session)
                        if updated:
                            # sell_result를 전달하여 실시간 지표(ADX, Volume 등) 포함
                            updated_items.append(self._history_to_dto(updated, sell_result))

                elif analysis_type == "buy":
                    from src.application.domain.strategy.buy_strategy_service import (
                        BuyStrategyService,
                    )

                    buy_service = BuyStrategyService(session=session)
                    # 단일 종목만 스캔 (force_refresh=True로 최신 데이터 요청)
                    scan_result = await buy_service.scan_symbols(
                        symbols=[{"symbol": symbol, "name": stock_name or symbol}],
                        gc_only=False,
                        force_refresh=True,
                    )

                    stock_data = scan_result.stocks[0] if scan_result.stocks else None
                    if stock_data and latest:
                        update_kwargs = {
                            "current_price": stock_data.current_price,
                            "ma_short": stock_data.ma_short,
                            "ma_long": stock_data.ma_long,
                            "ma_gap_ratio": stock_data.ma_gap_ratio,
                            "stoch_k": stock_data.stoch_k,
                            "stoch_d": stock_data.stoch_d,
                            "gc_state": stock_data.gc_state,
                            "is_gc_active": stock_data.is_gc_active,
                            "analyzed_at": datetime.now(),
                        }
                        if stock_name:
                            update_kwargs["name"] = stock_name

                        await history_repo.update_by_id(latest.id, session=session, **update_kwargs)
                        updated = await history_repo.get_by_id(latest.id, session=session)
                        if updated:
                            updated_items.append(self._history_to_dto(updated))

            except Exception as e:
                # 공백만 다른 행이 공존해도 구분되도록 raw(db_symbol) 기준.
                # 제어문자 포함 값이 로그/알림 형식을 깨지 않도록 repr 이스케이프.
                error_msg = f"{db_symbol!r}: {str(e)}"
                logger.warning(f"[Refresh] Error: {error_msg}")
                errors.append(error_msg)

        return AnalysisHistoryRefreshResultDTO(
            updated_count=len(updated_items),
            items=updated_items,
            errors=errors,
        )

    def _history_to_dto(
        self, model, sell_result: "SellSignalAnalysisDTO | None" = None
    ) -> AnalysisHistoryDTO:
        """AnalysisHistoryModel을 DTO로 변환

        Args:
            model: AnalysisHistoryModel 인스턴스
            sell_result: 매도 분석 결과 (선택적, 실시간 지표 포함용)
        """
        sell_reasons = None
        if model.sell_reasons:
            try:
                sell_reasons = json.loads(model.sell_reasons)
            except (json.JSONDecodeError, TypeError):
                sell_reasons = [model.sell_reasons] if model.sell_reasons else None

        # Phase 정보 조회
        sell_phase = model.sell_phase or "NONE"
        phase_info = SELL_PHASE_INFO.get(sell_phase, SELL_PHASE_INFO["NONE"])

        # 기본 DTO 필드
        dto_kwargs = {
            "id": model.id,
            "analysis_type": model.analysis_type,
            "symbol": model.symbol,
            "name": model.name,
            "current_price": model.current_price,
            "ma_short": model.ma_short,
            "ma_long": model.ma_long,
            "ma_gap_ratio": model.ma_gap_ratio,
            "stoch_k": model.stoch_k,
            "stoch_d": model.stoch_d,
            "gc_state": model.gc_state,
            "is_gc_active": model.is_gc_active,
            "rsi": model.rsi,
            "is_death_cross": model.is_death_cross,
            "is_stoch_overbought": model.is_stoch_overbought,
            "is_rsi_overbought": model.is_rsi_overbought,
            "sell_phase": sell_phase,
            "sell_phase_name": phase_info["name"],
            "sell_phase_action": phase_info["action"],
            "sell_reasons": sell_reasons,
            "analyzed_at": model.analyzed_at,
            "entry_price": model.entry_price,
            "note": model.note,
            "is_active": model.is_active,
            "candle_count": model.candle_count,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

        # sell_result가 있으면 실시간 지표 추가 (DB에 없는 필드들)
        if sell_result is not None:
            stage_value = (
                sell_result.final_stage.value
                if hasattr(sell_result.final_stage, "value")
                else sell_result.final_stage or sell_result.sell_stage
            )
            stage_info = SELL_STAGE_INFO.get(stage_value, SELL_STAGE_INFO["HOLD"])
            dto_kwargs.update(
                {
                    # 비중축소 분석
                    "sell_stage": stage_value,
                    "sell_stage_name": stage_info["name"],
                    "sell_ratio_min": sell_result.final_ratio_min or sell_result.sell_ratio_min,
                    "sell_ratio_max": sell_result.final_ratio_max or sell_result.sell_ratio_max,
                    # 거래량 분석
                    "volume_ratio": sell_result.volume_ratio,
                    "is_volume_spike": sell_result.is_volume_spike,
                    "is_volume_sell_signal": sell_result.is_volume_sell_signal,
                    # ADX 분석
                    "adx": sell_result.adx,
                    "plus_di": sell_result.plus_di,
                    "minus_di": sell_result.minus_di,
                    "is_strong_uptrend": sell_result.is_strong_uptrend,
                    "overbought_sell_blocked": sell_result.overbought_sell_blocked,
                    # 과열 보조지표
                    "is_personal_buying_overheated": sell_result.is_personal_buying_overheated,
                    "market_credit_label": sell_result.market_credit_label,
                    "is_market_credit_overheated": sell_result.is_market_credit_overheated,
                    # candle_count
                    "candle_count": sell_result.candle_count,
                }
            )

        return AnalysisHistoryDTO(**dto_kwargs)

    # ==================== Sell Signal Helper Methods ====================

    @transaction
    async def get_symbol_state_for_sell_signal(
        self,
        session: AsyncSession,
        strategy_id: int,
        symbol: str,
    ) -> dict | None:
        """
        매도 시그널용 종목 상태 조회

        Router에서 session 없이 Repository 호출이 어려워 Service에서 처리
        """
        state_repo = StrategySymbolStateRepository(session)
        state = await state_repo.get_by_strategy_and_symbol(strategy_id, symbol, session=session)
        if not state:
            return None

        return {
            "entry_price": float(state.entry_price) if state.entry_price else None,
            "highest_price": float(state.highest_price) if state.highest_price else None,
            "trailing_stop_activated": state.trailing_stop_activated,
        }

    @transaction
    async def get_stock_name_for_sell_signal(
        self,
        session: AsyncSession,
        symbol: str,
    ) -> str | None:
        """
        매도 시그널용 종목명 조회

        DB 유니버스에서 종목명 조회
        """
        universe_repo = StockUniverseRepository(session)
        stock = await universe_repo.get_by_symbol(symbol, session=session)
        if stock and stock.name:
            return stock.name
        return None
