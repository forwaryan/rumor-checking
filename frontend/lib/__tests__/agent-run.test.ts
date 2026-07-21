import { describe, expect, it } from "vitest";
import { deriveAgentRun } from "@/lib/agent-run";
import type { AnalysisLiveEvent, AnalysisLiveStatus } from "@/types/report";

function stage(
  stage_key: string,
  status: AnalysisLiveStatus,
  title: string,
  summary: string,
  details: string[] = [],
  emitted_at = "2026-03-20T00:00:00Z",
): AnalysisLiveEvent {
  return { type: "stage", stage_key, status, title, summary, details, emitted_at } as AnalysisLiveEvent;
}

function log(stage_key: string, details: string[], emitted_at = "2026-03-20T00:00:00Z"): AnalysisLiveEvent {
  return {
    type: "log",
    stage_key,
    title: "log",
    summary: "",
    details,
    level: "info",
    emitted_at,
  } as AnalysisLiveEvent;
}

describe("deriveAgentRun", () => {
  it("returns not-used for a plain (non-agent) event stream", () => {
    const events: AnalysisLiveEvent[] = [
      { type: "session", run_id: "r", trace_id: "t", input_type: "text", summary: "", preview: "", emitted_at: "x" } as AnalysisLiveEvent,
      stage("normalize_input", "completed", "标准化输入", "done"),
    ];
    const view = deriveAgentRun(events);
    expect(view.usedAgentOrchestrator).toBe(false);
    expect(view.planner).toBeNull();
    expect(view.actions).toHaveLength(0);
  });

  it("captures the planner from the orchestrator log", () => {
    const events = [log("agent_orchestrator", ["planner=llm"])];
    const view = deriveAgentRun(events);
    expect(view.usedAgentOrchestrator).toBe(true);
    expect(view.planner).toBe("llm");
  });

  it("groups plan, decision, tool_call and finalize actions", () => {
    const events: AnalysisLiveEvent[] = [
      log("agent_orchestrator", ["planner=llm"]),
      stage("investigation_plan", "running", "调查决策", "评估证据"),
      stage("investigation_plan", "completed", "调查决策", "决定补一轮", ["reason=证据偏弱", "follow_up_query=海州 通报"]),
      stage("investigation_retrieval", "running", "调查补检索", "补抓"),
      stage("investigation_retrieval", "completed", "调查补检索", "已采用", ["adopted=True"]),
      stage("agent_synthesis", "completed", "Agent 综合判断", "产出结论"),
      stage("report_build", "completed", "生成报告", "完成"),
    ];
    const view = deriveAgentRun(events);
    expect(view.usedAgentOrchestrator).toBe(true);

    const kinds = view.actions.map((a) => a.kind);
    expect(kinds).toContain("decision");
    expect(kinds).toContain("tool_call");
    expect(kinds).toContain("finalize");

    // running/completed pair collapses to one action per stage.
    const decisionActions = view.actions.filter((a) => a.stageKey === "investigation_plan");
    expect(decisionActions).toHaveLength(1);
    expect(decisionActions[0].status).toBe("completed");
    expect(decisionActions[0].details).toContain("reason=证据偏弱");

    expect(view.investigationRounds).toBe(1);
  });

  it("counts multiple investigation rounds distinctly", () => {
    const events: AnalysisLiveEvent[] = [
      log("agent_orchestrator", ["planner=llm"]),
      stage("investigation_retrieval", "completed", "调查补检索", "round1", [], "t1"),
      stage("investigation_retrieval", "warning", "调查补检索", "round2", [], "t2"),
    ];
    const view = deriveAgentRun(events);
    expect(view.investigationRounds).toBe(2);
  });

  it("surfaces investigation_fetch as a tool_call action and counts fetched pages", () => {
    const events: AnalysisLiveEvent[] = [
      log("agent_orchestrator", ["planner=llm"]),
      stage("investigation_fetch", "running", "抓取正文", "抓取中", ["url=https://gov.example.com/x"]),
      stage("investigation_fetch", "completed", "抓取正文", "已抓到正文", [
        "url=https://gov.example.com/x",
        "result_id=web-4",
        "body_chars=3200",
      ]),
      stage("agent_synthesis", "completed", "Agent 综合判断", "产出结论"),
    ];
    const view = deriveAgentRun(events);

    const fetchActions = view.actions.filter((a) => a.stageKey === "investigation_fetch");
    expect(fetchActions).toHaveLength(1); // running/completed collapse to one
    expect(fetchActions[0].kind).toBe("tool_call");
    expect(fetchActions[0].status).toBe("completed");
    expect(fetchActions[0].details).toContain("result_id=web-4");
    expect(view.fetchedPages).toBe(1);
  });

  it("does not count a skipped or failed fetch as a fetched page", () => {
    const events: AnalysisLiveEvent[] = [
      log("agent_orchestrator", ["planner=llm"]),
      stage("investigation_fetch", "warning", "抓取正文", "抓取失败", ["url=https://x"]),
      stage("investigation_fetch", "skipped", "抓取正文", "无可抓页面", [], "t2"),
    ];
    const view = deriveAgentRun(events);
    expect(view.fetchedPages).toBe(0);
  });
});
