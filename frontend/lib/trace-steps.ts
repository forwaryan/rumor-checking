import type {
  AnalysisLiveEvent,
  AnalysisLiveStatus,
  TraceKeyValue,
  TraceStep,
  TraceSubEvent,
} from "@/types/report";

// Human labels for each pipeline stage_key, so the trace reads as a narrative
// of what the backend actually did at each step.
const STAGE_LABEL: Record<string, string> = {
  normalize_input: "标准化输入",
  retrieval_initial: "首轮检索",
  question_resolution: "问题消歧",
  retrieval_follow_up: "追加检索",
  investigation_plan: "调查决策",
  investigation_retrieval: "补充检索",
  investigation_fetch: "抓取正文",
  agent_planner: "Agent 规划",
  agent_orchestrator: "Agent 编排",
  agent_synthesis: "综合判断",
  provider_enrichment: "结构化补全",
  claim_extraction: "拆解核查点",
  verdict_engine: "证据判定",
  timeline_builder: "构建时间线",
  report_build: "生成报告",
};

// How each detail key should be presented, and whether it reads as an input
// (what the step was given / decided to do) or an output (what it produced).
const DETAIL_META: Record<string, { label: string; kind: "input" | "output" }> = {
  query: { label: "检索词", kind: "input" },
  rationale: { label: "理由", kind: "input" },
  follow_up_query: { label: "追加检索词", kind: "input" },
  reason: { label: "决策理由", kind: "output" },
  round: { label: "轮次", kind: "input" },
  provider: { label: "检索源", kind: "input" },
  model: { label: "模型", kind: "input" },
  input_type: { label: "输入类型", kind: "input" },
  question_only: { label: "纯问题", kind: "input" },
  canonical_results: { label: "去重结果", kind: "output" },
  raw_results: { label: "原始结果", kind: "output" },
  independent_high_trust: { label: "高可信独立源", kind: "output" },
  retrieval_hits: { label: "命中数", kind: "output" },
  claims: { label: "核查点", kind: "output" },
  claim_results: { label: "判定数", kind: "output" },
  timeline_nodes: { label: "时间线节点", kind: "output" },
  evidence_grade: { label: "证据等级", kind: "output" },
  cache_status: { label: "缓存", kind: "output" },
  fallback_used: { label: "是否兜底", kind: "output" },
  event_title: { label: "事件标题", kind: "output" },
  resolved_title: { label: "锚定事件", kind: "output" },
  selected_result: { label: "选中结果", kind: "output" },
  source_name: { label: "来源", kind: "output" },
  mode: { label: "模式", kind: "output" },
  hit: { label: "命中", kind: "output" },
  failure_detail: { label: "失败原因", kind: "output" },
  error_type: { label: "错误类型", kind: "output" },
};

function splitDetail(detail: string): [string, string] | null {
  const eq = detail.indexOf("=");
  const cn = detail.indexOf("：");
  const idx = eq === -1 ? cn : cn === -1 ? eq : Math.min(eq, cn);
  if (idx <= 0) {
    return null;
  }
  return [detail.slice(0, idx).trim(), detail.slice(idx + 1).trim()];
}

function stageKeyOf(event: AnalysisLiveEvent): string {
  if ("stage_key" in event && typeof event.stage_key === "string") {
    return event.stage_key;
  }
  return "";
}

function labelFor(stageKey: string): string {
  return STAGE_LABEL[stageKey] ?? stageKey;
}

function isTerminal(status: AnalysisLiveStatus): boolean {
  return status !== "running";
}

/**
 * Group the flat live-event stream into ordered, observable steps.
 *
 * Each stage_key becomes one step. Stage events set status / did / inputs /
 * outputs; api_call, retrieval and log events that share the stage_key attach
 * as sub-events so the reader can see what the step called and returned. A step
 * only starts once its first event arrives, so this renders correctly while the
 * stream is still in flight (the last step shows as running).
 */
export function deriveTraceSteps(events: AnalysisLiveEvent[]): TraceStep[] {
  const order: string[] = [];
  const byStage = new Map<string, TraceStep>();

  const ensure = (stageKey: string, emittedAt: string): TraceStep => {
    let step = byStage.get(stageKey);
    if (!step) {
      step = {
        stageKey,
        label: labelFor(stageKey),
        status: "running",
        did: "",
        inputs: [],
        outputs: [],
        note: null,
        subEvents: [],
        startedAt: emittedAt,
        endedAt: null,
      };
      byStage.set(stageKey, step);
      order.push(stageKey);
    }
    return step;
  };

  const applyDetails = (step: TraceStep, details: string[]) => {
    for (const detail of details) {
      const pair = splitDetail(detail);
      if (!pair) {
        continue;
      }
      const [key, value] = pair;
      if (!value) {
        continue;
      }
      const meta = DETAIL_META[key];
      if (!meta) {
        continue;
      }
      const bucket: TraceKeyValue[] = meta.kind === "input" ? step.inputs : step.outputs;
      const existing = bucket.find((item) => item.key === key);
      const kv: TraceKeyValue = { key, label: meta.label, value };
      if (existing) {
        existing.value = value;
      } else {
        bucket.push(kv);
      }
    }
  };

  for (const event of events) {
    const stageKey = stageKeyOf(event);
    if (!stageKey) {
      continue;
    }

    if (event.type === "stage") {
      const step = ensure(stageKey, event.emitted_at);
      step.status = event.status;
      if (event.summary) {
        step.did = event.summary;
      }
      applyDetails(step, event.details);
      if (isTerminal(event.status)) {
        step.endedAt = event.emitted_at;
      }
      continue;
    }

    if (event.type === "api_call" || event.type === "retrieval" || event.type === "log") {
      const step = ensure(stageKey, event.emitted_at);
      applyDetails(step, event.details);

      const subStatus: AnalysisLiveStatus =
        event.type === "retrieval"
          ? "completed"
          : event.type === "api_call"
            ? event.status
            : event.level === "error"
              ? "error"
              : event.level === "warning"
                ? "warning"
                : "completed";

      const sub: TraceSubEvent = {
        kind: event.type,
        title:
          event.type === "retrieval"
            ? `检索: ${event.query || event.query_label}`
            : event.title,
        summary: event.summary,
        status: subStatus,
        level: event.type === "log" ? event.level : undefined,
      };
      step.subEvents.push(sub);

      // A warning/error log is the step's most useful "结论" note.
      if (event.type === "log" && (event.level === "warning" || event.level === "error")) {
        step.note = event.summary || event.title;
      }
      continue;
    }
  }

  return order.map((key) => byStage.get(key)!);
}
