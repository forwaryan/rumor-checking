import type {
  AnalyzeRequest,
  ClaimResult,
  ConfidenceValue,
  Evidence,
  Event,
  HealthResponse,
  OutputMode,
  Report,
  TimelineNode,
  Verdict,
} from "@/types/report";

const DEFAULT_API_BASE = "";

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
    evidence: parseEvidence(item.evidence),
    notes: ensureString(item.notes, "未提供补充说明"),
  }));
}

export function parseReport(value: unknown): Report {
  if (!isObject(value)) {
    throw new ApiClientError("后端返回了无法解析的 Report。");
  }

  const mode = ensureMode(value.mode);

  return {
    mode,
    event: parseEvent(value.event, mode),
    timeline: parseTimeline(value.timeline),
    claim_results: parseClaimResults(value.claim_results),
    final_summary: ensureString(value.final_summary, "暂无综合结论。"),
    risks: ensureStringArray(value.risks),
    sources: parseEvidence(value.sources),
  };
}

async function parseJson<T>(response: Response) {
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiClientError(detail || "请求失败", response.status);
  }

  return (await response.json()) as T;
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
