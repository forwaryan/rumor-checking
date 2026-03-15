import { describe, expect, it } from "vitest";
import { parseReport } from "@/lib/api-client";
import type { Report } from "@/types/report";

describe("parseReport", () => {
  it("parses a full backend report payload with provenance", () => {
    const report = parseReport({
      mode: "partial_mode",
      event: {
        title: "北城区化工厂异味投诉仍处在核查阶段",
        summary: "居民投诉、企业回应与环保部门核查信息同时存在。",
        source_url: "https://example.org/input/text-news",
        source_name: "用户提供文本",
        published_at: "2026-03-03T00:00:00+08:00",
        keywords: ["北城区化工厂", "异味"],
        mode: "partial_mode",
      },
      timeline: [
        {
          node_type: "turn",
          title: "环保部门进场核查",
          url: "https://env.example.cn/beicheng/2026-03-03",
          source_name: "北城区生态环境局",
          published_at: "2026-03-03T09:00:00+08:00",
          summary: "区生态环境局确认已进场核查。",
          why_selected: "它把事件从投诉转入监管核查阶段。",
        },
      ],
      claim_results: [
        {
          claim: "区生态环境局已经进场核查。",
          claim_type: "fact",
          verdict: "supported",
          confidence: "high",
          evidence: [
            {
              title: "区生态环境局称已进场核查",
              url: "https://env.example.cn/beicheng/2026-03-03",
              source_name: "北城区生态环境局",
              published_at: "2026-03-03T09:00:00+08:00",
              snippet: "生态环境局表示已对居民投诉启动现场核查。",
              relevance_reason: "官方确认介入调查。",
              source_tier: "S",
            },
          ],
          notes: "环保部门材料直接支持该说法。",
        },
      ],
      final_summary: "当前已有部分可核验结论，但证据链和时间线仍不完整，需要保留边界。",
      risks: ["存在相互冲突的证据，不能把单一版本当成最终事实。"],
      sources: [],
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
        summary: "官方核查已支撑部分事实，但停产范围仍存在冲突。",
        limiting_factors: ["停产范围缺少更高优先级的统一证据。"],
      },
      claim_contributions: [
        {
          claim: "区生态环境局已经进场核查。",
          claim_type: "fact",
          verdict: "supported",
          contribution_label: "supports",
          contribution_score: 20,
          reason: "官方介入核查显著抬升了事件可验证性。",
        },
      ],
      timeline_confidence: 61,
      independent_source_count: 3,
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
    });

    expect(report.mode).toBe("partial_mode");
    expect(report.event.title).toContain("北城区化工厂");
    expect(report.timeline[0]?.node_type).toBe("turn");
    expect(report.claim_results[0]?.evidence[0]?.source_tier).toBe("S");
    expect(report.provenance?.source_type).toBe("backend_live");
    expect(report.provenance?.evidence_source).toBe("retrieval_live");
    expect(report.provenance?.provider_used).toBe(true);
    expect((report as Report & Record<string, unknown>).overall_credibility_score).toBe(57);
    expect(((report as Report & Record<string, unknown>).score_breakdown as { timeline_score?: number })?.timeline_score).toBe(60);
  });

  it("fills conservative defaults for sparse payloads", () => {
    const report = parseReport({ mode: "safe_mode" });

    expect(report.event.title).toBe("未命名事件");
    expect(report.final_summary).toBe("缺少最终总结字段");
    expect(report.timeline).toEqual([]);
    expect(report.claim_results).toEqual([]);
    expect(report.sources).toEqual([]);
    expect(report.provenance).toBeNull();
  });

  it("drops incomplete provenance payloads onto the conservative path", () => {
    const report = parseReport({
      mode: "partial_mode",
      provenance: {
        source_type: "backend_mock",
        evidence_source: "retrieval_mock",
      },
    });

    expect(report.provenance).toBeNull();
  });

  it("throws on non-object payloads", () => {
    expect(() => parseReport(null)).toThrow("无法解析后端返回的 Report。");
  });
});
