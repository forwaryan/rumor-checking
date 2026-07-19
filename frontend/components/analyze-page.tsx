"use client";

import { useEffect, useMemo, useState } from "react";
import { AgentRunPanel } from "@/components/agent-run-panel";
import { AnalysisLivePanel } from "@/components/analysis-live-panel";
import { ClaimTable } from "@/components/claim-table";
import { ContentCheckPanel } from "@/components/content-check-panel";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { ReportOverviewPanel } from "@/components/report-overview-panel";
import { RiskPanel } from "@/components/risk-panel";
import { StatusBanner } from "@/components/status-banner";
import { TimelinePanel } from "@/components/timeline-panel";
import { analyzeReportStream, getHealth } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import { getStatusFromMode, validateInput } from "@/lib/report-utils";
import type {
  AnalysisLiveEvent,
  AnalysisStatus,
  AnalyzeRequest,
  DemoCaseSummary,
  InputType,
  Report,
  ReportProvenanceState,
} from "@/types/report";

type BackendState = "checking" | "online" | "offline" | "degraded";

interface LastRequest {
  request: AnalyzeRequest;
}

function buildReportProvenance(report: Report): ReportProvenanceState {
  return report.provenance
    ? {
        sourceKind: report.provenance.source_type,
        reportProvenance: report.provenance,
      }
    : {
        sourceKind: "unknown",
        fallbackReason: "missing_provenance",
      };
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
  const [isStreaming, setIsStreaming] = useState(false);
  const [analysisStartedAt, setAnalysisStartedAt] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<AnalysisLiveEvent[]>([]);

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
    if (isStreaming) {
      return;
    }

    setInputValue("");
    setInputType("auto");
    setSelectedDemoId(null);
    setErrorMessage(null);
    setLiveEvents([]);
    setAnalysisStartedAt(null);
    setStatus(report ? getStatusFromMode(report.mode) : "idle");
  }

  function selectDemo(demoCase: DemoCaseSummary) {
    setSelectedDemoId(demoCase.id);
    setInputType(demoCase.input_type);
    setInputValue(demoCase.sample_input);
    setErrorMessage(null);
  }

  function handleStreamEvent(event: AnalysisLiveEvent) {
    setLiveEvents((current) => [...current, event]);
    if (event.type === "report") {
      setReport(event.report);
      setReportProvenance(buildReportProvenance(event.report));
    }
  }

  async function executeSubmission(target: LastRequest) {
    setIsStreaming(true);
    setStatus("submitting");
    setErrorMessage(null);
    setReport(null);
    setReportProvenance(null);
    setLiveEvents([]);
    setAnalysisStartedAt(new Date().toISOString());

    try {
      const nextReport = await analyzeReportStream(target.request, handleStreamEvent);
      setReport(nextReport);
      setReportProvenance(buildReportProvenance(nextReport));
      setStatus(getStatusFromMode(nextReport.mode));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "请求失败，前端没有拿到可展示的分析结果。";
      setReport(null);
      setReportProvenance(null);
      setStatus("error");
      setErrorMessage(message);
    } finally {
      setIsStreaming(false);
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
    if (!lastRequest || isStreaming) {
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
            <p>输入一句话、新闻正文或 URL，输出可信度、传播链、内容核查结论和风险边界。</p>
          </div>
          <div className="masthead__summary">
            <p className="eyebrow">Input / Output</p>
            <strong>先回答更像真、假，还是真假混杂，再拆开看内容核查与传播链两条主流程。</strong>
            <p>现在点下“开始分析”后，页面会实时显示后端每个阶段在做什么、调了哪些 API、拿到了哪些结果。</p>
          </div>
        </div>

        <div className="masthead__workflow">
          <article className="workflow-stage-card workflow-stage-card--done">
            <span className="workflow-stage-card__step">01 输入</span>
            <strong>收集线索</strong>
            <p>支持问题、正文和 URL，先把人、事、时间与原帖线索收进来。</p>
          </article>
          <article className="workflow-stage-card workflow-stage-card--active">
            <span className="workflow-stage-card__step">02 检索</span>
            <strong>拉取公开信息</strong>
            <p>实时展示 query plan、外部 API 调用和命中的网页结果。</p>
          </article>
          <article className="workflow-stage-card workflow-stage-card--active">
            <span className="workflow-stage-card__step">03 判断</span>
            <strong>Agent 与规则链</strong>
            <p>展示消歧、claim 拆解、verdict 生成与时间线构建的执行过程。</p>
          </article>
          <article className="workflow-stage-card">
            <span className="workflow-stage-card__step">04 输出</span>
            <strong>返回报告</strong>
            <p>最后输出总体可信度、风险边界与可追溯的执行记录。</p>
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
              <p className="studio-section__copy">支持一句话、新闻正文和 URL，提交后会实时展示后端执行轨迹。</p>
            </div>
            <InputPanel
              value={inputValue}
              inputType={inputType}
              selectedDemoId={selectedDemoId}
              demoCases={demoCases}
              backendState={backendState}
              isSubmitting={isStreaming}
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
            <AnalysisLivePanel status={status} isStreaming={isStreaming} startedAt={analysisStartedAt} events={liveEvents} />
            <AgentRunPanel events={liveEvents} />
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
              <p className="studio-section__copy">这里展示最终模式、可信度、关键风险和来源说明。</p>
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
              <p className="studio-section__copy">把事实、观点、争议点和待补证项拆开展示，避免一刀切。</p>
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
              <p className="studio-section__copy">时间线解释它如何传播，claim 与证据列表解释为什么这么判断。</p>
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
