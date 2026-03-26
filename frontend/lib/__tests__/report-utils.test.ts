import { describe, expect, it } from "vitest";
import {
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
    title: "Sample event",
    summary: "Sample summary",
    source_url: "https://example.org/input/text-news",
    source_name: "User input",
    published_at: "2026-03-03T00:00:00+08:00",
    keywords: ["sample"],
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
          title: "Early evidence",
          url: "https://example.org/evidence/early",
          source_name: "Source A",
          published_at: "2026-03-01T09:00:00+08:00",
          snippet: "Early evidence snippet",
          relevance_reason: "ordering",
          source_tier: "A",
        },
        {
          title: "Shared evidence",
          url: "https://example.org/evidence/shared",
          source_name: "Source B",
          published_at: "2026-03-02T09:00:00+08:00",
          snippet: "Shared evidence snippet",
          relevance_reason: "dedupe",
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
      title: "Shared evidence",
      url: "https://example.org/evidence/shared",
      source_name: "Source B",
      published_at: "2026-03-02T09:00:00+08:00",
      snippet: "Shared evidence snippet",
      relevance_reason: "dedupe",
      source_tier: "S",
    },
    {
      title: "Late evidence",
      url: "https://example.org/evidence/late",
      source_name: "Source C",
      published_at: "2026-03-04T09:00:00+08:00",
      snippet: "Late evidence snippet",
      relevance_reason: "ordering",
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
    expect(validateInput("   ", "text")).toBeTruthy();
    expect(validateInput("not-a-url", "url")).toBeTruthy();
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

  it("labels backend_live reports with live provenance metadata", () => {
    const meta = getReportProvenanceMeta(sampleReport, null);

    expect(meta?.tone).toBe("live");
    expect(meta?.detailBadges).toContain("检索: SERPAPI");
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

    expect(meta?.tone).toBe("mock");
    expect(meta?.caution).toContain("mock");
  });

  it("defaults to an unknown provenance label when metadata is missing", () => {
    const meta = getReportProvenanceMeta(
      {
        ...sampleReport,
        provenance: null,
      },
      null,
    );

    expect(meta?.tone).toBe("unknown");
    expect(meta?.fallbackLabel).toBeTruthy();
  });

  it("scores a live partial report into the mid range", () => {
    const scoreMeta = getVerificationScoreMeta(sampleReport, null);

    expect(scoreMeta.score).toBe(6);
    expect(scoreMeta.tone).toBe("medium");
  });

  it("caps backend mock data below a perfect score", () => {
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
            title: "Node 1",
            url: "https://example.org/timeline/1",
            source_name: "Source A",
            published_at: "2026-03-01T09:00:00+08:00",
            summary: "Node 1",
            why_selected: "test",
          },
          {
            node_type: "clarification",
            title: "Node 2",
            url: "https://example.org/timeline/2",
            source_name: "Source B",
            published_at: "2026-03-02T09:00:00+08:00",
            summary: "Node 2",
            why_selected: "test",
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
                title: "Extra evidence",
                url: "https://example.org/evidence/extra",
                source_name: "Source D",
                published_at: "2026-03-05T09:00:00+08:00",
                snippet: "Extra evidence snippet",
                relevance_reason: "completeness",
                source_tier: "A",
              },
            ],
            notes: "test",
          },
        ],
      },
      {
        sourceKind: "backend_mock",
      },
    );

    expect(scoreMeta.score).toBe(7);
    expect(scoreMeta.summary).toContain("当前不是实时联网结果");
  });
});
