import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { getOverallVerdict, VerdictCard } from "@/components/verdict-card";
import type { Evidence, Report } from "@/types/report";

function reportFor(verdicts: Array<"supported" | "insufficient" | "refuted">, label?: Report["overall_credibility_label"]): Report {
  return {
    claim_results: verdicts.map((verdict, index) => ({
      claim: index === 0 ? "京东近期大规模裁员。" : "互联网行业近年来发生过裁员。",
      claim_type: "fact" as const,
      verdict,
      confidence: "low" as const,
      evidence: [],
      notes: "",
    })),
    overall_credibility_label: label,
  } as unknown as Report;
}

describe("overall verdict headline", () => {
  it("keeps the original claim unresolved when only context is supported", () => {
    expect(getOverallVerdict(reportFor(["insufficient", "supported"], "insufficient_evidence"))).toBe("insufficient");
  });

  it("keeps direct support and refutation decisive", () => {
    expect(getOverallVerdict(reportFor(["supported", "insufficient"]))).toBe("supported");
    expect(getOverallVerdict(reportFor(["refuted", "insufficient"]))).toBe("refuted");
  });
});

const evidence: Evidence = {
  title: "公开报道",
  url: "https://example.org/report",
  source_name: "公开来源",
  source_tier: "A",
  published_at: "2026-03-03T00:00:00+08:00",
  snippet: "相关事件的报道",
  relevance_reason: "与核查点相关",
};

function renderVerdict(report: Report) {
  return renderToStaticMarkup(createElement(VerdictCard, { report, reportProvenance: null }));
}

function displayReport(overrides: Partial<Report> = {}): Report {
  return {
    ...reportFor(["insufficient"]),
    final_summary: "仍需进一步核实。",
    timeline: [],
    risks: ["时间线尚未建立。"],
    sources: [],
    retrieval_hits: [],
    provenance: {
      source_type: "backend_live",
      event_source: "provider_enriched",
      claim_source: "rule",
      evidence_source: "retrieval_live",
      timeline_source: "none",
      retrieval_provider: "baidu",
      retrieval_cache_status: null,
      provider_used: true,
      fallback_used: false,
      fallback_reasons: [],
    },
    ...overrides,
  };
}

describe("verdict evidence provenance", () => {
  it("does not count uncited report sources or retrieval hits as accepted evidence", () => {
    const markup = renderVerdict(displayReport({ sources: [evidence], retrieval_hits: [evidence] }));

    expect(markup).toContain("联网检索 · 暂无采信证据");
    expect(markup).toContain("证据 0 条");
    expect(markup).toContain("时间线尚未建立。");
    expect(markup).toContain("当前没有被核查点引用的证据");
    expect(markup).not.toContain("联网检索 · 有采信证据");
  });

  it("counts only unique evidence cited by claims", () => {
    const claim = displayReport().claim_results[0];
    const markup = renderVerdict(displayReport({
      claim_results: [{ ...claim, evidence: [evidence] }, { ...claim, evidence: [evidence] }],
      sources: [evidence, { ...evidence, url: "https://example.org/uncited" }],
    }));

    expect(markup).toContain("联网检索 · 有采信证据");
    expect(markup).toContain("证据 1 条");
    expect(markup).not.toContain("当前没有被核查点引用的证据");
  });

  it("keeps mock and unknown source labels cautious with no cited evidence", () => {
    const mockReport = displayReport({ provenance: { ...displayReport().provenance!, source_type: "backend_mock" } });
    expect(renderVerdict(mockReport)).toContain("后端模拟结果");
    const unknownReport = displayReport({ provenance: null, risks: [] });
    const markup = renderVerdict(unknownReport);
    expect(markup).toContain("来源待确认");
    expect(markup).toContain("当前没有被核查点引用的证据");
    expect(markup).not.toContain("联网检索 · 有采信证据");
  });
});
