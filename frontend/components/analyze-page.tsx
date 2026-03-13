"use client";

import { useEffect, useMemo, useState } from "react";
import { ClaimTable } from "@/components/claim-table";
import { EvidenceList } from "@/components/evidence-list";
import { EventCard } from "@/components/event-card";
import { InputPanel } from "@/components/input-panel";
import { RiskPanel } from "@/components/risk-panel";
import { StatusBanner } from "@/components/status-banner";
import { TimelinePanel } from "@/components/timeline-panel";
import { analyzeReport, getHealth } from "@/lib/api-client";
import { getLocalDemoCaseSummaries, getLocalDemoReport } from "@/lib/demo-cases";
import { buildFallbackReport, getStatusFromMode, validateInput } from "@/lib/report-utils";
import type { AnalyzeRequest, AnalysisStatus, DemoCaseSummary, InputType, Report } from "@/types/report";

type BackendState = "checking" | "online" | "offline" | "degraded";

interface LastRequest {
  demoId: string | null;
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

    if (target.demoId && backendState === "offline") {
      const localReport = getLocalDemoReport(target.demoId);
      if (localReport) {
        setReport(localReport);
        setStatus(getStatusFromMode(localReport.mode));
        setFallbackMessage("后端当前离线，页面已直接回退到本地 demo payload。需要真实联调时请先恢复后端服务。");
        return;
      }
    }

    try {
      const nextReport = await analyzeReport(target.request);
      setReport(nextReport);
      setStatus(getStatusFromMode(nextReport.mode));
    } catch {
      if (target.demoId) {
        const localReport = getLocalDemoReport(target.demoId);
        if (localReport) {
          setReport(localReport);
          setStatus(getStatusFromMode(localReport.mode));
          setFallbackMessage(
            "真实 analyze 请求失败，页面已回退到同主题本地 demo payload，方便继续演示页面结构和三档模式。",
          );
          return;
        }
      }

      const fallbackReport = buildFallbackReport(target.request.raw_input, target.request.input_type);
      setReport(fallbackReport);
      setStatus("safe_mode");
      setFallbackMessage(
        "真实接口当前不可用，页面已自动切换到安全模式回退结果，方便继续演示边界和空态。",
      );
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

  return (
    <main className="page-shell">
      <header className="hero">
        <div className="hero__copy">
          <p className="eyebrow">Cluster-E / Experience Shell</p>
          <h1>单页 rumor-checking 工作台</h1>
          <p>
            当前示例输入已对齐后端真实 scenario。页面会优先走真实 <code>analyze</code> 链路，只有在后端离线或请求失败时，
            才回退到同主题本地 payload。
          </p>
        </div>
        <div className="hero__card">
          <span>三档模式</span>
          <strong>complete / partial / safe</strong>
          <p>在线时看真实 Report，离线时仍能稳定演示同主题页面，不再依赖缺失的 replay 接口。</p>
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
        onRetry={lastRequest ? () => void retryLastRequest() : null}
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