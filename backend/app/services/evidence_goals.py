from __future__ import annotations

import re

from backend.app.models.schemas import ClaimResult, EvidenceGap, EvidenceItem
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

_PRICE_CLAIM = re.compile(r"免票|门票|票价|入场费|参观费|(?:博物馆|美术馆|科技馆|景区|公园).{0,30}免费|免费.{0,10}(?:参观|入场)")
_PRICE_CONTENT = re.compile(
    r"(?:门票|票价|入场|参观|开放).{0,24}(?:免费|免票|收费|\d+\s*元|不收取|无须付费)"
    r"|(?:免费|免票|收费).{0,12}(?:开放|参观|入场|门票)"
)
_TRANSIT_MODE = re.compile(r"有轨电车|地铁|轻轨|公交(?:车)?|巴士|出租车|网约车|高铁|动车|火车|飞机|航班|轮渡|客轮")
_FARE_AMOUNT = r"(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百两]+)\s*元"
_FARE_CONTENT = re.compile(
    rf"(?:票价|起步价|起价|全程最高|最高票价|单程票价)[^，,。；;\n]{{0,12}}{_FARE_AMOUNT}"
    rf"|{_FARE_AMOUNT}\s*(?:起步价?|起价|封顶)"
    r"|(?:免费|免票)(?:乘坐|乘车)|(?:乘坐|乘车)(?:免费|免票)"
)
_ANCILLARY_PRICE = re.compile(r"停车|讲解|咨询|饮水|寄存|购物|游乐|餐饮|wifi", re.IGNORECASE)
_CLAIM_KEY = re.compile(r"[\s，。！？?!；;:：]")


def _requirements(claim: str) -> list[tuple[str, str, tuple[str, ...]]]:
    if _PRICE_CLAIM.search(claim):
        return [("price", "缺少与声明对应的票价或免费适用条件原文。", ("票价 收费标准 免费条件", "官方 门票公告"))]
    return []


def _content_covers(claim: str, dimension: str, result: SearchResult, body: str) -> bool:
    snippet = result.snippet
    title = result.title.strip()
    if title:
        title_key = _CLAIM_KEY.sub("", title)
        snippet = "".join(sentence for sentence in re.split(r"(?<=[。！？!?\n])", snippet)
                          if _CLAIM_KEY.sub("", sentence) != title_key)
    text = f"{snippet}\n{body}"
    if dimension == "price":
        subject = re.search(r"([\u4e00-\u9fffA-Za-z]{2,24}(?:博物馆|美术馆|科技馆|景区|公园))", claim)
        if subject and subject.group(1) not in f"{result.title} {text}":
            return False
        transit_modes = {mode.removesuffix("车") if mode.startswith("公交") else mode
                         for mode in _TRANSIT_MODE.findall(claim)}
        if transit_modes:
            # A fare may be expressed as a starting price or ceiling without
            # repeating "票价". Keep the mode and amount in related content;
            # station parking and another transport mode cannot fill this gap.
            # Only an explicit fare/boarding title can provide an omitted mode.
            # Carry subsequent mode/service changes across sentence boundaries:
            # a parking ceiling does not become a train fare after a full stop.
            modes = ({mode.removesuffix("车") if mode.startswith("公交") else mode
                      for mode in _TRANSIT_MODE.findall(title)}
                     if re.search(r"票价|票制|票务|乘车|乘坐", title) else set())
            ancillary_scope = False
            for clause in re.split(r"[，,。！？!?；;\n]", text):
                clause_modes = _TRANSIT_MODE.findall(clause)
                if clause_modes:
                    modes = {mode.removesuffix("车") if mode.startswith("公交") else mode
                             for mode in clause_modes}
                    ancillary_scope = False
                if _ANCILLARY_PRICE.search(clause):
                    ancillary_scope = True
                    continue
                if modes == transit_modes and not ancillary_scope and _FARE_CONTENT.search(clause):
                    return True
            return False
        text = re.sub(r"免费(?:停车|讲解|咨询|饮水|寄存|wifi|Wi-Fi)", "", text, flags=re.IGNORECASE)
        return bool(_PRICE_CONTENT.search(text))
    return False


def evidence_gaps_for_claim(claim: str, results: list[SearchResult], bodies: dict[str, str] | None = None) -> list[EvidenceGap]:
    bodies = bodies or {}
    return [EvidenceGap(
        dimension=dimension, description=description,
        suggested_queries=[f"{claim[:100]} {suffix}" for suffix in suffixes],
    ) for dimension, description, suffixes in _requirements(claim)
        if not any(_content_covers(claim, dimension, result, bodies.get(result.result_id, bodies.get(result.url, "")))
                   for result in results)]


def apply_evidence_goals(
    claims: list[ClaimResult], bundle: RetrievalBundle | None, bodies: dict[str, str] | None = None,
    raw_evidence: list[EvidenceItem] | None = None,
) -> list[ClaimResult]:
    available = list(bundle.canonical_results) if bundle else []
    if raw_evidence is not None:
        available = [SearchResult(case_id="request_mock", query="", result_id=f"request-{index}",
                                  title=item.title, url=item.url, source_name=item.source_name,
                                  published_at=item.published_at, snippet=item.snippet, source_tier=item.source_tier)
                     for index, item in enumerate(raw_evidence)]
    guarded = []
    for claim in claims:
        if claim.claim_type != "fact":
            guarded.append(claim)
            continue
        cited_urls = {item.url for item in claim.evidence}
        selected = [item for item in available if item.url in cited_urls]
        gaps = evidence_gaps_for_claim(claim.claim, selected, bodies)
        updates = {"evidence_gaps": gaps}
        if gaps and claim.verdict != "insufficient":
            updates.update(verdict="insufficient", confidence="low", truth_probability=None,
                           probability_basis=None, correction=None,
                           notes=f"{claim.notes} 证据缺口：{' '.join(gap.description for gap in gaps)}")
        guarded.append(claim.model_copy(update=updates))
    return guarded
