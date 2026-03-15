"use client";

import { useEffect, useMemo, useState } from "react";
import { ClaimTable } from "@/components/claim-table";
import { ContentCheckPanel } from "@/components/content-check-panel";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { InvestigationPanel } from "@/components/investigation-panel";
import { ProcessTracePanel } from "@/components/process-trace-panel";
import { RiskPanel } from "@/components/risk-panel";
import { StatusBanner } from "@/components/status-banner";
import { TimelinePanel } from "@/components/timeline-panel";
import { analyzeReport, getHealth } from "@/lib/api-client";
import { getLocalDemoCaseSummaries } from "@/lib/demo-cases";
import {
  collectEvidence,
  getStatusFromMode,
  getVerificationScoreMeta,
  validateInput,
} from "@/lib/report-utils";
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
  demoId: string | null;
  request: AnalyzeRequest;
}

type WorkflowStageState = "idle" | "active" | "done";

function getInputTypeLabel(inputType: InputType) {
  switch (inputType) {
    case "text":
      return "正文";
    case "url":
      return "URL";
    case "question":
      return "问题";
    default:
      return "自动判断";
  }
}

function truncateText(value: string, limit: number) {
  const trimmed = value.trim();
  if (trimmed.length <= limit) {
    return trimmed;
  }

  return `${trimmed.slice(0, limit - 1)}…`;
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
  const [fallbackMessage, setFallbackMessage] = useState<string | null>(null);
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
    setFallbackMessage(null);
    setStatus(report ? getStatusFromMode(report.mode) : "idle");
  }

  function selectDemo(demoCase: DemoCaseSummary) {
    setSelectedDemoId(demoCase.id);
    setInputType(demoCase.input_type);
    setInputValue(demoCase.sample_input);
    setErrorMessage(null);
    setFallbackMessage(null);
  }

  async function executeSubmission(target: LastRequest) {
    setStatus("submitting");
    setErrorMessage(null);
    setFallbackMessage(null);
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
      demoId: selectedDemoId,
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

  const evidenceCount = report ? collectEvidence(report).length : 0;
  const scoreMeta = report ? getVerificationScoreMeta(report, reportProvenance) : null;
  const workflowStages: Array<{
    step: string;
    title: string;
    description: string;
    state: WorkflowStageState;
  }> = [
    {
      step: "01",
      title: "接收输入",
      description: lastRequest
        ? `${getInputTypeLabel(lastRequest.request.input_type)}输入已提交`
        : "先输入一句话、正文或 URL",
      state: lastRequest ? "done" : "idle",
    },
    {
      step: "02",
      title: "一句话结论",
      description: report
        ? truncateText(report.final_summary, 58)
        : status === "submitting"
          ? "正在生成结论和边界"
          : "先给用户一个明确结论",
      state: report ? "done" : status === "submitting" ? "active" : "idle",
    },
    {
      step: "03",
      title: "内容拆解",
      description: report
        ? `核查点 ${report.claim_results.length} 条，可能情况 ${report.investigation?.possibilities?.length ?? 0} 条`
        : "把问题拆成可核查片段",
      state: report ? "done" : status === "submitting" ? "active" : "idle",
    },
    {
      step: "04",
      title: "传播与证据",
      description: report
        ? `时间线 ${report.timeline.length} 节点，证据 ${evidenceCount} 条`
        : "把传播过程和证据按顺序摆出来",
      state: report ? "done" : "idle",
    },
  ];

  const activeRequest = lastRequest?.request ?? null;
  const sessionSummary = report
    ? report.investigation?.reframed_question ?? report.event.title
    : activeRequest
      ? truncateText(activeRequest.raw_input, 72)
      : "还没有提交待核查内容";
  const sessionFacts = [
    {
      label: "输入类型",
      value: activeRequest ? getInputTypeLabel(activeRequest.input_type) : "未提交",
    },
    {
      label: "核查完成度",
      value: scoreMeta ? scoreMeta.label : status === "submitting" ? "计算中" : "未生成",
    },
    {
      label: "传播节点",
      value: report ? `${report.timeline.length} 个` : "0 个",
    },
    {
      label: "证据数量",
      value: report ? `${evidenceCount} 条` : "0 条",
    },
  ];

  return (
    <main className="page-shell">
      <header className="masthead">
        <div className="masthead__top">
          <div className="masthead__intro">
            <p className="eyebrow">Rumor Checking Desk</p>
            <h1>较真工作台</h1>
            <p>
              这一版页面把工作流按真实阅读顺序重排了：先接收问题，再给一句话结论，再拆内容、看传播、落证据。右侧单独保留处理链路，
              用来理解系统到底是怎么走到当前结果的。
            </p>
          </div>
          <div className="masthead__summary">
            <span className="stats-label">当前会话焦点</span>
            <strong>{sessionSummary}</strong>
            <p>
              目标不是把所有信息堆在一页，而是让用户能一眼看懂“现在结论是什么、为什么这么说、接下来证据和传播过程在哪里看”。
            </p>
          </div>
        </div>

        <div className="masthead__workflow" aria-label="页面工作流">
          {workflowStages.map((stage) => (
            <article key={stage.step} className={`workflow-stage-card workflow-stage-card--${stage.state}`}>
              <span className="workflow-stage-card__step">{stage.step}</span>
              <strong>{stage.title}</strong>
              <p>{stage.description}</p>
            </article>
          ))}
        </div>
      </header>

      <section className="studio-shell">
        <div className="studio-main">
          <section className="studio-section">
            <div className="studio-section__marker">
              <span>01</span>
              <small>输入</small>
            </div>
            <div className="studio-section__body">
              <div className="studio-section__header">
                <p className="studio-section__eyebrow">Start Here</p>
                <h2>先把待核查内容放进来</h2>
                <p className="studio-section__copy">支持一句话、新闻正文和 URL。先把问题说清楚，后面的结论和证据才会更稳。</p>
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
                <p className="studio-section__eyebrow">Answer First</p>
                <h2>先给用户一个明确、边界清楚的结论</h2>
                <p className="studio-section__copy">结论放在前面，边界和 provenance 紧跟其后，避免用户先被大段细节淹没。</p>
              </div>
              <StatusBanner
                status={status}
                report={report}
                provenance={reportProvenance}
                errorMessage={errorMessage}
                fallbackMessage={fallbackMessage}
                onRetry={lastRequest ? () => void retryLastRequest() : null}
              />
              <div className="result-hero-grid">
                <EventCard report={report} provenance={reportProvenance} />
                <RiskPanel report={report} provenance={reportProvenance} />
              </div>
            </div>
          </section>

          <section className="studio-section">
            <div className="studio-section__marker">
              <span>03</span>
              <small>拆解</small>
            </div>
            <div className="studio-section__body">
              <div className="studio-section__header">
                <p className="studio-section__eyebrow">Break It Down</p>
                <h2>把一句话拆成能逐项核对的内容</h2>
                <p className="studio-section__copy">这里先回答“哪些更像真的、哪些更像被加料了”，再展示系统收束问题时考虑过哪些可能情况。</p>
              </div>
              <div className="analysis-stage-grid">
                <ContentCheckPanel report={report} />
                <InvestigationPanel report={report} />
              </div>
            </div>
          </section>

          <section className="studio-section">
            <div className="studio-section__marker">
              <span>04</span>
              <small>传播</small>
            </div>
            <div className="studio-section__body">
              <div className="studio-section__header">
                <p className="studio-section__eyebrow">Story Over Time</p>
                <h2>按时间顺序查看传播过程</h2>
                <p className="studio-section__copy">先看事情如何发酵，再看转折和澄清，这样证据和结论才有时间背景。</p>
              </div>
              <TimelinePanel report={report} />
            </div>
          </section>

          <section className="studio-section">
            <div className="studio-section__marker">
              <span>05</span>
              <small>证据</small>
            </div>
            <div className="studio-section__body">
              <div className="studio-section__header">
                <p className="studio-section__eyebrow">Evidence Base</p>
                <h2>最后回到逐条核查点和证据原文</h2>
                <p className="studio-section__copy">claim 表告诉你系统判了什么，证据列表告诉你它是根据哪些公开来源这样判的。</p>
              </div>
              <div className="evidence-stage-grid">
                <ClaimTable report={report} />
                <EvidenceList report={report} />
              </div>
            </div>
          </section>
        </div>

        <aside className="studio-rail">
          <section className="panel workflow-inspector">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Session</p>
                <h2>当前会话</h2>
              </div>
            </div>
            <p className="workflow-inspector__summary">{sessionSummary}</p>
            <div className="workflow-inspector__stats">
              {sessionFacts.map((fact) => (
                <article key={fact.label} className="workflow-stat">
                  <span className="stats-label">{fact.label}</span>
                  <strong>{fact.value}</strong>
                </article>
              ))}
            </div>
            <p className="workflow-inspector__prompt">
              右侧只保留“会话摘要 + 真实处理链路”。调试问题时，不需要再在主结果区来回找步骤。
            </p>
          </section>

          <ProcessTracePanel report={report} provenance={reportProvenance} request={activeRequest} status={status} />
        </aside>
      </section>
    </main>
  );
}
