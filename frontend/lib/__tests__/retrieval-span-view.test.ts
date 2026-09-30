import { describe, expect, it } from "vitest";
import type { AgentTraceSpan } from "@/types/report";
import { retrievalSpanView } from "@/lib/retrieval-span-view";

function span(metadata: Record<string, unknown>): AgentTraceSpan {
  return { span_id: "s", parent_span_id: null, action: "retrieval.round", start_time: 1, end_time: 2,
    duration_ms: 1000, success: true, error_type: null, error_message: null, token_usage: {}, metadata };
}

describe("retrieval trace display", () => {
  it("keeps unrelated and unknown operations out of retrieval details", () => {
    expect(retrievalSpanView(span({ span_kind: "LLM" }))).toBeNull();
    expect(retrievalSpanView(span({ observability_type: "retrieval", operation: "private query" }))).toBeNull();
  });
  it("distinguishes reported zero from missing or malformed counts", () => {
    const view = retrievalSpanView(span({ observability_type: "retrieval", operation: "query", status: "empty",
      raw_result_count: 0, selected_result_count: -1, duplicate_count: Infinity, failure_count: "1", query_chars: 3.5 }));
    expect(view?.metrics).toEqual([{ key: "raw_result_count", label: "原始结果数", value: 0 }]);
    expect(view?.status).toBe("无结果");
  });
  it("explains partial failure, stale cache, and soft filtering separately", () => {
    const view = retrievalSpanView(span({ observability_type: "retrieval", operation: "selection", status: "partial",
      cache_status: "stale_hit", soft_relevance_fallback: true, fallback_used: true,
      filtered_navigation_count: 2, filtered_relevance_count: 0, evidence_grade: "C" }));
    expect(view).toMatchObject({ status: "部分失败", cache: "使用过期缓存", softRelevanceFallback: true, fallbackUsed: true, evidenceGrade: "C" });
    expect(view?.filters.map((item) => item.value)).toEqual([2, 0]);
  });
  it("does not expose arbitrary metadata, error text, or prototype properties", () => {
    const view = retrievalSpanView(span({ observability_type: "retrieval", operation: "round", status: "__proto__",
      cache_status: "constructor", evidence_grade: "private", provider: "private", query: "private",
      error: "private", arbitrary_count: 3, raw_result_count: NaN }));
    expect(view).toMatchObject({ status: "未知", cache: null, evidenceGrade: null, metrics: [] });
    expect(JSON.stringify(view)).not.toContain("private");
  });
});
