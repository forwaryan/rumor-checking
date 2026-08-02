from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime

from backend.app.core.config import Settings

_BUILTIN_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))
_RESERVED_KEYS = frozenset({"timestamp", "level", "logger", "message", "traceback"})


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            obj["traceback"] = "".join(traceback.format_exception(*record.exc_info))
        for key, value in vars(record).items():
            if key not in _BUILTIN_ATTRS:
                if key in _RESERVED_KEYS:
                    key = f"extra_{key}"
                obj[key] = value
        return json.dumps(obj, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    if settings.log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.basicConfig(level=level, handlers=[handler])
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    logging.getLogger("uvicorn.access").setLevel(level)
