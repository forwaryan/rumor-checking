"use client";

import { useEffect, useMemo, useState } from "react";
import { ClaimTable } from "@/components/claim-table";
import { ContentCheckPanel } from "@/components/content-check-panel";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { RiskPanel } from "@/components/risk-panel";
import { StatusBanner } from "@/components/status-banner";
import { TimelinePanel } from "@/components/timeline-panel";
import { analyzeReport, getHealth } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput } from "@/lib/report-utils";
import type {
  AnalyzeRequest,
  AnalysisStatus,
  DemoCaseSummary,
  InputType,
  Report,
  ReportProvenanceState,
} from "@/types/report";

type BackendState = "checking" | "online" | "offline" | "degraded";

interface LastRequest {
  request: AnalyzeRequest;
}

export function AnalyzePage() {
  const idleDemoCases = useMemo(() => getLocalDemoCaseSummaries(), []);
  const [demoCases, setDemoCases] = useState<DemoCaseSummary[]>(idleDemoCases);
  const [inputValue, setInputValue] = useState("");
  const [inputType, setInputType] = useState<InputType>("auto");
  const [selectedDemoId, setSelectedDemoId] = useState<string | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [reportProvenance, setReportProvenance] = useState<ReportProvenanceState | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [lastRequest, setLastRequest] = useState<LastRequest | null>(null);

  useEffect(() => {
    let active = true;

    async function hydrate() {
      const healthResult = await getHealth().catch(() => ({ status: "error" as const }));

      if (!active) {
        return;
      }

      setBackendState(
        healthResult.status === "ok"
          ? "online"
          : healthResult.status === "degraded"
            ? "degraded"
            : "offline",
      );
      setDemoCases(idleDemoCases);
    }

    void hydrate();

    return () => {
      active = false;
    };
  }, [idleDemoCases]);

  function resetDraft() {
    setInputValue("");
    setInputType("auto");
    setSelectedDemoId(null);
    setErrorMessage(null);
    setStatus(report ? getStatusFromMode(report.mode) : "idle");
  }

  function selectDemo(demoCase: DemoCaseSummary) {
    setSelectedDemoId(demoCase.id);
    setInputType(demoCase.input_type);
    setInputValue(demoCase.sample_input);
    setErrorMessage(null);
  }

  async function executeSubmission(target: LastRequest) {
    setStatus("submitting");
    setErrorMessage(null);
    setReportProvenance(null);

    try {
      const nextReport = await analyzeReport(target.request);
      setReport(nextReport);
      setReportProvenance(
        nextReport.provenance
          ? {
              sourceKind: nextReport.provenance.source_type,
              reportProvenance: nextReport.provenance,
            }
          : {
              sourceKind: "unknown",
              fallbackReason: "missing_provenance",
            },
      );
      setStatus(getStatusFromMode(nextReport.mode));
    } catch (error) {
      const message = error instanceof Error ? error.message : "请求失败，且页面不会再回退到本地假结果。";
      setReport(null);
      setStatus("error");
      setErrorMessage(message);
    }
  }

  async function handleSubmit() {
    const validation = validateInput(inputValue, inputType);
    if (validation) {
      setStatus("error");
      setErrorMessage(validation);
      return;
    }

    const nextRequest: LastRequest = {
      request: {
        raw_input: inputValue.trim(),
        input_type: inputType,
      },
    };

    setLastRequest(nextRequest);
    await executeSubmission(nextRequest);
  }

  async function retryLastRequest() {
    if (!lastRequest) {
      return;
    }

    await executeSubmission(lastRequest);
  }

  return (
    <main className="page-shell">
      <header className="masthead">
        <div className="masthead__intro">
          <p className="eyebrow">Rumor Checking Desk</p>
          <h1>较真工作台</h1>
          <p>页面只保留输入、结论、内容核查、时间线和证据五块核心信息，不再展示解释型流程卡片。</p>
        </div>
      </header>

      <div className="studio-main">
        <section className="studio-section">
          <div className="studio-section__marker">
            <span>01</span>
            <small>输入</small>
          </div>
          <div className="studio-section__body">
            <div className="studio-section__header">
              <p className="studio-section__eyebrow">Input</p>
              <h2>输入待核查内容</h2>
              <p className="studio-section__copy">支持一句话、新闻正文和 URL。</p>
            </div>
            <InputPanel
              value={inputValue}
              inputType={inputType}
              selectedDemoId={selectedDemoId}
              demoCases={demoCases}
              backendState={backendState}
              isSubmitting={status === "submitting"}
              onValueChange={(value) => {
                setInputValue(value);
                setSelectedDemoId(null);
              }}
              onInputTypeChange={(value) => {
                setInputType(value);
                setSelectedDemoId(null);
              }}
              onSelectDemo={selectDemo}
              onSubmit={() => {
                void handleSubmit();
              }}
              onReset={resetDraft}
            />
          </div>
        </section>

        <section className="studio-section">
          <div className="studio-section__marker">
            <span>02</span>
            <small>结论</small>
          </div>
          <div className="studio-section__body">
            <div className="studio-section__header">
              <p className="studio-section__eyebrow">Summary</p>
              <h2>先看结论和边界</h2>
              <p className="studio-section__copy">先回答，再看事件概览和风险。</p>
            </div>
            <StatusBanner
              status={status}
              report={report}
              provenance={reportProvenance}
              errorMessage={errorMessage}
              onRetry={lastRequest ? () => void retryLastRequest() : null}
            />
            <div className="result-hero-grid">
              <EventCard report={report} />
              <RiskPanel report={report} provenance={reportProvenance} />
            </div>
          </div>
        </section>

        <section className="studio-section">
          <div className="studio-section__marker">
            <span>03</span>
            <small>核查</small>
          </div>
          <div className="studio-section__body">
            <div className="studio-section__header">
              <p className="studio-section__eyebrow">Content</p>
              <h2>看句子里哪些部分站得住</h2>
              <p className="studio-section__copy">只保留内容核查本身，不再展示额外的解释卡片。</p>
            </div>
            <ContentCheckPanel report={report} />
          </div>
        </section>

        <section className="studio-section">
          <div className="studio-section__marker">
            <span>04</span>
            <small>证据</small>
          </div>
          <div className="studio-section__body">
            <div className="studio-section__header">
              <p className="studio-section__eyebrow">Evidence</p>
              <h2>最后看传播过程和证据</h2>
              <p className="studio-section__copy">时间线解释传播，claim 和来源解释判定依据。</p>
            </div>
            <TimelinePanel report={report} />
            <div className="evidence-stage-grid">
              <ClaimTable report={report} />
              <EvidenceList report={report} />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
