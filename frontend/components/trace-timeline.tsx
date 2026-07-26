"use client";

import { useState } from "react";
import type { TraceStep } from "@/types/report";
import { formatLlmText, humanizeLlmText } from "@/lib/trace-steps";
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
  // The system prompt is a fixed instruction block (not JSON), long and identical
  // across calls — render it raw and collapsed by default so it doesn't bury the
  // per-call 提问/回答. prompt/response keep the 人类可读 / 原始 JSON toggle.
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

export interface TraceTimelineProps {
  traceSteps: TraceStep[];
  isStreaming: boolean;
  traceOpen: boolean;
  onToggleTrace: () => void;
}

export function TraceTimeline({ traceSteps, isStreaming, traceOpen, onToggleTrace }: TraceTimelineProps) {
  if (traceSteps.length === 0) return null;

  return (
    <div className="trace-section">
      <button className="trace-toggle" onClick={onToggleTrace}>
        <span>{traceOpen ? "▼" : "▶"}</span>
        <span>执行过程 ({traceSteps.length} 步{isStreaming ? " · 进行中" : ""})</span>
      </button>
      {traceOpen && (
        <ol className="exec-timeline">
          {traceSteps.map((step, i) => (
            <li key={`${step.stageKey}-${i}`} className={`exec-step exec-step--${step.status}`}>
              <div className="exec-step__marker">
                <span className="exec-step__dot" />
                <span className="exec-step__index">{i + 1}</span>
              </div>
              <div className="exec-step__body">
                <div className="exec-step__head">
                  <span className="exec-step__label">{step.label}</span>
                  <span className={`exec-step__status exec-step__status--${step.status}`}>
                    {step.status === "running" ? "进行中"
                      : step.status === "completed" ? "完成"
                      : step.status === "warning" ? "降级"
                      : step.status === "skipped" ? "跳过"
                      : "出错"}
                  </span>
                </div>
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
                          {call.system && (
                            <LlmTextBlock stageKey={step.stageKey} role="system" text={call.system} />
                          )}
                          {call.prompt && (
                            <LlmTextBlock stageKey={step.stageKey} role="prompt" text={call.prompt} />
                          )}
                          {call.response && (
                            <LlmTextBlock stageKey={step.stageKey} role="response" text={call.response} />
                          )}
                          {parsedClaims && parsedClaims.length > 0 && (
                            <LlmClaimsSummary claims={parsedClaims} />
                          )}
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
                                  {hit.url ? (
                                    <a href={hit.url} target="_blank" rel="noreferrer">{hit.title}</a>
                                  ) : (
                                    hit.title
                                  )}
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
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
