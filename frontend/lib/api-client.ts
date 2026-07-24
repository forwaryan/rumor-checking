import type {
  AnalyzeRequest,
  AnalysisLiveApiCallEvent,
  AnalysisLiveCompleteEvent,
  AnalysisLiveErrorEvent,
  AnalysisLiveEvent,
  AnalysisLiveLogEvent,
  AnalysisLiveReportEvent,
  AnalysisLiveRetrievalEvent,
  AnalysisLiveSessionEvent,
  AnalysisLiveStageEvent,
  AnalysisLiveStatus,
  ClaimResult,
  ClaimSourceType,
  ConfidenceValue,
  ContentCheck,
  Evidence,
  EvidenceSourceType,
  Event,
  EventSourceType,
  HealthResponse,
  Investigation,
  OutputMode,
  PipelineTrace,
  PipelineStepStatus,
  ProbabilityBasis,
  Report,
  ReportProvenance,
  RetrievalDiagnostics,
  RetrievalResultItem,
  ReportSourceType,
  TimelineNode,
  TimelineSourceType,
  Verdict,
} from "@/types/report";

const DEFAULT_API_BASE = "";
const reportSourceTypes = [
  "backend_live",
  "backend_mock",
] as const satisfies readonly ReportSourceType[];
const eventSourceTypes = ["input_normalized", "url_extract", "provider_enriched", "retrieval_resolved"] as const satisfies readonly EventSourceType[];
const claimSourceTypes = ["rule", "provider", "provider_plus_rule"] as const satisfies readonly ClaimSourceType[];
const evidenceSourceTypes = ["retrieval_live", "retrieval_mock", "request_mock", "none"] as const satisfies readonly EvidenceSourceType[];
const timelineSourceTypes = ["retrieval", "input_seed", "none"] as const satisfies readonly TimelineSourceType[];
const pipelineStepStatuses = ["completed", "warning", "skipped", "error"] as const satisfies readonly PipelineStepStatus[];
const liveStatuses = ["running", "completed", "warning", "skipped", "error"] as const satisfies readonly AnalysisLiveStatus[];

function getApiBase() {
  const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return configuredBase ? configuredBase.replace(/\/$/, "") : DEFAULT_API_BASE;
}

export class ApiClientError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function ensureString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function ensureStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function ensureOptionalString(value: unknown) {
  return typeof value === "string" ? value : null;
}

function ensureMode(value: unknown, fallback: OutputMode = "safe_mode"): OutputMode {
  return value === "complete_mode" || value === "partial_mode" || value === "safe_mode"
    ? value
    : fallback;
}

function ensureVerdict(value: unknown): Verdict {
  return value === "supported" ||
    value === "refuted" ||
    value === "insufficient" ||
    value === "conflicting"
    ? value
    : "insufficient";
}

function ensureConfidence(value: unknown): ConfidenceValue {
  if (typeof value === "number" && value >= 0 && value <= 1) {
    return value;
  }

  return value === "high" || value === "medium" || value === "low" ? value : "low";
}

function ensureLiteral<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return typeof value === "string" && allowed.includes(value as T) ? (value as T) : null;
}

function ensureProbability(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return Math.max(0, Math.min(100, value));
}

function ensureProbabilityBasis(value: unknown): ProbabilityBasis | null {
  return ensureLiteral(value, ["evidence", "prior"] as const);
}

function ensureTimestamp(value: unknown) {
  return ensureString(value, new Date().toISOString());
}

function parseEvidence(value: unknown): Evidence[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .filter(isObject)
    .map((item) => ({
      title: ensureString(item.title, "未命名证据"),
      url: ensureString(item.url, "https://example.org/demo/missing-source"),
      source_name: ensureString(item.source_name, "来源待补充"),
      published_at: ensureString(item.published_at, new Date().toISOString()),
      snippet: ensureString(item.snippet, "暂无摘要"),
      relevance_reason: ensureString(item.relevance_reason, "未提供相关性说明"),
      source_tier:
        item.source_tier === "S" ||
        item.source_tier === "A" ||
        item.source_tier === "B" ||
        item.source_tier === "C"
          ? item.source_tier
          : "C",
    }));
}

function parseRetrievalResults(value: unknown): RetrievalResultItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter(isObject)
    .map((item) => ({
      title: ensureString(item.title, "未命名结果"),
      url: ensureString(item.url),
      snippet: ensureString(item.snippet),
      source_name: ensureString(item.source_name, "来源待补充"),
      source_tier:
        item.source_tier === "S" ||
        item.source_tier === "A" ||
        item.source_tier === "B" ||
        item.source_tier === "C"
          ? item.source_tier
          : "C",
      published_at: ensureString(item.published_at),
      category: ensureString(item.category),
    }));
}

function parseEvent(value: unknown, mode: OutputMode): Event {
  const event = isObject(value) ? value : {};

  return {
    title: ensureString(event.title, "未命名事件"),
    summary: ensureString(event.summary, "当前没有足够上下文来生成事件摘要。"),
    source_url: ensureString(event.source_url, "https://example.org/demo/missing-source"),
    source_name: ensureString(event.source_name, "来源待补充"),
    published_at: ensureString(event.published_at, new Date().toISOString()),
    keywords: ensureStringArray(event.keywords),
    mode: ensureMode(event.mode, mode),
  };
}

function parseTimeline(value: unknown): TimelineNode[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(isObject).map((item) => ({
    node_type:
      item.node_type === "origin" ||
      item.node_type === "amplification" ||
      item.node_type === "peak" ||
      item.node_type === "turn" ||
      item.node_type === "clarification"
        ? item.node_type
        : "origin",
    title: ensureString(item.title, "未命名节点"),
    url: ensureString(item.url, "https://example.org/demo/missing-node"),
    source_name: ensureString(item.source_name, "来源待补充"),
    published_at: ensureString(item.published_at, new Date().toISOString()),
    summary: ensureString(item.summary, "暂无节点摘要"),
    why_selected: ensureString(item.why_selected, "未提供入选原因"),
  }));
}

function parseClaimResults(value: unknown): ClaimResult[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(isObject).map((item) => ({
    claim: ensureString(item.claim, "未命名 claim"),
    claim_type:
      item.claim_type === "fact" ||
      item.claim_type === "opinion" ||
      item.claim_type === "prediction" ||
      item.claim_type === "unverifiable"
        ? item.claim_type
        : "unverifiable",
    verdict: ensureVerdict(item.verdict),
    confidence: ensureConfidence(item.confidence),
    truth_probability: ensureProbability(item.truth_probability),
    probability_basis: ensureProbabilityBasis(item.probability_basis),
    evidence: parseEvidence(item.evidence),
    notes: ensureString(item.notes, "未提供补充说明"),
  }));
}

function parseReportProvenance(value: unknown): ReportProvenance | null {
  if (!isObject(value)) {
    return null;
  }

  const sourceType = ensureLiteral(value.source_type, reportSourceTypes);
  const eventSource = ensureLiteral(value.event_source, eventSourceTypes);
  const claimSource = ensureLiteral(value.claim_source, claimSourceTypes);
  const evidenceSource = ensureLiteral(value.evidence_source, evidenceSourceTypes);
  const timelineSource = ensureLiteral(value.timeline_source, timelineSourceTypes);

  if (!sourceType || !eventSource || !claimSource || !evidenceSource || !timelineSource) {
    return null;
  }

  return {
    source_type: sourceType,
    event_source: eventSource,
    claim_source: claimSource,
    evidence_source: evidenceSource,
    timeline_source: timelineSource,
    retrieval_provider: ensureOptionalString(value.retrieval_provider),
    retrieval_cache_status: ensureOptionalString(value.retrieval_cache_status),
    provider_used: value.provider_used === true,
    fallback_used: value.fallback_used === true,
    fallback_reasons: ensureStringArray(value.fallback_reasons),
  };
}

function parseRetrievalDiagnostics(value: unknown): RetrievalDiagnostics | null {
  if (!isObject(value)) {
    return null;
  }

  return {
    query: ensureString(value.query),
    provider_name: ensureOptionalString(value.provider_name),
    cache_status: ensureOptionalString(value.cache_status),
    retrieved_at: ensureOptionalString(value.retrieved_at),
    raw_result_count: typeof value.raw_result_count === "number" ? value.raw_result_count : 0,
    canonical_result_count: typeof value.canonical_result_count === "number" ? value.canonical_result_count : 0,
    failure_detail: ensureOptionalString(value.failure_detail),
  };
}

function parseInvestigation(value: unknown): Investigation | null {
  if (!isObject(value)) {
    return null;
  }

  const thinkingProcess = Array.isArray(value.thinking_process)
    ? value.thinking_process
        .filter(isObject)
        .map((item) => ({
          title: ensureString(item.title, "核查步骤"),
          detail: ensureString(item.detail, "暂无步骤详情"),
        }))
    : [];

  const possibilities = Array.isArray(value.possibilities)
    ? value.possibilities
        .filter(isObject)
        .map((item) => {
          const likelihood: "high" | "medium" | "low" =
            item.likelihood === "high" || item.likelihood === "medium" || item.likelihood === "low"
              ? item.likelihood
              : "low";

          return {
            scenario: ensureString(item.scenario, "待核查可能性"),
            likelihood,
            probability: ensureProbability(item.probability),
            basis: ensureProbabilityBasis(item.basis),
            summary: ensureString(item.summary, "暂无可能性说明"),
          };
        })
    : [];

  return {
    question: ensureString(value.question, "待核查问题"),
    reframed_question: ensureString(value.reframed_question, "待核查命题"),
    thinking_process: thinkingProcess,
    possibilities,
    final_conclusion: ensureString(value.final_conclusion, "暂无最终结论"),
  };
}

function parseContentCheckItems(value: unknown): ContentCheck["likely_true"] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(isObject).map((item) => ({
    claim: ensureString(item.claim, "待核查 claim"),
    claim_type:
      item.claim_type === "fact" ||
      item.claim_type === "opinion" ||
      item.claim_type === "prediction" ||
      item.claim_type === "unverifiable"
        ? item.claim_type
        : "unverifiable",
    verdict: ensureVerdict(item.verdict),
    confidence: ensureConfidence(item.confidence),
    truth_probability: ensureProbability(item.truth_probability),
    probability_basis: ensureProbabilityBasis(item.probability_basis),
    reason: ensureString(item.reason, "当前没有返回补充说明。"),
  }));
}

function parseContentCheck(value: unknown): ContentCheck | null {
  if (!isObject(value)) {
    return null;
  }

  const possibleAnswers = Array.isArray(value.possible_answers)
    ? value.possible_answers.filter(isObject).map((item) => ({
        angle: ensureString(item.angle, "回答建议"),
        answer: ensureString(item.answer, "当前没有返回建议话术。"),
      }))
    : [];

  return {
    likely_true: parseContentCheckItems(value.likely_true),
    likely_false: parseContentCheckItems(value.likely_false),
    controversial: parseContentCheckItems(value.controversial),
    opinions: parseContentCheckItems(value.opinions),
    uncertain: parseContentCheckItems(value.uncertain),
    possible_answers: possibleAnswers,
  };
}

function parsePipelineTrace(value: unknown): PipelineTrace | null {
  if (!isObject(value) || !Array.isArray(value.steps)) {
    return null;
  }

  return {
    steps: value.steps.filter(isObject).map((item) => ({
      stage_key: ensureString(item.stage_key, "unknown_stage"),
      title: ensureString(item.title, "链路步骤"),
      status: ensureLiteral(item.status, pipelineStepStatuses) ?? "warning",
      summary: ensureString(item.summary, "当前步骤没有返回摘要。"),
      details: ensureStringArray(item.details),
    })),
  };
}

export function parseReport(value: unknown): Report {
  if (!isObject(value)) {
    throw new ApiClientError("\u65e0\u6cd5\u89e3\u6790\u540e\u7aef\u8fd4\u56de\u7684 Report\u3002");
  }

  const mode = ensureMode(value.mode);

  const report: Report = {
    mode,
    event: parseEvent(value.event, mode),
    timeline: parseTimeline(value.timeline),
    claim_results: parseClaimResults(value.claim_results),
    final_summary: ensureString(value.final_summary, "\u7f3a\u5c11\u6700\u7ec8\u603b\u7ed3\u5b57\u6bb5"),
    risks: ensureStringArray(value.risks),
    sources: parseEvidence(value.sources),
    retrieval_hits: parseEvidence(value.retrieval_hits),
    retrieval_diagnostics: parseRetrievalDiagnostics(value.retrieval_diagnostics),
    investigation: parseInvestigation(value.investigation),
    content_check: parseContentCheck(value.content_check),
    pipeline_trace: parsePipelineTrace(value.pipeline_trace),
    provenance: parseReportProvenance(value.provenance),
  };

  return Object.assign(report, {
    overall_credibility_score: value.overall_credibility_score,
    overall_credibility_label: value.overall_credibility_label,
    score_breakdown: value.score_breakdown,
    claim_contributions: value.claim_contributions,
    timeline_confidence: value.timeline_confidence,
    independent_source_count: value.independent_source_count,
  }) as Report;
}

async function parseJson<T>(response: Response) {
  if (!response.ok) {
    const detail = await response.text();
    let parsedMessage: string | null = null;
    try {
      const payload = JSON.parse(detail) as { error?: { message?: string } };
      parsedMessage = payload.error?.message?.trim() || null;
    } catch {}
    throw new ApiClientError(parsedMessage || detail || "请求失败", response.status);
  }

  return (await response.json()) as T;
}

function parseLiveEvent(value: unknown): AnalysisLiveEvent {
  if (!isObject(value)) {
    throw new ApiClientError("无法解析流式分析事件。");
  }

  const type = ensureString(value.type);
  const emittedAt = ensureTimestamp(value.emitted_at);

  if (type === "session") {
    const event: AnalysisLiveSessionEvent = {
      type,
      emitted_at: emittedAt,
      run_id: ensureString(value.run_id),
      trace_id: ensureString(value.trace_id),
      input_type: ensureString(value.input_type, "auto"),
      summary: ensureString(value.summary),
      preview: ensureString(value.preview),
    };
    return event;
  }

  if (type === "stage") {
    const event: AnalysisLiveStageEvent = {
      type,
      emitted_at: emittedAt,
      stage_key: ensureString(value.stage_key),
      title: ensureString(value.title, "处理阶段"),
      status: ensureLiteral(value.status, liveStatuses) ?? "running",
      summary: ensureString(value.summary),
      details: ensureStringArray(value.details),
    };
    return event;
  }

  if (type === "api_call") {
    const event: AnalysisLiveApiCallEvent = {
      type,
      emitted_at: emittedAt,
      call_type: ensureString(value.call_type, "http"),
      status: ensureLiteral(value.status, liveStatuses) ?? "running",
      title: ensureString(value.title, "外部调用"),
      summary: ensureString(value.summary),
      details: ensureStringArray(value.details),
      stage_key: ensureOptionalString(value.stage_key),
    };
    return event;
  }

  if (type === "retrieval") {
    const event: AnalysisLiveRetrievalEvent = {
      type,
      emitted_at: emittedAt,
      stage_key: ensureString(value.stage_key),
      query_label: ensureString(value.query_label),
      query: ensureString(value.query),
      provider_name: ensureString(value.provider_name, "unknown"),
      summary: ensureString(value.summary),
      details: ensureStringArray(value.details),
      results: parseRetrievalResults(value.results),
    };
    return event;
  }

  if (type === "log") {
    const rawLevel = ensureString(value.level, "info");
    const event: AnalysisLiveLogEvent = {
      type,
      emitted_at: emittedAt,
      title: ensureString(value.title, "运行日志"),
      summary: ensureString(value.summary),
      details: ensureStringArray(value.details),
      level: rawLevel === "warning" || rawLevel === "error" ? rawLevel : "info",
      stage_key: ensureOptionalString(value.stage_key),
    };
    return event;
  }

  if (type === "report") {
    const event: AnalysisLiveReportEvent = {
      type,
      emitted_at: emittedAt,
      run_id: ensureString(value.run_id),
      summary: ensureString(value.summary),
      report: parseReport(value.report),
    };
    return event;
  }

  if (type === "error") {
    const event: AnalysisLiveErrorEvent = {
      type,
      emitted_at: emittedAt,
      run_id: ensureString(value.run_id),
      code: ensureString(value.code, "internal_server_error"),
      message: ensureString(value.message, "分析失败。"),
      status_code: typeof value.status_code === "number" ? value.status_code : 500,
      details: ensureStringArray(value.details),
    };
    return event;
  }

  if (type === "complete") {
    const event: AnalysisLiveCompleteEvent = {
      type,
      emitted_at: emittedAt,
      run_id: ensureString(value.run_id),
      success: value.success === true,
      summary: ensureString(value.summary),
    };
    return event;
  }

  throw new ApiClientError(`未知流式事件类型: ${type || "unknown"}`);
}

export async function analyzeReport(request: AnalyzeRequest): Promise<Report> {
  const response = await fetch(`${getApiBase()}/api/v1/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    cache: "no-store",
  });

  const payload = await parseJson<unknown>(response);
  return parseReport(payload);
}

export async function analyzeReportStream(
  request: AnalyzeRequest,
  onEvent: (event: AnalysisLiveEvent) => void,
): Promise<Report> {
  const response = await fetch(`${getApiBase()}/api/v1/analyze/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.text();
    let parsedMessage: string | null = null;
    try {
      const payload = JSON.parse(detail) as { error?: { message?: string } };
      parsedMessage = payload.error?.message?.trim() || null;
    } catch {}
    throw new ApiClientError(parsedMessage || detail || "请求失败", response.status);
  }

  if (!response.body) {
    throw new ApiClientError("浏览器没有返回可读取的流式响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalReport: Report | null = null;
  let streamError: ApiClientError | null = null;

  const handleLine = (line: string) => {
    if (!line) {
      return;
    }
    const rawEvent = JSON.parse(line) as unknown;
    // Transport-level keepalive emitted during slow backend work; not an
    // analysis event, so skip it before strict parsing.
    if (rawEvent && typeof rawEvent === "object" && (rawEvent as { type?: unknown }).type === "heartbeat") {
      return;
    }
    const event = parseLiveEvent(rawEvent);
    onEvent(event);
    if (event.type === "report") {
      finalReport = event.report;
    }
    if (event.type === "error") {
      const message = [event.message, ...event.details].filter(Boolean).join(" ");
      streamError = new ApiClientError(message || event.code, event.status_code);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      handleLine(line);
      newlineIndex = buffer.indexOf("\n");
    }

    if (done) {
      handleLine(buffer.trim());
      break;
    }
  }

  if (streamError) {
    throw streamError;
  }
  if (!finalReport) {
    throw new ApiClientError("流式分析结束了，但没有拿到最终 Report。");
  }
  return finalReport;
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${getApiBase()}/api/v1/health`, {
    cache: "no-store",
  });

  const payload = await parseJson<unknown>(response);

  if (isObject(payload) && typeof payload.status === "string") {
    return {
      status:
        payload.status === "ok" || payload.status === "degraded" || payload.status === "error"
          ? payload.status
          : "error",
      detail: typeof payload.detail === "string" ? payload.detail : undefined,
    };
  }

  return { status: "ok" };
}

export interface ModelsResponse {
  models: string[];
  default: string;
}

export async function getModels(): Promise<ModelsResponse> {
  const response = await fetch(`${getApiBase()}/api/v1/models`, { cache: "no-store" });
  const payload = await parseJson<unknown>(response);
  if (isObject(payload) && Array.isArray(payload.models)) {
    const models = payload.models.filter((m): m is string => typeof m === "string");
    return {
      models,
      default: typeof payload.default === "string" ? payload.default : models[0] ?? "",
    };
  }
  return { models: [], default: "" };
}
