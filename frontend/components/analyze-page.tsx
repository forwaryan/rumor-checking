"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getHealth, getModels, getSearchSources } from "@/lib/api-client";
import type { SearchSource } from "@/lib/api-client";
import { buildAnalysisRequest, createRunSession, runLocation, selectRunTarget } from "@/lib/run-session";
import type { RunSession } from "@/lib/run-session";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput, collectEvidence } from "@/lib/report-utils";
import { deriveTraceSteps, applyBackendTiming } from "@/lib/trace-steps";
import type { AnalysisLiveEvent, AnalysisRun, AnalysisStatus, Report, ReportProvenanceState } from "@/types/report";
import { SearchInput } from "@/components/search-input";
import { VerdictCard } from "@/components/verdict-card";
import { CredibilityHeader } from "@/components/credibility-header";
import { ClaimList } from "@/components/claim-list";
import { EvidenceList, RetrievalHitsList } from "@/components/evidence-list";
import { PossibleAnswers, PossibilitiesDistribution } from "@/components/possibilities-section";
import { TimelineSection } from "@/components/timeline-section";
import { TraceTimeline } from "@/components/trace-timeline";
import { RunMetricsPanel } from "@/components/run-metrics-panel";
import { AgentSpanTree } from "@/components/agent-span-tree";

type BackendState = "checking" | "online" | "offline" | "degraded";

function buildReportProvenance(report: Report): ReportProvenanceState {
  return report.provenance ? { sourceKind: report.provenance.source_type, reportProvenance: report.provenance } : { sourceKind: "unknown", fallbackReason: "missing_provenance" };
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
  // The server's own default model. We surface it in the picker for display, but
  // must NOT send it as an explicit request_context.model: the backend reads any
  // explicit model as "user pinned this — never fail over", which disables the
  // health-aware failover and lets one flaky model collapse a run into safe_mode.
  // Only a model the user actively chose (≠ this default) is sent.
  const [serverDefaultModel, setServerDefaultModel] = useState<string>("");
  const [searchSources, setSearchSources] = useState<SearchSource[]>([]);
  const [activeSources, setActiveSources] = useState<string[]>([]);
  const [claimsOpen, setClaimsOpen] = useState(true);
  const [answersOpen, setAnswersOpen] = useState(true);
  const [possibilitiesOpen, setPossibilitiesOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [retrievalHitsOpen, setRetrievalHitsOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [metricsOpen, setMetricsOpen] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [runState, setRunState] = useState<AnalysisRun | null>(null);
  const sessionRef = useRef<RunSession | null>(null);
  const subscriptionRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const [agentSpanTreeOpen, setAgentSpanTreeOpen] = useState(false);

  useEffect(() => {
    let active = true;
    void getHealth().catch(() => ({ status: "error" as const })).then((r) => {
      if (!active) return;
      setBackendState(r.status === "ok" ? "online" : r.status === "degraded" ? "degraded" : "offline");
    });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    void getModels().then((res) => {
      if (!active) return;
      setModels(res.models);
      setServerDefaultModel(res.default || res.models[0] || "");
      setSelectedModel((cur) => cur || res.default || res.models[0] || "");
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    void getSearchSources().then((res) => {
      if (!active) return;
      setSearchSources(res.sources);
      setActiveSources((cur) => cur.length > 0 ? cur : res.sources.filter((s) => s.enabled && s.default_on).map((s) => s.id));
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const cleanup = () => { subscriptionRef.current?.abort(); busyRef.current = false; };
    const target = selectRunTarget(window.location.search);
    if (target) {
      if ("runId" in target) setRunId(target.runId);
      if ("request" in target) {
        const validation = validateInput(target.request.raw_input, "auto");
        if (validation) { setStatus("error"); setErrorMessage(validation); return cleanup; }
        setInputValue(target.request.raw_input);
        setLastQuery(target.request.raw_input);
        setActiveMode(target.request.request_context?.mode === "deep" ? "deep" : "fast");
      }
      sessionRef.current ??= createRunSession(target);
      void watchRun(sessionRef.current);
    }
    return cleanup;
  }, []);

  function handleStreamEvent(event: AnalysisLiveEvent) {
    setLiveEvents((current) => [...current, event]);
    if (event.type === "report") { setReport(event.report); setReportProvenance(buildReportProvenance(event.report)); }
  }

  async function watchRun(session: RunSession, resume = false) {
    subscriptionRef.current?.abort();
    const controller = new AbortController();
    subscriptionRef.current = controller;
    busyRef.current = true;
    setIsStreaming(true); setStatus("submitting"); setErrorMessage(null);
    const isCurrent = () => !controller.signal.aborted && subscriptionRef.current === controller;
    try {
      const nextRun = await session.watch({
        onRun: (run) => {
          if (!isCurrent()) return;
          setRunId(run.run_id); setRunState(run); setActiveMode(run.mode);
          setInputValue(run.raw_input); setLastQuery(run.raw_input);
          window.history.replaceState(null, "", runLocation(window.location.pathname, run.run_id));
        },
        onEvent: (event) => { if (isCurrent()) handleStreamEvent(event); },
      }, controller.signal, resume);
      if (!isCurrent()) return;
      if (nextRun.status === "completed" && nextRun.report) {
        setReport(nextRun.report); setReportProvenance(buildReportProvenance(nextRun.report));
        setStatus(getStatusFromMode(nextRun.report.mode));
      } else {
        setReport(null); setReportProvenance(null); setStatus("error");
        setErrorMessage(nextRun.status === "interrupted"
          ? "核查已中断。继续时将从可用检查点恢复；没有检查点时重新执行。"
          : "此次核查未能完成，请开始新查询。");
      }
    } catch (error) {
      if (!isCurrent()) return;
      setStatus("error");
      setErrorMessage(error instanceof Error && error.name === "ApiClientError" ? error.message : "暂时无法连接核查服务，请稍后重新连接。");
    } finally {
      if (isCurrent()) { busyRef.current = false; setIsStreaming(false); }
    }
  }

  async function handleSubmit(mode: "fast" | "deep" = "fast", queryOverride?: string, modelOverride?: string) {
    if (busyRef.current) return;
    const trimmed = (queryOverride ?? (inputValue.trim() || lastQuery.trim())).trim();
    if (!trimmed) return;
    const validation = validateInput(trimmed, "auto");
    if (validation) { setStatus("error"); setErrorMessage(validation); return; }
    const model = modelOverride ?? selectedModel;
    // Only treat it as an explicit pick when it differs from the server default —
    // otherwise omit it so the backend keeps failover enabled (see serverDefaultModel).
    const explicitModel = model && model !== serverDefaultModel ? model : "";
    window.history.replaceState(null, "", runLocation(window.location.pathname));
    setLastQuery(trimmed); setActiveMode(mode); setIsStreaming(true);
    setStatus("submitting"); setErrorMessage(null); setReport(null);
    setReportProvenance(null); setLiveEvents([]); setClaimsOpen(true);
    setEvidenceOpen(false); setTimelineOpen(false); setTraceOpen(mode === "deep");
    setRunId(null); setRunState(null); setAgentSpanTreeOpen(false);
    const request = buildAnalysisRequest(trimmed, mode, { model: explicitModel, searchSources: activeSources });
    sessionRef.current = createRunSession({ request });
    await watchRun(sessionRef.current);
  }

  function handleReset() {
    subscriptionRef.current?.abort(); subscriptionRef.current = null;
    sessionRef.current = null; busyRef.current = false;
    setIsStreaming(false); setRunId(null); setRunState(null);
    setInputValue(""); setStatus("idle"); setReport(null); setReportProvenance(null);
    setErrorMessage(null); setLiveEvents([]); setLastQuery("");
    if (typeof window !== "undefined") window.history.replaceState(null, "", window.location.pathname);
  }

  function handleToggleSource(sourceId: string) {
    setActiveSources((cur) => {
      if (cur.includes(sourceId)) {
        // Keep at least one source selected. An empty list would omit
        // search_sources from the request, which the backend reads as "run all"
        // — the opposite of what unchecking everything implies. Block the last
        // uncheck so the checkboxes always mean exactly what they show.
        if (cur.length <= 1) return cur;
        return cur.filter((id) => id !== sourceId);
      }
      return [...cur, sourceId];
    });
  }

  // Hooks must run every render regardless of the showResult branch below —
  // do NOT move this below the early return, or React will crash with
  // "Rendered more hooks than during the previous render" on the transition
  // from the idle SearchInput view to the result view.
  const runMetrics = useMemo(() => {
    for (let i = liveEvents.length - 1; i >= 0; i--) {
      const e = liveEvents[i];
      if (e.type === "metrics") return e.metrics;
    }
    return null;
  }, [liveEvents]);

  const showResult = report !== null || status === "submitting" || status === "error";

  if (!showResult) {
    return (
      <SearchInput inputValue={inputValue} onInputChange={setInputValue}
        onSubmit={() => void handleSubmit("fast")} isStreaming={isStreaming}
        demoCases={idleDemoCases} onSelectExample={(d) => setInputValue(d.sample_input)}
        backendState={backendState}
        searchSources={searchSources} activeSources={activeSources} onToggleSource={handleToggleSource} />
    );
  }

  const evidence = report ? collectEvidence(report) : [];
  const citedUrls = new Set(evidence.map((item) => item.url));
  const retrievalOnlyHits = (report?.retrieval_hits ?? []).filter((item) => !citedUrls.has(item.url));
  const lastLiveEvent = liveEvents[liveEvents.length - 1];
  // Live-derived timing is fine while the stream is in flight; once the
  // report arrives the backend's authoritative timing (started_at/duration_ms/
  // offset_ms baked into pipeline_trace steps) overwrites it so bar positions
  // match server-side reality instead of stream deltas.
  const traceSteps = applyBackendTiming(deriveTraceSteps(liveEvents), report?.pipeline_trace);

  return (
    <main className="app app--result">
      <div className="result-page">
        <header className="result-header">
          <button className="result-header__back" onClick={handleReset} aria-label="返回并开始新查询">
            <span aria-hidden="true">←</span> 新查询
          </button>
          <div className="result-header__brand" aria-label="较真核查">
            <span className="result-header__brand-dot" aria-hidden="true" />
            较真核查
          </div>
          <span className="result-header__query" title={lastQuery || runState?.input_preview}>{lastQuery || runState?.input_preview}</span>
        </header>

        {status === "submitting" && !report && (
          <div className="loading-card">
            <div className="loading-card__spinner" />
            <div className="loading-card__text">{activeMode === "deep" ? "AI 深度核查中，可能需要几分钟..." : "正在联网核查..."}</div>
            {lastLiveEvent && (
              <div className="loading-card__step">
                {lastLiveEvent.type === "api_call" ? lastLiveEvent.title : lastLiveEvent.type === "stage" ? lastLiveEvent.title : lastLiveEvent.type === "retrieval" ? `检索: ${lastLiveEvent.query}` : "处理中"}
              </div>
            )}
          </div>
        )}

        {status === "error" && (
          <div className="error-card">
            <div className="error-card__title">{runState?.status === "interrupted" ? "核查已中断" : runState?.status === "failed" ? "核查失败" : runId ? "连接暂时中断" : "无法开始核查"}</div>
            <div className="error-card__message">{errorMessage || "请稍后重试"}</div>
            {runState?.status === "interrupted" && runState.resumable && (
              <button className="error-card__retry" onClick={() => { if (!busyRef.current && sessionRef.current) void watchRun(sessionRef.current, true); }}>继续核查</button>
            )}
            {runState?.status !== "failed" && runState?.status !== "interrupted" && runId && (
              <button className="error-card__retry" onClick={() => { if (!busyRef.current && sessionRef.current) void watchRun(sessionRef.current); }}>重新连接</button>
            )}
            <button className="error-card__retry" onClick={handleReset}>新查询</button>
          </div>
        )}

        {report && <VerdictCard report={report} reportProvenance={reportProvenance} />}
        {report && <CredibilityHeader report={report} reportProvenance={reportProvenance} />}
        {report && lastQuery && activeMode === "fast" && !isStreaming && status !== "error" && (
          <div className="deep-cta">
            <div className="deep-cta__text">还不确定？可以深入核查：多轮检索、逐条判定、交叉比对来源。</div>
            <div className="deep-cta__actions">
              {models.length > 1 && (
                <select className="deep-cta__model" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} aria-label="选择分析模型">
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              )}
              <button className="deep-cta__button" onClick={() => void handleSubmit("deep")}>深度核查（较慢）</button>
            </div>
          </div>
        )}

        {report?.content_check && <PossibleAnswers answers={report.content_check.possible_answers} isOpen={answersOpen} onToggle={() => setAnswersOpen(!answersOpen)} />}
        {report?.investigation && <PossibilitiesDistribution possibilities={report.investigation.possibilities} isOpen={possibilitiesOpen} onToggle={() => setPossibilitiesOpen(!possibilitiesOpen)} />}
        {report && <ClaimList claims={report.claim_results} isOpen={claimsOpen} onToggle={() => setClaimsOpen(!claimsOpen)} />}
        {report && <EvidenceList evidence={evidence} isOpen={evidenceOpen} onToggle={() => setEvidenceOpen(!evidenceOpen)} report={report} />}
        {report && <RetrievalHitsList hits={retrievalOnlyHits} isOpen={retrievalHitsOpen} onToggle={() => setRetrievalHitsOpen(!retrievalHitsOpen)} />}
        {report && <TimelineSection timeline={report.timeline} isOpen={timelineOpen} onToggle={() => setTimelineOpen(!timelineOpen)} />}
        {runMetrics && <RunMetricsPanel metrics={runMetrics} isOpen={metricsOpen} onToggle={() => setMetricsOpen(!metricsOpen)} />}
        {runId && report && <AgentSpanTree runId={runId} isOpen={agentSpanTreeOpen} onToggle={() => setAgentSpanTreeOpen(!agentSpanTreeOpen)} />}
        <TraceTimeline traceSteps={traceSteps} isStreaming={isStreaming} traceOpen={traceOpen} onToggleTrace={() => setTraceOpen(!traceOpen)} />
      </div>
    </main>
  );
}
