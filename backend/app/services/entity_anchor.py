from __future__ import annotations

import re
from typing import Sequence

QUESTION_NOISE_PATTERNS = (
    r"[\uFF1F?]",
    r"^(请问|想问一下|想问|最近|网传|听说)",
    r"(是真的吗|真的还是假的|真的假的|是否属实|属实吗)$",
    r"是不是",
    r"是否",
    r"有没有",
    r"有无",
    r"有一个",
    r"有个",
)
ENTITY_SUFFIXES = (
    "公司",
    "集团",
    "生物",
    "科技",
    "药业",
    "药厂",
    "药企",
    "资本",
    "控股",
    "证券",
    "基金",
    "银行",
    "医院",
    "学校",
    "大学",
    "学院",
    "政府",
    "警方",
    "公安",
    "平台",
    "传媒",
    "研究所",
)
ACTION_MARKERS = (
    "裁员",
    "去世",
    "死亡",
    "脑出血",
    "脑溢血",
    "住院",
    "抢救",
    "病危",
    "停课",
    "停运",
    "通报",
    "回应",
    "辟谣",
    "抽检",
    "召回",
    "否认",
    "证实",
)
GENERIC_SUBJECT_ANCHORS = {
    "女网红",
    "男网红",
    "网红",
    "主播",
    "明星",
    "演员",
    "博主",
    "某公司",
    "某企业",
    "某医院",
    "某学校",
    "某品牌",
    "某平台",
    "这个人",
    "这个事",
    "这件事",
    "相关事件",
}
SUBJECT_MISMATCH_MARKERS = (
    "未点名",
    "没有点名",
    "未提及",
    "主体不一致",
    "不是同一家公司",
    "并非同一家公司",
    "未确认与同一公司",
    "无法确认与同一公司",
    "无法确认是否同一公司",
    "没有确认与用户提问的是同一家公司",
)
ENTITY_PATTERN = re.compile(
    rf"[\u4e00-\u9fffA-Za-z0-9]{{2,24}}(?:{'|'.join(map(re.escape, ENTITY_SUFFIXES))})"
)
ACTION_PREFIX_PATTERN = re.compile(
    rf"([\u4e00-\u9fffA-Za-z0-9]{{2,24}}?)(?:已经|已|将|会)?(?:{'|'.join(map(re.escape, ACTION_MARKERS))})"
)
LATIN_TOKEN_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9&.\-]{2,30}\b")


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_anchor_text(text: str) -> str:
    normalized = text.strip()
    for pattern in QUESTION_NOISE_PATTERNS:
        normalized = re.sub(pattern, " ", normalized)
    normalized = re.sub(r"[，。！？?!；;:：()\[\]【】]", " ", normalized)
    return _collapse_whitespace(normalized)


def _clean_anchor_candidate(text: str) -> str:
    cleaned = _normalize_anchor_text(text)
    cleaned = cleaned.strip(" -_/|")
    cleaned = re.sub(r"^(关于|针对|有关)", "", cleaned).strip()
    return cleaned


def _is_generic_anchor(anchor: str) -> bool:
    compact = anchor.strip()
    if not compact or compact in GENERIC_SUBJECT_ANCHORS:
        return True
    if compact.isdigit():
        return True
    if len(compact) < 2:
        return True
    if all(marker in compact for marker in ("网", "红")):
        return True
    return False


def extract_subject_anchors(text: str) -> list[str]:
    normalized = _normalize_anchor_text(text)
    if not normalized:
        return []

    anchors: list[str] = []
    seen: set[str] = set()

    def push(candidate: str) -> None:
        cleaned = _clean_anchor_candidate(candidate)
        if not cleaned or _is_generic_anchor(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        anchors.append(cleaned)

    for match in ENTITY_PATTERN.finditer(normalized):
        push(match.group(0))

    for match in ACTION_PREFIX_PATTERN.finditer(normalized):
        push(match.group(1))

    for token in LATIN_TOKEN_PATTERN.findall(normalized):
        if token.lower() in {"http", "https"}:
            continue
        push(token)

    return anchors


def candidate_matches_subject_anchors(anchors: Sequence[str], *texts: str | None) -> bool:
    if not anchors:
        return True
    haystack = _normalize_anchor_text(" ".join(text for text in texts if text)).lower()
    if not haystack:
        return False
    return any(_normalize_anchor_text(anchor).lower() in haystack for anchor in anchors if anchor.strip())


def text_contains_subject_mismatch(*texts: str | None) -> bool:
    haystack = _normalize_anchor_text(" ".join(text for text in texts if text)).lower()
    if not haystack:
        return False
    return any(marker in haystack for marker in SUBJECT_MISMATCH_MARKERS)
