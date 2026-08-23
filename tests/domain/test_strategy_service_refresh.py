# -*- coding: utf-8 -*-
"""refresh_analysis_history의 raw/stripped 심볼 라우팅 회귀 테스트

split_valid_symbol_pairs 헬퍼 단위 테스트(tests/domain/test_symbol_validation.py)만으로는
서비스 루프가 (raw, stripped) 쌍을 올바른 호출처에 전달하는지 보장하지 못한다.

계약 (strategy_service.refresh_analysis_history):
- DB 행 조회/갱신(get_latest_by_symbol, update_by_id, get_by_id)에는 raw 값
- 외부 조회(유니버스 get_by_symbol, KIS 분석/시세, get_stock_name)에는 stripped 값
- 메모 행(MEMO-BROADCAST-* 등)은 루프에서 제외
- 공백만 다른 행들도 각각 개별 갱신 경로를 탄다 (행 누락 금지)

전부 mock — 실 DB/네트워크/KIS 호출 없음.
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.application.domain.strategy.strategy_service as strategy_service_module
from src.application.domain.strategy.strategy_service import StrategyService

RAW_PLAIN = "005930"
RAW_PADDED = " 005930 "
STRIPPED = "005930"
MEMO_ROW = "MEMO-BROADCAST-1"
RAW_ACTIVE_SYMBOLS = [RAW_PLAIN, RAW_PADDED, MEMO_ROW]


def _make_history_model(
    model_id: int,
    raw_symbol: str,
    analysis_type: str,
    name=None,
    *,
    entry_price: Decimal | None = None,
    highest_price: Decimal | None = None,
):
    """_history_to_dto가 요구하는 속성을 갖춘 AnalysisHistoryModel 대역"""
    return SimpleNamespace(
        id=model_id,
        analysis_type=analysis_type,
        symbol=raw_symbol,
        name=name,
        current_price=Decimal("70000"),
        ma_short=None,
        ma_long=None,
        ma_gap_ratio=None,
        stoch_k=None,
        stoch_d=None,
        gc_state=None,
        is_gc_active=None,
        rsi=None,
        is_death_cross=False,
        is_stoch_overbought=False,
        is_rsi_overbought=False,
        sell_phase="NONE",
        sell_reasons=None,
        analyzed_at=datetime(2026, 7, 20, 9, 30),
        entry_price=entry_price,
        highest_price=highest_price,
        note=None,
        is_active=True,
        candle_count=200,
        created_at=None,
        updated_at=None,
    )


def _make_sell_result():
    """SellStrategyService.analyze_sell_signal 반환 DTO 대역"""
    return SimpleNamespace(
        current_price=Decimal("70000"),
        ma_short=None,
        ma_long=None,
        ma_gap_ratio=None,
        stoch_k=None,
        stoch_d=None,
        rsi=None,
        is_death_cross=False,
        is_stoch_overbought=False,
        is_rsi_overbought=False,
        sell_phase="NONE",
        sell_reasons=["테스트 사유"],
        final_stage="HOLD",
        sell_stage="HOLD",
        final_ratio_min=None,
        sell_ratio_min=None,
        final_ratio_max=None,
        sell_ratio_max=None,
        volume_ratio=1.0,
        is_volume_spike=False,
        is_volume_sell_signal=False,
        adx=None,
        plus_di=None,
        minus_di=None,
        is_strong_uptrend=None,
        overbought_sell_blocked=None,
        is_personal_buying_overheated=None,
        market_credit_label=None,
        is_market_credit_overheated=None,
        candle_count=200,
        highest_price=Decimal("72000"),
    )


def _make_history_repo(active_symbols: list[str], models_by_raw: dict):
    """AnalysisHistoryRepository 대역 (DI로 서비스에 주입)"""
    models_by_id = {m.id: m for m in models_by_raw.values()}

    async def raise_highest_price(history_id, candidate, *args, **kwargs):
        _ = args, kwargs
        model = models_by_id[history_id]
        if model.highest_price is None or candidate > model.highest_price:
            model.highest_price = candidate
        return model

    return SimpleNamespace(
        get_active_symbols=AsyncMock(return_value=list(active_symbols)),
        get_latest_by_symbol=AsyncMock(
            side_effect=lambda symbol, *a, **k: models_by_raw.get(symbol)
        ),
        update_by_id=AsyncMock(return_value=None),
        raise_highest_price=AsyncMock(side_effect=raise_highest_price),
        get_by_id=AsyncMock(side_effect=lambda history_id, *a, **k: models_by_id.get(history_id)),
    )


def _make_service(history_repo) -> tuple[StrategyService, MagicMock]:
    """analysis_repo DI 주입 + @transaction 내부호출 경로용 세션 대역"""
    service = StrategyService(strategy_repo=MagicMock(), analysis_repo=history_repo)
    # spec=AsyncSession → @transaction의 isinstance 검사를 통과해
    # 실 DB 세션(AsyncSessionLocal) 생성 없이 내부호출 경로를 탄다.
    fake_session = MagicMock(spec=AsyncSession)
    return service, fake_session


@pytest.mark.asyncio
async def test_sell_refresh_uses_raw_for_db_and_stripped_for_external():
    """sell 경로: DB 조회/갱신=raw, 외부 조회(유니버스/KIS/종목명)=stripped."""
    models_by_raw = {
        RAW_PLAIN: _make_history_model(1, RAW_PLAIN, "sell", name=None),
        RAW_PADDED: _make_history_model(2, RAW_PADDED, "sell", name=None),
    }
    history_repo = _make_history_repo(RAW_ACTIVE_SYMBOLS, models_by_raw)
    service, session = _make_service(history_repo)

    market_data_service = SimpleNamespace(get_stock_name=AsyncMock(return_value="삼성전자"))

    with (
        patch.object(strategy_service_module, "StockUniverseRepository") as universe_cls,
        patch(
            "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
        ) as sell_cls,
    ):
        # 유니버스 미등록 → market_data_service.get_stock_name 폴백까지 stripped 검증
        universe_repo = universe_cls.return_value
        universe_repo.get_by_symbol = AsyncMock(return_value=None)
        sell_service = sell_cls.return_value
        sell_service.analyze_sell_signal = AsyncMock(return_value=_make_sell_result())

        result = await service.refresh_analysis_history(
            session, "sell", market_data_service=market_data_service
        )

    # 1) DB 행 조회는 raw 값 그대로, 행별 1회씩 (공백 행 누락/병합 금지)
    latest_calls = [c.args[0] for c in history_repo.get_latest_by_symbol.await_args_list]
    assert latest_calls == [RAW_PLAIN, RAW_PADDED]
    history_repo.get_latest_by_symbol.assert_any_await(
        RAW_PLAIN, "sell", is_active=True, session=session
    )
    history_repo.get_latest_by_symbol.assert_any_await(
        RAW_PADDED, "sell", is_active=True, session=session
    )

    # 2) 외부 조회는 전부 stripped — 공백 포함 raw가 새어나가면 안 된다
    universe_calls = [c.args[0] for c in universe_repo.get_by_symbol.await_args_list]
    assert universe_calls == [STRIPPED, STRIPPED]
    name_calls = [c.args[0] for c in market_data_service.get_stock_name.await_args_list]
    assert name_calls == [STRIPPED, STRIPPED]
    analyze_calls = [c.kwargs for c in sell_service.analyze_sell_signal.await_args_list]
    assert [c["symbol"] for c in analyze_calls] == [STRIPPED, STRIPPED]
    assert all(c["force_refresh"] is True for c in analyze_calls)
    assert all(c["entry_price"] is None for c in analyze_calls)
    assert all(c["highest_price"] is None for c in analyze_calls)

    # 3) 두 행 모두 갱신 경로 통과 (메모 행 제외)
    update_calls = history_repo.update_by_id.await_args_list
    assert [c.args[0] for c in update_calls] == [1, 2]
    for c in update_calls:
        assert c.kwargs["session"] is session
        assert c.kwargs["name"] == "삼성전자"  # 폴백으로 찾은 종목명 반영
    assert [c.args[0] for c in history_repo.get_by_id.await_args_list] == [1, 2]

    assert result.updated_count == 2
    assert [item.symbol for item in result.items] == [RAW_PLAIN, RAW_PADDED]
    assert result.errors == []

    # 4) 메모 행은 어떤 경로로도 전달되지 않는다
    assert MEMO_ROW not in latest_calls
    assert sell_service.analyze_sell_signal.await_count == 2


@pytest.mark.asyncio
async def test_buy_refresh_uses_raw_for_db_and_stripped_for_scan():
    """buy 경로: DB 조회/갱신=raw, scan_symbols 페이로드=stripped."""
    models_by_raw = {
        RAW_PLAIN: _make_history_model(11, RAW_PLAIN, "buy", name="삼성전자"),
        RAW_PADDED: _make_history_model(12, RAW_PADDED, "buy", name="삼성전자"),
    }
    history_repo = _make_history_repo(RAW_ACTIVE_SYMBOLS, models_by_raw)
    service, session = _make_service(history_repo)

    stock_data = SimpleNamespace(
        current_price=Decimal("70000"),
        ma_short=None,
        ma_long=None,
        ma_gap_ratio=None,
        stoch_k=None,
        stoch_d=None,
        gc_state="GC_ACTIVE",
        is_gc_active=True,
    )

    with (
        patch.object(strategy_service_module, "StockUniverseRepository") as universe_cls,
        patch("src.application.domain.strategy.buy_strategy_service.BuyStrategyService") as buy_cls,
    ):
        universe_repo = universe_cls.return_value
        universe_repo.get_by_symbol = AsyncMock(return_value=None)
        buy_service = buy_cls.return_value
        buy_service.scan_symbols = AsyncMock(return_value=SimpleNamespace(stocks=[stock_data]))

        result = await service.refresh_analysis_history(session, "buy")

    # DB 행 조회는 raw 값 그대로
    latest_calls = [c.args[0] for c in history_repo.get_latest_by_symbol.await_args_list]
    assert latest_calls == [RAW_PLAIN, RAW_PADDED]
    history_repo.get_latest_by_symbol.assert_any_await(
        RAW_PADDED, "buy", is_active=True, session=session
    )

    # 스캔 페이로드는 stripped (name은 stock_name 미조회 시 symbol 폴백)
    scan_calls = [c.kwargs for c in buy_service.scan_symbols.await_args_list]
    assert [c["symbols"] for c in scan_calls] == [
        [{"symbol": STRIPPED, "name": STRIPPED}],
        [{"symbol": STRIPPED, "name": STRIPPED}],
    ]
    assert all(c["force_refresh"] is True for c in scan_calls)

    # 이름이 이미 있으므로 유니버스 조회는 발생하지 않는다
    assert universe_repo.get_by_symbol.await_count == 0

    # 두 행 모두 갱신, 메모 행 제외
    assert [c.args[0] for c in history_repo.update_by_id.await_args_list] == [11, 12]
    for c in history_repo.update_by_id.await_args_list:
        assert "name" not in c.kwargs  # stock_name 미조회 → name 갱신 없음
    assert result.updated_count == 2
    assert result.errors == []
    assert MEMO_ROW not in latest_calls


@pytest.mark.asyncio
async def test_refresh_with_only_memo_rows_returns_early_with_error():
    """메모 행만 있으면 루프 진입 없이 조기 반환한다."""
    history_repo = _make_history_repo(["MEMO-BROADCAST-1", "HALLOWEEN-STRAT"], models_by_raw={})
    service, session = _make_service(history_repo)

    with (
        patch.object(strategy_service_module, "StockUniverseRepository") as universe_cls,
        patch(
            "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
        ) as sell_cls,
    ):
        result = await service.refresh_analysis_history(session, "sell")

    assert result.updated_count == 0
    assert result.items == []
    assert result.errors == ["No active tracking items found"]

    # 조기 반환: DB 행 조회/외부 의존성 모두 미사용
    assert history_repo.get_latest_by_symbol.await_count == 0
    assert history_repo.update_by_id.await_count == 0
    universe_cls.assert_not_called()
    sell_cls.assert_not_called()


@pytest.mark.asyncio
async def test_sell_refresh_error_labels_use_raw_repr():
    """실패 시 에러 라벨은 raw(db_symbol)의 repr — 공백 변형 행 구분 + 형식 보존."""
    models_by_raw = {
        RAW_PLAIN: _make_history_model(1, RAW_PLAIN, "sell", name="삼성전자"),
        RAW_PADDED: _make_history_model(2, RAW_PADDED, "sell", name="삼성전자"),
    }
    history_repo = _make_history_repo([RAW_PLAIN, RAW_PADDED], models_by_raw)
    service, session = _make_service(history_repo)

    with (
        patch.object(strategy_service_module, "StockUniverseRepository") as universe_cls,
        patch(
            "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
        ) as sell_cls,
    ):
        universe_cls.return_value.get_by_symbol = AsyncMock(return_value=None)
        sell_service = sell_cls.return_value
        # 두 번째 호출(공백 패딩 행)만 실패시킨다
        sell_service.analyze_sell_signal = AsyncMock(
            side_effect=[_make_sell_result(), RuntimeError("boom")]
        )
        sell_service.load_latest_close = AsyncMock(return_value=70000.0)

        result = await service.refresh_analysis_history(session, "sell")

    # 실패 행도 INSUFFICIENT_DATA 상태로 영속 갱신되므로 처리 건수에 포함한다.
    assert result.updated_count == 2
    # repr 이스케이프로 공백 변형 행이 그대로 식별된다
    assert result.errors == [f"{RAW_PADDED!r}: boom"]


@pytest.mark.asyncio
async def test_sell_refresh_passes_entry_price_and_persists_insufficient_data_state():
    """진입가는 재분석에 전달하고, 실패는 HOLD가 아닌 데이터 부족 상태로 남긴다."""
    model = _make_history_model(
        21,
        RAW_PLAIN,
        "sell",
        name="삼성전자",
        entry_price=Decimal("100000"),
        highest_price=Decimal("120000"),
    )
    # 저장 가격은 -8.3%지만 오늘 최신가는 -16.7%: 실패 시에도 당일 손절을 보존한다.
    model.current_price = Decimal("110000")
    history_repo = _make_history_repo([RAW_PLAIN], {RAW_PLAIN: model})
    service, session = _make_service(history_repo)

    async def update_model(_id, **kwargs):
        for key, value in kwargs.items():
            if key != "session":
                setattr(model, key, value)

    history_repo.update_by_id.side_effect = update_model

    with (
        patch.object(strategy_service_module, "StockUniverseRepository") as universe_cls,
        patch(
            "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
        ) as sell_cls,
    ):
        universe_cls.return_value.get_by_symbol = AsyncMock(return_value=None)
        sell_service = sell_cls.return_value
        sell_service.analyze_sell_signal = AsyncMock(side_effect=RuntimeError("candles missing"))
        sell_service.load_latest_close = AsyncMock(return_value=100000.0)

        result = await service.refresh_analysis_history(session, "sell")

    sell_service.analyze_sell_signal.assert_awaited_once_with(
        symbol=RAW_PLAIN,
        entry_price=100000.0,
        highest_price=120000.0,
        force_refresh=True,
    )
    assert model.sell_phase == "INSUFFICIENT_DATA"
    assert model.current_price == Decimal("100000")
    assert result.updated_count == 1
    assert result.items[0].analysis_status == "INSUFFICIENT_DATA"
    assert result.items[0].sell_stage == "EXIT_ALL"
    assert result.items[0].sell_stage_name == "전량 청산"
    assert result.errors == [f"{RAW_PLAIN!r}: candles missing"]
