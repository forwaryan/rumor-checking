from __future__ import annotations

import re
from collections.abc import Sequence

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
    "裁了",
    "裁掉",
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
# Well-known brand/entity names recognized as subject anchors regardless of where
# they sit in the sentence. The ENTITY/ACTION patterns below only find an entity
# via a suffix (公司/集团/…) or by being adjacent to an action verb (裁员/回应/…);
# a bare brand far from the verb is missed — e.g. "京东在今年830 930 730的时间内
# 开始裁员" made ACTION_PREFIX_PATTERN capture "730的时间内开始" and drop 京东
# entirely, so a split "主要针对中层" sub-claim floated with no subject and the
# rule engine couldn't align it to the obvious 京东砍层级 hits. Only UNAMBIGUOUS
# full names go here (mirrors retrieval_service._SUBJECT_BRANDS): a 2-char prefix
# like 阿里/字节 collides with 阿里山/字节 and would false-anchor place names.
KNOWN_BRANDS = (
    "拼多多",
    "京东",
    "淘宝",
    "天猫",
    "阿里巴巴",
    "腾讯",
    "百度",
    "美团",
    "字节跳动",
    "华为",
    "小米",
    "滴滴",
    "网易",
    "京东物流",
    "京东集团",
)
# Temporal adverbs the action-prefix capture greedily swallows into the subject
# (e.g. "美团最近裁员" -> "美团最近"). Left attached, the anchor demands the literal
# substring "美团最近", so a real "美团回应裁员" article fails the subject gate and
# gets dropped as off-topic. Strip them from both ends of every candidate.
TEMPORAL_ADVERBS = (
    "最近",
    "近日",
    "近期",
    "日前",
    "目前",
    "现在",
    "如今",
    "眼下",
    "当前",
    "今日",
    "今天",
    "昨日",
    "昨天",
    "此前",
    "早前",
    "刚刚",
    "近来",
)
# Frequency / mood adverbs the non-greedy action-prefix capture also swallows
# when they sit between subject and verb without being in the optional prefix
# group (e.g. "公司又回应" -> subject "公司又", which then double-prints as
# "公司又又回应" once re-prepended). These are always single trailing chars on a
# real subject, so strip only from the tail to avoid clipping a legitimate name.
TRAILING_ADVERBS = (
    "又",
    "也",
    "还",
    "仍",
    "再",
    "就",
    "更",
    "亦",
    "则",
)
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
# Non-greedy body ({2,24}?) so the match stops at the FIRST entity suffix rather
# than the last. A greedy body ran the whole way to the final suffix, so a claim
# like "\u4e2d\u56fd\u79d1\u5b66\u6280\u672f\u5927\u5b66\u65b0\u589e\u4eba\u5de5\u667a\u80fd\u5b66\u9662" (two suffixes: \u5927\u5b66, \u5b66\u9662) collapsed into a
# single anchor spanning the entire claim \u2014 which then demanded that whole string
# appear verbatim in evidence, dropping every real article. Non-greedy yields the
# bare entity "\u4e2d\u56fd\u79d1\u5b66\u6280\u672f\u5927\u5b66" instead. Any "\u27e8entity\u27e9\u27e8action\u27e9" claim hit this.
ENTITY_PATTERN = re.compile(
    rf"[\u4e00-\u9fffA-Za-z0-9]{{2,24}}?(?:{'|'.join(map(re.escape, ENTITY_SUFFIXES))})"
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


def _strip_temporal_adverbs(text: str) -> str:
    cleaned = text
    changed = True
    while changed:
        changed = False
        for adverb in TEMPORAL_ADVERBS:
            if cleaned.startswith(adverb) and len(cleaned) > len(adverb):
                cleaned = cleaned[len(adverb):]
                changed = True
            if cleaned.endswith(adverb) and len(cleaned) > len(adverb):
                cleaned = cleaned[: -len(adverb)]
                changed = True
    return cleaned


def _strip_trailing_adverbs(text: str) -> str:
    cleaned = text
    changed = True
    while changed:
        changed = False
        for adverb in TRAILING_ADVERBS:
            if cleaned.endswith(adverb) and len(cleaned) > len(adverb):
                cleaned = cleaned[: -len(adverb)]
                changed = True
    return cleaned


def _clean_anchor_candidate(text: str) -> str:
    cleaned = _normalize_anchor_text(text)
    cleaned = cleaned.strip(" -_/|")
    cleaned = re.sub(r"^(关于|针对|有关)", "", cleaned).strip()
    cleaned = _strip_temporal_adverbs(cleaned)
    cleaned = _strip_trailing_adverbs(cleaned)
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

    # Known brands first: a recognized brand anywhere in the text is the primary
    # subject, even when it's far from the action verb (the patterns below would
    # miss it). Guard the 京东→京东镇 / 京东白条 collision so a brand only anchors
    # when it isn't the prefix of a different compound noun.
    _BRAND_COMPOUND_SUFFIXES = ("镇", "村", "区", "县", "白条", "金融")
    for brand in KNOWN_BRANDS:
        start = 0
        while True:
            idx = normalized.find(brand, start)
            if idx < 0:
                break
            tail = normalized[idx + len(brand):]
            if not any(tail.startswith(suffix) for suffix in _BRAND_COMPOUND_SUFFIXES):
                push(brand)
                break
            start = idx + len(brand)

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
    for anchor in anchors:
        needle = _normalize_anchor_text(anchor).lower()
        if not needle:
            continue
        if needle not in haystack:
            continue
        # A known brand must match as the brand itself, not as the prefix of a
        # different compound (京东 must not match 京东镇/京东白条). For non-brand
        # anchors keep plain substring matching, which legitimately allows
        # abbreviation overlaps elsewhere.
        if _normalize_anchor_text(anchor) in KNOWN_BRANDS and not _brand_mentioned(haystack, needle):
            continue
        return True
    return False


# CJK chars that, immediately after a brand, form a DIFFERENT proper noun.
_BRAND_MATCH_SUFFIXES = ("镇", "村", "白条", "金融")


def _brand_mentioned(haystack: str, brand: str) -> bool:
    start = 0
    while True:
        idx = haystack.find(brand, start)
        if idx < 0:
            return False
        tail = haystack[idx + len(brand):]
        if not any(tail.startswith(suffix) for suffix in _BRAND_MATCH_SUFFIXES):
            return True
        start = idx + len(brand)


def text_contains_subject_mismatch(*texts: str | None) -> bool:
    haystack = _normalize_anchor_text(" ".join(text for text in texts if text)).lower()
    if not haystack:
        return False
    return any(marker in haystack for marker in SUBJECT_MISMATCH_MARKERS)
