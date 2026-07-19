import type {
  AgentActionKind,
  AgentRunAction,
  AgentRunView,
  AnalysisLiveEvent,
  AnalysisLiveStatus,
} from "@/types/report";

// Which stage_key maps to which agent-action kind. Stage keys not listed here
// are still shown, defaulting to "tool_call" (they are concrete pipeline steps).
const STAGE_KIND: Record<string, AgentActionKind> = {
  agent_planner: "plan",
  investigation_plan: "decision",
  investigation_retrieval: "tool_call",
  investigation_fetch: "tool_call",
  agent_synthesis: "tool_call",
  normalize_input: "tool_call",
  retrieval_initial: "tool_call",
  question_resolution: "observation",
  retrieval_follow_up: "tool_call",
  claim_extraction: "tool_call",
  verdict_engine: "observation",
  timeline_builder: "tool_call",
  report_build: "finalize",
};

// Stage keys the investigation view surfaces. The generic live trace shows the
// rest; here we keep the agent-decision narrative focused.
const AGENT_STAGE_KEYS = new Set([
  "agent_planner",
  "investigation_plan",
  "investigation_retrieval",
  "investigation_fetch",
  "agent_synthesis",
  "report_build",
]);

function detailValue(details: string[], prefix: string): string | null {
  const hit = details.find((item) => item.startsWith(`${prefix}=`) || item.startsWith(`${prefix}：`));
  if (!hit) {
    return null;
  }
  return hit.slice(hit.indexOf(hit.includes("=") ? "=" : "：") + 1).trim();
}

export function deriveAgentRun(events: AnalysisLiveEvent[]): AgentRunView {
  const actions: AgentRunAction[] = [];
  let usedAgentOrchestrator = false;
  let planner: "llm" | "rule" | null = null;
  let investigationRounds = 0;

  for (const event of events) {
    // The orchestrator announces itself (and its planner) via a log event.
    if (event.type === "log" && event.stage_key === "agent_orchestrator") {
      usedAgentOrchestrator = true;
      const value = detailValue(event.details, "planner");
      if (value === "llm" || value === "rule") {
        planner = value;
      }
      continue;
    }

    const stageKey = "stage_key" in event ? event.stage_key ?? "" : "";
    if (!stageKey || !AGENT_STAGE_KEYS.has(stageKey)) {
      continue;
    }
    if (event.type !== "stage") {
      continue;
    }

    usedAgentOrchestrator = usedAgentOrchestrator || AGENT_STAGE_KEYS.has(stageKey);

    if (stageKey === "investigation_retrieval" && event.status !== "running") {
      investigationRounds += 1;
    }

    actions.push({
      kind: STAGE_KIND[stageKey] ?? "tool_call",
      stageKey,
      title: event.title,
      status: event.status as AnalysisLiveStatus,
      summary: event.summary,
      details: event.details,
      emittedAt: event.emitted_at,
    });
  }

  // Drop a "running" action when a later terminal action for the same
  // stage+title arrives, so each action shows once in its final state. Distinct
  // rounds (e.g. multiple investigation_retrieval) are preserved because each
  // has its own terminal event.
  const terminalKeys = new Set(
    actions
      .filter((action) => action.status !== "running")
      .map((action) => `${action.stageKey}:${action.title}`),
  );
  const collapsed = actions.filter(
    (action) => action.status !== "running" || !terminalKeys.has(`${action.stageKey}:${action.title}`),
  );

  // A fetched page = a completed investigation_fetch (skipped/warning = no body).
  const fetchedPages = collapsed.filter(
    (action) => action.stageKey === "investigation_fetch" && action.status === "completed",
  ).length;

  return {
    usedAgentOrchestrator,
    planner,
    actions: collapsed,
    investigationRounds,
    fetchedPages,
  };
}
