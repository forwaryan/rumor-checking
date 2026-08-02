import type {
  AnalysisLiveEvent,
  AnalysisLiveStatus,
  TraceKeyValue,
  TraceLlmCall,
  TraceStep,
  TraceSubEvent,
} from "@/types/report";

/**
 * Format a millisecond duration as a short human string:
 *   "—" when null (still running / unknown)
 *   "482ms" when < 1000ms
 *   "1.24s" when < 60s
 *   "1m 05s" when >= 60s
 */
export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`;
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

/**
 * For a step that is still running, return "已跑 X" based on now vs startedAt.
 * Used by the live-tick renderer while the stream is in flight.
 */
export function elapsedSince(startedAtIso: string, nowMs: number): number {
  const start = new Date(startedAtIso).getTime();
  if (!Number.isFinite(start)) return 0;
  return Math.max(0, nowMs - start);
}

/**
 * Aggregate the "wall clock" of a parallel group: max(child endedAt) - min(child startedAt).
 * Returns null if any child is still running (endedAt === null), so we never
 * display a wall-clock that would grow if we waited longer.
 */
export function parallelWallClockMs(children: TraceStep[]): number | null {
  if (children.length === 0) return null;
  if (children.some((c) => c.endedAt === null)) return null;
  const starts = children.map((c) => new Date(c.startedAt).getTime()).filter(Number.isFinite);
  const ends = children.map((c) => new Date(c.endedAt as string).getTime()).filter(Number.isFinite);
  if (starts.length === 0 || ends.length === 0) return null;
  return Math.max(...ends) - Math.min(...starts);
}

/**
 * Naive sum of child durations. When we compare this against
 * parallelWallClockMs, the difference is how much wall-clock the fan-out saved.
 */
export function sumChildDurationsMs(children: TraceStep[]): number {
  return children.reduce((acc, c) => acc + (c.durationMs ?? 0), 0);
}

/**
 * Make an LLM prompt/response readable: pretty-print the embedded JSON object
 * (the compressed one-line JSON is unreadable), while keeping any leading
 * instruction text ("Choose the single best… Context JSON:") as-is. Falls back
 * to the original string when there is no parseable JSON.
 */
export function formatLlmText(text: string): string {
  if (!text) return "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) {
    return text.trim();
  }
  const lead = text.slice(0, start).trim();
  const jsonPart = text.slice(start, end + 1);
  try {
    const pretty = JSON.stringify(JSON.parse(jsonPart), null, 2);
    return lead ? `${lead}\n\n${pretty}` : pretty;
  } catch {
    return text.trim();
  }
}

function extractJson(text: string): Record<string, unknown> | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

const VERDICT_CN: Record<string, string> = {
  supported: "基本属实",
  refuted: "不实",
  insufficient: "证据不足",
  conflicting: "各方说法矛盾",
};

/**
 * Translate an LLM prompt/response into a natural-language summary so a
 * non-technical reader understands what the model was asked and answered,
 * without reading JSON. Falls back to the pretty-printed JSON when the shape
 * is unrecognized.
 */
export function humanizeLlmText(stageKey: string, role: "prompt" | "response", text: string): string {
  const json = extractJson(text);
  if (!json) return formatLlmText(text);

  if (role === "response") {
    // planner: { next_action, reason }
    if (typeof json.next_action === "string") {
      const actionCn: Record<string, string> = {
        investigate: "再补一轮检索",
        fetch_url: "抓取某条证据的正文",
        synthesize: "直接综合下结论",
      };
      const action = actionCn[json.next_action] ?? String(json.next_action);
      const reason = typeof json.reason === "string" ? json.reason : "";
      return `决定：${action}。${reason ? `\n原因：${reason}` : ""}`;
    }
    // investigation: { should_continue, follow_up_query, reason }
    if (typeof json.should_continue === "boolean") {
      const cont = json.should_continue ? "需要再查一轮" : "不再补检索";
      const q = typeof json.follow_up_query === "string" && json.follow_up_query ? json.follow_up_query : null;
      const reason = typeof json.reason === "string" ? json.reason : "";
      return [
        `判断：${cont}。`,
        q ? `追加检索词：${q}` : null,
        reason ? `原因：${reason}` : null,
      ].filter(Boolean).join("\n");
    }
    // synthesis: { event, claims[], timeline[] }
    if (json.event || Array.isArray(json.claims)) {
      const lines: string[] = [];
      const event = json.event as Record<string, unknown> | undefined;
      if (event && typeof event.summary === "string") {
        lines.push(`事件小结：${event.summary}`);
      }
      const claims = Array.isArray(json.claims) ? json.claims : [];
      if (claims.length) {
        lines.push(`核查了 ${claims.length} 条：`);
        claims.forEach((c, i) => {
          const claim = c as Record<string, unknown>;
          const text = typeof claim.claim === "string" ? claim.claim : `核查点 ${i + 1}`;
          const verdict = typeof claim.verdict === "string" ? (VERDICT_CN[claim.verdict] ?? claim.verdict) : "";
          const notes = typeof claim.notes === "string" ? claim.notes : "";
          lines.push(`  ${i + 1}. ${text} → ${verdict}${notes ? `（${notes}）` : ""}`);
        });
      }
      const timeline = Array.isArray(json.timeline) ? json.timeline : [];
      if (timeline.length) lines.push(`时间线节点：${timeline.length} 个`);
      return lines.join("\n") || formatLlmText(text);
    }
  }

  if (role === "prompt") {
    // The prompt is an instruction + Context JSON; summarize the evidence snapshot.
    const lead = text.slice(0, text.indexOf("{")).trim();
    const lines: string[] = [];
    if (lead) lines.push(lead);
    const snap = (json.evidence_snapshot ?? json.evidence ?? json) as Record<string, unknown>;
    const parts: string[] = [];
    const grade = snap.evidence_grade ?? (json.evidence_grade_hint as unknown);
    if (typeof grade === "string") parts.push(`证据等级 ${grade}`);
    const n = snap.canonical_result_count ?? snap.canonical_result_count;
    if (typeof n === "number") parts.push(`候选结果 ${n} 条`);
    const ht = snap.high_trust_result_count;
    if (typeof ht === "number") parts.push(`高可信 ${ht} 条`);
    const hits = json.retrieval_hits;
    if (Array.isArray(hits)) parts.push(`附带 ${hits.length} 条检索命中`);
    if (parts.length) lines.push(`给模型的证据：${parts.join("、")}`);
    return lines.join("\n") || formatLlmText(text);
  }

  return formatLlmText(text);
}

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
  per_claim_retrieval: "逐条补检索",
  re_judge_claims: "Claim 重判",
  llm_verdict: "LLM 补判",
  agent_planner: "Agent 规划",
  agent_orchestrator: "Agent 编排",
  agent_synthesis: "综合判断",
  provider_enrichment: "结构化补全",
  claim_extraction: "拆解核查点",
  verdict_engine: "证据判定",
  timeline_builder: "构建时间线",
  report_build: "生成报告",
  // Multi-agent parallel DAG stages
  agent_retrieval_orchestrator: "并行检索编排",
  agent_retrieval_baidu: "百度检索",
  agent_retrieval_xiaohongshu: "小红书检索",
  agent_retrieval_toutiao: "今日头条检索",
  agent_retrieval_sogou_weixin: "搜狗微信检索",
  agent_retrieval_piyao: "辟谣平台检索",
  agent_retrieval_merge: "检索合并",
  agent_normalize: "输入规整",
  agent_analysis: "综合分析",
  agent_critic: "结果复核",
};

// Parent-child mapping: which stage_keys are children of a group, and which is
// their parent's stage_key. Children roll their bars up under the parent, and
// the parent's duration is computed as max(child.endedAt) - min(child.startedAt).
// Only stages that appear as VALUES here become children; unmapped stages stay
// at the top level. Parallel-branch groups set `parallel: true` so the renderer
// visualizes the fan-out as overlapping bars instead of sequential.
interface ParentSpec {
  parent: string;
  parentLabel: string;
  children: string[];
  parallel: boolean;
}

const PARALLEL_GROUPS: ParentSpec[] = [
  {
    parent: "agent_retrieval_orchestrator",
    parentLabel: "并行检索编排",
    children: [
      "agent_retrieval_baidu",
      "agent_retrieval_xiaohongshu",
      "agent_retrieval_toutiao",
      "agent_retrieval_sogou_weixin",
      "agent_retrieval_piyao",
    ],
    parallel: true,
  },
];

const CHILD_TO_PARENT = new Map<string, ParentSpec>();
for (const spec of PARALLEL_GROUPS) {
  for (const child of spec.children) {
    CHILD_TO_PARENT.set(child, spec);
  }
}

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
  outcome: { label: "本次结果", kind: "output" },
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

function detailOf(details: string[], key: string): string | null {
  for (const detail of details) {
    const pair = splitDetail(detail);
    if (pair && pair[0] === key) {
      return pair[1];
    }
  }
  return null;
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

// Rank a sub-event's severity so a step's inferred terminal status reflects its
// worst outcome (an error sub-event should not resolve to a bland "completed").
function severityRank(status: AnalysisLiveStatus): number {
  if (status === "error") return 3;
  if (status === "warning") return 2;
  return 1;
}

// Concurrent retrieval emits each query as a running (from a worker thread) and
// then a completed sub-event, and the threads interleave — so a step's raw
// sub-event list is both out of order and doubled. Sort by emit time, then fold
// each running+terminal pair of the same (kind, title) into its final state,
// mirroring how llmCalls pair a prompt with its response.
function normalizeSubEvents(subEvents: TraceSubEvent[]): TraceSubEvent[] {
  const ordered = subEvents
    .map((sub, index) => ({ sub, index }))
    .sort((a, b) => {
      const ta = a.sub.emittedAt ?? "";
      const tb = b.sub.emittedAt ?? "";
      if (ta !== tb) return ta < tb ? -1 : 1;
      return a.index - b.index; // stable within the same timestamp
    })
    .map((entry) => entry.sub);

  const collapsed: TraceSubEvent[] = [];
  const byKey = new Map<string, TraceSubEvent>();
  for (const sub of ordered) {
    const key = `${sub.kind}:${sub.title}`;
    const open = byKey.get(key);
    if (open && open.status === "running") {
      open.status = sub.status;
      open.summary = sub.summary || open.summary;
      // The terminal event carries the actual hits; keep them on the folded row.
      if (sub.results && sub.results.length) open.results = sub.results;
      if (sub.query) open.query = sub.query;
      if (isTerminal(sub.status)) byKey.delete(key);
      continue;
    }
    collapsed.push(sub);
    if (sub.status === "running") byKey.set(key, sub);
  }
  return collapsed;
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
        llmCalls: [],
        subEvents: [],
        startedAt: emittedAt,
        endedAt: null,
        durationMs: null,
        offsetMs: 0,
        parentKey: null,
        children: [],
        isParallelGroup: false,
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

      // LLM calls carry prompt= (on the running event) and response= (on the
      // completed "返回" event); pair them into one 提问/回答 record so the
      // trace shows what was actually asked and answered.
      if (event.type === "api_call" && event.call_type === "llm") {
        const details = event.details ?? [];
        const system = detailOf(details, "system");
        const prompt = detailOf(details, "prompt");
        const response = detailOf(details, "response");
        if (prompt !== null) {
          step.llmCalls.push({
            title: event.title,
            system,
            prompt,
            response: null,
            status: event.status,
          });
        } else if (response !== null) {
          // Attach to the most recent open call, else start a new record.
          const open = [...step.llmCalls].reverse().find((c) => c.response === null);
          if (open) {
            open.response = response;
            open.status = event.status;
          } else {
            step.llmCalls.push({ title: event.title, system, prompt: null, response, status: event.status });
          }
        }
      }

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
        emittedAt: event.emitted_at,
        query: event.type === "retrieval" ? event.query : undefined,
        results: event.type === "retrieval" ? event.results : undefined,
        details: event.details?.length ? event.details : undefined,
      };
      step.subEvents.push(sub);

      // A warning/error log is the step's most useful "结论" note.
      if (event.type === "log" && (event.level === "warning" || event.level === "error")) {
        step.note = event.summary || event.title;
      }
      continue;
    }
  }

  // Some stages (agent_orchestrator, agent_planner) only ever emit log/api_call
  // events, never a terminal `stage` event, so their step is born "running" and
  // would hang there forever. Once the run itself has ended, resolve any step
  // still marked running from its own sub-events (worst outcome wins), so no step
  // is left falsely "进行中" after the pipeline finished. While the stream is
  // still in flight we leave the last step running, as before.
  const streamEnded = events.some(
    (event) => event.type === "complete" || event.type === "error" || event.type === "report",
  );

  const flatSteps = order.map((key) => byStage.get(key)!);
  for (const step of flatSteps) {
    step.subEvents = normalizeSubEvents(step.subEvents);
    if (streamEnded && step.status === "running") {
      const worst = step.subEvents.reduce(
        (acc, sub) => (severityRank(sub.status) > severityRank(acc) ? sub.status : acc),
        "completed" as AnalysisLiveStatus,
      );
      step.status = worst;
      const lastSub = step.subEvents[step.subEvents.length - 1];
      step.endedAt = lastSub?.emittedAt ?? step.startedAt;
    }
    // If a step has sub-events later than its own endedAt (e.g. retrieval events
    // that ran after the terminal stage event), extend endedAt so the timing
    // reflects actual work — otherwise `durationMs` under-reports parallel work.
    if (step.endedAt && step.subEvents.length) {
      const latestSub = step.subEvents.reduce((acc, s) => {
        const t = s.emittedAt ?? "";
        return t > acc ? t : acc;
      }, "");
      if (latestSub && latestSub > step.endedAt) {
        step.endedAt = latestSub;
      }
    }
  }

  // Synthesize a parent group step for parallel branches (the multi-agent
  // orchestrator does not emit its own stage events — only children do). This
  // lets the renderer show the 4 parallel source-agent bars nested inside one
  // "并行检索编排" row with a wall-clock duration = max(end) - min(start).
  for (const spec of PARALLEL_GROUPS) {
    const childSteps = spec.children
      .map((k) => byStage.get(k))
      .filter((s): s is TraceStep => Boolean(s));
    if (childSteps.length === 0) continue;
    if (byStage.has(spec.parent)) continue;

    const earliestStart = childSteps.reduce(
      (acc, s) => (s.startedAt < acc ? s.startedAt : acc),
      childSteps[0].startedAt,
    );
    // If any child hasn't ended yet, the parent's wall-clock is unknown — leave
    // endedAt null so the renderer shows "—" instead of a misleading duration.
    const anyChildOpen = childSteps.some((s) => s.endedAt === null);
    const latestEnd: string | null = anyChildOpen
      ? null
      : childSteps.reduce<string | null>((acc, s) => {
          if (!s.endedAt) return acc;
          if (acc === null) return s.endedAt;
          return s.endedAt > acc ? s.endedAt : acc;
        }, null);
    const someRunning = childSteps.some((s) => s.status === "running");
    const someError = childSteps.some((s) => s.status === "error");
    const someWarn = childSteps.some((s) => s.status === "warning");
    const parentStatus: AnalysisLiveStatus = someRunning
      ? "running"
      : someError
        ? "error"
        : someWarn
          ? "warning"
          : "completed";
    const parent: TraceStep = {
      stageKey: spec.parent,
      label: spec.parentLabel,
      status: parentStatus,
      did: `并行 ${childSteps.length} 路检索源`,
      inputs: [],
      outputs: [],
      note: null,
      llmCalls: [],
      subEvents: [],
      startedAt: earliestStart,
      endedAt: latestEnd,
      durationMs: null,
      offsetMs: 0,
      parentKey: null,
      children: [],
      isParallelGroup: true,
    };
    byStage.set(spec.parent, parent);
    // Insert parent right before its first child in the ordered list so timeline
    // ordering stays chronological.
    const firstChildIdx = order.findIndex((k) => spec.children.includes(k));
    if (firstChildIdx >= 0) {
      order.splice(firstChildIdx, 0, spec.parent);
    } else {
      order.push(spec.parent);
    }
  }

  // Wire parent<->children references and remove children from the top level.
  const childKeys = new Set<string>();
  for (const step of order.map((k) => byStage.get(k)!)) {
    const spec = CHILD_TO_PARENT.get(step.stageKey);
    if (spec) {
      const parent = byStage.get(spec.parent);
      if (parent) {
        step.parentKey = parent.stageKey;
        parent.children.push(step);
        childKeys.add(step.stageKey);
      }
    }
  }

  const topLevel = order.map((k) => byStage.get(k)!).filter((s) => !childKeys.has(s.stageKey));

  // Compute t=0 as the earliest startedAt across all steps, and populate
  // durationMs (null if the step is still running) and offsetMs (from t=0).
  // Recursion covers the two-level tree.
  const allStepsFlat: TraceStep[] = [];
  const walk = (s: TraceStep) => {
    allStepsFlat.push(s);
    s.children.forEach(walk);
  };
  topLevel.forEach(walk);

  if (allStepsFlat.length === 0) return topLevel;

  const t0 = allStepsFlat.reduce(
    (acc, s) => (s.startedAt < acc ? s.startedAt : acc),
    allStepsFlat[0].startedAt,
  );
  const t0Ms = new Date(t0).getTime();

  for (const step of allStepsFlat) {
    const startMs = new Date(step.startedAt).getTime();
    step.offsetMs = Number.isFinite(startMs) && Number.isFinite(t0Ms) ? Math.max(0, startMs - t0Ms) : 0;
    if (step.endedAt) {
      const endMs = new Date(step.endedAt).getTime();
      if (Number.isFinite(endMs) && Number.isFinite(startMs) && endMs >= startMs) {
        step.durationMs = endMs - startMs;
      }
    }
  }

  return topLevel;
}

/**
 * Overwrite streaming-derived timing with the backend's authoritative values
 * once the run completes. The stream carries live inputs/outputs/LLM calls
 * that the backend trace doesn't (so we can't just replace the tree), but
 * the wall-clock coordinates are strictly better on the backend where they
 * were captured at emit time instead of derived from stream deltas.
 *
 * Called with the final report's pipeline_trace after streaming ends. Live
 * ticks before the report arrives keep the stream-derived timing so bars
 * grow smoothly in real time.
 */
export function applyBackendTiming(
  steps: TraceStep[],
  pipelineTrace: { steps: { stage_key: string; started_at?: string | null; ended_at?: string | null; duration_ms?: number | null; offset_ms?: number | null }[] } | null | undefined,
): TraceStep[] {
  if (!pipelineTrace?.steps?.length) return steps;
  const byKey = new Map<string, (typeof pipelineTrace.steps)[number]>();
  for (const s of pipelineTrace.steps) byKey.set(s.stage_key, s);
  const walk = (list: TraceStep[]): TraceStep[] => list.map((step) => {
    const src = byKey.get(step.stageKey);
    const merged: TraceStep = {
      ...step,
      startedAt: src?.started_at ?? step.startedAt,
      endedAt: src?.ended_at ?? step.endedAt,
      durationMs: src?.duration_ms ?? step.durationMs,
      offsetMs: src?.offset_ms ?? step.offsetMs,
    };
    if (step.children.length) merged.children = walk(step.children);
    return merged;
  });
  return walk(steps);
}
