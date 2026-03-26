import { describe, expect, it } from "vitest";
import {
  getClaimContributionIntro,
  getClaimContributions,
  getClaimSummaryBuckets,
  getCompletionBreakdown,
  getOverallCredibilityMeta,
  getScoreBreakdown,
  getScoreBreakdownMetrics,
  getTimelineConfidence,
} from "@/lib/report-high-score";
import type { Report } from "@/types/report";

const baseReport: Report = {
  mode: "partial_mode",
  event: {
    title: "Factory odor check",
    summary: "Residents complained, officials inspected, company replied.",
    source_url: "https://example.org/input/text-news",
    source_name: "User input",
    published_at: "2026-03-03T00:00:00+08:00",
    keywords: ["factory", "odor"],
    mode: "partial_mode",
  },
  timeline: [
    {
      node_type: "origin",
      title: "Residents posted complaints",
      url: "https://example.org/timeline/1",
      source_name: "Forum",
      published_at: "2026-03-02T20:00:00+08:00",
      summary: "Complaints spread online.",
      why_selected: "Origin point",
    },
    {
      node_type: "turn",
      title: "Officials inspected site",
      url: "https://example.org/timeline/2",
      source_name: "Environment bureau",
      published_at: "2026-03-03T09:00:00+08:00",
      summary: "Officials confirmed an inspection.",
      why_selected: "Formal response",
    },
  ],
  claim_results: [
    {
      claim: "Residents repeatedly complained about the overnight odor.",
      claim_type: "fact",
      verdict: "supported",
      confidence: "high",
      evidence: [],
      notes: "Multiple public references align.",
    },
    {
      claim: "The factory fully shut down production.",
      claim_type: "fact",
      verdict: "conflicting",
      confidence: "medium",
      evidence: [],
      notes: "Media and company statements conflict.",
    },
    {
      claim: "The factory has been hiding the full pollution story.",
      claim_type: "opinion",
      verdict: "insufficient",
      confidence: "low",
      evidence: [],
      notes: "This is still an opinion extension.",
    },
  ],
  final_summary: "Officials support part of the story, but the shutdown scope is still conflicted.",
  risks: ["Shutdown scope still lacks a higher-priority unified source."],
  sources: [],
  provenance: {
    source_type: "backend_mock",
    event_source: "retrieval_resolved",
    claim_source: "rule",
    evidence_source: "retrieval_mock",
    timeline_source: "retrieval",
    retrieval_provider: "mock",
    retrieval_cache_status: "seeded",
    provider_used: false,
    fallback_used: false,
    fallback_reasons: [],
  },
  content_check: {
    likely_true: [
      {
        claim: "Officials inspected the site.",
        claim_type: "fact",
        verdict: "supported",
        confidence: "high",
        reason: "Confirmed by official response.",
      },
    ],
    likely_false: [],
    controversial: [
      {
        claim: "The factory fully shut down production.",
        claim_type: "fact",
        verdict: "conflicting",
        confidence: "medium",
        reason: "Public accounts still conflict.",
      },
    ],
    opinions: [
      {
        claim: "The factory has been hiding the full pollution story.",
        claim_type: "opinion",
        verdict: "insufficient",
        confidence: "low",
        reason: "Opinion extension only.",
      },
    ],
    uncertain: [],
    possible_answers: [],
  },
};

const scoredReport = Object.assign({}, baseReport, {
  overall_credibility_score: 57,
  overall_credibility_label: "mixed",
  score_breakdown: {
    claim_score: 58,
    source_quality_score: 70,
    cross_source_agreement_score: 40,
    timeline_score: 60,
    weights: {
      claim: 0.5,
      source_quality: 0.2,
      cross_source_agreement: 0.2,
      timeline: 0.1,
    },
    summary: "Officials support part of the story, but high-priority sources still conflict on the shutdown scope.",
    limiting_factors: ["Shutdown scope still lacks a higher-priority unified source."],
  },
  claim_contributions: [
    {
      claim: "Officials inspected the site.",
      claim_type: "fact",
      verdict: "supported",
      contribution_label: "supports",
      contribution_score: 20,
      reason: "Official action improves verifiability.",
    },
    {
      claim: "The factory fully shut down production.",
      claim_type: "fact",
      verdict: "conflicting",
      contribution_label: "mixed",
      contribution_score: -18,
      reason: "High-priority sources still conflict.",
    },
  ],
  timeline_confidence: 61,
  independent_source_count: 3,
}) as Report;

describe("report-high-score", () => {
  it("reads score breakdown and overall credibility fields from extended reports", () => {
    const overall = getOverallCredibilityMeta(scoredReport, {
      sourceKind: "backend_mock",
    });
    const breakdown = getScoreBreakdown(scoredReport);
    const metrics = getScoreBreakdownMetrics(scoredReport);

    expect(overall?.score).toBe(57);
    expect(overall?.label).toBe("真假混杂");
    expect(breakdown?.timeline_score).toBe(60);
    expect(metrics).toHaveLength(4);
    expect(metrics[0]?.weightLabel).toBe("50%");
  });

  it("separates content checking and propagation completion", () => {
    const completion = getCompletionBreakdown(scoredReport, {
      sourceKind: "backend_mock",
    });

    expect(completion?.content.valueLabel).toBe("5/10");
    expect(completion?.propagation.valueLabel).toBe("61/100");
    expect(getTimelineConfidence(scoredReport)).toBe(61);
  });

  it("summarizes facts, opinions and possible mistakes for quick scan", () => {
    const buckets = getClaimSummaryBuckets(scoredReport);

    expect(buckets.map((item) => item.label)).toEqual(["事实", "可能有误", "观点", "待补证"]);
    expect(buckets.find((item) => item.key === "facts")?.count).toBe(1);
    expect(buckets.find((item) => item.key === "possible_mistakes")?.count).toBe(1);
    expect(buckets.find((item) => item.key === "opinions")?.count).toBe(1);
  });

  it("explains mixed claim contributions and falls back when backend scores are missing", () => {
    const contributions = getClaimContributions(scoredReport);
    const fallbackContributions = getClaimContributions(baseReport);

    expect(contributions[0]?.contributionScore).toBe(20);
    expect(contributions[1]?.contributionLabel).toBe("mixed");
    expect(getClaimContributionIntro(scoredReport)).toContain("claim");
    expect(fallbackContributions[0]?.derived).toBe(true);
    expect(fallbackContributions[1]?.contributionLabel).toBe("mixed");
  });
});
