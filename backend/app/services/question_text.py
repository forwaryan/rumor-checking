from __future__ import annotations

import re

QUESTION_TAIL_PATTERNS = (
    r"(是真的吗|真的还是假的|真的假的|真的是假的吗|是否属实|属实吗|真的吗|是真的么)\s*$",
)
QUESTION_PARTICLE_TAIL_PATTERN = re.compile(r"(了吗|了么|了吧|了呢|了啊|吗|么|吧|呢|啊|呀|是|了)$")


def strip_question_tail(text: str) -> str:
    cleaned = text.strip()
    for pattern in QUESTION_TAIL_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip()


def clean_question_term(term: str) -> str:
    cleaned = strip_question_tail(term.strip())
    if re.fullmatch(r"[\u4e00-\u9fff]{2,}", cleaned) and len(cleaned) > 2:
        cleaned = QUESTION_PARTICLE_TAIL_PATTERN.sub("", cleaned)
    return cleaned.strip()
