"use client";

import { useEffect, useMemo, useState } from "react";
import { analyzeReportStream, getHealth } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput, getVerdictLabel, formatConfidence, collectEvidence } from "@/lib/report-utils";
import { getOverallCredibilityMeta } from "@/lib/report-high-score";
import { deriveTraceSteps, formatLlmText } from "@/lib/trace-steps";
import type {
  AnalysisLiveEvent,
  AnalysisStatus,
  AnalyzeRequest,
  DemoCaseSummary,
  Report,
  ReportProvenanceState,
} from "@/types/report";

type BackendState = "checking" | "online" | "offline" | "degraded";

function buildReportProvenance(report: Report): ReportProvenanceState {
  return report.provenance
    ? { sourceKind: report.provenance.source_type, reportProvenance: report.provenance }
    : { sourceKind: "unknown", fallbackReason: "missing_provenance" };
}

function getOverallVerdict(report: Report): string {
  const supported = report.claim_results.filter(c => c.verdict === "supported").length;
  const refuted = report.claim_results.filter(c => c.verdict === "refuted").length;
  const insufficient = report.claim_results.filter(c => c.verdict === "insufficient").length;
  if (refuted > 0 && refuted >= supported) return "refuted";
  if (supported > 0 && supported > refuted) return "supported";
  if (insufficient > 0) return "insufficient";
  return "insufficient";
}

function getVerdictDisplayLabel(verdict: string): string {
  switch (verdict) {
    case "supported": return "基本属实";
    case "refuted": return "不实信息";
    case "insufficient": return "证据不足";
    case "conflicting": return "各方矛盾";
    default: return "待核查";
  }
}

function getVerdictIcon(verdict: string): string {
  switch (verdict) {
    case "supported": return "✓";
    case "refuted": return "✗";
    case "insufficient": return "?";
    case "conflicting": return "!";
    default: return "·";
  }
}

export function AnalyzePage() {
  const idleDemoCases = useMemo(() => getLocalDemoCaseSummaries(), []);
  const [inputValue, setInputValue] = useState("");
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [reportProvenance, setReportProvenance] = useState<ReportProvenanceState | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [isStreaming, setIsStreaming] = useState(false);
  const [liveEvents, setLiveEvents] = useState<AnalysisLiveEvent[]>([]);
  const [lastQuery, setLastQuery] = useState("");
  const [activeMode, setActiveMode] = useState<"fast" | "deep">("fast");

  // Collapsible sections
  const [claimsOpen, setClaimsOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);

  useEffect(() => {
    let active = true;
    async function checkHealth() {
      const result = await getHealth().catch(() => ({ status: "error" as const }));
      if (!active) return;
      setBackendState(
        result.status === "ok" ? "online" : result.status === "degraded" ? "degraded" : "offline",
      );
    }
    void checkHealth();
    return () => { active = false; };
  }, []);

  // Restore from a shared/refreshed URL: ?q=<query>&mode=<fast|deep> re-runs the
  // same check on load. Runs once on mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q")?.trim();
    if (!q) return;
    const mode = params.get("mode") === "deep" ? "deep" : "fast";
    setInputValue(q);
    void handleSubmit(mode, q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleStreamEvent(event: AnalysisLiveEvent) {
    setLiveEvents((current) => [...current, event]);
    if (event.type === "report") {
      setReport(event.report);
      setReportProvenance(buildReportProvenance(event.report));
    }
  }

  async function handleSubmit(mode: "fast" | "deep" = "fast", queryOverride?: string) {
    const trimmed = (queryOverride ?? (inputValue.trim() || lastQuery.trim())).trim();
    if (!trimmed) return;
    const validation = validateInput(trimmed, "auto");
    if (validation) {
      setStatus("error");
      setErrorMessage(validation);
      return;
    }

    // Reflect the query in the URL so a refresh/share re-runs the same check.
    // We store the query + mode, not the result — deep re-runs take minutes.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams();
      params.set("q", trimmed);
      if (mode === "deep") params.set("mode", "deep");
      window.history.replaceState(null, "", `?${params.toString()}`);
    }

    setLastQuery(trimmed);
    setActiveMode(mode);
    setIsStreaming(true);
    setStatus("submitting");
    setErrorMessage(null);
    setReport(null);
    setReportProvenance(null);
    setLiveEvents([]);
    setClaimsOpen(true);
    setEvidenceOpen(false);
    setTimelineOpen(false);
    setTraceOpen(mode === "deep");

    try {
      const request: AnalyzeRequest = {
        raw_input: trimmed,
        input_type: "auto",
        request_context: { mode },
      };
      const nextReport = await analyzeReportStream(request, handleStreamEvent);
      setReport(nextReport);
      setReportProvenance(buildReportProvenance(nextReport));
      setStatus(getStatusFromMode(nextReport.mode));
    } catch (error) {
      const message = error instanceof Error ? error.message : "请求失败";
      setReport(null);
      setReportProvenance(null);
      setStatus("error");
      setErrorMessage(message);
    } finally {
      setIsStreaming(false);
    }
  }

  function handleReset() {
    setInputValue("");
    setStatus("idle");
    setReport(null);
    setReportProvenance(null);
    setErrorMessage(null);
    setLiveEvents([]);
    setLastQuery("");
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }

  function selectExample(demo: DemoCaseSummary) {
    setInputValue(demo.sample_input);
  }

  const hasResult = report !== null;
  const showResult = hasResult || status === "submitting" || status === "error";

  // Idle: search page
  if (!showResult) {
    return (
      <main className="app app--idle">
        <div className="search-page">
          <div className="search-page__brand">
            <h1>较真核查</h1>
            <p>输入你看到的消息，帮你判断真假</p>
          </div>

          <div className="search-box">
            <textarea
              className="search-box__input"
              rows={1}
              placeholder="粘贴一条消息、新闻标题或链接..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSubmit("fast");
                }
              }}
            />
            <button
              className="search-box__submit"
              onClick={() => void handleSubmit("fast")}
              disabled={isStreaming || !inputValue.trim()}
            >
              核查
            </button>
          </div>

          <div className="examples">
            {idleDemoCases.slice(0, 4).map((demo) => (
              <button key={demo.id} className="examples__chip" onClick={() => selectExample(demo)}>
                {demo.title}
              </button>
            ))}
          </div>

          <div className="search-page__status">
            <span className={`status-dot status-dot--${backendState}`} />
            <span>{backendState === "online" ? "服务正常" : backendState === "offline" ? "服务离线" : backendState === "degraded" ? "服务降级" : "检测中..."}</span>
          </div>
        </div>
      </main>
    );
  }

  // Result page
  const verdict = report ? getOverallVerdict(report) : null;
  const overallMeta = report ? getOverallCredibilityMeta(report, reportProvenance) : null;
  const evidence = report ? collectEvidence(report) : [];
  const lastLiveEvent = liveEvents[liveEvents.length - 1];
  const traceSteps = deriveTraceSteps(liveEvents);

  return (
    <main className="app app--result">
      <div className="result-page">
        <header className="result-header">
          <button className="result-header__back" onClick={handleReset}>
            &larr; 新查询
          </button>
          <span className="result-header__query">{lastQuery}</span>
        </header>

        {/* Loading */}
        {status === "submitting" && !report && (
          <div className="loading-card">
            <div className="loading-card__spinner" />
            <div className="loading-card__text">
              {activeMode === "deep" ? "AI 深度核查中，可能需要几分钟..." : "正在联网核查..."}
            </div>
            {lastLiveEvent && (
              <div className="loading-card__step">
                {lastLiveEvent.type === "api_call" ? lastLiveEvent.title
                  : lastLiveEvent.type === "stage" ? lastLiveEvent.title
                  : lastLiveEvent.type === "retrieval" ? `检索: ${lastLiveEvent.query}`
                  : "处理中"}
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {status === "error" && (
          <div className="error-card">
            <div className="error-card__title">核查失败</div>
            <div className="error-card__message">{errorMessage || "请稍后重试"}</div>
            <button className="error-card__retry" onClick={() => void handleSubmit(activeMode)}>重试</button>
          </div>
        )}

        {/* Verdict */}
        {report && verdict && (
          <div className={`verdict-card verdict-card--${verdict}`}>
            <div className={`verdict-card__label verdict-card__label--${verdict}`}>
              <span>{getVerdictIcon(verdict)}</span>
              <span>{getVerdictDisplayLabel(verdict)}</span>
            </div>
            <div className="verdict-card__summary">{report.final_summary}</div>
            {overallMeta?.summary && (
              <div className="verdict-card__detail">{overallMeta.summary}</div>
            )}
            <div className="verdict-card__meta">
              <span className="meta-tag">证据 {evidence.length} 条</span>
              <span className="meta-tag">核查点 {report.claim_results.length} 个</span>
              {report.timeline.length > 0 && <span className="meta-tag">时间线 {report.timeline.length} 节点</span>}
              <span className="meta-tag">
                {report.provenance?.evidence_source === "retrieval_live" ? "实时检索" : "模拟数据"}
              </span>
            </div>
          </div>
        )}

        {/* Deep-mode upsell: only after a fast result, when not already streaming */}
        {report && activeMode === "fast" && !isStreaming && (
          <div className="deep-cta">
            <div className="deep-cta__text">还不确定？让 AI 深入分析证据、逐条判定。</div>
            <button className="deep-cta__button" onClick={() => void handleSubmit("deep")}>
              深度核查（较慢）
            </button>
          </div>
        )}

        {/* Claims */}
        {report && report.claim_results.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setClaimsOpen(!claimsOpen)}>
              <span className="section-card__title">
                逐条核查
                <span className="section-card__badge">{report.claim_results.length}</span>
              </span>
              <span className={`section-card__arrow${claimsOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {claimsOpen && (
              <div className="section-card__body">
                <div className="claim-list">
                  {report.claim_results.map((claim, i) => (
                    <div key={`${claim.claim}-${i}`} className={`claim-item claim-item--${claim.verdict}`}>
                      <div className="claim-item__text">{claim.claim}</div>
                      <span className={`claim-item__verdict claim-item__verdict--${claim.verdict}`}>
                        {getVerdictLabel(claim.verdict)} · {formatConfidence(claim.confidence)}
                      </span>
                      {claim.notes && <div className="claim-item__notes">{claim.notes}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Evidence */}
        {report && evidence.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setEvidenceOpen(!evidenceOpen)}>
              <span className="section-card__title">
                证据来源
                <span className="section-card__badge">{evidence.length}</span>
              </span>
              <span className={`section-card__arrow${evidenceOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {evidenceOpen && (
              <div className="section-card__body">
                {evidence.map((item, i) => (
                  <div key={`${item.url}-${i}`} className="evidence-item">
                    <div className="evidence-item__source">{item.source_name} · {item.source_tier}</div>
                    <div className="evidence-item__title">
                      <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
                    </div>
                    <div className="evidence-item__snippet">{item.snippet}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Timeline */}
        {report && report.timeline.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setTimelineOpen(!timelineOpen)}>
              <span className="section-card__title">
                传播时间线
                <span className="section-card__badge">{report.timeline.length}</span>
              </span>
              <span className={`section-card__arrow${timelineOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {timelineOpen && (
              <div className="section-card__body">
                <div className="timeline">
                  {report.timeline.map((node, i) => (
                    <div key={`${node.url}-${i}`} className={`timeline__node timeline__node--${node.node_type}`}>
                      <div className="timeline__node-title">{node.title}</div>
                      <div className="timeline__node-meta">{node.source_name} · {node.published_at || "时间未知"}</div>
                      <div className="timeline__node-summary">{node.summary}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Execution trace — observable step timeline */}
        {traceSteps.length > 0 && (
          <div className="trace-section">
            <button className="trace-toggle" onClick={() => setTraceOpen(!traceOpen)}>
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
                          {step.llmCalls.map((call, k) => (
                            <div key={`llm-${k}`} className="exec-llm">
                              {call.prompt && (
                                <details className="exec-llm__block">
                                  <summary className="exec-llm__summary exec-llm__summary--q">
                                    提问模型 · 展开查看
                                  </summary>
                                  <pre className="exec-llm__text">{formatLlmText(call.prompt)}</pre>
                                </details>
                              )}
                              {call.response && (
                                <details className="exec-llm__block" open>
                                  <summary className="exec-llm__summary exec-llm__summary--a">
                                    模型回答
                                  </summary>
                                  <pre className="exec-llm__text">{formatLlmText(call.response)}</pre>
                                </details>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {step.subEvents.length > 0 && (
                        <div className="exec-step__subs">
                          {step.subEvents.map((sub, j) => (
                            <div key={`sub-${j}`} className={`exec-sub exec-sub--${sub.level ?? sub.status}`}>
                              <span className="exec-sub__title">{sub.title}</span>
                              {sub.summary && <span className="exec-sub__summary">{sub.summary}</span>}
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
        )}
      </div>
    </main>
  );
}
