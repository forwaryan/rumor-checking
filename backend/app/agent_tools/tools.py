from __future__ import annotations

from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, tool
from backend.app.services.analyze_pipeline import (
    _GRADE_RANK,
    _apply_clarification_note,
    _bundle_quality,
    _claim_details,
    _event_details,
    _question_resolution_details,
    _retrieval_bundle_details,
    _timeline_details,
)
from backend.app.services.progress import emit_log, emit_stage
from backend.app.services.timeline_builder import TimelineBuild

# Provenance fallback reason: LLM synthesis was expected (LLM enabled) but did
# not produce a grounded result, so the rule engine answered instead.
LLM_SYNTHESIS_FALLBACK_REASON = "llm_synthesis_unavailable_rule_fallback"

# Hard cap on a fetched page body fed into synthesis (keeps prompt/token bounded).
_FETCH_BODY_MAX_CHARS = 4000


def _build_completion_fn(ctx: ToolContext):
    """Build a completion_fn from the agent reasoner's streaming layer.

    Returns None when the reasoner is disabled (zero-key path), so the verdict
    engine and correction module fall back to their own httpx POST paths. When
    the reasoner IS enabled, the returned callable routes through the reliable
    retry/streaming layer that avoids the one-shot timeout on this gateway."""
    reasoner = ctx.agent_reasoner
    if not getattr(reasoner, "enabled", False):
        return None

    def _complete(system_prompt: str, user_prompt: str) -> str:
        return reasoner._request_completion(
            stage_key="verdict_engine",
            title="LLM verdict/correction",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    return _complete


@tool("normalize", description="标准化用户输入为结构化事件", critical=True, retries=2)
def normalize(ctx: ToolContext, state: AgentState) -> None:
    request = state.request
    emit_stage(
        stage_key="normalize_input",
        title="标准化输入",
        status="running",
        summary="正在识别输入类型并抽取基础事件线索。",
        details=[
            f"input_type={request.input_type or 'auto'}",
            f"input_chars={len(request.raw_input.strip())}",
        ],
    )
    normalized_event = ctx.input_normalizer.normalize(request)
    state.normalized_event = normalized_event
    state.resolved_event = normalized_event
    emit_stage(
        stage_key="normalize_input",
        title="标准化输入",
        status="completed",
        summary="已整理出初始事件草稿。",
        details=_event_details(normalized_event),
    )
    state.record("normalize", "标准化输入完成", _event_details(normalized_event))


@tool("search_news", description="联网检索与事件相关的新闻和证据", critical=True, retries=2)
def search_news(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="retrieval_initial",
        title="首轮检索",
        status="running",
        summary="正在生成 query plan 并拉取第一批公开网页结果。",
        details=[f"provider={ctx.settings.retrieval_provider}"],
    )
    bundle = ctx.retriever.retrieve_for_event(
        state.normalized_event, request_context=state.request.request_context
    )
    state.initial_retrieval_bundle = bundle
    state.retrieval_bundle = bundle
    emit_stage(
        stage_key="retrieval_initial",
        title="首轮检索",
        status="completed",
        summary="首轮检索已返回结果集。",
        details=_retrieval_bundle_details(bundle),
    )
    state.record("search_news", "首轮检索完成", _retrieval_bundle_details(bundle))


@tool("resolve_question", description="消歧问题类输入，锚定具体事件")
def resolve_question(ctx: ToolContext, state: AgentState) -> None:
    event = state.normalized_event
    bundle = state.initial_retrieval_bundle
    emit_stage(
        stage_key="question_resolution",
        title="问题消歧",
        status="running",
        summary="正在判断这次输入是否能稳定锚定到单一事件。",
        details=[f"question_only={event.input_type == 'question_only'}"],
    )
    resolution = _resolve_question(ctx, event=event, retrieval_bundle=bundle)
    state.question_resolution = resolution
    state.resolved_event = resolution.event
    status = "skipped" if event.input_type != "question_only" else "completed"
    summary = "输入不是纯问题，沿用当前事件草稿。" if status == "skipped" else "问题消歧已完成。"
    emit_stage(
        stage_key="question_resolution",
        title="问题消歧",
        status=status,
        summary=summary,
        details=_question_resolution_details(resolution),
    )
    state.record("resolve_question", summary, _question_resolution_details(resolution))


@tool("follow_up_retrieval", description="基于消歧结果执行跟进检索")
def follow_up_retrieval(ctx: ToolContext, state: AgentState) -> None:
    resolution = state.question_resolution
    # A follow-up retrieval is a real network round-trip. Under the token-budget
    # fast-path it still runs (it costs no LLM tokens), but once the wall-clock
    # deadline has fired the whole point is to stop spending latency — so skip the
    # fetch and let the planner head straight to synthesis with what we have.
    if resolution is not None and resolution.follow_up_query and not state.time_exhausted:
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="running",
            summary="已根据候选事件生成 follow-up query，正在补抓更精准的结果。",
            details=[f"follow_up_query={resolution.follow_up_query}"],
        )
        follow_up_context = dict(state.request.request_context)
        follow_up_context["force_retrieval_query"] = resolution.follow_up_query
        follow_up_context["retrieval_stage_key"] = "retrieval_follow_up"
        follow_up_bundle = ctx.retriever.retrieve_for_event(
            state.resolved_event, request_context=follow_up_context
        )
        state.follow_up_bundle = follow_up_bundle
        if follow_up_bundle.canonical_results or follow_up_bundle.matched_case_id:
            state.retrieval_bundle = follow_up_bundle
            state.follow_up_used = True
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="completed",
            summary="follow-up 检索已结束。",
            details=_retrieval_bundle_details(follow_up_bundle),
        )
    else:
        skipped_for_time = state.time_exhausted and resolution is not None and bool(resolution.follow_up_query)
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="skipped",
            summary="已超时软着陆，跳过追加检索。" if skipped_for_time else "当前输入不需要 follow-up query。",
            details=[],
        )
    state.record("follow_up_retrieval", "follow-up 阶段结束")


@tool("investigate", description="LLM 决策：是否进行额外一轮定向检索", retries=1)
def investigate(ctx: ToolContext, state: AgentState) -> None:
    """Optional evidence-driven extra retrieval rounds (LLM planner)."""
    if not ctx.settings.lightweight_agent_ready or not ctx.agent_reasoner.enabled:
        return
    bundle = state.retrieval_bundle
    if bundle is None:
        return

    max_rounds = ctx.settings.agent_max_extra_rounds
    current_bundle = bundle
    for round_index in range(1, max_rounds + 1):
        emit_stage(
            stage_key="investigation_plan",
            title="调查决策",
            status="running",
            summary=f"第 {round_index} 轮：正在评估当前证据是否足够，决定要不要再补一轮检索。",
            details=[
                f"round={round_index}/{max_rounds}",
                f"evidence_grade={current_bundle.evidence_grade}",
                f"independent_high_trust={current_bundle.independent_high_trust_source_count}",
            ],
        )
        try:
            plan = ctx.agent_reasoner.plan_investigation(
                event=state.resolved_event,
                retrieval_bundle=current_bundle,
                round_index=round_index,
            )
        except Exception as exc:
            emit_log(
                stage_key="investigation_plan",
                level="warning",
                title="调查决策失败",
                summary="investigation planner 抛错，停止补检索并沿用当前证据。",
                details=[f"error_type={exc.__class__.__name__}"],
            )
            break

        if plan is None or not plan.should_continue or not plan.follow_up_query:
            emit_stage(
                stage_key="investigation_plan",
                title="调查决策",
                status="completed",
                summary="决策：当前证据已足够或无法收紧，停止补检索。",
                details=[f"reason={plan.reason}" if plan is not None else "reason=planner_unavailable"],
            )
            break

        emit_stage(
            stage_key="investigation_plan",
            title="调查决策",
            status="completed",
            summary="决策：证据仍偏弱，追加一轮定向检索。",
            details=[f"reason={plan.reason}", f"follow_up_query={plan.follow_up_query}"],
        )

        follow_up_context = dict(state.request.request_context)
        follow_up_context["force_retrieval_query"] = plan.follow_up_query
        follow_up_context["retrieval_stage_key"] = "investigation_retrieval"
        emit_stage(
            stage_key="investigation_retrieval",
            title="调查补检索",
            status="running",
            summary="正在按调查决策补抓更权威的结果。",
            details=[f"follow_up_query={plan.follow_up_query}"],
        )
        candidate_bundle = ctx.retriever.retrieve_for_event(
            state.resolved_event, request_context=follow_up_context
        )
        adopted = _bundle_quality(candidate_bundle) > _bundle_quality(current_bundle)
        # Name the dimension that actually improved so the summary can't claim
        # "更强证据" while every visible metric reads unchanged. _bundle_quality
        # ranks by (grade, independent high-trust count, decisive count, canonical
        # count), so an adoption can be driven by any one of the four.
        grade_up = _GRADE_RANK.get(candidate_bundle.evidence_grade, 0) > _GRADE_RANK.get(current_bundle.evidence_grade, 0)
        high_trust_up = candidate_bundle.independent_high_trust_source_count > current_bundle.independent_high_trust_source_count
        decisive_up = candidate_bundle.decisive_result_count > current_bundle.decisive_result_count
        canonical_up = len(candidate_bundle.canonical_results) > len(current_bundle.canonical_results)
        if adopted:
            if grade_up:
                summary = "补检索把证据等级提上去了，已采用。"
            elif high_trust_up:
                summary = "补检索新增了高可信独立源，已采用。"
            elif decisive_up:
                summary = "补检索抓到了官方回应/辟谣等决定性来源，已采用。"
            elif canonical_up:
                summary = "补检索多召回了相关结果（但证据等级/高可信源没变），已采用。"
            else:
                summary = "补检索质量略有提升，已采用。"
        else:
            summary = "补检索未带来更强证据，沿用原结果。"
        emit_stage(
            stage_key="investigation_retrieval",
            title="调查补检索",
            status="completed" if adopted else "warning",
            summary=summary,
            details=[
                f"adopted={adopted}",
                f"grade={current_bundle.evidence_grade}->{candidate_bundle.evidence_grade}",
                f"independent_high_trust={current_bundle.independent_high_trust_source_count}"
                f"->{candidate_bundle.independent_high_trust_source_count}",
                f"decisive_results={current_bundle.decisive_result_count}"
                f"->{candidate_bundle.decisive_result_count}",
                f"canonical_results={len(current_bundle.canonical_results)}"
                f"->{len(candidate_bundle.canonical_results)}",
            ],
        )
        state.investigation_rounds += 1
        if adopted:
            current_bundle = candidate_bundle
    state.retrieval_bundle = current_bundle


def _pick_fetch_target(state: AgentState):
    """Highest-value canonical result whose body has not been fetched yet.

    Prefers high-trust, non-aggregator, higher-tier sources (a full-body read is
    most useful on an authoritative page), then falls back to existing order.
    """
    bundle = state.retrieval_bundle
    if bundle is None:
        return None
    candidates = [
        r
        for r in bundle.canonical_results
        if r.result_id not in state.fetched_bodies and r.url and r.url not in state.fetched_urls
    ]
    if not candidates:
        return None

    def score(result):
        return (
            1 if result.is_high_trust else 0,
            0 if result.is_aggregator_source else 1,
            result.tier_weight,
        )

    return max(candidates, key=score)


def _try_rendered_fallback(url: str, ctx: ToolContext) -> str | None:
    """Attempt a Playwright-rendered fetch when static extraction failed.

    Gated by RENDERED_FETCH_ENABLED setting. Returns extracted body text or None.
    """
    if not getattr(ctx.settings, "rendered_fetch_enabled", False):
        return None
    from backend.app.services.rendered_page_fetcher import render_page
    html = render_page(url)
    if not html:
        return None
    from backend.app.services.url_content_extractor import UrlContentExtractor
    extractor = UrlContentExtractor(settings=ctx.settings)
    result = extractor._extract_from_html(
        html=html[:ctx.settings.url_fetch_max_chars],
        final_url=url,
        content_type="text/html",
        fallback_source_name=None,
    )
    if result.status == "ok" and result.body:
        return result.body[:_FETCH_BODY_MAX_CHARS]
    return None


@tool("fetch_url", description="抓取高置信源全文以增强证据", retries=1)
def fetch_url(ctx: ToolContext, state: AgentState) -> None:
    """Fetch the full body of a high-value evidence page to strengthen grounding.

    Retrieval only returns short snippets; this reads one full page and stores it
    against the existing SearchResult.result_id so synthesis can ground on it
    without introducing a new evidence source.
    """
    target = _pick_fetch_target(state)
    if target is None:
        emit_stage(
            stage_key="investigation_fetch",
            title="抓取正文",
            status="skipped",
            summary="没有可抓取的新证据页面。",
            details=[],
        )
        return

    emit_stage(
        stage_key="investigation_fetch",
        title="抓取正文",
        status="running",
        summary="正在抓取高价值证据页面的正文以加强判定依据。",
        details=[f"url={target.url}", f"source={target.source_name}", f"tier={target.source_tier}"],
    )
    fetch = None
    if ctx.settings.url_fetch_cache_enabled and ctx.url_fetch_cache is not None:
        try:
            fetch = ctx.url_fetch_cache.read(url=target.url)
        except Exception:
            fetch = None

    cache_hit = fetch is not None
    if fetch is None:
        try:
            fetch = ctx.url_content_extractor.extract(target.url)
        except Exception as exc:
            emit_stage(
                stage_key="investigation_fetch",
                title="抓取正文",
                status="warning",
                summary="正文抓取失败，沿用检索摘要继续。",
                details=[f"url={target.url}", f"error_type={exc.__class__.__name__}"],
            )
            state.fetched_urls.add(target.url)
            return

        if ctx.settings.url_fetch_cache_enabled and ctx.url_fetch_cache is not None:
            try:
                ctx.url_fetch_cache.write(url=target.url, result=fetch)
            except Exception:
                pass

    if fetch is None:
        emit_stage(
            stage_key="investigation_fetch",
            title="抓取正文",
            status="warning",
            summary="正文抓取失败，沿用检索摘要继续。",
            details=[f"url={target.url}"],
        )
        state.fetched_urls.add(target.url)
        return

    body = (fetch.body or "").strip()
    state.fetched_urls.add(target.url)
    if fetch.status != "ok" or not body:
        # Attempt rendered fallback for JS-heavy pages (e.g. 163.com)
        rendered_body = _try_rendered_fallback(target.url, ctx)
        if rendered_body:
            body = rendered_body
            fetch = type(fetch)(status="ok", body=rendered_body)
        else:
            emit_stage(
                stage_key="investigation_fetch",
                title="抓取正文",
                status="warning",
                summary="页面未返回可用正文，沿用检索摘要继续。",
                details=[f"url={target.url}", f"status={fetch.status}"],
            )
            return

    body = body[:_FETCH_BODY_MAX_CHARS]
    state.fetched_bodies[target.result_id] = body
    emit_stage(
        stage_key="investigation_fetch",
        title="抓取正文",
        status="completed",
        summary="已抓到正文，将作为额外依据喂给综合判定。",
        details=[
            f"url={target.url}",
            f"result_id={target.result_id}",
            f"body_chars={len(body)}",
            f"cache={'hit' if cache_hit else 'miss'}",
        ],
    )
    state.record("fetch_url", "抓取证据正文", [f"result_id={target.result_id}"])


@tool("synthesize", description="LLM 综合证据生成结构化判定")
def synthesize(ctx: ToolContext, state: AgentState) -> bool:
    """Try the agent synthesis path. Returns True if it produced a result."""
    # "Attempted" only when the LLM reasoner is actually enabled — on the
    # zero-key off+mock path this stays False so no fallback signal is emitted.
    state.synthesis_attempted = bool(getattr(ctx.agent_reasoner, "enabled", False))
    emit_stage(
        stage_key="agent_synthesis",
        title="Agent 综合判断",
        status="running",
        summary="正在让 LLM 基于检索结果生成事件、claims、verdict 和 timeline。",
        details=[f"enabled={ctx.agent_reasoner.enabled}"],
    )
    agent_synthesis = _synthesize_with_agent(
        ctx,
        request=state.request,
        event=state.resolved_event,
        retrieval_bundle=state.retrieval_bundle,
        fetched_bodies=state.fetched_bodies or None,
    )
    if agent_synthesis is None:
        emit_stage(
            stage_key="agent_synthesis",
            title="Agent 综合判断",
            status="warning",
            summary="Agent 没有稳定产出，退回规则兜底链路。",
            details=[
                f"retrieval_hits={len(state.retrieval_bundle.canonical_results) if state.retrieval_bundle else 0}"
            ],
        )
        return False

    state.final_event = agent_synthesis.event
    state.provider_claims = agent_synthesis.claim_extraction.claims
    state.claim_extraction = agent_synthesis.claim_extraction
    state.verdict = agent_synthesis.verdict
    state.timeline = agent_synthesis.timeline
    state.possibilities = agent_synthesis.possibilities
    state.agent_synthesized = True
    emit_stage(
        stage_key="agent_synthesis",
        title="Agent 综合判断",
        status="completed",
        summary="Agent 路径已产出结构化结论。",
        details=[
            f"event_title={state.final_event.title or 'unknown'}",
            f"claims={len(state.claim_extraction.claims)}",
            f"timeline_nodes={len(state.timeline.nodes)}",
            f"evidence_grade={state.verdict.evidence_grade}",
        ],
    )
    state.record("synthesize", "Agent 综合判断完成")
    return True


@tool("enrich", description="补充事件时间线和可能性场景")
def enrich(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="provider_enrichment",
        title="结构化补全",
        status="running",
        summary="正在调用 provider 对事件和 claims 做结构化补全。",
        details=[],
    )
    try:
        event, provider_claims = ctx.provider_enricher.enrich(state.resolved_event)
        status = "completed"
        summary = "Provider enrichment 已返回结构化事件草稿。"
        details = _event_details(event)
    except Exception as exc:
        event, provider_claims = state.resolved_event, None
        status = "warning"
        summary = "Provider enrichment 失败，继续使用当前事件草稿。"
        details = [f"error_type={exc.__class__.__name__}"]
    state.final_event = event
    state.provider_claims = provider_claims
    emit_stage(
        stage_key="provider_enrichment",
        title="结构化补全",
        status=status,
        summary=summary,
        details=details,
    )
    state.record("enrich", summary, details)


@tool("extract_claims", description="从事件和检索结果中抽取可核查声明")
def extract_claims(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="claim_extraction",
        title="Claim 拆解",
        status="running",
        summary="正在把事件表述拆成可核查的 atomic claims。",
        details=[],
    )
    claim_extraction = ctx.claim_extractor.extract_with_source(
        state.final_event, provider_claims=state.provider_claims
    )
    state.claim_extraction = claim_extraction
    emit_stage(
        stage_key="claim_extraction",
        title="Claim 拆解",
        status="completed",
        summary="Claim 拆解完成。",
        details=_claim_details(claim_extraction.claims),
    )
    state.record("extract_claims", "Claim 拆解完成", _claim_details(claim_extraction.claims))


@tool("per_claim_search", description="对存疑声明进行定向补充检索", parallelizable=True)
def per_claim_search(ctx: ToolContext, state: AgentState) -> None:
    """Per-claim targeted retrieval: for each weak fact claim, run a focused search
    using the claim text as query, then re-judge all claims with the enriched bundle."""
    from backend.app.services.per_claim_retriever import enrich_retrieval_for_claims

    verdict = state.verdict
    if verdict is None or state.retrieval_bundle is None or state.claim_extraction is None:
        return

    has_weak = any(
        cr.claim_type == "fact" and cr.verdict == "insufficient"
        for cr in verdict.claim_results
    )
    if not has_weak:
        emit_stage(
            stage_key="per_claim_retrieval",
            title="逐条补检索",
            status="skipped",
            summary="所有 fact claims 都已有足够证据，跳过。",
            details=[],
        )
        return

    try:
        enriched_bundle = enrich_retrieval_for_claims(
            claims=state.claim_extraction.claims,
            retrieval_bundle=state.retrieval_bundle,
            retrieval_service=ctx.retriever,
            resolved_event=state.resolved_event,
            iteration=state.per_claim_iterations,
        )

        if enriched_bundle is not state.retrieval_bundle:
            state.retrieval_bundle = enriched_bundle
    except Exception as exc:
        emit_log(
            stage_key="per_claim_retrieval",
            level="warning",
            title="逐条补检索失败",
            summary="per_claim_search 异常，沿用已有证据继续。",
            details=[f"error_type={exc.__class__.__name__}"],
        )

    state.record("per_claim_search", f"逐条补检索完成 (iteration {state.per_claim_iterations + 1})")


@tool("re_judge_claims", description="对补充证据后的声明重新判定", retries=1)
def re_judge_claims(ctx: ToolContext, state: AgentState) -> None:
    """Re-judge claims with enriched evidence after per-claim search."""
    if state.retrieval_bundle is None or state.claim_extraction is None:
        return

    emit_stage(
        stage_key="verdict_engine",
        title="Claim 重判",
        status="running",
        summary=f"第 {state.per_claim_iterations + 1} 轮重判：结合新证据重新为每条 claim 打 verdict。",
        details=[f"iteration={state.per_claim_iterations + 1}"],
    )
    try:
        re_verdict = ctx.verdict_engine.evaluate_with_source(
            request=state.request,
            event=state.final_event,
            claims=state.claim_extraction.claims,
            retrieval_bundle=state.retrieval_bundle,
            completion_fn=_build_completion_fn(ctx),
        )
        state.verdict = re_verdict
        emit_stage(
            stage_key="verdict_engine",
            title="Claim 重判",
            status="completed",
            summary="重判完成。",
            details=[
                f"claim_results={len(re_verdict.claim_results)}",
                f"evidence_grade={re_verdict.evidence_grade}",
                f"iteration={state.per_claim_iterations + 1}",
            ],
        )
    except Exception as exc:
        emit_log(
            stage_key="verdict_engine",
            level="warning",
            title="Claim 重判失败",
            summary="re_judge 异常，沿用已有 verdict 继续。",
            details=[f"error_type={exc.__class__.__name__}"],
        )
    state.record("re_judge_claims", f"Claim 重判完成 (iteration {state.per_claim_iterations + 1})")



@tool("judge_claims", description="基于证据对声明进行初次判定", retries=1)
def judge_claims(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="verdict_engine",
        title="Claim 判定",
        status="running",
        summary="正在结合 retrieval hits 为每条 claim 打 verdict。",
        details=[],
    )
    verdict = ctx.verdict_engine.evaluate_with_source(
        request=state.request,
        event=state.final_event,
        claims=state.claim_extraction.claims,
        retrieval_bundle=state.retrieval_bundle,
        completion_fn=_build_completion_fn(ctx),
    )
    state.verdict = verdict
    emit_stage(
        stage_key="verdict_engine",
        title="Claim 判定",
        status="completed",
        summary="Claim verdict 已生成。",
        details=[
            f"claim_results={len(verdict.claim_results)}",
            f"evidence_items={len(verdict.evidence)}",
            f"evidence_grade={verdict.evidence_grade}",
            f"evidence_source={verdict.evidence_source}",
        ],
    )
    state.record("judge_claims", "Claim 判定完成")


@tool("build_timeline", description="构建事件传播时间线")
def build_timeline(ctx: ToolContext, state: AgentState) -> None:
    # If synthesis already produced a timeline (from LLM enrichment), keep it —
    # the heuristic builder would overwrite with less relevant picks.
    if state.timeline and state.timeline.nodes:
        emit_stage(
            stage_key="timeline_builder",
            title="时间线构建",
            status="completed",
            summary="沿用 Agent 综合判断阶段已产出的时间线。",
            details=_timeline_details(state.timeline.nodes, state.timeline.source, state.timeline.completeness, state.timeline.confidence),
        )
        state.record("build_timeline", "沿用已有时间线")
        return

    # When all claims are insufficient with no evidence, retrieval hits are
    # unrelated — building a timeline from them produces misleading nodes.
    verdict = state.verdict
    if verdict and verdict.claim_results and all(
        cr.verdict == "insufficient" and not cr.evidence
        for cr in verdict.claim_results
    ):
        state.timeline = TimelineBuild(nodes=[], source="none", completeness=0, confidence=0)
        emit_stage(
            stage_key="timeline_builder",
            title="时间线构建",
            status="skipped",
            summary="所有核查点均证据不足，跳过时间线构建以避免噪音。",
            details=[],
        )
        state.record("build_timeline", "证据不足，跳过时间线")
        return

    emit_stage(
        stage_key="timeline_builder",
        title="时间线构建",
        status="running",
        summary="正在从检索结果里挑选传播与澄清节点。",
        details=[],
    )
    timeline = ctx.timeline_builder.build_with_source(
        state.final_event, retrieval_bundle=state.retrieval_bundle
    )
    state.timeline = timeline
    emit_stage(
        stage_key="timeline_builder",
        title="时间线构建",
        status="completed",
        summary="时间线节点已生成。",
        details=_timeline_details(timeline.nodes, timeline.source, timeline.completeness, timeline.confidence),
    )
    state.record("build_timeline", "时间线构建完成")


@tool("finalize_report", description="组装最终核查报告", critical=True, retries=2)
def finalize_report(ctx: ToolContext, state: AgentState) -> None:
    from backend.app.services.analyze_pipeline import _report_details

    event = state.final_event
    claim_extraction = state.claim_extraction
    verdict = state.verdict
    timeline = state.timeline
    retrieval_bundle = state.retrieval_bundle
    request = state.request

    provenance = _build_provenance(
        request=request,
        event=event,
        retrieval_bundle=retrieval_bundle,
        claim_source=claim_extraction.source,
        evidence_source=verdict.evidence_source,
        timeline_source=timeline.source,
        provider_used=bool(state.provider_claims) or event.event_source == "provider_enriched",
        synthesis_fell_back=(
            state.synthesis_attempted
            and not state.agent_synthesized
            and claim_extraction.source == "rule"
        ),
    )
    retrieval_hits = retrieval_bundle.to_retrieval_hit_items() if retrieval_bundle is not None else []
    retrieval_diagnostics = retrieval_bundle.to_diagnostics() if retrieval_bundle is not None else None

    emit_stage(
        stage_key="report_build",
        title="生成报告",
        status="running",
        summary="正在组装最终报告、内容核查视图和 pipeline trace。",
        details=[],
    )
    report = ctx.report_builder.build(
        event=event,
        claim_results=verdict.claim_results,
        timeline=timeline.nodes,
        evidence=verdict.evidence,
        retrieval_hits=retrieval_hits,
        retrieval_diagnostics=retrieval_diagnostics,
        evidence_grade=verdict.evidence_grade,
        provenance=provenance,
        original_input=request.raw_input,
        possibilities_override=state.possibilities or None,
    )
    content_check = ctx.content_check_builder.build(
        report=report,
        original_input=request.raw_input,
    )
    pipeline_trace = ctx.pipeline_trace_builder.build(
        request=request,
        normalized_event=state.normalized_event,
        resolved_event=state.resolved_event,
        final_event=event,
        initial_retrieval_bundle=state.initial_retrieval_bundle,
        question_resolution=state.question_resolution,
        follow_up_bundle=state.follow_up_bundle,
        follow_up_used=state.follow_up_used,
        provider_claims=state.provider_claims,
        claim_extraction=claim_extraction,
        verdict=verdict,
        timeline=timeline,
        report=report,
    )
    final_report = report.model_copy(update={"content_check": content_check, "pipeline_trace": pipeline_trace})
    final_report = _apply_clarification_note(ctx.settings, final_report, state.question_resolution)
    state.report = final_report
    emit_stage(
        stage_key="report_build",
        title="生成报告",
        status="completed",
        summary="最终报告已组装完成。",
        details=_report_details(final_report),
    )
    emit_log(
        stage_key="report_build",
        title="分析结束",
        summary="后端已返回最终 Report payload。",
        details=[
            f"mode={final_report.mode}",
            f"fallback_used={final_report.provenance.fallback_used}",
            f"retrieval_provider={final_report.provenance.retrieval_provider or 'unknown'}",
            f"llm_calls={state.token_usage.call_count}",
            f"total_tokens={state.token_usage.total_tokens}",
        ],
    )
    state.record("finalize_report", "报告组装完成")


# --- helpers reused from the legacy pipeline (kept behaviourally identical) ---


def _resolve_question(ctx: ToolContext, *, event, retrieval_bundle):
    try:
        agent_resolution = ctx.agent_reasoner.resolve_question(event=event, retrieval_bundle=retrieval_bundle)
    except Exception as exc:
        emit_log(
            stage_key="question_resolution",
            level="warning",
            title="Agent 消歧失败",
            summary="Agent question resolution 抛错，退回规则消歧。",
            details=[f"error_type={exc.__class__.__name__}"],
        )
        agent_resolution = None
    if agent_resolution is not None:
        return agent_resolution
    return ctx.question_resolver.resolve(event=event, retrieval_bundle=retrieval_bundle)


def _synthesize_with_agent(ctx: ToolContext, *, request, event, retrieval_bundle, fetched_bodies=None):
    try:
        return ctx.agent_reasoner.synthesize(
            request=request,
            event=event,
            retrieval_bundle=retrieval_bundle,
            fetched_bodies=fetched_bodies,
        )
    except Exception as exc:
        emit_log(
            stage_key="agent_synthesis",
            level="warning",
            title="Agent 综合失败",
            summary="Agent synthesis 抛错，退回规则链。",
            details=[f"error_type={exc.__class__.__name__}"],
        )
        return None


def _build_provenance(
    *,
    request,
    event,
    retrieval_bundle,
    claim_source,
    evidence_source,
    timeline_source,
    provider_used,
    synthesis_fell_back: bool = False,
):
    from backend.app.models.schemas import ReportProvenance

    fallback_reasons: list[str] = []
    for reason in [event.fallback_reason, retrieval_bundle.fallback_reason if retrieval_bundle else None]:
        if reason and reason not in fallback_reasons:
            fallback_reasons.append(reason)
    if synthesis_fell_back and LLM_SYNTHESIS_FALLBACK_REASON not in fallback_reasons:
        fallback_reasons.append(LLM_SYNTHESIS_FALLBACK_REASON)

    source_type = "backend_live"
    retrieval_provider = None
    retrieval_cache_status = None
    if retrieval_bundle is not None:
        retrieval_provider = retrieval_bundle.provider_name or None
        retrieval_cache_status = retrieval_bundle.cache_status or None
        if retrieval_bundle.provider_name == "mock" or evidence_source == "retrieval_mock":
            source_type = "backend_mock"

    return ReportProvenance(
        source_type=source_type,
        event_source=event.event_source,
        claim_source=claim_source,
        evidence_source=evidence_source,
        timeline_source=timeline_source,
        retrieval_provider=retrieval_provider,
        retrieval_cache_status=retrieval_cache_status,
        provider_used=provider_used,
        fallback_used=event.fallback_used or bool(retrieval_bundle and retrieval_bundle.fallback_used) or bool(fallback_reasons),
        fallback_reasons=fallback_reasons,
    )
