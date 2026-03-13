from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.app.models.schemas import InternalInputType

SHANGHAI_TZ = timezone(timedelta(hours=8))


def looks_like_url(value: str) -> bool:
    compact = value.strip()
    return compact.startswith(("http://", "https://"))


def ensure_datetime_string(value: Optional[str]) -> str:
    if value:
        compact = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", compact):
            return f"{compact}T00:00:00+08:00"

        try:
            normalized = compact.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
            return parsed.isoformat()
        except ValueError:
            pass

    return datetime.now(SHANGHAI_TZ).isoformat()


def default_source_name(input_type: InternalInputType) -> str:
    if input_type in {"url_news", "url_unknown"}:
        return "用户提供链接"
    if input_type == "question_only":
        return "用户问题输入"
    return "用户提供文本"


def default_source_url(input_type: InternalInputType, raw_input: str) -> str:
    if input_type in {"url_news", "url_unknown"} and looks_like_url(raw_input):
        return raw_input.strip()
    if input_type == "question_only":
        return "https://example.org/input/question-only"
    return "https://example.org/input/text-news"
