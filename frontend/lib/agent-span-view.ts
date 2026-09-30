import type { AgentTraceSpan } from "@/types/report";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

const contextFields = {
  message_count: "消息数", system_chars: "系统字符", user_chars: "用户字符",
  assistant_chars: "助手字符", tool_chars: "工具字符", tool_count: "工具数",
  request_bytes: "JSON 字节（紧凑）",
} as const;

const changeLabels: Record<string, string> = {
  messages: "消息", tools: "工具定义", model: "模型",
  temperature: "温度", max_tokens: "输出上限", response_format: "响应格式",
  stream: "流式模式", stream_options: "流式选项",
};

/** Read only known telemetry fields; never render arbitrary context or field names. */
export function llmSpanView(span: AgentTraceSpan) {
  const meta = record(span.metadata);
  if (meta.span_kind !== "LLM") return null;
  const context = record(meta.context);
  const usageReported = meta.usage_reported === true;
  const usage = usageReported ? record(span.token_usage) : {};
  const changedLabels = Array.isArray(context.changed_fields)
    ? [...new Set(context.changed_fields.flatMap((key) =>
      typeof key === "string" && Object.hasOwn(changeLabels, key) ? [changeLabels[key]] : []))]
    : [];
  const changed = context.changed === true ? true : context.changed === false ? false : null;
  const attempt = count(meta.attempt);
  return {
    model: text(meta.model), provider: text(meta.provider), stage: text(meta.stage_key),
    callId: text(meta.call_id), attempt: attempt !== null && attempt > 0 ? attempt : null,
    status: ({ ok: "完成", empty: "空响应", error: "失败", truncated: "响应截断" } as Record<string, string>)[
      typeof meta.status === "string" && ["ok", "empty", "error", "truncated"].includes(meta.status) ? meta.status : ""
    ] ?? "未知",
    usageReported,
    tokens: { prompt: count(usage.prompt), completion: count(usage.completion), total: count(usage.total), cacheRead: count(usage.cache_read) },
    firstTokenMs: typeof meta.first_token_ms === "number" && Number.isFinite(meta.first_token_ms) && meta.first_token_ms >= 0 ? meta.first_token_ms : null,
    responseChars: count(meta.response_chars), reasoningChars: count(meta.reasoning_chars),
    toolCallCount: count(meta.tool_call_count), statusCode: count(meta.status_code),
    context: Object.entries(contextFields).map(([key, label]) => ({ key, label, value: count(context[key]) })),
    contextChange: changed === null ? "无可比较的前次请求" : changed === false ? "与前次请求相同" :
      `与前次请求不同${changedLabels.length ? `：${changedLabels.join("、")}` : ""}`,
  };
}

export function summarizeLlmSpans(spans: AgentTraceSpan[]) {
  const calls = spans.map(llmSpanView).filter((view) => view !== null);
  const reported = calls.filter((view) => view.usageReported).length;
  return { calls: calls.length, reported, coverage: calls.length ? Math.round(reported / calls.length * 100) : null };
}
