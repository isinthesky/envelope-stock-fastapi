# -*- coding: utf-8 -*-
"""WalkForwardReportReader 단위 테스트 — read-only 최신 리포트 로더."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.application.domain.backtest.report_reader import WalkForwardReportReader

_FULL_REPORT = {
    "generated_at": "2026-08-02T05:49:35+00:00",
    "symbols": 98,
    "window": {
        "start": "2020-01-01",
        "end": "2026-08-01",
        "train": 504,
        "test": 126,
        "step": 126,
        "embargo": 5,
    },
    "oos": {
        "total_return": 8.14,
        "cagr": 1.91,
        "sharpe": -0.238,
        "mdd": -8.34,
        "trading_days": 1008,
        "folds": 8,
    },
    "stats": {
        "deflated_sharpe": 0.365583,
        "pbo": 0.0286,
        "oos_sharpe_ci_low": -0.0357,
        "oos_sharpe_ci_high": 0.0949,
        "n_trials": 32,
        "n_obs": 1008,
        "regime": {
            "bull": {"n_days": 469, "total_return": 19.42, "daily_sharpe": 0.131, "mdd": -2.03},
            "bear": {"n_days": 355, "total_return": -6.91, "daily_sharpe": -0.068, "mdd": -9.11},
            "chop": {"n_days": 184, "total_return": -2.72, "daily_sharpe": -0.055, "mdd": -6.84},
        },
    },
    "gate": {
        "verdict": "NO_GO",
        "reason": "게이트 3개 미달(G1, G2, G3)",
        "passed": 2,
        "failed": 3,
        "na": 2,
        "checks": [
            {"key": "G1", "name": "DSR ≥ 0.95", "status": "FAIL", "detail": "DSR=0.366"},
            {
                "key": "G4",
                "name": "약세장 MDD ≤ 벤치",
                "status": "PASS",
                "detail": "-9.11 vs -43.91",
            },
            {"key": "G6", "name": "IS→OOS 감쇠", "status": "NA", "detail": "정의 불가"},
        ],
    },
}


def _write(dir_: Path, name: str, payload: dict) -> None:
    (dir_ / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_latest_maps_full_report(tmp_path: Path) -> None:
    _write(tmp_path, "walk_forward_20260802_054935.json", _FULL_REPORT)

    r = WalkForwardReportReader(tmp_path).load_latest(now=datetime(2026, 8, 3, tzinfo=timezone.utc))

    assert r.available is True
    assert r.source_file == "walk_forward_20260802_054935.json"
    assert r.verdict == "NO_GO"
    assert r.symbols == 98
    assert r.is_stale is False
    assert r.window.train == 504 and r.window.embargo == 5
    assert r.gate.passed == 2 and r.gate.failed == 3 and r.gate.na == 2
    assert len(r.gate.checks) == 3
    assert r.gate.checks[0].key == "G1" and r.gate.checks[0].status == "FAIL"
    assert r.oos.sharpe == -0.238 and r.oos.folds == 8
    assert r.stats.deflated_sharpe == 0.365583 and r.stats.pbo == 0.0286
    assert set(r.regime.keys()) == {"bull", "bear", "chop"}
    assert r.regime["bear"].mdd == -9.11


def test_missing_dir_returns_unavailable(tmp_path: Path) -> None:
    r = WalkForwardReportReader(tmp_path / "does_not_exist").load_latest()
    assert r.available is False
    assert r.verdict is None


def test_empty_dir_returns_unavailable(tmp_path: Path) -> None:
    r = WalkForwardReportReader(tmp_path).load_latest()
    assert r.available is False


def test_corrupt_json_returns_unavailable(tmp_path: Path) -> None:
    (tmp_path / "walk_forward_20260101_000000.json").write_text("{ not json", encoding="utf-8")
    r = WalkForwardReportReader(tmp_path).load_latest()
    assert r.available is False


def test_latest_selected_by_filename(tmp_path: Path) -> None:
    _write(tmp_path, "walk_forward_20260101_000000.json", {"gate": {"verdict": "GO"}})
    _write(tmp_path, "walk_forward_20260201_000000.json", {"gate": {"verdict": "NO_GO"}})

    r = WalkForwardReportReader(tmp_path).load_latest()

    assert r.source_file == "walk_forward_20260201_000000.json"
    assert r.verdict == "NO_GO"


def test_stale_flag_after_7_days(tmp_path: Path) -> None:
    _write(tmp_path, "walk_forward_20260201_000000.json", _FULL_REPORT)

    stale = WalkForwardReportReader(tmp_path).load_latest(
        now=datetime(2026, 8, 20, tzinfo=timezone.utc)
    )
    fresh = WalkForwardReportReader(tmp_path).load_latest(
        now=datetime(2026, 8, 3, tzinfo=timezone.utc)
    )

    assert stale.is_stale is True
    assert fresh.is_stale is False


def test_partial_report_tolerates_missing_sections(tmp_path: Path) -> None:
    _write(tmp_path, "walk_forward_20260201_000000.json", {"gate": {"verdict": "INCOMPLETE"}})

    r = WalkForwardReportReader(tmp_path).load_latest()

    assert r.available is True
    assert r.verdict == "INCOMPLETE"
    assert r.oos is None
    assert r.stats is None
    assert r.regime is None
    assert r.window is None
