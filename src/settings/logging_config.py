# -*- coding: utf-8 -*-
"""
Logging Configuration - 애플리케이션 로깅 부트스트랩

`settings.log_*` 값을 실제 `logging` 설정(dictConfig)으로 연결한다.

설계 근거:
- uvicorn 은 `Config.__init__` 에서 `configure_logging()` 을 호출해 자체 dictConfig 를
  먼저 적용한 뒤 `src.main:app` 을 import 한다. 따라서 앱 모듈 import 시점에 호출되는
  `setup_logging()` 이 최종 설정자가 된다.
- uvicorn 로거는 `propagate=False` + 자체 핸들러 구조라 그대로 두면 우리 파일 핸들러에
  요청 로그가 남지 않는다. 동일 핸들러/포맷으로 명시적으로 재바인딩한다.
- `disable_existing_loggers` 는 반드시 False. import 시점에 이미 만들어진
  `src.*` 로거와 uvicorn 로거를 죽이면 안 된다.
- 컨테이너에서 stdout 은 1급 시민이므로 콘솔 핸들러는 어떤 경우에도 유지한다.
- 파일 로깅은 옵트인이며, 디렉터리 생성/쓰기 실패는 기동 실패로 만들지 않고
  콘솔 전용으로 폴백한다(경고 1회 기록).
"""

import logging
import logging.config
from pathlib import Path
from typing import Any

from src.settings.config import Settings, settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# 자격증명/민감 데이터가 로그로 새는 서드파티 로거는 INFO 이상으로 올리지 않는다.
# - httpx 는 INFO 에서 `request.url` 전체(쿼리스트링 포함)를 남긴다.
#     Telegram: https://api.telegram.org/bot<BOT_TOKEN>/sendMessage
#     DART:     https://opendart.fss.or.kr/...?crtfc_key=<API_KEY>
#   httpx/httpcore/urllib3 는 표준 logging 경로이므로 이 pin 이 실제로 유효하다.
# - sqlalchemy.engine 은 기본 경로(`DATABASE_ECHO=false`)에서만 이 pin 이 유효하다.
#   ⚠️ `DATABASE_ECHO=true` 는 이 설정을 우회한다:
#     `adapters/database/connection.py` 가 `create_async_engine(echo=settings.database_echo)`
#     로 엔진을 만드는데(모듈 import 시점 = setup_logging() 이후), echo 가 켜지면 SQLAlchemy 의
#     `InstanceLogger.log()` 가 로거 레벨 검사를 건너뛰고 `logger._log()` 를 직접 호출하며
#     `sqlalchemy.engine.Engine` 에 자체 stdout 핸들러까지 붙인다. 결과적으로 SQL 전문과
#     바인드 파라미터(주문 수량/가격 등)가 자체 핸들러 + 루트 핸들러로 두 번 출력된다.
#     (SQLAlchemy 2.0.51 실측. 이 pin 을 걷어내는 것이 아니라 echo 자체를 끄는 것이 방어책이며,
#      setup_logging() 이 database_echo=True 를 감지하면 아래에서 경고를 남긴다.)
# (CLAUDE.md: 로그에 인증정보를 남기지 말 것)
THIRD_PARTY_LOGGER_LEVELS: dict[str, str] = {
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "urllib3": "WARNING",
    "asyncio": "WARNING",
    "sqlalchemy.engine": "WARNING",
    "apscheduler": "INFO",
}


def _resolve_log_path(cfg: Settings) -> Path | None:
    """파일 핸들러 사용 여부/경로 결정. 사용하지 않으면 None."""
    if not cfg.log_to_file:
        return None
    raw = (cfg.log_file or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _ensure_writable(path: Path) -> bool:
    """로그 디렉터리를 만들고 쓰기 가능한지 확인한다. 실패해도 예외를 올리지 않는다."""
    try:
        parent = path.parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError:
        return False
    return True


def build_logging_config(cfg: Settings | None = None) -> dict[str, Any]:
    """
    dictConfig 에 넘길 설정 dict 를 만든다.

    전역 `logging` 상태는 건드리지 않지만, `log_to_file=True` 인 경우
    로그 디렉터리 생성/파일 touch 라는 파일시스템 부수효과가 있다.
    """
    active = cfg if cfg is not None else settings
    level = active.log_level

    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
            "level": level,
        }
    }
    handler_names: list[str] = ["console"]

    log_path = _resolve_log_path(active)
    if log_path is not None:
        if _ensure_writable(log_path):
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filename": str(log_path),
                "maxBytes": active.log_max_bytes,
                "backupCount": active.log_backup_count,
                "encoding": "utf-8",
                "level": level,
            }
            handler_names.append("file")
        else:
            # 기동을 실패시키지 않고 콘솔 전용으로 폴백한다.
            logging.getLogger(__name__).warning(
                "로그 파일 경로를 사용할 수 없어 콘솔 로깅만 활성화한다: %s", log_path
            )

    loggers: dict[str, dict[str, Any]] = {
        name: {"level": lvl} for name, lvl in THIRD_PARTY_LOGGER_LEVELS.items()
    }
    for name in UVICORN_LOGGERS:
        loggers[name] = {
            "handlers": list(handler_names),
            "level": level,
            "propagate": False,
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
        },
        "handlers": handlers,
        "loggers": loggers,
        "root": {"handlers": list(handler_names), "level": level},
    }


DATABASE_ECHO_WARNING = (
    "DATABASE_ECHO=true — SQL 문과 바인드 파라미터가 로그에 남습니다. "
    "sqlalchemy.engine 로거 레벨(WARNING)로는 막히지 않으니 운영 환경에서는 끄십시오."
)


def setup_logging(cfg: Settings | None = None) -> None:
    """애플리케이션 로깅을 설정한다. 여러 번 호출해도 안전하다(핸들러가 누적되지 않는다)."""
    active = cfg if cfg is not None else settings
    logging.config.dictConfig(build_logging_config(active))

    # echo 는 로거 레벨을 우회하므로(위 THIRD_PARTY_LOGGER_LEVELS 주석 참고) 무음화를 시도하는
    # 대신, 켜져 있다는 사실만 기동 로그에 1회 남긴다. 자격증명은 찍지 않는다.
    if active.database_echo:
        logging.getLogger(__name__).warning(DATABASE_ECHO_WARNING)
