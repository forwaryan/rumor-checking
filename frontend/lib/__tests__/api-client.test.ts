import { describe, expect, it, vi } from "vitest";
import { analyzeReportStream, parseReport } from "@/lib/api-client";
import type { AnalysisLiveEvent, Report } from "@/types/report";

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

  it("parses claim + scenario probabilities and clamps/validates them", () => {
    const report = parseReport({
      mode: "safe_mode",
      claim_results: [
        {
          claim: "拼多多在雄安买了三栋楼。",
          claim_type: "fact",
          verdict: "insufficient",
          confidence: "low",
          truth_probability: 15,
          probability_basis: "prior",
          evidence: [],
          notes: "无检索证据。",
        },
        {
          claim: "溢出与非法基准都被兜住。",
          claim_type: "fact",
          verdict: "supported",
          confidence: "high",
          truth_probability: 150,
          probability_basis: "bogus",
          evidence: [],
          notes: "n",
        },
      ],
      investigation: {
        question: "q",
        reframed_question: "r",
        thinking_process: [],
        possibilities: [
          { scenario: "暂无法证实", likelihood: "high", probability: 60, basis: "prior", summary: "s1" },
          { scenario: "分类降级", likelihood: "low", summary: "s2" },
        ],
        final_conclusion: "c",
      },
    });

    const claims = report.claim_results;
    expect(claims[0]?.truth_probability).toBe(15);
    expect(claims[0]?.probability_basis).toBe("prior");
    // Clamp to 100, reject bogus basis -> null.
    expect(claims[1]?.truth_probability).toBe(100);
    expect(claims[1]?.probability_basis).toBeNull();

    const possibilities = report.investigation?.possibilities ?? [];
    expect(possibilities[0]?.probability).toBe(60);
    expect(possibilities[0]?.basis).toBe("prior");
    // Missing probability stays null (falls back to categorical likelihood chip).
    expect(possibilities[1]?.probability).toBeNull();
    expect(possibilities[1]?.basis).toBeNull();
  });
});

function ndjsonResponse(lines: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const line of lines) {
        controller.enqueue(encoder.encode(line + "\n"));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
}

describe("analyzeReportStream heartbeat handling", () => {
  it("skips heartbeat lines without throwing and still returns the report", async () => {
    const lines = [
      JSON.stringify({ type: "heartbeat", run_id: "r", emitted_at: "2026-03-20T00:00:00Z" }),
      JSON.stringify({
        type: "stage",
        stage_key: "normalize_input",
        title: "标准化输入",
        status: "completed",
        summary: "done",
        details: [],
        emitted_at: "2026-03-20T00:00:01Z",
      }),
      JSON.stringify({ type: "heartbeat", run_id: "r", emitted_at: "2026-03-20T00:00:11Z" }),
      JSON.stringify({
        type: "report",
        run_id: "r",
        summary: "分析完成",
        report: { mode: "safe_mode" },
        emitted_at: "2026-03-20T00:00:12Z",
      }),
      JSON.stringify({ type: "complete", run_id: "r", success: true, summary: "结束", emitted_at: "2026-03-20T00:00:13Z" }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(lines));
    vi.stubGlobal("fetch", fetchMock);

    const seen: AnalysisLiveEvent[] = [];
    try {
      const report = await analyzeReportStream(
        { raw_input: "x", input_type: "auto" },
        (event) => seen.push(event),
      );
      expect(report.mode).toBe("safe_mode");
    } finally {
      vi.unstubAllGlobals();
    }

    // Heartbeats never reach onEvent; real events do.
    expect(seen.some((event) => (event as { type: string }).type === "heartbeat")).toBe(false);
    expect(seen.some((event) => event.type === "stage")).toBe(true);
    expect(seen.some((event) => event.type === "report")).toBe(true);
  });

  it("preserves a retrieval event's structured results through parsing", async () => {
    // Regression: the retrieval parser dropped `results`, so the frontend showed
    // no per-query hits even though the backend emitted them.
    const lines = [
      JSON.stringify({
        type: "retrieval",
        stage_key: "retrieval_initial",
        query_label: "event_core",
        query: "拼多多 雄安 办公楼",
        provider_name: "playwright",
        summary: "已返回 1 条去重结果。",
        details: [],
        results: [
          {
            title: "拼多多雄安办公楼正式投用",
            url: "https://news.qq.com/pdd-1",
            snippet: "购置整栋楼宇。",
            source_name: "news.qq.com",
            source_tier: "B",
            published_at: "2026-07-20T08:00:00+08:00",
            category: "mainstream_media",
          },
        ],
        emitted_at: "2026-03-20T00:00:02Z",
      }),
      JSON.stringify({ type: "report", run_id: "r", summary: "done", report: { mode: "safe_mode" }, emitted_at: "2026-03-20T00:00:12Z" }),
      JSON.stringify({ type: "complete", run_id: "r", success: true, summary: "结束", emitted_at: "2026-03-20T00:00:13Z" }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(lines));
    vi.stubGlobal("fetch", fetchMock);

    const seen: AnalysisLiveEvent[] = [];
    try {
      await analyzeReportStream({ raw_input: "x", input_type: "auto" }, (event) => seen.push(event));
    } finally {
      vi.unstubAllGlobals();
    }

    const retrieval = seen.find((e) => e.type === "retrieval");
    expect(retrieval).toBeDefined();
    const results = (retrieval as { results?: unknown[] }).results ?? [];
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({
      title: "拼多多雄安办公楼正式投用",
      url: "https://news.qq.com/pdd-1",
      snippet: "购置整栋楼宇。",
      source_tier: "B",
    });
  });

  it("skips unknown event types without aborting the stream", async () => {
    // Forward-compat: a new backend event type must not crash an older client
    // mid-analysis. The unknown event is silently dropped; the report survives.
    const lines = [
      JSON.stringify({ type: "some_future_event", foo: "bar", emitted_at: "2026-03-20T00:00:00Z" }),
      JSON.stringify({ type: "report", run_id: "r", summary: "done", report: { mode: "safe_mode" }, emitted_at: "2026-03-20T00:00:12Z" }),
      JSON.stringify({ type: "complete", run_id: "r", success: true, summary: "结束", emitted_at: "2026-03-20T00:00:13Z" }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(lines));
    vi.stubGlobal("fetch", fetchMock);

    const seen: AnalysisLiveEvent[] = [];
    try {
      const report = await analyzeReportStream({ raw_input: "x", input_type: "auto" }, (e) => seen.push(e));
      expect(report.mode).toBe("safe_mode");
    } finally {
      vi.unstubAllGlobals();
    }
    expect(seen.some((e) => (e as { type: string }).type === "some_future_event")).toBe(false);
    expect(seen.some((e) => e.type === "report")).toBe(true);
  });

  it("tolerates a malformed (non-JSON) line without dropping the report", async () => {
    const lines = [
      "this is not json {{{",
      JSON.stringify({ type: "report", run_id: "r", summary: "done", report: { mode: "safe_mode" }, emitted_at: "2026-03-20T00:00:12Z" }),
      JSON.stringify({ type: "complete", run_id: "r", success: true, summary: "结束", emitted_at: "2026-03-20T00:00:13Z" }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(lines));
    vi.stubGlobal("fetch", fetchMock);
    try {
      const report = await analyzeReportStream({ raw_input: "x", input_type: "auto" }, () => {});
      expect(report.mode).toBe("safe_mode");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("parses a metrics event into a structured RunMetrics payload", async () => {
    const lines = [
      JSON.stringify({
        type: "metrics",
        stage_key: "supervisor",
        emitted_at: "2026-03-20T00:00:05Z",
        metrics: {
          mode: "parallel",
          total_ms: 4200,
          time_exhausted: false,
          looped_back: false,
          completed: ["normalize", "retrieval_merge"],
          failed: [],
          agents: [
            { role: "retrieval_baidu", status: "completed", elapsed_ms: 1800, actions: ["search_baidu"], model: null, error: null },
          ],
          source_hits: { baidu: 5, xiaohongshu: 2 },
          tokens: { prompt: 1000, completion: 400, total: 1400, llm_calls: 3 },
        },
      }),
      JSON.stringify({ type: "report", run_id: "r", summary: "done", report: { mode: "safe_mode" }, emitted_at: "2026-03-20T00:00:12Z" }),
      JSON.stringify({ type: "complete", run_id: "r", success: true, summary: "结束", emitted_at: "2026-03-20T00:00:13Z" }),
    ];
    const fetchMock = vi.fn().mockResolvedValue(ndjsonResponse(lines));
    vi.stubGlobal("fetch", fetchMock);

    const seen: AnalysisLiveEvent[] = [];
    try {
      await analyzeReportStream({ raw_input: "x", input_type: "auto" }, (e) => seen.push(e));
    } finally {
      vi.unstubAllGlobals();
    }
    const metrics = seen.find((e) => e.type === "metrics");
    expect(metrics).toBeDefined();
    const m = (metrics as { metrics: { mode: string; source_hits: Record<string, number>; tokens: { total: number } } }).metrics;
    expect(m.mode).toBe("parallel");
    expect(m.source_hits.baidu).toBe(5);
    expect(m.tokens.total).toBe(1400);
  });

  it("preserves an empty published_at rather than fabricating new Date().toISOString()", () => {
    // Regression: parseReport used to fill missing timeline/evidence
    // published_at with `new Date().toISOString()`. On the "京东要造游艇"
    // run four different articles all rendered with the same
    // millisecond-precision timestamp because they were all filled at
    // report-parse time. Empty string flows through timeline-section.tsx's
    // `|| "时间未知"` fallback instead.
    const report = parseReport({
      mode: "safe_mode",
      event: { title: "事件", summary: "s", source_url: "https://ex.com", source_name: "s", published_at: "" },
      timeline: [
        { node_type: "origin", title: "无日期节点", url: "https://ex.com/a", source_name: "s", summary: "x", why_selected: "y" },
      ],
      claim_results: [
        {
          claim: "c",
          verdict: "supported",
          confidence: "high",
          evidence: [
            { title: "无日期证据", url: "https://ex.com/e", source_name: "s", snippet: "x", relevance_reason: "r", source_tier: "B" },
          ],
        },
      ],
      final_summary: "",
      risks: [],
      provenance: { input_type: "text_only", mode_hint: "safe", event_source: "input_normalized" },
    });
    expect(report.timeline[0]?.published_at).toBe("");
    expect(report.claim_results[0]?.evidence[0]?.published_at).toBe("");
    expect(report.event.published_at).toBe("");
  });
});
