from unittest.mock import AsyncMock, MagicMock

from src.adapters.database.repositories.analysis_history_repository import AnalysisHistoryRepository


async def test_get_active_symbols_with_names_includes_market() -> None:
    repo = AnalysisHistoryRepository(session=MagicMock())
    repo._get_session = MagicMock(return_value=repo.session)  # type: ignore[attr-defined]
    repo.session.execute = AsyncMock(
        return_value=MagicMock(
            all=MagicMock(
                return_value=[("005930", "삼성전자", "KOSPI")]
            )
        )
    )

    result = await repo.get_active_symbols_with_names("sell")

    assert result == [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI"}]
