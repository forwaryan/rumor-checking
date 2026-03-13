from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.app.models.schemas import ClaimItem, EvidenceItem, TimelineNode


@dataclass(frozen=True)
class ScenarioTemplate:
    scenario_id: str
    title: str
    summary: str
    keywords: List[str]
    default_mode_hint: str
    default_evidence_grade: str
    claims: List[ClaimItem] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)
    timeline: List[TimelineNode] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


SCENARIOS = {
    "expired_yogurt": ScenarioTemplate(
        scenario_id="expired_yogurt",
        title="海州市市场监管局通报海州新鲜屋酸奶抽检结果",
        summary="海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。",
        keywords=["海州新鲜屋", "酸奶", "停业整改", "海州市市场监管局"],
        default_mode_hint="complete_or_partial",
        default_evidence_grade="A",
        claims=[
            ClaimItem(claim="海州市市场监管局已对涉事门店下达停业整改通知。", claim_type="fact"),
            ClaimItem(claim="抽检发现海州新鲜屋有2批次酸奶超过保质期。", claim_type="fact"),
            ClaimItem(claim="目前未发现大规模食物中毒病例。", claim_type="fact"),
            ClaimItem(claim="这次通报明显只是企业公关。", claim_type="opinion"),
        ],
        evidence=[
            EvidenceItem(
                title="海州市市场监管局通报海州新鲜屋整改情况",
                url="https://gov.example.cn/hzsamr/2026-03-01",
                source_name="海州市市场监管局",
                published_at="2026-03-01",
                snippet="通报显示，涉事门店已被责令停业整改，并发现2批次酸奶超过保质期。",
                relevance_reason="官方通报直接给出处置结论。",
                source_tier="S",
            ),
            EvidenceItem(
                title="海州新鲜屋发布致歉说明",
                url="https://brand.example.cn/apology/2026-03-03",
                source_name="海州新鲜屋",
                published_at="2026-03-03",
                snippet="品牌方表示已完成问题商品下架，并配合整改。",
                relevance_reason="当事主体补充整改进展。",
                source_tier="A",
            ),
        ],
        timeline=[
            TimelineNode(
                title="监管部门发布抽检通报",
                date="2026-03-01",
                description="海州市市场监管局通报海州新鲜屋部分酸奶批次超过保质期，并责令停业整改。",
                node_type="origin",
                source_name="海州市市场监管局",
                source_url="https://gov.example.cn/hzsamr/2026-03-01",
                confidence="high",
            ),
            TimelineNode(
                title="品牌方公开致歉并说明整改",
                date="2026-03-03",
                description="品牌方发布致歉说明，承诺完成问题商品下架和门店整改。",
                node_type="turning_point",
                source_name="海州新鲜屋",
                source_url="https://brand.example.cn/apology/2026-03-03",
                confidence="medium",
            ),
        ],
        unknowns=["涉事批次的完整流向和后续复检结果尚未披露。"],
        next_steps=["继续补充官方复检结果和消费者处置进展。"],
    ),
    "ferry_fog": ScenarioTemplate(
        scenario_id="ferry_fog",
        title="清河市渡轮停航半日 官方称因大雾临时管制",
        summary="清河市交通局通报称，江面大雾导致能见度过低，城区渡轮于3月5日上午临时停航半日。",
        keywords=["清河市交通局", "渡轮", "大雾", "停航"],
        default_mode_hint="complete_or_partial",
        default_evidence_grade="A",
        claims=[
            ClaimItem(claim="清河市渡轮停航的原因是大雾临时管制。", claim_type="fact"),
            ClaimItem(claim="清河市渡轮在3月5日下午恢复运行。", claim_type="fact"),
            ClaimItem(claim="这次停航暴露了清河渡运系统长期管理混乱。", claim_type="opinion"),
        ],
        evidence=[
            EvidenceItem(
                title="清河市交通局发布停航说明",
                url="https://gov.example.cn/qhjt/2026-03-05",
                source_name="清河市交通局",
                published_at="2026-03-05",
                snippet="因江面大雾导致能见度低，渡轮上午临时停航。",
                relevance_reason="官方直接说明停航原因。",
                source_tier="S",
            ),
            EvidenceItem(
                title="渡轮下午恢复运行",
                url="https://news.example.cn/metro/2026-03-05-2",
                source_name="清河日报",
                published_at="2026-03-05",
                snippet="清河日报转述交通局说法，称下午已恢复运行。",
                relevance_reason="主流媒体补充恢复运行信息。",
                source_tier="A",
            ),
        ],
        timeline=[
            TimelineNode(
                title="交通局上午发布停航说明",
                date="2026-03-05",
                description="清河市交通局说明渡轮停航原因为大雾临时管制。",
                node_type="origin",
                source_name="清河市交通局",
                source_url="https://gov.example.cn/qhjt/2026-03-05",
                confidence="high",
            ),
            TimelineNode(
                title="下午恢复通航",
                date="2026-03-05",
                description="当日下午交通恢复，主流媒体同步转述官方说法。",
                node_type="turning_point",
                source_name="清河日报",
                source_url="https://news.example.cn/metro/2026-03-05-2",
                confidence="medium",
            ),
        ],
        unknowns=["停航之外的系统性管理问题仍缺少公开审计材料。"],
        next_steps=["如果需要评估管理问题，应补充历史通航记录和监管文件。"],
    ),
    "morningstar_layoff": ScenarioTemplate(
        scenario_id="morningstar_layoff",
        title="晨星生物裁员40%传闻待核实",
        summary="围绕晨星生物是否裁员40%的说法正在传播，但仅凭提问或截图不能直接下确定性结论。",
        keywords=["晨星生物", "裁员40%", "传闻"],
        default_mode_hint="safe",
        default_evidence_grade="D",
        claims=[
            ClaimItem(claim="晨星生物已经宣布裁员40%。", claim_type="fact"),
            ClaimItem(claim="晨星生物下周肯定会继续裁员。", claim_type="prediction"),
            ClaimItem(claim="很多内部员工提前收到晨星生物裁员名单。", claim_type="unverifiable"),
        ],
        evidence=[
            EvidenceItem(
                title="晨星生物关于网络传言的声明",
                url="https://ir.example.com/morningstar/2026-03-06",
                source_name="晨星生物",
                published_at="2026-03-06",
                snippet="公司未发布任何40%裁员计划，相关截图不实。",
                relevance_reason="当事主体直接否认相关传闻。",
                source_tier="S",
            ),
            EvidenceItem(
                title="证券时报：公司否认裁员40%",
                url="https://finance.example.cn/2026-03-06-3",
                source_name="证券时报",
                published_at="2026-03-06",
                snippet="交易所问询后公司否认40%裁员安排。",
                relevance_reason="主流财经媒体进行二次确认。",
                source_tier="A",
            ),
        ],
        unknowns=["是否存在结构调整、部门缩编等相近但不同的动作仍需更多材料。"],
        next_steps=["补充公司公告、交易所问询回复或完整新闻正文后再判断。"],
    ),
    "beichuan_school": ScenarioTemplate(
        scenario_id="beichuan_school",
        title="北川中学停课传闻缺少正式来源",
        summary="当前流传内容主要来自转发截图和聚合页面，尚未看到学校或教育部门给出的完整正式通知。",
        keywords=["北川中学", "停课", "传闻", "来源缺失"],
        default_mode_hint="safe",
        default_evidence_grade="D",
        claims=[
            ClaimItem(claim="北川中学将从下周起全面停课一个月。", claim_type="fact"),
            ClaimItem(claim="多名家长已经确认学校会全面停课。", claim_type="unverifiable"),
            ClaimItem(claim="当前传播内容缺少正式来源。", claim_type="fact"),
        ],
        evidence=[
            EvidenceItem(
                title="家长群截图称北川中学将停课",
                url="https://social.example.com/post/777",
                source_name="家长群转发",
                published_at="2026-03-07",
                snippet="截图称学校即将停课一个月，但无正式落款。",
                relevance_reason="只说明传闻正在传播。",
                source_tier="C",
            ),
            EvidenceItem(
                title="聚合页：北川中学停课传闻持续发酵",
                url="https://aggregate.example.cn/topic/901",
                source_name="资讯聚合",
                published_at="2026-03-07",
                snippet="聚合多个转发，无正式来源。",
                relevance_reason="进一步说明来源链条不稳定。",
                source_tier="B",
            ),
        ],
        timeline=[
            TimelineNode(
                title="停课截图开始在社交平台传播",
                date="2026-03-07",
                description="家长群截图被多次转发，但尚未附带官方通知原件。",
                node_type="origin",
                source_name="家长群转发",
                source_url="https://social.example.com/post/777",
                confidence="low",
            ),
            TimelineNode(
                title="聚合页放大传播范围",
                date="2026-03-07",
                description="资讯聚合页面汇总多个转发版本，仍未补齐权威来源。",
                node_type="turning_point",
                source_name="资讯聚合",
                source_url="https://aggregate.example.cn/topic/901",
                confidence="low",
            ),
        ],
        unknowns=["教育部门是否已有正式通知、学校当前教学安排是什么仍未可知。"],
        next_steps=["补充学校通知、教育局通报或正文截图后再做判断。"],
    ),
    "chemical_odor": ScenarioTemplate(
        scenario_id="chemical_odor",
        title="北城区化工厂异味投诉仍处在核查阶段",
        summary="居民投诉、企业回应与环保部门核查信息同时存在，传播链可见，但核心结论仍有冲突。",
        keywords=["北城区化工厂", "生态环境局", "异味", "核查"],
        default_mode_hint="partial",
        default_evidence_grade="C",
        claims=[
            ClaimItem(claim="北城区化工厂已被居民连续投诉夜间异味。", claim_type="fact"),
            ClaimItem(claim="区生态环境局已经进场核查。", claim_type="fact"),
            ClaimItem(claim="北城区化工厂已经完全停产。", claim_type="fact"),
            ClaimItem(claim="北城区化工厂一直在隐瞒真实污染情况。", claim_type="opinion"),
        ],
        evidence=[
            EvidenceItem(
                title="区生态环境局称已进场核查",
                url="https://env.example.cn/beicheng/2026-03-03",
                source_name="北城区生态环境局",
                published_at="2026-03-03",
                snippet="生态环境局表示已对居民投诉启动现场核查。",
                relevance_reason="官方确认介入调查。",
                source_tier="S",
            ),
            EvidenceItem(
                title="公司回应仅暂停一条产线",
                url="https://company.example.cn/news/2026-03-05",
                source_name="北城区化工厂",
                published_at="2026-03-05",
                snippet="公司称仅有一条产线暂停，其余产线正常。",
                relevance_reason="与完全停产说法冲突。",
                source_tier="A",
            ),
            EvidenceItem(
                title="财经媒体称化工厂停产整顿",
                url="https://finance.example.cn/industry/2026-03-05-2",
                source_name="财经观察",
                published_at="2026-03-05",
                snippet="报道提到工厂已停产整顿。",
                relevance_reason="与公司回应形成冲突。",
                source_tier="A",
            ),
        ],
        timeline=[
            TimelineNode(
                title="居民发出夜间异味投诉",
                date="2026-03-01",
                description="居民开始投诉夜间异味问题。",
                node_type="origin",
                confidence="medium",
            ),
            TimelineNode(
                title="企业首次回应设备检修正常",
                date="2026-03-02",
                description="工厂称设备检修正常，未正面回应污染指控。",
                node_type="response",
                source_name="北城区化工厂",
                confidence="medium",
            ),
            TimelineNode(
                title="环保部门进场核查",
                date="2026-03-03",
                description="区生态环境局确认已进场核查。",
                node_type="turning_point",
                source_name="北城区生态环境局",
                source_url="https://env.example.cn/beicheng/2026-03-03",
                confidence="high",
            ),
            TimelineNode(
                title="停产规模出现冲突说法",
                date="2026-03-05",
                description="财经媒体与公司声明对停产范围给出相互冲突的信息。",
                node_type="conflict",
                confidence="medium",
            ),
        ],
        unknowns=["异味来源、检测结果和停产范围仍未形成统一公开结论。"],
        next_steps=["补充监测报告、整改通知和更完整的企业通报。"],
    ),
    "generic": ScenarioTemplate(
        scenario_id="generic",
        title="待核实事件",
        summary="输入内容已接收，但当前只有有限上下文，系统会以保守方式输出结果。",
        keywords=["待核实"],
        default_mode_hint="safe",
        default_evidence_grade="D",
        claims=[ClaimItem(claim="当前输入涉及一个待核实事实。", claim_type="fact")],
        unknowns=["尚未识别到稳定的权威来源和完整传播链。"],
        next_steps=["补充完整正文、来源链接或更具体的问题描述。"],
    ),
}


def match_scenario(text: str) -> ScenarioTemplate:
    compact = text.lower()
    if "海州新鲜屋" in compact or ("酸奶" in compact and "海州" in compact):
        return SCENARIOS["expired_yogurt"]
    if "清河" in compact and "渡轮" in compact:
        return SCENARIOS["ferry_fog"]
    if "晨星生物" in compact and "裁员" in compact:
        return SCENARIOS["morningstar_layoff"]
    if "北川中学" in compact and "停课" in compact:
        return SCENARIOS["beichuan_school"]
    if "化工厂" in compact and "异味" in compact:
        return SCENARIOS["chemical_odor"]
    return SCENARIOS["generic"]
