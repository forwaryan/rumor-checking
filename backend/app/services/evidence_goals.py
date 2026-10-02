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
_ROUTE_CLAIM = re.compile(r"直飞|直达航班|不经停航班")
_ROUTE_CONTENT = re.compile(r"直飞|直达航班|不经停|无经停|转机|经停")
_CLAIM_KEY = re.compile(r"[\s，。！？?!；;:：]")
_EXPLICIT_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}[日号])?)?|[-/]\d{1,2}[-/]\d{1,2})(?!\d)")
_ACTIONS = tuple(re.compile(pattern) for pattern in (
    r"成立|设立", r"生效|实施", r"开通|停运", r"开业|营业|停业|关停|关闭",
    r"开放|闭馆", r"招聘|招收|招募", r"裁员|裁减", r"停课|复课|上课", r"召回",
))
_COUNT = r"(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百千两]+)\s*(?:万|亿)?\s*"
_MEASURES = tuple(re.compile(_COUNT + units) for units in (
    r"(?:人|名|位)", r"(?:家|间)(?:门店|店铺|分店)", r"(?:个)?岗位", r"(?:件|批次)产品",
))
_SCOPE_CLAIM = re.compile(r"所有|全部|全都|都是|全是|均为|仅招聘|只招聘|只招")
_SCOPE_COVERAGE = r"所有|全部|全都|都是|全是|均为|仅部分|只有部分|仅有部分|仅招聘|只招聘|只招"
_SCOPE_TOPICS = ("门店", "店铺", "分店", "岗位", "员工", "学校", "产品")
_NAMED_SUBJECT = re.compile(r"^(?:网传|据称)?([\u4e00-\u9fffA-Za-z]{2,18}?(?:公司|集团|大学|医院|博物馆))")


def _attribute_action(claim: str) -> re.Pattern | None:
    actions = [pattern for pattern in _ACTIONS if pattern.search(claim)]
    return actions[0] if len(actions) == 1 else None


def _scope_topic(claim: str) -> str | None:
    topics = [topic for topic in _SCOPE_TOPICS if topic in claim]
    return topics[0] if len(topics) == 1 else None


def _attribute_covered(claim: str, dimension: str, text: str) -> bool:
    action = _attribute_action(claim)
    if action is None:
        return False
    if dimension == "time":
        action = re.compile("|".join(dict.fromkeys(action.findall(claim))))
    subject_match = _NAMED_SUBJECT.search(claim)
    subject = subject_match.group(1) if subject_match else None
    if subject and subject.startswith(("某", "这", "该", "所有", "全部")):
        subject = None
    for sentence in re.split(r"[。！？!?\n]", text):
        if subject and subject not in sentence:
            continue
        for clause in re.split(r"[，,；;]", sentence):
            clause_subject = _NAMED_SUBJECT.search(clause.strip())
            if subject and clause_subject and clause_subject.group(1) != subject:
                continue
            if not action.search(clause):
                continue
            denial = re.search(rf"(?:没有|并未|尚未|未曾|未|不再).{{0,4}}(?:{action.pattern})", clause)
            if dimension == "time" and (_EXPLICIT_DATE.search(clause) or denial):
                return True
            if dimension == "quantity":
                measures = [pattern for pattern in _MEASURES if pattern.search(claim)]
                if denial or all(pattern.search(clause) for pattern in measures):
                    return True
            if dimension == "scope":
                topic = _scope_topic(claim)
                if re.search(r"仅招聘|只招聘|只招", claim) and re.search(r"(?:并非|不是|并不)(?:仅招聘|只招聘|只招)", clause):
                    return True
                if topic and topic in clause and re.search(
                    rf"(?:{_SCOPE_COVERAGE}).{{0,8}}{topic}|{topic}.{{0,8}}(?:{_SCOPE_COVERAGE})", clause,
                ):
                    return True
    return False


def _requirements(claim: str) -> list[tuple[str, str, tuple[str, ...]]]:
    requirements = []
    if _PRICE_CLAIM.search(claim):
        requirements.append(("price", "缺少与声明对应的票价或免费适用条件原文。", ("票价 收费标准 免费条件", "官方 门票公告")))
    if _ROUTE_CLAIM.search(claim):
        requirements.append(("route", "缺少对应起讫地点的直飞、经停或转机航线原文。", ("直飞 航班 航线 经停", "航空公司 航班时刻表")))
    if _attribute_action(claim):
        if _EXPLICIT_DATE.search(claim):
            requirements.append(("time", "缺少对应事件发生时间或尚未发生的原文。", ("发生时间 官方 日期", "时间 更正 公告")))
        if any(pattern.search(claim) for pattern in _MEASURES):
            requirements.append(("quantity", "缺少对应事项的数量、人数或明确否定原文。", ("实际数量 人数 官方数据", "数量 更正 公告")))
        if _SCOPE_CLAIM.search(claim) and _scope_topic(claim):
            requirements.append(("scope", "缺少对应对象的全称范围、部分适用或例外原文。", ("适用范围 全部 部分 例外", "范围 官方 完整说明")))
    return requirements


def _content_covers(claim: str, dimension: str, result: SearchResult, body: str) -> bool:
    snippet = result.snippet
    title = result.title.strip()
    if title and result.case_id != "supplemental":
        title_key = _CLAIM_KEY.sub("", title)
        snippet = "".join(sentence for sentence in re.split(r"(?<=[。！？!?\n])", snippet)
                          if _CLAIM_KEY.sub("", sentence) != title_key)
    text = f"{snippet}\n{body}"
    if dimension in {"time", "quantity", "scope"}:
        return _attribute_covered(claim, dimension, text)
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
    route_claim = re.sub(r"(?:已经|现已|已|正式)?(?:开通|开设|新增)|已经|目前|(?:国际)?机场", "", claim)
    route = re.search(r"([\u4e00-\u9fffA-Za-z]{2,12})(?:至|到|飞往|[-—])([\u4e00-\u9fffA-Za-z]{2,12}?)(?=的|有|已|开|直飞|航|每|$)", route_claim)
    route = route or re.search(r"([\u4e00-\u9fffA-Za-z]{2,12}?)(?:有|可以)?直飞([\u4e00-\u9fffA-Za-z]{2,12}?)(?=的|航班|每|$)", route_claim)
    if route and not all(endpoint.removeprefix("从") in text for endpoint in route.groups()):
        return False
    return bool(_ROUTE_CONTENT.search(text))


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
    """Annotate missing evidence dimensions; never adjudicate.

    The dimension detectors below are keyword/regex probes over a handful of
    domains (admission prices, transit fares, direct flight routes). They are
    good enough to *flag* that the cited evidence never speaks to a property the
    claim asserts, and to seed a follow-up query for it — but a pattern miss is
    not proof of a missing proof. So a gap only ever adds ``evidence_gaps`` plus
    a note; the verdict, correction and probability stay exactly as the rule or
    LLM judge left them. ``refine_evidence_gaps`` keys off the annotation, so the
    gap-driven re-retrieval loop still runs, and the judge gets another look with
    better evidence instead of being overridden by a regex.
    """
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
        updates: dict = {"evidence_gaps": gaps}
        if gaps:
            updates["notes"] = f"{claim.notes} 证据缺口：{' '.join(gap.description for gap in gaps)}"
        guarded.append(claim.model_copy(update=updates))
    return guarded
