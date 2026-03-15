import { describe, expect, it } from "vitest";
import {
  buildFallbackReport,
  collectEvidence,
  getReportProvenanceMeta,
  getStatusFromMode,
  getVerificationScoreMeta,
  validateInput,
} from "@/lib/report-utils";
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
  provenance: {
    source_type: "backend_live",
    event_source: "provider_enriched",
    claim_source: "provider_plus_rule",
    evidence_source: "retrieval_live",
    timeline_source: "retrieval",
    retrieval_provider: "serpapi",
    retrieval_cache_status: "miss",
    provider_used: true,
    fallback_used: false,
    fallback_reasons: [],
  },
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

  it("labels backend_live reports with human-readable provenance", () => {
    const meta = getReportProvenanceMeta(sampleReport, null);

    expect(meta?.sourceLabel).toBe("实时联网结果");
    expect(meta?.detailBadges).toContain("证据: 联网检索");
    expect(meta?.detailBadges).toContain("检索: SERPAPI");
    expect(meta?.tone).toBe("live");
  });

  it("marks backend_mock results as mock instead of real live analysis", () => {
    const meta = getReportProvenanceMeta(
      {
        ...sampleReport,
        provenance: {
          ...sampleReport.provenance!,
          source_type: "backend_mock",
          evidence_source: "retrieval_mock",
          provider_used: false,
          retrieval_provider: null,
        },
      },
      null,
    );

    expect(meta?.sourceLabel).toBe("后端模拟结果");
    expect(meta?.caution).toContain("mock 结果");
  });

  it("marks backend_replay results as replayed rather than current input analysis", () => {
    const meta = getReportProvenanceMeta(
      {
        ...sampleReport,
        provenance: {
          ...sampleReport.provenance!,
          source_type: "backend_replay",
          evidence_source: "request_mock",
        },
      },
      null,
    );

    expect(meta?.sourceLabel).toBe("回放结果");
    expect(meta?.caution).toContain("实时 analyze");
  });

  it("marks local demo payloads as demo data", () => {
    const meta = getReportProvenanceMeta(sampleReport, {
      sourceKind: "demo_payload",
      fallbackReason: "backend_offline",
    });

    expect(meta?.sourceLabel).toBe("本地演示数据");
    expect(meta?.fallbackLabel).toBe("后端离线回退");
    expect(meta?.caution).toContain("claim");
  });

  it("marks frontend fallback results as conservative shells", () => {
    const fallbackReport = buildFallbackReport("最近有个女网红脑出血死了真的假的？", "question");
    const meta = getReportProvenanceMeta(fallbackReport, {
      sourceKind: "frontend_fallback",
      fallbackReason: "analyze_failed",
    });

    expect(meta?.sourceLabel).toBe("前端保守回退");
    expect(meta?.fallbackLabel).toBe("请求失败回退");
    expect(meta?.summary).toContain("前端保守回退壳");
  });

  it("defaults to an unknown provenance label when metadata is missing", () => {
    const meta = getReportProvenanceMeta(
      {
        ...sampleReport,
        provenance: null,
      },
      null,
    );

    expect(meta?.sourceLabel).toBe("来源待确认");
    expect(meta?.fallbackLabel).toBe("来源待确认");
    expect(meta?.caution).toContain("缺字段");
  });

  it("scores a live partial report into the mid range", () => {
    const scoreMeta = getVerificationScoreMeta(sampleReport, null);

    expect(scoreMeta.score).toBe(6);
    expect(scoreMeta.tone).toBe("medium");
    expect(scoreMeta.modeLabel).toBe("中完成度");
  });

  it("caps demo or replay style data below a perfect score", () => {
    const scoreMeta = getVerificationScoreMeta(
      {
        ...sampleReport,
        mode: "complete_mode",
        event: {
          ...sampleReport.event,
          mode: "complete_mode",
        },
        timeline: [
          {
            node_type: "origin",
            title: "节点 1",
            url: "https://example.org/timeline/1",
            source_name: "来源 A",
            published_at: "2026-03-01T09:00:00+08:00",
            summary: "节点 1",
            why_selected: "测试",
          },
          {
            node_type: "clarification",
            title: "节点 2",
            url: "https://example.org/timeline/2",
            source_name: "来源 B",
            published_at: "2026-03-02T09:00:00+08:00",
            summary: "节点 2",
            why_selected: "测试",
          },
        ],
        claim_results: [
          ...sampleReport.claim_results,
          {
            claim: "claim B",
            claim_type: "fact",
            verdict: "refuted",
            confidence: "medium",
            evidence: [
              {
                title: "补充证据",
                url: "https://example.org/evidence/extra",
                source_name: "来源 D",
                published_at: "2026-03-05T09:00:00+08:00",
                snippet: "补充证据摘要",
                relevance_reason: "用于拉高完整度",
                source_tier: "A",
              },
            ],
            notes: "test",
          },
        ],
      },
      {
        sourceKind: "demo_payload",
        fallbackReason: "backend_offline",
      },
    );

    expect(scoreMeta.score).toBe(7);
    expect(scoreMeta.summary).toContain("不是实时联网结果");
  });

  it("keeps frontend fallback reports in the low score band", () => {
    const fallbackReport = buildFallbackReport("最近有个女网红脑出血死了真的假的？", "question");
    const scoreMeta = getVerificationScoreMeta(fallbackReport, {
      sourceKind: "frontend_fallback",
      fallbackReason: "analyze_failed",
    });

    expect(scoreMeta.score).toBeLessThanOrEqual(3);
    expect(scoreMeta.tone).toBe("low");
  });
});
