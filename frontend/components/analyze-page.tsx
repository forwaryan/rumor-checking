"use client";

import { useEffect, useMemo, useState } from "react";
import { analyzeReportStream, getHealth, getModels } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput, getVerdictLabel, formatConfidence, collectEvidence } from "@/lib/report-utils";
import { getOverallCredibilityMeta } from "@/lib/report-high-score";
import { deriveTraceSteps, formatLlmText, humanizeLlmText } from "@/lib/trace-steps";
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

function formatProbability(value?: number | null): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return `${Math.round(value)}%`;
}

function getBasisLabel(basis?: string | null): string | null {
  if (basis === "evidence") return "有证据";
  if (basis === "prior") return "凭常识";
  return null;
}

function getLikelihoodLabel(likelihood: string): string {
  switch (likelihood) {
    case "high": return "可能性高";
    case "medium": return "可能性中";
    default: return "可能性低";
  }
}

// One prompt-or-response block with 人类可读 / 原始 JSON tabs.
function LlmTextBlock({ stageKey, role, text }: { stageKey: string; role: "prompt" | "response"; text: string }) {
  const [view, setView] = useState<"human" | "json">("human");
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
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");

  // Collapsible sections
  const [claimsOpen, setClaimsOpen] = useState(true);
  const [answersOpen, setAnswersOpen] = useState(true);
  const [possibilitiesOpen, setPossibilitiesOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [retrievalHitsOpen, setRetrievalHitsOpen] = useState(false);
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

  // Load the selectable model whitelist for the deep-mode picker.
  useEffect(() => {
    let active = true;
    void getModels()
      .then((res) => {
        if (!active) return;
        setModels(res.models);
        setSelectedModel((cur) => cur || res.default || res.models[0] || "");
      })
      .catch(() => {});
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
    const urlModel = params.get("model") ?? undefined;
    if (urlModel) setSelectedModel(urlModel);
    setInputValue(q);
    void handleSubmit(mode, q, urlModel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleStreamEvent(event: AnalysisLiveEvent) {
    setLiveEvents((current) => [...current, event]);
    if (event.type === "report") {
      setReport(event.report);
      setReportProvenance(buildReportProvenance(event.report));
    }
  }

  async function handleSubmit(mode: "fast" | "deep" = "fast", queryOverride?: string, modelOverride?: string) {
    const trimmed = (queryOverride ?? (inputValue.trim() || lastQuery.trim())).trim();
    if (!trimmed) return;
    const validation = validateInput(trimmed, "auto");
    if (validation) {
      setStatus("error");
      setErrorMessage(validation);
      return;
    }

    const model = modelOverride ?? selectedModel;

    // Reflect the query in the URL so a refresh/share re-runs the same check.
    // We store the query + mode, not the result — deep re-runs take minutes.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams();
      params.set("q", trimmed);
      if (mode === "deep") params.set("mode", "deep");
      if (mode === "deep" && model) params.set("model", model);
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
        request_context: {
          mode,
          ...(mode === "deep" && model ? { model } : {}),
        },
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
  // Retrieved results the verdict did NOT cite. They stay visible as "检索命中"
  // (search hits) rather than inflating the cited-evidence count / card.
  const citedUrls = new Set(evidence.map((item) => item.url));
  const retrievalOnlyHits = (report?.retrieval_hits ?? []).filter((item) => !citedUrls.has(item.url));
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
            <div className="deep-cta__actions">
              {models.length > 1 && (
                <select
                  className="deep-cta__model"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  aria-label="选择分析模型"
                >
                  {models.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              )}
              <button className="deep-cta__button" onClick={() => void handleSubmit("deep")}>
                深度核查（较慢）
              </button>
            </div>
          </div>
        )}

        {/* Possible answers: evidence-grounded corrective takes, so a half-true
            rumor shows "what's more likely true" instead of only 证据不足. */}
        {report && report.content_check && report.content_check.possible_answers.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setAnswersOpen(!answersOpen)}>
              <span className="section-card__title">
                更可能的答案
                <span className="section-card__badge">{report.content_check.possible_answers.length}</span>
              </span>
              <span className={`section-card__arrow${answersOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {answersOpen && (
              <div className="section-card__body">
                <div className="section-card__hint">基于当前证据给出的更可能正确的说法，用来纠正被夸大或失真的部分。</div>
                <div className="answer-list">
                  {report.content_check.possible_answers.map((item, i) => (
                    <div key={`${item.angle}-${i}`} className="answer-item">
                      <span className="answer-item__angle">{item.angle}</span>
                      <span className="answer-item__text">{item.answer}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Possibilities distribution */}
        {report && report.investigation && report.investigation.possibilities.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setPossibilitiesOpen(!possibilitiesOpen)}>
              <span className="section-card__title">
                可能性分布
                <span className="section-card__badge">{report.investigation.possibilities.length}</span>
              </span>
              <span className={`section-card__arrow${possibilitiesOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {possibilitiesOpen && (
              <div className="section-card__body">
                <div className="possibility-list">
                  {report.investigation.possibilities.map((item, i) => {
                    const prob = formatProbability(item.probability);
                    const basisLabel = getBasisLabel(item.basis);
                    const width = typeof item.probability === "number" ? Math.max(0, Math.min(100, item.probability)) : null;
                    return (
                      <div key={`${item.scenario}-${i}`} className="possibility-item">
                        <div className="possibility-item__head">
                          <span className="possibility-item__scenario">{item.scenario}</span>
                          <span className={`possibility-item__prob possibility-item__prob--${item.likelihood}`}>
                            {prob ?? getLikelihoodLabel(item.likelihood)}
                            {basisLabel ? ` · ${basisLabel}` : ""}
                          </span>
                        </div>
                        {width !== null && (
                          <div className="possibility-item__bar">
                            <div className={`possibility-item__bar-fill possibility-item__bar-fill--${item.likelihood}`} style={{ width: `${width}%` }} />
                          </div>
                        )}
                        {item.summary && <div className="possibility-item__summary">{item.summary}</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
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
                  {report.claim_results.map((claim, i) => {
                    const prob = formatProbability(claim.truth_probability);
                    const basisLabel = getBasisLabel(claim.probability_basis);
                    return (
                    <div key={`${claim.claim}-${i}`} className={`claim-item claim-item--${claim.verdict}`}>
                      <div className="claim-item__text">{claim.claim}</div>
                      <div className="claim-item__tags">
                        <span className={`claim-item__verdict claim-item__verdict--${claim.verdict}`}>
                          {getVerdictLabel(claim.verdict)} · {formatConfidence(claim.confidence)}
                        </span>
                        {prob && (
                          <span className="claim-item__prob" title={claim.probability_basis === "prior" ? "无检索证据，基于常识的先验估计" : "基于检索证据的估计"}>
                            为真 {prob}{basisLabel ? ` · ${basisLabel}` : ""}
                          </span>
                        )}
                      </div>
                      {claim.notes && <div className="claim-item__notes">{claim.notes}</div>}
                    </div>
                    );
                  })}
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

        {/* Retrieval hits: results we fetched but no claim cited as evidence.
            Kept separate so they don't inflate the cited-evidence count. */}
        {report && retrievalOnlyHits.length > 0 && (
          <div className="section-card">
            <div className="section-card__header" onClick={() => setRetrievalHitsOpen(!retrievalHitsOpen)}>
              <span className="section-card__title">
                检索命中（未被采信）
                <span className="section-card__badge">{retrievalOnlyHits.length}</span>
              </span>
              <span className={`section-card__arrow${retrievalHitsOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
            </div>
            {retrievalHitsOpen && (
              <div className="section-card__body">
                <div className="section-card__hint">这些是检索到、但没有被任何核查点当作判定证据的结果，仅供参考。</div>
                {retrievalOnlyHits.map((item, i) => (
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
                                <LlmTextBlock stageKey={step.stageKey} role="prompt" text={call.prompt} />
                              )}
                              {call.response && (
                                <LlmTextBlock stageKey={step.stageKey} role="response" text={call.response} />
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
