"use client";

import { useEffect, useMemo, useState } from "react";
import { ClaimTable } from "@/components/claim-table";
import { ContentCheckPanel } from "@/components/content-check-panel";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { ReportOverviewPanel } from "@/components/report-overview-panel";
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
        <div className="masthead__top">
          <div className="masthead__intro">
            <p className="eyebrow">Rumor Checking Desk</p>
            <h1>较真工作台</h1>
            <p>输入一句话、新闻正文或 URL，输出整体可信度、传播链还原、内容核查结论和风险边界。</p>
          </div>
          <div className="masthead__summary">
            <p className="eyebrow">Input / Output</p>
            <strong>先回答“更像真、假，还是真假混杂”，再拆开看内容核查和传播链两条主流程。</strong>
            <p>结果页只讲已经冻结的字段，不伪装 live 能力，不把局部结果包装成完整复盘。</p>
          </div>
        </div>

        <div className="masthead__workflow">
          <article className="workflow-stage-card workflow-stage-card--done">
            <span className="workflow-stage-card__step">01 输入</span>
            <strong>输入线索</strong>
            <p>支持问题、正文和 URL，先把人、事、时间线索收进来。</p>
          </article>
          <article className="workflow-stage-card workflow-stage-card--active">
            <span className="workflow-stage-card__step">02 核查</span>
            <strong>拆 claim 做内容核查</strong>
            <p>把事实、观点、可能有误分开看，避免整条新闻一刀切。</p>
          </article>
          <article className="workflow-stage-card workflow-stage-card--active">
            <span className="workflow-stage-card__step">03 传播</span>
            <strong>还原传播链</strong>
            <p>解释它是怎么传开的，哪些节点值得被选进时间线。</p>
          </article>
          <article className="workflow-stage-card">
            <span className="workflow-stage-card__step">04 输出</span>
            <strong>合并结果与边界</strong>
            <p>最后只输出整体可信度、风险提示和当前局限，不做额外承诺。</p>
          </article>
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
              <p className="studio-section__copy">支持一句话、新闻正文和 URL，提交后会输出整体可信度、双主流程结果和风险边界。</p>
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
              <p className="studio-section__copy">先看一句话结论、整体可信度、双主流程完成度和风险边界。</p>
            </div>
            <StatusBanner
              status={status}
              report={report}
              provenance={reportProvenance}
              errorMessage={errorMessage}
              onRetry={lastRequest ? () => void retryLastRequest() : null}
            />
            <div className="result-hero-grid">
              <ReportOverviewPanel report={report} provenance={reportProvenance} />
              <div className="result-side-stack">
                <EventCard report={report} />
                <RiskPanel report={report} provenance={reportProvenance} />
              </div>
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
              <p className="studio-section__copy">把事实、观点、可能有误和待补证项分开展示，避免把整条新闻混成一句话。</p>
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
              <p className="studio-section__copy">传播链解释“它如何传开”，claim 和来源解释“为什么这么判断”。</p>
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
