"use client";

import { useEffect, useMemo, useState } from "react";
import { analyzeReportStream, getHealth, getModels, getSearchSources } from "@/lib/api-client";
import type { SearchSource } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput, collectEvidence } from "@/lib/report-utils";
import { deriveTraceSteps } from "@/lib/trace-steps";
import type { AnalysisLiveEvent, AnalysisStatus, AnalyzeRequest, Report, ReportProvenanceState } from "@/types/report";
import { SearchInput } from "@/components/search-input";
import { VerdictCard } from "@/components/verdict-card";
import { CredibilityHeader } from "@/components/credibility-header";
import { ClaimList } from "@/components/claim-list";
import { EvidenceList, RetrievalHitsList } from "@/components/evidence-list";
import { PossibleAnswers, PossibilitiesDistribution } from "@/components/possibilities-section";
import { TimelineSection } from "@/components/timeline-section";
import { TraceTimeline } from "@/components/trace-timeline";
import { RunMetricsPanel } from "@/components/run-metrics-panel";

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
    if (event.type === "report") { setReport(event.report); setReportProvenance(buildReportProvenance(event.report)); }
  }

  async function handleSubmit(mode: "fast" | "deep" = "fast", queryOverride?: string, modelOverride?: string) {
    const trimmed = (queryOverride ?? (inputValue.trim() || lastQuery.trim())).trim();
    if (!trimmed) return;
    const validation = validateInput(trimmed, "auto");
    if (validation) { setStatus("error"); setErrorMessage(validation); return; }
    const model = modelOverride ?? selectedModel;
    if (typeof window !== "undefined") {
      const params = new URLSearchParams();
      params.set("q", trimmed);
      if (mode === "deep") params.set("mode", "deep");
      if (mode === "deep" && model) params.set("model", model);
      window.history.replaceState(null, "", `?${params.toString()}`);
    }
    setLastQuery(trimmed); setActiveMode(mode); setIsStreaming(true);
    setStatus("submitting"); setErrorMessage(null); setReport(null);
    setReportProvenance(null); setLiveEvents([]); setClaimsOpen(true);
    setEvidenceOpen(false); setTimelineOpen(false); setTraceOpen(mode === "deep");
    try {
      const request: AnalyzeRequest = { raw_input: trimmed, input_type: "auto", request_context: { mode, ...(mode === "deep" && model ? { model } : {}), ...(activeSources.length > 0 ? { search_sources: activeSources } : {}) } };
      const nextReport = await analyzeReportStream(request, handleStreamEvent);
      setReport(nextReport); setReportProvenance(buildReportProvenance(nextReport));
      setStatus(getStatusFromMode(nextReport.mode));
    } catch (error) {
      setReport(null); setReportProvenance(null); setStatus("error");
      setErrorMessage(error instanceof Error ? error.message : "请求失败");
    } finally { setIsStreaming(false); }
  }

  function handleReset() {
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
  const traceSteps = deriveTraceSteps(liveEvents);

  return (
    <main className="app app--result">
      <div className="result-page">
        <header className="result-header">
          <button className="result-header__back" onClick={handleReset}>&larr; 新查询</button>
          <span className="result-header__query">{lastQuery}</span>
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
            <div className="error-card__title">核查失败</div>
            <div className="error-card__message">{errorMessage || "请稍后重试"}</div>
            <button className="error-card__retry" onClick={() => void handleSubmit(activeMode)}>重试</button>
          </div>
        )}

        {report && <VerdictCard report={report} reportProvenance={reportProvenance} />}
        {report && <CredibilityHeader report={report} reportProvenance={reportProvenance} />}
        {report && activeMode === "fast" && !isStreaming && (
          <div className="deep-cta">
            <div className="deep-cta__text">还不确定？让 AI 深入分析证据、逐条判定。</div>
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
        <TraceTimeline traceSteps={traceSteps} isStreaming={isStreaming} traceOpen={traceOpen} onToggleTrace={() => setTraceOpen(!traceOpen)} />
      </div>
    </main>
  );
}
