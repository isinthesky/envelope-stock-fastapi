# -*- coding: utf-8 -*-
"""로깅 부트스트랩 단위 테스트 — 전역 logging 상태 오염 없이 dict 산출을 검증한다."""

import io
import logging

import pytest

from src.settings.config import settings
from src.settings.logging_config import (
    DATABASE_ECHO_WARNING,
    THIRD_PARTY_LOGGER_LEVELS,
    UVICORN_LOGGERS,
    build_logging_config,
    setup_logging,
)


def _cfg(**overrides):
    """전역 settings 를 건드리지 않고 필드만 바꾼 사본을 만든다."""
    return settings.model_copy(update=overrides)


@pytest.fixture
def restore_logging_state():
    """
    setup_logging() 의 부수효과가 다른 테스트로 새지 않도록 복원한다.

    `logging.config.dictConfig` 는 disable_existing_loggers 값과 무관하게 기존 핸들러를
    정리하고, 설정 dict 에 등장하는 로거의 level/propagate 를 영구히 바꾼다. 따라서
    root 뿐 아니라 우리가 손대는 이름 있는 로거들도 함께 저장/복원해야 한다.
    """
    names = list(UVICORN_LOGGERS) + list(THIRD_PARTY_LOGGER_LEVELS.keys())
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved: dict[str, tuple[list[logging.Handler], int, bool]] = {}
    for name in names:
        target = logging.getLogger(name)
        saved[name] = (target.handlers[:], target.level, target.propagate)

    yield

    root.handlers[:] = saved_root[0]
    root.setLevel(saved_root[1])
    for name, (handlers, level, propagate) in saved.items():
        target = logging.getLogger(name)
        target.handlers[:] = handlers
        target.setLevel(level)
        target.propagate = propagate


def test_console_handler_always_present_and_file_is_opt_in():
    config = build_logging_config(_cfg(log_to_file=False, log_level="INFO"))

    assert config["root"]["handlers"] == ["console"]
    assert "file" not in config["handlers"]
    assert config["handlers"]["console"]["class"] == "logging.StreamHandler"
    assert config["handlers"]["console"]["stream"] == "ext://sys.stdout"
    assert config["root"]["level"] == "INFO"


def test_disable_existing_loggers_is_false():
    # uvicorn 이 먼저 설정한 로거와 import 시점의 src.* 로거를 죽이면 안 된다.
    config = build_logging_config(_cfg(log_to_file=False))
    assert config["disable_existing_loggers"] is False


def test_format_includes_timestamp_level_and_logger_name():
    config = build_logging_config(_cfg(log_to_file=False))
    fmt = config["formatters"]["standard"]["format"]
    assert "%(asctime)s" in fmt
    assert "%(levelname)" in fmt
    assert "%(name)s" in fmt


def test_rotating_file_handler_added_when_enabled(tmp_path):
    log_file = tmp_path / "nested" / "app.log"
    config = build_logging_config(
        _cfg(
            log_to_file=True,
            log_file=str(log_file),
            log_max_bytes=2048,
            log_backup_count=3,
            log_level="DEBUG",
        )
    )

    assert config["root"]["handlers"] == ["console", "file"]
    file_handler = config["handlers"]["file"]
    assert file_handler["class"] == "logging.handlers.RotatingFileHandler"
    assert file_handler["filename"] == str(log_file)
    assert file_handler["maxBytes"] == 2048
    assert file_handler["backupCount"] == 3
    assert log_file.parent.is_dir()  # 디렉터리 자동 생성


def test_graceful_fallback_when_log_dir_cannot_be_created(tmp_path):
    # 부모 경로가 '파일'이라 mkdir 이 OSError 를 낸다 → 기동 실패가 아니라 콘솔 폴백.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    config = build_logging_config(_cfg(log_to_file=True, log_file=str(blocker / "app.log")))

    assert config["root"]["handlers"] == ["console"]
    assert "file" not in config["handlers"]


def test_empty_log_file_path_disables_file_handler():
    config = build_logging_config(_cfg(log_to_file=True, log_file="   "))
    assert "file" not in config["handlers"]


def test_uvicorn_loggers_rebound_without_propagation():
    config = build_logging_config(_cfg(log_to_file=False))
    for name in UVICORN_LOGGERS:
        entry = config["loggers"][name]
        assert entry["handlers"] == ["console"]
        assert entry["propagate"] is False


def test_credential_leaking_clients_are_muted_below_warning():
    # httpx 는 INFO 에서 request.url 전체를 남긴다.
    # Telegram bot token(/bot<token>/...)과 DART crtfc_key 가 로그로 새면 안 된다.
    config = build_logging_config(_cfg(log_to_file=False, log_level="DEBUG"))
    assert config["loggers"]["httpx"]["level"] == "WARNING"
    assert config["loggers"]["httpcore"]["level"] == "WARNING"
    assert THIRD_PARTY_LOGGER_LEVELS["httpx"] == "WARNING"


def test_sqlalchemy_engine_muted_below_warning():
    # 기본 경로(DATABASE_ECHO=false)에서 sqlalchemy.engine 은 루트 레벨과 무관하게 WARNING 고정.
    # ⚠️ echo=True 는 이 pin 을 우회한다(SQLAlchemy InstanceLogger 가 레벨 검사를 건너뛴다).
    #    그 경로는 여기서 검증하지 않으며, setup_logging() 의 경고로만 다룬다.
    config = build_logging_config(_cfg(log_to_file=False, log_level="DEBUG"))
    assert config["loggers"]["sqlalchemy.engine"]["level"] == "WARNING"


def test_sqlalchemy_default_path_suppresses_sql_below_warning(restore_logging_state):
    """echo=False 인 기본 경로에서는 pin 이 실제로 SQL/바인드 파라미터를 억제한다."""
    from sqlalchemy import create_engine, text

    setup_logging(_cfg(log_to_file=False, log_level="DEBUG"))

    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    capture.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        engine = create_engine("sqlite://", echo=False)
        with engine.connect() as conn:
            conn.execute(text("select 1 where 1 = :marker"), {"marker": 424242})
        engine.dispose()
    finally:
        root.removeHandler(capture)

    captured = stream.getvalue()
    assert "424242" not in captured  # 바인드 파라미터가 새지 않는다
    assert "sqlalchemy.engine" not in captured


def _capture_setup_logging_records(cfg) -> list[logging.LogRecord]:
    """
    setup_logging() 이 남기는 로그를 잡는다.

    caplog 를 쓰지 않는 이유: dictConfig 가 root 핸들러를 통째로 교체하므로 pytest 가
    root 에 붙여둔 캡처 핸들러가 제거된다. 대신 설정 dict 에 등장하지 않는
    모듈 로거에 직접 붙이면(disable_existing_loggers=False) dictConfig 를 견딘다.
    """
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    module_logger = logging.getLogger("src.settings.logging_config")
    handler = _Collector(level=logging.DEBUG)
    saved_level = module_logger.level
    module_logger.addHandler(handler)
    module_logger.setLevel(logging.DEBUG)
    try:
        setup_logging(cfg)
    finally:
        module_logger.removeHandler(handler)
        module_logger.setLevel(saved_level)
    return records


def test_setup_logging_warns_when_database_echo_enabled(restore_logging_state):
    # echo 는 로거 레벨로 막히지 않으므로, 최소한 켜져 있다는 사실은 경고로 드러나야 한다.
    records = _capture_setup_logging_records(
        _cfg(log_to_file=False, log_level="INFO", database_echo=True)
    )

    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert DATABASE_ECHO_WARNING in warnings
    assert "DATABASE_ECHO=true" in DATABASE_ECHO_WARNING


def test_setup_logging_is_silent_when_database_echo_disabled(restore_logging_state):
    records = _capture_setup_logging_records(
        _cfg(log_to_file=False, log_level="INFO", database_echo=False)
    )

    assert not [r for r in records if "DATABASE_ECHO" in r.getMessage()]


def test_setup_logging_applies_and_is_idempotent(restore_logging_state):
    cfg = _cfg(log_to_file=False, log_level="INFO")

    setup_logging(cfg)
    first = list(logging.getLogger().handlers)
    setup_logging(cfg)
    second = list(logging.getLogger().handlers)

    assert len(first) == 1
    assert len(second) == 1  # 중복 핸들러가 쌓이지 않는다
    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("uvicorn.access").propagate is False


def test_setup_logging_keeps_existing_application_logger(restore_logging_state):
    # disable_existing_loggers=False 이므로 import 시점에 만들어진 src.* 로거가 살아있어야 한다.
    existing = logging.getLogger("src.application.domain.sample_for_test")

    setup_logging(_cfg(log_to_file=False, log_level="INFO"))

    assert existing.disabled is False
    assert existing.isEnabledFor(logging.INFO) is True
