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
    title: "北城区化工厂异味核查",
    summary: "居民投诉、官方核查和企业回应同时存在。",
    source_url: "https://example.org/input/text-news",
    source_name: "用户提供文本",
    published_at: "2026-03-03T00:00:00+08:00",
    keywords: ["异味", "化工厂"],
    mode: "partial_mode",
  },
  timeline: [
    {
      node_type: "origin",
      title: "居民投诉发酵",
      url: "https://example.org/timeline/1",
      source_name: "本地论坛",
      published_at: "2026-03-02T20:00:00+08:00",
      summary: "居民连续投诉夜间异味。",
      why_selected: "它解释了事件从零散讨论进入公共议题。",
    },
    {
      node_type: "turn",
      title: "生态环境局进场核查",
      url: "https://example.org/timeline/2",
      source_name: "北城区生态环境局",
      published_at: "2026-03-03T09:00:00+08:00",
      summary: "官方确认已进场核查。",
      why_selected: "它把传播从传闻推向正式核查。",
    },
  ],
  claim_results: [
    {
      claim: "北城区化工厂已被居民连续投诉夜间异味。",
      claim_type: "fact",
      verdict: "supported",
      confidence: "high",
      evidence: [],
      notes: "投诉线索已有多个来源重复出现。",
    },
    {
      claim: "北城区化工厂已经完全停产。",
      claim_type: "fact",
      verdict: "conflicting",
      confidence: "medium",
      evidence: [],
      notes: "媒体说法和企业回应仍然冲突。",
    },
    {
      claim: "北城区化工厂一直在隐瞒真实污染情况。",
      claim_type: "opinion",
      verdict: "insufficient",
      confidence: "low",
      evidence: [],
      notes: "这是观点延伸，当前不能直接计入事实判断。",
    },
  ],
  final_summary: "官方核查已支撑部分事实，但停产范围仍存在冲突。",
  risks: ["停产范围缺少更高优先级的统一证据。"],
  sources: [],
  provenance: {
    source_type: "demo_payload",
    event_source: "retrieval_resolved",
    claim_source: "rule",
    evidence_source: "retrieval_mock",
    timeline_source: "retrieval",
    retrieval_provider: "demo_payload",
    retrieval_cache_status: "demo_seeded",
    provider_used: false,
    fallback_used: false,
    fallback_reasons: [],
  },
  content_check: {
    likely_true: [
      {
        claim: "区生态环境局已经进场核查。",
        claim_type: "fact",
        verdict: "supported",
        confidence: "high",
        reason: "官方口径已明确确认核查。",
      },
    ],
    likely_false: [],
    controversial: [
      {
        claim: "北城区化工厂已经完全停产。",
        claim_type: "fact",
        verdict: "conflicting",
        confidence: "medium",
        reason: "媒体与企业回应不一致。",
      },
    ],
    opinions: [
      {
        claim: "北城区化工厂一直在隐瞒真实污染情况。",
        claim_type: "opinion",
        verdict: "insufficient",
        confidence: "low",
        reason: "这是观点延伸。",
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
    summary: "官方核查已支撑部分事实，但停产范围存在互相冲突的 A 级来源。",
    limiting_factors: ["停产范围缺少更高优先级的统一证据。"],
  },
  claim_contributions: [
    {
      claim: "区生态环境局已经进场核查。",
      claim_type: "fact",
      verdict: "supported",
      contribution_label: "supports",
      contribution_score: 20,
      reason: "官方介入显著抬升了事件可验证性。",
    },
    {
      claim: "北城区化工厂已经完全停产。",
      claim_type: "fact",
      verdict: "conflicting",
      contribution_label: "mixed",
      contribution_score: -18,
      reason: "关键细节在多个 A 级来源之间冲突。",
    },
  ],
  timeline_confidence: 61,
  independent_source_count: 3,
}) as Report;

describe("report-high-score", () => {
  it("reads score breakdown and overall credibility fields from extended reports", () => {
    const overall = getOverallCredibilityMeta(scoredReport, {
      sourceKind: "demo_payload",
      fallbackReason: "backend_offline",
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
      sourceKind: "demo_payload",
      fallbackReason: "backend_offline",
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
    expect(getClaimContributionIntro(scoredReport)).toContain("不同 claim");
    expect(fallbackContributions[0]?.derived).toBe(true);
    expect(fallbackContributions[1]?.contributionLabel).toBe("mixed");
  });
});
