import { describe, expect, it } from "vitest";
import { deriveTraceSteps, formatLlmText, humanizeLlmText } from "@/lib/trace-steps";
import type { AnalysisLiveEvent, AnalysisLiveStatus } from "@/types/report";

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
