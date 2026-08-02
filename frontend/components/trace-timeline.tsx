"use client";

import { useEffect, useState } from "react";
import type { TraceStep } from "@/types/report";
import {
  elapsedSince,
  formatDuration,
  formatLlmText,
  humanizeLlmText,
  parallelWallClockMs,
  sumChildDurationsMs,
} from "@/lib/trace-steps";
import { extractModelFromTitle, estimateTokens, getLlmStatusLabel, tryParseClaims, type ParsedClaim } from "@/lib/trace-utils";

/** Header row showing model, status, and token estimate for an LLM call */
function LlmCallMeta({ title, status, response }: { title: string; status: string; response: string | null }) {
  const model = extractModelFromTitle(title);
  const tokens = estimateTokens(response);
  const statusLabel = getLlmStatusLabel(status);
  return (
    <div className="exec-llm__meta">
      {model && <span className="exec-llm__meta-model">{model}</span>}
      <span className={`exec-llm__meta-badge exec-llm__meta-badge--${statusLabel}`}>
        {statusLabel === "completed" ? "completed" : statusLabel === "warning" ? "warning" : statusLabel === "error" ? "error" : "running"}
      </span>
      {tokens !== null && <span className="exec-llm__meta-tokens">~{tokens} tokens</span>}
    </div>
  );
}

/** Compact summary when response is a claims JSON array */
function LlmClaimsSummary({ claims }: { claims: ParsedClaim[] }) {
  return (
    <div className="exec-llm__claims-summary">
      <span className="exec-llm__claims-summary-count">产出 {claims.length} 条 claims:</span>
      <span className="exec-llm__claims-summary-list">
        {claims.map((c, i) => (
          <span key={i} className="exec-llm__claims-summary-item">
            <span className={`exec-llm__verdict-badge exec-llm__verdict-badge--${c.verdict}`}>
              {c.verdict === "supported" ? "属实" : c.verdict === "refuted" ? "不实" : c.verdict === "conflicting" ? "矛盾" : "不足"}
            </span>
            <span className="exec-llm__claims-summary-text">{c.claim}</span>
          </span>
        ))}
      </span>
    </div>
  );
}

// One prompt-or-response block with 人类可读 / 原始 JSON tabs.
function LlmTextBlock({ stageKey, role, text }: { stageKey: string; role: "prompt" | "response" | "system"; text: string }) {
  const [view, setView] = useState<"human" | "json">("human");
  const [systemOpen, setSystemOpen] = useState(false);
  if (role === "system") {
    return (
      <div className="exec-llm__block exec-llm__block--system">
        <div className="exec-llm__head" onClick={() => setSystemOpen(!systemOpen)} style={{ cursor: "pointer" }}>
          <span className="exec-llm__label exec-llm__label--s">系统指令</span>
          <span className={`section-card__arrow${systemOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
        </div>
        {systemOpen && <pre className="exec-llm__text">{text}</pre>}
      </div>
    );
  }
  const label = role === "prompt" ? "提问模型" : "模型回答";
  const body = view === "human" ? humanizeLlmText(stageKey, role, text) : formatLlmText(text);
  return (
    <div className={`exec-llm__block exec-llm__block--${role}`}>
      <div className="exec-llm__head">
        <span className={`exec-llm__label exec-llm__label--${role === "prompt" ? "q" : "a"}`}>{label}</span>
        <div className="exec-llm__tabs">
          <button
            className={`exec-llm__tab${view === "human" ? " exec-llm__tab--active" : ""}`}
            onClick={() => setView("human")}
          >
            人类可读
          </button>
          <button
            className={`exec-llm__tab${view === "json" ? " exec-llm__tab--active" : ""}`}
            onClick={() => setView("json")}
          >
            原始 JSON
          </button>
        </div>
      </div>
      <pre className="exec-llm__text">{body}</pre>
    </div>
  );
}

/**
 * Log-scale axis span. Every timeline coordinate is projected via
 * ``log10(max(ms, LOG_FLOOR_MS))`` so a run that spans 1ms → 3 minutes
 * (5 orders of magnitude) still shows the sub-second steps as visible bars
 * instead of hairlines. The floor collapses "0ms" and sub-millisecond
 * events into the leftmost decade — they render as a small marker rather
 * than mathematically inflating to -infinity.
 */
const LOG_FLOOR_MS = 1;

function toLog(ms: number): number {
  return Math.log10(Math.max(ms, LOG_FLOOR_MS));
}

/** Project a raw millisecond count to a 0-100 percentage on the log axis. */
function logPercent(ms: number, totalMs: number): number {
  const denom = toLog(Math.max(totalMs, LOG_FLOOR_MS));
  if (denom <= 0) return 0;
  return Math.max(0, Math.min(100, (toLog(ms) / denom) * 100));
}

/**
 * Log-scale ticks: decades that fit inside the run (1ms, 10ms, ..., 10m, 1h)
 * plus an endpoint tick at the exact total. If the endpoint would land within
 * 6% (log-space) of the last decade tick their labels overlap in practice, so
 * we drop the decade and keep the endpoint — the exact total is more useful
 * than a nearby round decade the user can already tell from context.
 */
function pickLogTicks(totalMs: number): number[] {
  const decades = [1, 10, 100, 1_000, 10_000, 60_000, 600_000, 3_600_000];
  const ticks = decades.filter((t) => t <= totalMs);
  if (ticks.length === 0) return [totalMs];
  if (ticks[ticks.length - 1] === totalMs) return ticks;
  const denom = toLog(totalMs);
  if (denom > 0) {
    // Percentage-space collision check: at 10% (log-space) apart the two labels
    // still visually crowd on typical decade→endpoint pairs like "10s" vs
    // "22.7s" (5+ chars). 6% was too tight and left the endpoint colliding with
    // the last decade in real runs — see the 22.66s screenshot.
    const OVERLAP_PCT = 10;
    while (ticks.length > 0) {
      const lastPct = (toLog(ticks[ticks.length - 1]) / denom) * 100;
      const endPct = 100; // endpoint is by definition at 100%
      if (endPct - lastPct < OVERLAP_PCT) {
        ticks.pop();
        continue;
      }
      break;
    }
  }
  ticks.push(totalMs);
  return ticks;
}

/** Compact tick label — like formatDuration but strips trailing zeros on the
 * seconds decimal so `10s` doesn't show up as `10.00s` and crowd its neighbor. */
function formatTickLabel(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) {
    const s = ms / 1000;
    // Whole-second decade ticks render as "10s"; non-round labels get one decimal.
    if (Math.abs(s - Math.round(s)) < 0.05) return `${Math.round(s)}s`;
    return `${s.toFixed(1)}s`;
  }
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (s === 0) return `${m}m`;
  return `${m}m${s}s`;
}

/**
 * Pick a "nice" tick step (1s / 2s / 5s / 10s / 30s / 1m / 5m) so the axis
 * renders 4–8 labels regardless of run length. Kept as a plain lookup — no need
 * to be clever about arbitrary durations for a UI ruler.
 *
 * NOTE: unused since the ruler switched to log-scale ticks; retained in case
 * we need a linear ruler again for a run-analysis mode.
 */
function pickTickStepMs(totalMs: number): number {
  const target = totalMs / 6;
  const candidates = [
    500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
    60_000, 120_000, 300_000, 600_000, 1_800_000, 3_600_000,
  ];
  for (const c of candidates) {
    if (c >= target) return c;
  }
  return candidates[candidates.length - 1];
}

/** Ruler across the top of the timeline. Aligned with .gantt-row__track.
 *
 * Uses a log scale so the 1ms → 3m spread in a typical run doesn't collapse
 * short steps to hairlines. Each decade (1ms, 10ms, 100ms, 1s, 10s, 1m, 10m)
 * gets its own tick, plus an endpoint marker at the exact total. */
function TimelineRuler({ totalMs }: { totalMs: number }) {
  const ticks = pickLogTicks(totalMs);
  return (
    <div className="gantt-ruler">
      <div className="gantt-ruler__labels" aria-hidden="true" />
      <div className="gantt-ruler__track">
        {ticks.map((t, i) => {
          const left = logPercent(t, totalMs);
          const label = formatTickLabel(t);
          return (
            <div key={i} className="gantt-ruler__tick" style={{ left: `${left}%` }}>
              <span className="gantt-ruler__tick-mark" />
              <span className="gantt-ruler__tick-label">{label}</span>
            </div>
          );
        })}
      </div>
      <div className="gantt-ruler__timing" aria-hidden="true" />
    </div>
  );
}

/**
 * Compute the total wall-clock of the run, plus min/max child durations across
 * all leaves (used for fastest/slowest markers inside a parallel group).
 */
function computeTotals(steps: TraceStep[]): { totalMs: number | null; minMs: number; maxMs: number } {
  let earliestStart = Infinity;
  let latestEnd = -Infinity;
  let anyRunning = false;
  const walk = (s: TraceStep) => {
    const start = new Date(s.startedAt).getTime();
    if (Number.isFinite(start)) earliestStart = Math.min(earliestStart, start);
    if (s.endedAt) {
      const end = new Date(s.endedAt).getTime();
      if (Number.isFinite(end)) latestEnd = Math.max(latestEnd, end);
    } else {
      anyRunning = true;
    }
    s.children.forEach(walk);
  };
  steps.forEach(walk);
  const total = anyRunning || earliestStart === Infinity || latestEnd === -Infinity ? null : latestEnd - earliestStart;
  return { totalMs: total, minMs: 0, maxMs: 0 };
}

/**
 * Render one step as a Gantt row: an inline time bar positioned by offsetMs and
 * sized by durationMs, followed by the details body. For parent (parallel-group)
 * steps, the body includes nested child rows.
 */
function GanttRow({
  step,
  runTotalMs,
  runIsInProgress,
  isChild,
  fastestSiblingKey,
  slowestSiblingKey,
  nowMs,
  expanded,
  onToggle,
}: {
  step: TraceStep;
  runTotalMs: number;
  runIsInProgress: boolean;
  isChild: boolean;
  fastestSiblingKey?: string;
  slowestSiblingKey?: string;
  nowMs: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  // Duration for display. If the step hasn't ended yet, either count from
  // startedAt to now (live tick) or show "—".
  const liveMs = step.durationMs ?? (step.status === "running" ? elapsedSince(step.startedAt, nowMs) : null);
  const durationLabel = formatDuration(liveMs);
  // Log-scale positioning: a stage running from offsetMs (start) to
  // offsetMs+durationMs (end) is projected as [log(start), log(end)] on the
  // shared log axis. Steps that started at exactly t=0 collapse to log(1ms);
  // steps with sub-millisecond duration still get a visible minimum width so
  // they don't disappear into a hairline.
  const effectiveDuration = liveMs ?? 0;
  const endMs = step.offsetMs + effectiveDuration;
  const barLeft = logPercent(step.offsetMs, runTotalMs);
  const barRight = logPercent(endMs, runTotalMs);
  const barWidth = Math.max(barRight - barLeft, 0.6);

  const isParallelParent = step.isParallelGroup && step.children.length > 0;
  const wallClock = isParallelParent ? parallelWallClockMs(step.children) : null;
  const sumChildren = isParallelParent ? sumChildDurationsMs(step.children) : 0;
  const savedMs = isParallelParent && wallClock !== null && sumChildren > wallClock ? sumChildren - wallClock : 0;

  const speedMark =
    isChild && step.stageKey === fastestSiblingKey
      ? { label: "最快", cls: "gantt-mark--fast" }
      : isChild && step.stageKey === slowestSiblingKey
        ? { label: "最慢", cls: "gantt-mark--slow" }
        : null;

  return (
    <div className={`gantt-row gantt-row--${step.status}${isChild ? " gantt-row--child" : " gantt-row--parent"}${isParallelParent ? " gantt-row--group" : ""}`}>
      <div className="gantt-row__head" onClick={onToggle}>
        <div className="gantt-row__label-block">
          <span className={`gantt-row__caret${expanded ? " gantt-row__caret--open" : ""}`}>▸</span>
          <span className="gantt-row__label">{step.label}</span>
          <span className={`gantt-row__status gantt-row__status--${step.status}`}>
            {step.status === "running"
              ? "进行中"
              : step.status === "completed"
                ? "完成"
                : step.status === "warning"
                  ? "降级"
                  : step.status === "skipped"
                    ? "跳过"
                    : "出错"}
          </span>
          {speedMark && <span className={`gantt-mark ${speedMark.cls}`}>{speedMark.label}</span>}
        </div>
        <div className="gantt-row__track" title={`开始 +${formatDuration(step.offsetMs)} · 耗时 ${durationLabel}`}>
          <div
            className={`gantt-bar gantt-bar--${step.status}${step.status === "running" && runIsInProgress ? " gantt-bar--live" : ""}`}
            style={{ left: `${barLeft}%`, width: `${barWidth}%` }}
          />
        </div>
        <div className="gantt-row__timing">
          <span className="gantt-row__duration">{durationLabel}</span>
          <span className="gantt-row__offset">起 +{formatDuration(step.offsetMs)}</span>
        </div>
      </div>

      {expanded && (
        <div className="gantt-row__body">
          {isParallelParent && wallClock !== null && (
            <div className="gantt-row__parallel-hint">
              并行 {step.children.length} 路 · 合计 {formatDuration(sumChildren)} · 实际 {formatDuration(wallClock)}
              {savedMs > 0 && <span className="gantt-row__saved"> · 并行节省 {formatDuration(savedMs)}</span>}
            </div>
          )}
          {step.did && <div className="exec-step__did">{step.did}</div>}
          {step.inputs.length > 0 && (
            <div className="exec-step__kvs">
              {step.inputs.map((kv) => (
                <div key={`in-${kv.key}`} className="exec-kv exec-kv--in">
                  <span className="exec-kv__label">{kv.label}</span>
                  <span className="exec-kv__value">{kv.value}</span>
                </div>
              ))}
            </div>
          )}
          {step.outputs.length > 0 && (
            <div className="exec-step__kvs">
              {step.outputs.map((kv) => (
                <div key={`out-${kv.key}`} className="exec-kv exec-kv--out">
                  <span className="exec-kv__label">{kv.label}</span>
                  <span className="exec-kv__value">{kv.value}</span>
                </div>
              ))}
            </div>
          )}
          {step.note && <div className="exec-step__note">{step.note}</div>}
          {step.llmCalls.length > 0 && (
            <div className="exec-step__llm">
              {step.llmCalls.map((call, k) => {
                const parsedClaims = tryParseClaims(call.response);
                return (
                  <div key={`llm-${k}`} className="exec-llm">
                    <LlmCallMeta title={call.title} status={call.status} response={call.response} />
                    {call.system && <LlmTextBlock stageKey={step.stageKey} role="system" text={call.system} />}
                    {call.prompt && <LlmTextBlock stageKey={step.stageKey} role="prompt" text={call.prompt} />}
                    {call.response && <LlmTextBlock stageKey={step.stageKey} role="response" text={call.response} />}
                    {parsedClaims && parsedClaims.length > 0 && <LlmClaimsSummary claims={parsedClaims} />}
                  </div>
                );
              })}
            </div>
          )}
          {step.subEvents.length > 0 && (
            <div className="exec-step__subs">
              {step.subEvents.map((sub, j) => (
                <div key={`sub-${j}`} className={`exec-sub exec-sub--${sub.level ?? sub.status}`}>
                  <span className="exec-sub__title">{sub.title}</span>
                  {sub.summary && <span className="exec-sub__summary">{sub.summary}</span>}
                  {sub.details && sub.details.length > 0 && (
                    <div className="exec-sub__details">
                      {sub.details.map((d, di) => (
                        <span key={di} className="exec-sub__detail">{d}</span>
                      ))}
                    </div>
                  )}
                  {sub.results && sub.results.length > 0 && (
                    <div className="exec-hits">
                      {sub.results.map((hit, h) => (
                        <div key={`hit-${h}`} className="exec-hit">
                          <div className="exec-hit__meta">
                            <span className={`exec-hit__tier exec-hit__tier--${hit.source_tier}`}>{hit.source_tier}</span>
                            <span className="exec-hit__source">{hit.source_name}</span>
                            {hit.published_at && <span className="exec-hit__date">{hit.published_at.slice(0, 10)}</span>}
                          </div>
                          <div className="exec-hit__title">
                            {hit.url ? <a href={hit.url} target="_blank" rel="noreferrer">{hit.title}</a> : hit.title}
                          </div>
                          {hit.snippet && <div className="exec-hit__snippet">{hit.snippet}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export interface TraceTimelineProps {
  traceSteps: TraceStep[];
  isStreaming: boolean;
  traceOpen: boolean;
  onToggleTrace: () => void;
}

export function TraceTimeline({ traceSteps, isStreaming, traceOpen, onToggleTrace }: TraceTimelineProps) {
  // Live tick: while any step is running, refresh nowMs every 250ms so bars
  // and duration labels grow in real time.
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  useEffect(() => {
    if (!isStreaming) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [isStreaming]);

  // Per-row expand state, keyed by stageKey. Parents default expanded, leaves
  // default collapsed (so the timeline reads as an overview at a glance).
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const isRowExpanded = (step: TraceStep): boolean => {
    if (step.stageKey in expanded) return expanded[step.stageKey];
    return step.children.length > 0 || step.status === "error" || step.status === "warning";
  };
  const toggleRow = (stageKey: string) => {
    setExpanded((prev) => ({ ...prev, [stageKey]: !(stageKey in prev ? prev[stageKey] : true) }));
  };

  if (traceSteps.length === 0) return null;

  const { totalMs } = computeTotals(traceSteps);
  // While the run is in flight, use "now - min start" as the denominator so bars
  // grow smoothly instead of jumping when a step finishes.
  let effectiveTotal = totalMs;
  if (effectiveTotal === null) {
    const earliestStart = Math.min(
      ...traceSteps.map((s) => new Date(s.startedAt).getTime()).filter(Number.isFinite),
    );
    if (Number.isFinite(earliestStart)) {
      effectiveTotal = Math.max(1, nowMs - earliestStart);
    } else {
      effectiveTotal = 1;
    }
  }
  const runTotalDenom = Math.max(effectiveTotal, 1);

  // Count leaves for the header badge.
  const leafCount = traceSteps.reduce((n, s) => n + (s.children.length > 0 ? s.children.length : 1), 0);

  return (
    <div className="trace-section">
      <button className="trace-toggle" onClick={onToggleTrace}>
        <span>{traceOpen ? "▼" : "▶"}</span>
        <span>
          执行过程 ({leafCount} 步{isStreaming ? " · 进行中" : ""} · 总耗时 {formatDuration(effectiveTotal)})
        </span>
      </button>
      {traceOpen && (
        <div className="gantt-timeline">
          <div className="gantt-hint">位置 = 阶段开始时间 · 宽度 = 阶段耗时 · 对数刻度（毫秒到分钟同屏可见）</div>
          <TimelineRuler totalMs={runTotalDenom} />
          {traceSteps.map((step, i) => {
            // For parallel groups, pre-compute fastest/slowest child by duration
            // (skip in-progress children so an unfinished branch isn't ranked).
            let fastKey: string | undefined;
            let slowKey: string | undefined;
            if (step.isParallelGroup && step.children.length > 1) {
              const withDur = step.children.filter((c) => c.durationMs !== null);
              if (withDur.length > 1) {
                const sorted = [...withDur].sort((a, b) => (a.durationMs! - b.durationMs!));
                fastKey = sorted[0].stageKey;
                slowKey = sorted[sorted.length - 1].stageKey;
              }
            }
            const parentExpanded = isRowExpanded(step);
            return (
              <div key={`${step.stageKey}-${i}`} className="gantt-group">
                <GanttRow
                  step={step}
                  runTotalMs={runTotalDenom}
                  runIsInProgress={isStreaming}
                  isChild={false}
                  nowMs={nowMs}
                  expanded={parentExpanded}
                  onToggle={() => toggleRow(step.stageKey)}
                />
                {parentExpanded && step.children.length > 0 && (
                  <div className="gantt-children">
                    {step.children.map((child, j) => (
                      <GanttRow
                        key={`${child.stageKey}-${j}`}
                        step={child}
                        runTotalMs={runTotalDenom}
                        runIsInProgress={isStreaming}
                        isChild
                        fastestSiblingKey={fastKey}
                        slowestSiblingKey={slowKey}
                        nowMs={nowMs}
                        expanded={isRowExpanded(child)}
                        onToggle={() => toggleRow(child.stageKey)}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
