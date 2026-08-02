# -*- coding: utf-8 -*-
"""
Walk-Forward Report Reader - 저장된 walk-forward 리포트 read-only 로더

`scripts/run_walk_forward.py`가 컨테이너에서 생성해 `reports/walk_forward_*.json`
으로 저장한 최신 검증 리포트를 읽어 DTO로 매핑한다. 이 모듈은 재계산/재실행을
하지 않고 self-contained JSON 산출물만 파싱한다(웹 요청에서 무거운 잡을 돌리지 않음).

파일명 규칙(`walk_forward_YYYYMMDD_HHMMSS.json`)은 사전식 정렬 = 시간순 정렬이므로
glob 후 정렬 최댓값이 최신 리포트다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.application.domain.backtest.dto import (
    WalkForwardGateCheckDTO,
    WalkForwardGateDTO,
    WalkForwardOosDTO,
    WalkForwardRegimeLegDTO,
    WalkForwardReportDTO,
    WalkForwardStatsDTO,
    WalkForwardWindowDTO,
)

logger = logging.getLogger(__name__)

# report_reader.py → backtest → domain → application → src → <ROOT>
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_REPORTS_DIR = _PROJECT_ROOT / "reports"

STALE_AFTER = timedelta(days=7)


class WalkForwardReportReader:
    """`reports/` 최신 walk-forward 리포트를 읽어 DTO로 반환한다."""

    def __init__(self, reports_dir: Path | None = None) -> None:
        self._reports_dir = reports_dir or _DEFAULT_REPORTS_DIR

    def load_latest(self, *, now: datetime | None = None) -> WalkForwardReportDTO:
        """최신 리포트 1건을 로드한다. 없거나 파손 시 available=False로 반환."""
        path = self._latest_path()
        if path is None:
            return WalkForwardReportDTO(available=False)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("walk-forward 리포트 읽기 실패: %s (%s)", path.name, exc)
            return WalkForwardReportDTO(available=False)

        if not isinstance(raw, dict):
            logger.warning("walk-forward 리포트 형식 오류(dict 아님): %s", path.name)
            return WalkForwardReportDTO(available=False)

        return self._to_dto(raw, path, now)

    def _latest_path(self) -> Path | None:
        if not self._reports_dir.is_dir():
            return None
        files = sorted(self._reports_dir.glob("walk_forward_*.json"))
        return files[-1] if files else None

    def _to_dto(self, raw: dict, path: Path, now: datetime | None) -> WalkForwardReportDTO:
        generated_at = self._parse_dt(raw.get("generated_at"))
        is_stale = self._is_stale(generated_at, now)

        gate_raw = raw.get("gate") or {}
        oos_raw = raw.get("oos") or {}
        stats_raw = raw.get("stats") or {}
        window_raw = raw.get("window") or {}
        regime_raw = stats_raw.get("regime") or {}

        return WalkForwardReportDTO(
            available=True,
            generated_at=generated_at,
            is_stale=is_stale,
            source_file=path.name,
            symbols=raw.get("symbols"),
            verdict=gate_raw.get("verdict"),
            window=self._window(window_raw),
            gate=self._gate(gate_raw),
            oos=self._oos(oos_raw),
            stats=self._stats(stats_raw),
            regime=self._regime(regime_raw),
        )

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _is_stale(generated_at: datetime | None, now: datetime | None) -> bool:
        if generated_at is None:
            return False
        ref = now or datetime.now(timezone.utc)
        gen = generated_at
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return (ref - gen) > STALE_AFTER

    @staticmethod
    def _window(data: dict) -> WalkForwardWindowDTO | None:
        if not data:
            return None
        return WalkForwardWindowDTO(
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
            train=int(data.get("train", 0)),
            test=int(data.get("test", 0)),
            step=int(data.get("step", 0)),
            embargo=int(data.get("embargo", 0)),
        )

    @staticmethod
    def _gate(data: dict) -> WalkForwardGateDTO | None:
        if not data:
            return None
        checks = [
            WalkForwardGateCheckDTO(
                key=str(c.get("key", "")),
                name=str(c.get("name", "")),
                status=str(c.get("status", "")),
                detail=str(c.get("detail", "")),
            )
            for c in (data.get("checks") or [])
            if isinstance(c, dict)
        ]
        return WalkForwardGateDTO(
            verdict=str(data.get("verdict", "INCOMPLETE")),
            reason=str(data.get("reason", "")),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            na=int(data.get("na", 0)),
            checks=checks,
        )

    @staticmethod
    def _oos(data: dict) -> WalkForwardOosDTO | None:
        if not data:
            return None
        return WalkForwardOosDTO(
            total_return=float(data.get("total_return", 0.0)),
            cagr=float(data.get("cagr", 0.0)),
            sharpe=float(data.get("sharpe", 0.0)),
            mdd=float(data.get("mdd", 0.0)),
            trading_days=int(data.get("trading_days", 0)),
            folds=int(data.get("folds", 0)),
        )

    @staticmethod
    def _stats(data: dict) -> WalkForwardStatsDTO | None:
        if not data:
            return None
        return WalkForwardStatsDTO(
            deflated_sharpe=data.get("deflated_sharpe"),
            pbo=data.get("pbo"),
            oos_sharpe_ci_low=data.get("oos_sharpe_ci_low"),
            oos_sharpe_ci_high=data.get("oos_sharpe_ci_high"),
            n_trials=data.get("n_trials"),
            n_obs=data.get("n_obs"),
        )

    @staticmethod
    def _regime(data: dict) -> dict[str, WalkForwardRegimeLegDTO] | None:
        if not data:
            return None
        legs: dict[str, WalkForwardRegimeLegDTO] = {}
        for key, leg in data.items():
            if not isinstance(leg, dict):
                continue
            legs[key] = WalkForwardRegimeLegDTO(
                n_days=int(leg.get("n_days", 0)),
                total_return=float(leg.get("total_return", 0.0)),
                daily_sharpe=float(leg.get("daily_sharpe", 0.0)),
                mdd=float(leg.get("mdd", 0.0)),
            )
        return legs or None
