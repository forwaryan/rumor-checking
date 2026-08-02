import { describe, expect, it } from "vitest";
import {
  applyBackendTiming,
  deriveTraceSteps,
  elapsedSince,
  formatDuration,
  formatLlmText,
  humanizeLlmText,
  parallelWallClockMs,
  sumChildDurationsMs,
} from "@/lib/trace-steps";
import type { AnalysisLiveEvent, AnalysisLiveStatus, TraceStep } from "@/types/report";

function stage(
  stage_key: string,
  status: AnalysisLiveStatus,
  summary: string,
  details: string[] = [],
  emitted_at = "2026-03-20T00:00:00Z",
): AnalysisLiveEvent {
  return { type: "stage", stage_key, status, title: stage_key, summary, details, emitted_at } as AnalysisLiveEvent;
}

function retrieval(stage_key: string, query: string, summary: string, emitted_at = "2026-03-20T00:00:01Z"): AnalysisLiveEvent {
  return {
    type: "retrieval",
    stage_key,
    query_label: "q",
    query,
    provider_name: "playwright",
    summary,
    details: [],
    emitted_at,
  } as AnalysisLiveEvent;
}

function log(stage_key: string, level: "info" | "warning" | "error", summary: string): AnalysisLiveEvent {
  return { type: "log", stage_key, title: "log", summary, details: [], level, emitted_at: "2026-03-20T00:00:02Z" } as AnalysisLiveEvent;
}

function apiCall(
  stage_key: string,
  status: AnalysisLiveStatus,
  title: string,
  details: string[],
  emitted_at = "2026-03-20T00:00:03Z",
  call_type = "llm",
): AnalysisLiveEvent {
  return { type: "api_call", stage_key, call_type, status, title, summary: "", details, emitted_at } as AnalysisLiveEvent;
}

function complete(emitted_at = "2026-03-20T00:00:09Z"): AnalysisLiveEvent {
  return { type: "complete", run_id: "r", success: true, summary: "done", emitted_at } as AnalysisLiveEvent;
}

describe("deriveTraceSteps", () => {
  it("groups events by stage and preserves first-seen order", () => {
    const steps = deriveTraceSteps([
      stage("normalize_input", "completed", "整理出初始事件草稿"),
      stage("retrieval_initial", "running", "生成 query plan"),
      stage("retrieval_initial", "completed", "首轮检索已返回结果集"),
    ]);
    expect(steps.map((s) => s.stageKey)).toEqual(["normalize_input", "retrieval_initial"]);
    expect(steps[0].label).toBe("标准化输入");
    expect(steps[1].status).toBe("completed"); // terminal event wins
    expect(steps[1].did).toBe("首轮检索已返回结果集");
  });

  it("splits details into inputs and outputs by known keys", () => {
    const steps = deriveTraceSteps([
      stage("retrieval_initial", "completed", "检索完成", [
        "query=京东 造船",
        "rationale=围绕主体建立主检索",
        "canonical_results=4",
        "evidence_grade=B",
      ]),
    ]);
    const step = steps[0];
    expect(step.inputs.map((kv) => kv.key)).toContain("query");
    expect(step.inputs.map((kv) => kv.key)).toContain("rationale");
    expect(step.outputs.map((kv) => kv.key)).toContain("canonical_results");
    expect(step.outputs.find((kv) => kv.key === "canonical_results")?.value).toBe("4");
  });

  it("attaches retrieval and log sub-events, and surfaces warnings as the step note", () => {
    const steps = deriveTraceSteps([
      stage("retrieval_initial", "running", "执行检索"),
      retrieval("retrieval_initial", "京东 造船", "已返回 4 条去重结果"),
      log("retrieval_initial", "warning", "百度失败，改用 Bing"),
      stage("retrieval_initial", "completed", "检索完成"),
    ]);
    const step = steps[0];
    expect(step.subEvents).toHaveLength(2);
    expect(step.subEvents[0].title).toContain("京东 造船");
    expect(step.note).toBe("百度失败，改用 Bing");
  });

  it("keeps the last step running while the stream is still in flight", () => {
    const steps = deriveTraceSteps([
      stage("normalize_input", "completed", "done"),
      stage("agent_synthesis", "running", "正在综合判断"),
    ]);
    expect(steps[steps.length - 1].status).toBe("running");
    expect(steps[steps.length - 1].endedAt).toBeNull();
  });

  it("ignores events without a stage_key", () => {
    const steps = deriveTraceSteps([
      { type: "session", run_id: "r", trace_id: "t", input_type: "text", summary: "", preview: "", emitted_at: "x" } as AnalysisLiveEvent,
      { type: "complete", run_id: "r", success: true, summary: "done", emitted_at: "x" } as AnalysisLiveEvent,
    ]);
    expect(steps).toHaveLength(0);
  });

  it("pairs an LLM prompt (running) with its response (completed) into one call", () => {
    const steps = deriveTraceSteps([
      stage("agent_synthesis", "running", "正在综合判断"),
      apiCall("agent_synthesis", "running", "调用 Agent synthesis", ["model=DemoModel", "prompt=判断这条消息真假：京东造游轮"]),
      apiCall("agent_synthesis", "completed", "调用 Agent synthesis 返回", ["model=DemoModel", "content_chars=120", "response={\"verdict\":\"insufficient\"}"]),
      stage("agent_synthesis", "completed", "已产出结构化结论"),
    ]);
    const step = steps[0];
    expect(step.llmCalls).toHaveLength(1);
    expect(step.llmCalls[0].prompt).toContain("京东造游轮");
    expect(step.llmCalls[0].response).toContain("insufficient");
    expect(step.llmCalls[0].status).toBe("completed");
    // prompt/response must NOT leak into the generic kv rows
    expect(step.inputs.find((kv) => kv.key === "prompt")).toBeUndefined();
    expect(step.outputs.find((kv) => kv.key === "response")).toBeUndefined();
  });

  it("captures the system prompt on an LLM call", () => {
    const steps = deriveTraceSteps([
      stage("agent_synthesis", "running", "正在综合判断"),
      apiCall("agent_synthesis", "running", "调用 Agent synthesis", [
        "model=DemoModel",
        "system=你是核查后端的综合判定阶段。CLAIM DECOMPOSITION 规则...",
        "prompt=判断这条消息真假：京东造游轮",
      ]),
      apiCall("agent_synthesis", "completed", "调用 Agent synthesis 返回", ["response={\"claims\":[]}"]),
    ]);
    const step = steps[0];
    expect(step.llmCalls[0].system).toContain("CLAIM DECOMPOSITION");
    // system must NOT leak into the generic kv rows either
    expect(step.inputs.find((kv) => kv.key === "system")).toBeUndefined();
    expect(step.outputs.find((kv) => kv.key === "system")).toBeUndefined();
  });

  it("shows each retry attempt as its own call with its raw output", () => {
    // A truncated first attempt (warning) then an accepted retry (completed) must
    // surface as TWO llmCalls, so the trace shows what each attempt returned.
    const steps = deriveTraceSteps([
      stage("agent_synthesis", "running", "正在综合判断"),
      apiCall("agent_synthesis", "running", "调用 Agent synthesis", ["prompt=判断真假", "system=sys"]),
      apiCall("agent_synthesis", "warning", "调用 Agent synthesis 返回", ["outcome=unparseable", "response={ \"event\": { \"summary\": \"拼"]),
      apiCall("agent_synthesis", "running", "调用 Agent synthesis（重试 1）", ["prompt=判断真假", "system=sys"]),
      apiCall("agent_synthesis", "completed", "调用 Agent synthesis（重试 1） 返回", ["outcome=accepted", "response={\"claims\":[{\"claim\":\"c\"}]}"]),
    ]);
    const step = steps[0];
    expect(step.llmCalls).toHaveLength(2);
    expect(step.llmCalls[0].response).toContain("拼");
    expect(step.llmCalls[0].status).toBe("warning");
    expect(step.llmCalls[1].response).toContain("claims");
    expect(step.llmCalls[1].status).toBe("completed");
  });

  it("resolves a log-only step (agent_orchestrator) once the run completes", () => {
    // agent_orchestrator only emits a log, never a terminal stage event — it must
    // not hang at 进行中 after the run ends.
    const steps = deriveTraceSteps([
      log("agent_orchestrator", "info", "Agent orchestrator 接管本次分析。"),
      stage("agent_synthesis", "completed", "done"),
      complete(),
    ]);
    const orch = steps.find((s) => s.stageKey === "agent_orchestrator")!;
    expect(orch.status).toBe("completed");
    expect(orch.endedAt).not.toBeNull();
  });

  it("resolves a stuck step to its worst sub-event outcome", () => {
    const steps = deriveTraceSteps([
      apiCall("agent_planner", "running", "调用 planner", ["prompt=x"]),
      log("agent_planner", "warning", "planner 返回非法动作，退回规则 planner。"),
      complete(),
    ]);
    const planner = steps.find((s) => s.stageKey === "agent_planner")!;
    expect(planner.status).toBe("warning");
  });

  it("keeps a log-only step running while the stream is still in flight", () => {
    // No complete/error/report event yet -> do not force-resolve.
    const steps = deriveTraceSteps([log("agent_orchestrator", "info", "接管中")]);
    expect(steps[0].status).toBe("running");
    expect(steps[0].endedAt).toBeNull();
  });

  it("collapses a running+completed retrieval pair into one ordered sub-event", () => {
    // Concurrent retrieval emits each query as running (from a worker) then
    // completed, and threads interleave — the trace must show one entry per query,
    // in time order, in its final state.
    const steps = deriveTraceSteps([
      stage("retrieval_initial", "running", "执行检索"),
      retrieval("retrieval_initial", "query B", "B running", "2026-03-20T00:00:05Z"),
      retrieval("retrieval_initial", "query A", "A running", "2026-03-20T00:00:02Z"),
      stage("retrieval_initial", "completed", "检索完成"),
      complete(),
    ]);
    const step = steps[0];
    // retrieval sub-events already arrive as "completed"; distinct queries stay
    // distinct, and they are ordered by emit time (A before B).
    expect(step.subEvents).toHaveLength(2);
    expect(step.subEvents[0].title).toContain("query A");
    expect(step.subEvents[1].title).toContain("query B");
  });

  it("folds a running api_call sub-event into its terminal event", () => {
    const steps = deriveTraceSteps([
      stage("retrieval_initial", "running", "执行检索"),
      apiCall("retrieval_initial", "running", "百度检索（HTTP 抓取）", ["query=x"], "2026-03-20T00:00:02Z", "http"),
      apiCall("retrieval_initial", "completed", "百度检索（HTTP 抓取）", ["count=4"], "2026-03-20T00:00:04Z", "http"),
      stage("retrieval_initial", "completed", "检索完成"),
      complete(),
    ]);
    const step = steps[0];
    const httpSubs = step.subEvents.filter((s) => s.title.includes("HTTP 抓取"));
    expect(httpSubs).toHaveLength(1);
    expect(httpSubs[0].status).toBe("completed");
  });
});

describe("formatLlmText", () => {
  it("pretty-prints a compressed one-line JSON response", () => {
    const out = formatLlmText('{"next_action":"investigate","reason":"weak"}');
    expect(out).toContain('"next_action": "investigate"');
    expect(out.split("\n").length).toBeGreaterThan(1);
  });

  it("keeps leading instruction text and pretty-prints the embedded Context JSON", () => {
    const out = formatLlmText('Choose the best action. Context JSON: {"a":1,"b":{"c":2}}');
    expect(out.startsWith("Choose the best action. Context JSON:")).toBe(true);
    expect(out).toContain('"c": 2');
  });

  it("returns plain text unchanged when there is no JSON", () => {
    expect(formatLlmText("just some text")).toBe("just some text");
  });

  it("falls back to the raw string when the JSON is malformed", () => {
    const broken = "prefix {not valid json";
    expect(formatLlmText(broken)).toBe(broken);
  });
});

describe("humanizeLlmText", () => {
  it("summarizes a planner response into a decision + reason", () => {
    const out = humanizeLlmText("agent_planner", "response", '{"next_action":"investigate","reason":"证据太弱"}');
    expect(out).toContain("决定：再补一轮检索");
    expect(out).toContain("证据太弱");
  });

  it("summarizes an investigation response with follow-up query", () => {
    const out = humanizeLlmText(
      "investigation_plan",
      "response",
      '{"should_continue":true,"follow_up_query":"京东 游轮 官方","reason":"来源不权威"}',
    );
    expect(out).toContain("需要再查一轮");
    expect(out).toContain("京东 游轮 官方");
    expect(out).toContain("来源不权威");
  });

  it("summarizes a synthesis response into claims with Chinese verdicts", () => {
    const out = humanizeLlmText(
      "agent_synthesis",
      "response",
      '{"event":{"summary":"检索无相关信息"},"claims":[{"claim":"京东造游轮","verdict":"insufficient","notes":"未找到来源"}],"timeline":[{"node_type":"origin"}]}',
    );
    expect(out).toContain("事件小结：检索无相关信息");
    expect(out).toContain("京东造游轮 → 证据不足");
    expect(out).toContain("未找到来源");
    expect(out).toContain("时间线节点：1");
  });

  it("summarizes a prompt's evidence snapshot", () => {
    const out = humanizeLlmText(
      "agent_planner",
      "prompt",
      'Choose the best action. Context JSON: {"evidence_snapshot":{"evidence_grade":"C","canonical_result_count":5,"high_trust_result_count":0}}',
    );
    expect(out).toContain("证据等级 C");
    expect(out).toContain("候选结果 5 条");
  });

  it("falls back to formatted JSON for an unknown shape", () => {
    const out = humanizeLlmText("agent_synthesis", "response", '{"weird":"shape"}');
    expect(out).toContain('"weird": "shape"');
  });
});

describe("formatDuration", () => {
  it("returns dash for null / negative / non-finite", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-5)).toBe("—");
    expect(formatDuration(Number.NaN)).toBe("—");
  });

  it("formats sub-second in milliseconds", () => {
    expect(formatDuration(0)).toBe("0ms");
    expect(formatDuration(482)).toBe("482ms");
    expect(formatDuration(999)).toBe("999ms");
  });

  it("formats seconds with two decimals under a minute", () => {
    expect(formatDuration(1000)).toBe("1.00s");
    expect(formatDuration(1235)).toBe("1.24s");
    expect(formatDuration(59_999)).toBe("60.00s");
  });

  it("formats minutes with zero-padded seconds beyond a minute", () => {
    expect(formatDuration(60_000)).toBe("1m 00s");
    expect(formatDuration(65_000)).toBe("1m 05s");
    expect(formatDuration(3_599_000)).toBe("59m 59s");
  });
});

describe("elapsedSince", () => {
  it("returns positive delta when now is after start", () => {
    const start = "2026-03-20T00:00:00Z";
    const now = new Date("2026-03-20T00:00:03.500Z").getTime();
    expect(elapsedSince(start, now)).toBe(3500);
  });

  it("clamps to zero when start is in the future", () => {
    const start = "2026-03-20T00:00:10Z";
    const now = new Date("2026-03-20T00:00:00Z").getTime();
    expect(elapsedSince(start, now)).toBe(0);
  });

  it("returns zero for an unparseable start", () => {
    expect(elapsedSince("not-a-date", Date.now())).toBe(0);
  });
});

function makeStep(overrides: Partial<TraceStep>): TraceStep {
  return {
    stageKey: "x",
    label: "x",
    status: "completed",
    did: "",
    inputs: [],
    outputs: [],
    note: null,
    llmCalls: [],
    subEvents: [],
    startedAt: "2026-03-20T00:00:00Z",
    endedAt: "2026-03-20T00:00:01Z",
    durationMs: 1000,
    offsetMs: 0,
    parentKey: null,
    children: [],
    isParallelGroup: false,
    ...overrides,
  };
}

describe("parallelWallClockMs", () => {
  it("computes max(end) - min(start) across children", () => {
    const children = [
      makeStep({
        stageKey: "a",
        startedAt: "2026-03-20T00:00:00.000Z",
        endedAt: "2026-03-20T00:00:01.500Z",
      }),
      makeStep({
        stageKey: "b",
        startedAt: "2026-03-20T00:00:00.200Z",
        endedAt: "2026-03-20T00:00:02.400Z",
      }),
      makeStep({
        stageKey: "c",
        startedAt: "2026-03-20T00:00:00.500Z",
        endedAt: "2026-03-20T00:00:01.000Z",
      }),
    ];
    expect(parallelWallClockMs(children)).toBe(2400);
  });

  it("returns null if a child has no endedAt", () => {
    const children = [
      makeStep({ startedAt: "2026-03-20T00:00:00.000Z", endedAt: "2026-03-20T00:00:01.000Z" }),
      makeStep({ startedAt: "2026-03-20T00:00:00.500Z", endedAt: null }),
    ];
    expect(parallelWallClockMs(children)).toBe(null);
  });

  it("returns null for an empty child list", () => {
    expect(parallelWallClockMs([])).toBe(null);
  });
});

describe("sumChildDurationsMs", () => {
  it("sums populated durations, treating null as zero", () => {
    const children = [
      makeStep({ durationMs: 1000 }),
      makeStep({ durationMs: 2500 }),
      makeStep({ durationMs: null }),
    ];
    expect(sumChildDurationsMs(children)).toBe(3500);
  });
});

describe("deriveTraceSteps · duration + offset", () => {
  it("computes durationMs from startedAt and endedAt on the terminal stage", () => {
    const events: AnalysisLiveEvent[] = [
      { type: "stage", stage_key: "normalize_input", status: "running", title: "n", summary: "", details: [], emitted_at: "2026-03-20T00:00:00.000Z" } as AnalysisLiveEvent,
      { type: "stage", stage_key: "normalize_input", status: "completed", title: "n", summary: "", details: [], emitted_at: "2026-03-20T00:00:00.480Z" } as AnalysisLiveEvent,
      { type: "complete", run_id: "r", success: true, summary: "", emitted_at: "2026-03-20T00:00:00.500Z" } as AnalysisLiveEvent,
    ];
    const steps = deriveTraceSteps(events);
    expect(steps).toHaveLength(1);
    expect(steps[0].durationMs).toBe(480);
    expect(steps[0].offsetMs).toBe(0);
  });

  it("computes offsetMs relative to the earliest step start (t=0)", () => {
    const events: AnalysisLiveEvent[] = [
      { type: "stage", stage_key: "normalize_input", status: "completed", title: "n", summary: "", details: [], emitted_at: "2026-03-20T00:00:01.000Z" } as AnalysisLiveEvent,
      { type: "stage", stage_key: "retrieval_initial", status: "running", title: "r", summary: "", details: [], emitted_at: "2026-03-20T00:00:01.700Z" } as AnalysisLiveEvent,
      { type: "stage", stage_key: "retrieval_initial", status: "completed", title: "r", summary: "", details: [], emitted_at: "2026-03-20T00:00:02.900Z" } as AnalysisLiveEvent,
      { type: "complete", run_id: "r", success: true, summary: "", emitted_at: "2026-03-20T00:00:03.000Z" } as AnalysisLiveEvent,
    ];
    const steps = deriveTraceSteps(events);
    expect(steps[0].offsetMs).toBe(0);
    expect(steps[1].offsetMs).toBe(700);
    expect(steps[1].durationMs).toBe(1200);
  });

  it("leaves durationMs null when the step is still running", () => {
    const events: AnalysisLiveEvent[] = [
      { type: "stage", stage_key: "agent_synthesis", status: "running", title: "s", summary: "", details: [], emitted_at: "2026-03-20T00:00:00.000Z" } as AnalysisLiveEvent,
    ];
    const steps = deriveTraceSteps(events);
    expect(steps[0].durationMs).toBe(null);
    expect(steps[0].endedAt).toBe(null);
  });
});

describe("deriveTraceSteps · parallel group synthesis", () => {
  it("groups the 4 source-agent children under a synthesized parent with wall-clock duration", () => {
    const evt = (stage: string, status: AnalysisLiveStatus, at: string): AnalysisLiveEvent =>
      ({ type: "stage", stage_key: stage, status, title: stage, summary: "", details: [], emitted_at: at } as AnalysisLiveEvent);
    const events: AnalysisLiveEvent[] = [
      evt("agent_retrieval_baidu", "running", "2026-03-20T00:00:00.100Z"),
      evt("agent_retrieval_xiaohongshu", "running", "2026-03-20T00:00:00.200Z"),
      evt("agent_retrieval_toutiao", "running", "2026-03-20T00:00:00.150Z"),
      evt("agent_retrieval_sogou_weixin", "running", "2026-03-20T00:00:00.180Z"),
      evt("agent_retrieval_baidu", "completed", "2026-03-20T00:00:01.700Z"),
      evt("agent_retrieval_xiaohongshu", "completed", "2026-03-20T00:00:01.900Z"),
      evt("agent_retrieval_toutiao", "completed", "2026-03-20T00:00:01.200Z"),
      evt("agent_retrieval_sogou_weixin", "completed", "2026-03-20T00:00:02.100Z"),
      { type: "complete", run_id: "r", success: true, summary: "", emitted_at: "2026-03-20T00:00:03Z" } as AnalysisLiveEvent,
    ];
    const steps = deriveTraceSteps(events);
    expect(steps).toHaveLength(1);
    const parent = steps[0];
    expect(parent.stageKey).toBe("agent_retrieval_orchestrator");
    expect(parent.isParallelGroup).toBe(true);
    expect(parent.children.map((c) => c.stageKey)).toEqual([
      "agent_retrieval_baidu",
      "agent_retrieval_xiaohongshu",
      "agent_retrieval_toutiao",
      "agent_retrieval_sogou_weixin",
    ]);
    // Wall clock = max(2.100) - min(0.100) = 2000ms
    expect(parent.durationMs).toBe(2000);
    // Sum-of-children (naive) is much larger
    expect(sumChildDurationsMs(parent.children)).toBeGreaterThan(2000);
  });

  it("propagates a still-running child up as parent status='running'", () => {
    const evt = (stage: string, status: AnalysisLiveStatus, at: string): AnalysisLiveEvent =>
      ({ type: "stage", stage_key: stage, status, title: stage, summary: "", details: [], emitted_at: at } as AnalysisLiveEvent);
    const events: AnalysisLiveEvent[] = [
      evt("agent_retrieval_baidu", "running", "2026-03-20T00:00:00Z"),
      evt("agent_retrieval_xiaohongshu", "running", "2026-03-20T00:00:00Z"),
      evt("agent_retrieval_baidu", "completed", "2026-03-20T00:00:01Z"),
      // xiaohongshu never completes
    ];
    const steps = deriveTraceSteps(events);
    expect(steps[0].status).toBe("running");
    expect(steps[0].durationMs).toBe(null);
  });
});

describe("applyBackendTiming", () => {
  it("overwrites live-derived timing with backend values, matching by stageKey", () => {
    // Build a step tree the way deriveTraceSteps would produce it, then simulate
    // the final report arriving with authoritative timing.
    const step: TraceStep = {
      stageKey: "retrieval_initial",
      label: "首轮检索",
      status: "completed",
      did: "",
      inputs: [],
      outputs: [],
      note: null,
      llmCalls: [],
      subEvents: [],
      startedAt: "2026-03-20T00:00:00Z",
      endedAt: "2026-03-20T00:00:05Z",
      durationMs: 5000,
      offsetMs: 1234, // wrong: stream deltas said 1234ms, backend truth is 0
      parentKey: null,
      children: [],
      isParallelGroup: false,
    };
    const merged = applyBackendTiming([step], {
      steps: [{
        stage_key: "retrieval_initial",
        started_at: "2026-03-20T00:00:00Z",
        ended_at: "2026-03-20T00:00:03Z",
        duration_ms: 3000,
        offset_ms: 0,
      }],
    });
    expect(merged[0].durationMs).toBe(3000);
    expect(merged[0].offsetMs).toBe(0);
    expect(merged[0].endedAt).toBe("2026-03-20T00:00:03Z");
  });

  it("leaves timing untouched when no backend record matches the step", () => {
    // The stream may carry stages that the backend never wrote a
    // pipeline_trace row for (e.g. a supervisor sub-branch). Those must not
    // get their timing wiped just because we couldn't find a match.
    const step: TraceStep = {
      stageKey: "agent_sub_branch",
      label: "分支",
      status: "completed",
      did: "",
      inputs: [],
      outputs: [],
      note: null,
      llmCalls: [],
      subEvents: [],
      startedAt: "2026-03-20T00:00:00Z",
      endedAt: "2026-03-20T00:00:02Z",
      durationMs: 2000,
      offsetMs: 500,
      parentKey: null,
      children: [],
      isParallelGroup: false,
    };
    const merged = applyBackendTiming([step], {
      steps: [{ stage_key: "unrelated_stage", started_at: null, ended_at: null, duration_ms: null, offset_ms: null }],
    });
    expect(merged[0].durationMs).toBe(2000);
    expect(merged[0].offsetMs).toBe(500);
  });

  it("no-ops when the pipeline_trace argument is null or empty", () => {
    const step: TraceStep = {
      stageKey: "x",
      label: "x",
      status: "completed",
      did: "",
      inputs: [], outputs: [], note: null, llmCalls: [], subEvents: [],
      startedAt: "2026-03-20T00:00:00Z", endedAt: null,
      durationMs: 42, offsetMs: 42, parentKey: null, children: [], isParallelGroup: false,
    };
    expect(applyBackendTiming([step], null)[0].durationMs).toBe(42);
    expect(applyBackendTiming([step], { steps: [] })[0].durationMs).toBe(42);
  });
});
