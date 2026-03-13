import { describe, expect, it } from "vitest";
import { collectEvidence, getStatusFromMode, validateInput } from "@/lib/report-utils";
import type { Report } from "@/types/report";

const sampleReport: Report = {
  mode: "partial_mode",
  event: {
    title: "测试事件",
    summary: "测试摘要",
    source_url: "https://example.org/input/text-news",
    source_name: "用户提供文本",
    published_at: "2026-03-03T00:00:00+08:00",
    keywords: ["测试"],
    mode: "partial_mode",
  },
  timeline: [],
  claim_results: [
    {
      claim: "claim A",
      claim_type: "fact",
      verdict: "supported",
      confidence: "high",
      evidence: [
        {
          title: "较早证据",
          url: "https://example.org/evidence/early",
          source_name: "来源 A",
          published_at: "2026-03-01T09:00:00+08:00",
          snippet: "较早证据摘要",
          relevance_reason: "用于校验排序",
          source_tier: "A",
        },
        {
          title: "重复证据",
          url: "https://example.org/evidence/shared",
          source_name: "来源 B",
          published_at: "2026-03-02T09:00:00+08:00",
          snippet: "重复证据摘要",
          relevance_reason: "用于校验去重",
          source_tier: "S",
        },
      ],
      notes: "test",
    },
  ],
  final_summary: "test",
  risks: [],
  sources: [
    {
      title: "重复证据",
      url: "https://example.org/evidence/shared",
      source_name: "来源 B",
      published_at: "2026-03-02T09:00:00+08:00",
      snippet: "重复证据摘要",
      relevance_reason: "用于校验去重",
      source_tier: "S",
    },
    {
      title: "较晚证据",
      url: "https://example.org/evidence/late",
      source_name: "来源 C",
      published_at: "2026-03-04T09:00:00+08:00",
      snippet: "较晚证据摘要",
      relevance_reason: "用于校验倒序排序",
      source_tier: "A",
    },
  ],
};

describe("report-utils", () => {
  it("validates required input", () => {
    expect(validateInput("   ", "text")).toBe("请先输入 URL、正文或问题，再开始分析。");
    expect(validateInput("not-a-url", "url")).toBe("当前输入类型是 URL，请粘贴一个有效链接。");
    expect(validateInput("https://example.org/news", "url")).toBeNull();
  });

  it("maps output mode to status", () => {
    expect(getStatusFromMode("complete_mode")).toBe("complete");
    expect(getStatusFromMode("partial_mode")).toBe("partial");
    expect(getStatusFromMode("safe_mode")).toBe("safe_mode");
  });

  it("deduplicates and sorts evidence by latest publish time first", () => {
    const evidence = collectEvidence(sampleReport);

    expect(evidence).toHaveLength(3);
    expect(evidence[0]?.url).toBe("https://example.org/evidence/late");
    expect(evidence[1]?.url).toBe("https://example.org/evidence/shared");
    expect(evidence[2]?.url).toBe("https://example.org/evidence/early");
  });
});
