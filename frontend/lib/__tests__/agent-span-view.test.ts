import { describe, expect, it } from "vitest";
import { llmSpanView, summarizeLlmSpans } from "@/lib/agent-span-view";
import type { AgentTraceSpan } from "@/types/report";

function span(metadata: Record<string, unknown> = {}, token_usage: Record<string, number> = {}): AgentTraceSpan {
  return {
    span_id: "s", parent_span_id: null, action: "invoke", start_time: 1, end_time: 2,
    duration_ms: 1000, success: true, error_type: null, error_message: null, token_usage, metadata,
  };
}

describe("LLM span views", () => {
  it("keeps ordinary and legacy spans out of LLM usage coverage", () => {
    const legacy = span({ model: "legacy-model" }, { total: 20 });
    expect(llmSpanView(legacy)).toBeNull();
    expect(summarizeLlmSpans([legacy])).toEqual({ calls: 0, reported: 0, coverage: null });
  });

  it("distinguishes missing usage and missing individual fields from reported zero", () => {
    const unreported = llmSpanView(span({ span_kind: "LLM", usage_reported: false }, { prompt: 0, total: 0 }));
    expect(unreported?.tokens).toEqual({ prompt: null, completion: null, total: null, cacheRead: null });
    const reported = llmSpanView(span({ span_kind: "LLM", usage_reported: true }, { prompt: 10, completion: 2, total: 12, cache_read: 0 }));
    expect(reported?.tokens).toEqual({ prompt: 10, completion: 2, total: 12, cacheRead: 0 });
    expect(llmSpanView(span({ span_kind: "LLM", usage_reported: true }, { total: 12 }))?.tokens.prompt).toBeNull();
  });

  it("sanitizes malformed telemetry without exposing arbitrary metadata", () => {
    const view = llmSpanView(span({
      span_kind: "LLM", model: [], provider: {}, attempt: 0, status: "__proto__",
      first_token_ms: Infinity, usage_reported: "true", response_chars: -5,
      context: { message_count: "2", tool_count: 2.5, system_chars: NaN, changed: true,
        changed_fields: ["messages", "secret prompt", "__proto__", "messages", {}, "stream_options"],
        raw_prompt: "sensitive text" },
    }));
    expect(view?.model).toBeNull();
    expect(view?.provider).toBeNull();
    expect(view?.attempt).toBeNull();
    expect(view?.firstTokenMs).toBeNull();
    expect(view?.responseChars).toBeNull();
    expect(view?.status).toBe("未知");
    expect(view?.context.every(({ value }) => value === null)).toBe(true);
    expect(view?.contextChange).toBe("与前次请求不同：消息、流式选项");
    expect(JSON.stringify(view)).not.toContain("sensitive text");
    expect(JSON.stringify(view)).not.toContain("secret prompt");
  });

  it("handles malformed context values and nullable first comparisons", () => {
    for (const context of [null, [], "bad", { changed: null }]) {
      expect(llmSpanView(span({ span_kind: "LLM", context }))?.contextChange).toBe("无可比较的前次请求");
    }
    expect(llmSpanView(span({ span_kind: "LLM", context: { changed: false } }))?.contextChange).toBe("与前次请求相同");
  });

  it("counts every retry attempt and only includes explicitly reported usage", () => {
    const spans = [
      span({ span_kind: "LLM", call_id: "call", attempt: 1, usage_reported: false }),
      span({ span_kind: "LLM", call_id: "call", attempt: 2, usage_reported: true }, { total: 19 }),
      span({ span_kind: "AGENT" }, { total: 19 }),
    ];
    expect(summarizeLlmSpans(spans)).toEqual({ calls: 2, reported: 1, coverage: 50 });
    expect(llmSpanView(spans[1])?.attempt).toBe(2);
    expect(llmSpanView(spans[1])?.tokens.total).toBe(19);
  });

  it("keeps valid zero timings and context counts", () => {
    const view = llmSpanView(span({ span_kind: "LLM", first_token_ms: 0, context: { message_count: 0, tool_count: 0 } }));
    expect(view?.firstTokenMs).toBe(0);
    expect(view?.context.find(({ key }) => key === "tool_count")?.value).toBe(0);
  });
});
