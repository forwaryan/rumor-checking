from __future__ import annotations

import re

from backend.app.services.entity_anchor import extract_subject_anchors
from backend.app.services.question_text import strip_question_tail

TREND_QUESTION_MARKERS = ("是不是", "有没有", "是否", "有无")
TREND_TIME_MARKERS = ("最近", "近期", "这阵子", "这段时间", "现在")
TREND_TOPIC_RULES = {
    "裁员": {
        "markers": ("裁员", "裁撤", "减员", "优化岗位"),
        "fact_claim": "最近公开报道里确实出现了多起裁员消息。",
        "supported_summary": "是的，最近确实有裁员相关消息，但它不是单一事件，更像多个公司在不同时点的组织调整。",
        "safe_summary": "这更像一个范围问题，不是单一事件；当前检索还没稳定命中，暂时不能直接回答最近是不是有裁员。",
        "follow_up_hint": "如果要继续较真，最好把公司名、行业或时间范围再说具体一点。",
    }
}


def _normalize_question(text: str) -> str:
    normalized = strip_question_tail(text.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" ，,。！？?!；;：:")


def detect_trend_topic(text: str) -> str | None:
    normalized = _normalize_question(text)
    if not normalized:
        return None
    for topic, rule in TREND_TOPIC_RULES.items():
        if any(marker in normalized for marker in rule["markers"]):
            return topic
    return None


def is_broad_trend_question(text: str) -> bool:
    normalized = _normalize_question(text)
    if not normalized or extract_subject_anchors(normalized):
        return False
    if detect_trend_topic(normalized) is None:
        return False
    return any(marker in normalized for marker in TREND_QUESTION_MARKERS) or any(
        marker in normalized for marker in TREND_TIME_MARKERS
    )


def rewrite_broad_trend_question_as_claim(text: str) -> str | None:
    topic = detect_trend_topic(text)
    if not topic or not is_broad_trend_question(text):
        return None
    return str(TREND_TOPIC_RULES[topic]["fact_claim"])


def is_broad_trend_claim(text: str) -> bool:
    normalized = _normalize_question(text).rstrip("。")
    return any(str(rule["fact_claim"]).rstrip("。") == normalized for rule in TREND_TOPIC_RULES.values())


def supported_trend_summary(text: str) -> str | None:
    topic = detect_trend_topic(text)
    if not topic or not is_broad_trend_question(text):
        return None
    return str(TREND_TOPIC_RULES[topic]["supported_summary"])


def safe_trend_summary(text: str) -> str | None:
    topic = detect_trend_topic(text)
    if not topic or not is_broad_trend_question(text):
        return None
    return str(TREND_TOPIC_RULES[topic]["safe_summary"])


def trend_follow_up_hint(text: str) -> str | None:
    topic = detect_trend_topic(text)
    if not topic or not is_broad_trend_question(text):
        return None
    return str(TREND_TOPIC_RULES[topic]["follow_up_hint"])
