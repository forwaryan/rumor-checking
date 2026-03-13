"use client";

import { useEffect, useMemo, useState } from "react";
import { ClaimTable } from "@/components/claim-table";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { RiskPanel } from "@/components/risk-panel";
import { StatusBanner } from "@/components/status-banner";
import { TimelinePanel } from "@/components/timeline-panel";
import { analyzeReport, getDemoCases, getHealth, replayDemoCase } from "@/lib/api-client";
import { buildFallbackReport, getIdleDemoHints, getStatusFromMode, validateInput } from "@/lib/report-utils";
import type { AnalyzeRequest, AnalysisStatus, DemoCaseSummary, InputType, Report } from "@/types/report";

type BackendState = "checking" | "online" | "offline" | "degraded";

type LastRequest =
  | {
      kind: "demo";
      demoId: string;
    }
  | {
      kind: "analyze";
      request: AnalyzeRequest;
    };

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function AnalyzePage() {
  const idleDemoCases = useMemo(() => getIdleDemoHints(), []);
  const [demoCases, setDemoCases] = useState<DemoCaseSummary[]>(idleDemoCases);
  const [inputValue, setInputValue] = useState("");
  const [inputType, setInputType] = useState<InputType>("auto");
  const [selectedDemoId, setSelectedDemoId] = useState<string | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fallbackMessage, setFallbackMessage] = useState<string | null>(null);
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [lastRequest, setLastRequest] = useState<LastRequest | null>(null);

  useEffect(() => {
    let active = true;

    async function hydrate() {
      try {
        const [healthResult, demoResult] = await Promise.all([
          getHealth().catch(() => ({ status: "error" as const })),
          getDemoCases(),
        ]);

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
        setDemoCases(demoResult.length ? demoResult : idleDemoCases);
      } catch {
        if (!active) {
          return;
        }

        setBackendState("offline");
        setDemoCases(idleDemoCases);
      }
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

    try {
      if (target.kind === "demo") {
        await wait(650);
        const nextReport = await replayDemoCase(target.demoId);
        setReport(nextReport);
        setStatus(getStatusFromMode(nextReport.mode));
        return;
      }

      const nextReport = await analyzeReport(target.request);
      setReport(nextReport);
      setStatus(getStatusFromMode(nextReport.mode));
    } catch {
      if (target.kind === "analyze") {
        const fallbackReport = buildFallbackReport(target.request.input, target.request.input_type);
        setReport(fallbackReport);
        setStatus("safe_mode");
        setFallbackMessage(
          "真实接口当前不可用，页面已自动切换到安全模式回退结果，方便继续演示边界和空态。",
        );
        return;
      }

      setStatus("error");
      setErrorMessage("demo 回放失败，请稍后再试或换一个示例。");
    }
  }

  async function handleSubmit() {
    const validation = validateInput(inputValue, inputType);
    if (validation) {
      setStatus("error");
      setErrorMessage(validation);
      return;
    }

    const nextRequest: LastRequest = selectedDemoId
      ? { kind: "demo", demoId: selectedDemoId }
      : {
          kind: "analyze",
          request: {
            input: inputValue.trim(),
            input_type: inputType,
            use_demo_case: false,
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

  const retryHandler = lastRequest ? retryLastRequest : null;

  return (
    <main className="page-shell">
      <header className="hero">
        <div className="hero__copy">
          <p className="eyebrow">Cluster-E / Experience Shell</p>
          <h1>单页 rumor-checking 工作台</h1>
          <p>
            这个前端壳按“先看结论，再看传播链，再看 claim，再看证据”的顺序组织页面，专门为
            V1 演示稳定性设计。
          </p>
        </div>
        <div className="hero__card">
          <span>三档模式</span>
          <strong>complete / partial / safe</strong>
          <p>本地 demo 可独立回放，后端接通后自动复用相同 Report 结构。</p>
        </div>
      </header>

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

      <StatusBanner
        status={status}
        report={report}
        errorMessage={errorMessage}
        fallbackMessage={fallbackMessage}
        onRetry={retryHandler ? () => void retryHandler() : null}
      />

      <section className="dashboard-grid">
        <EventCard report={report} />
        <RiskPanel report={report} />
        <TimelinePanel report={report} />
        <ClaimTable report={report} />
        <EvidenceList report={report} />
      </section>
    </main>
  );
}
