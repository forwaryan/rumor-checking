"use client";

import { useEffect, useMemo, useState } from "react";
import { getVerificationScoreMeta } from "@/lib/report-utils";
import type {
  AnalyzeRequest,
  AnalysisStatus,
  PipelineTrace,
  PipelineTraceStep,
  Report,
  ReportProvenanceState,
} from "@/types/report";

interface ProcessTracePanelProps {
  report: Report | null;
  provenance: ReportProvenanceState | null;
  request: AnalyzeRequest | null;
  status: AnalysisStatus;
}

const settledStatusLabel: Record<PipelineTraceStep["status"], string> = {
  completed: "已完成",
  warning: "需关注",
  skipped: "未触发",
  error: "异常",
};

function formatElapsed(ms: number) {
  if (ms < 1000) {
    return `${Math.max(0, ms)}ms`;
  }

  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}

function getSettledCurrentIndex(trace: PipelineTrace) {
  const firstAttention = trace.steps.findIndex((step) => step.status === "warning" || step.status === "error");
  if (firstAttention >= 0) {
    return firstAttention;
  }

  return Math.max(0, trace.steps.length - 1);
}

function getStatusLabel(step: PipelineTraceStep) {
  return settledStatusLabel[step.status];
}

const modeLinePattern = /^(最终模式|当前模式|mode)\s*[：:]/i;

function sanitizeTraceCopy(text: string, scoreLabel: string) {
  const trimmed = text.trim();
  if (modeLinePattern.test(trimmed)) {
    return `核查完成度：${scoreLabel}`;
  }

  return trimmed
    .replaceAll("安全模式回退结果", "回退结果")
    .replaceAll("完整模式", "高完成度结果")
    .replaceAll("部分模式", "中完成度结果")
    .replaceAll("安全模式", "低完成度结果")
    .replaceAll("complete_mode", "高完成度结果")
    .replaceAll("partial_mode", "中完成度结果")
    .replaceAll("safe_mode", "低完成度结果")
    .replaceAll("safe mode", "低完成度结果");
}

export function ProcessTracePanel({ report, provenance, request, status }: ProcessTracePanelProps) {
  const requestSignature = request ? `${request.input_type}:${request.raw_input}` : null;
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [frozenElapsedMs, setFrozenElapsedMs] = useState<number | null>(null);

  useEffect(() => {
    if (status !== "submitting" || !requestSignature) {
      return undefined;
    }

    const start = Date.now();
    setStartedAt(start);
    setElapsedMs(0);
    setFrozenElapsedMs(null);

    const timer = window.setInterval(() => {
      setElapsedMs(Date.now() - start);
    }, 250);

    return () => {
      window.clearInterval(timer);
    };
  }, [requestSignature, status]);

  useEffect(() => {
    if (status === "submitting" || startedAt === null) {
      return;
    }

    setFrozenElapsedMs((current) => current ?? Math.max(elapsedMs, Date.now() - startedAt));
    setStartedAt(null);
  }, [elapsedMs, startedAt, status]);

  const trace = useMemo(() => {
    if (status === "submitting") {
      return null;
    }

    return report?.pipeline_trace?.steps.length ? report.pipeline_trace : null;
  }, [report, status]);

  const displayElapsedMs = status === "submitting" ? elapsedMs : frozenElapsedMs;
  const scoreLabel = report ? getVerificationScoreMeta(report, provenance).label : "0/10";

  if (status === "submitting") {
    return (
      <section className="panel panel--trace">
        <div className="trace-runbar">
          <div>
            <p className="eyebrow">Process Trace</p>
            <h2>处理链路</h2>
          </div>
          <div className="trace-meta">
            <span className="trace-live-pill trace-live-pill--pending">等待真实链路</span>
            {displayElapsedMs !== null ? <span className="trace-live-pill">耗时 {formatElapsed(displayElapsedMs)}</span> : null}
          </div>
        </div>

        <div className="trace-overview">
          <span className="stats-label">当前阶段</span>
          <strong>等待后端返回真实链路</strong>
          <p>当前 `analyze` 接口只会在任务结束后返回 `pipeline_trace`。页面不会按猜测补一套“看起来像过程”的步骤。</p>
        </div>
      </section>
    );
  }

  if (!trace) {
    return (
      <section className="panel panel--trace">
        <div className="trace-runbar">
          <div>
            <p className="eyebrow">Process Trace</p>
            <h2>处理链路</h2>
          </div>
        </div>
        <p className="empty-state">这里只展示后端真实返回的 `pipeline_trace`。当前结果没有链路数据，所以页面不会补写一套假的过程。</p>
      </section>
    );
  }

  const currentIndex = getSettledCurrentIndex(trace);
  const currentStep = trace.steps[currentIndex] ?? trace.steps[trace.steps.length - 1];

  return (
    <section className="panel panel--trace">
      <div className="trace-runbar">
        <div>
          <p className="eyebrow">Process Trace</p>
          <h2>处理链路</h2>
        </div>
        <div className="trace-meta">
          <span className="trace-live-pill trace-live-pill--report">真实链路</span>
          {displayElapsedMs !== null ? <span className="trace-live-pill">耗时 {formatElapsed(displayElapsedMs)}</span> : null}
          <span className="trace-live-pill">{`阶段 ${currentIndex + 1}/${trace.steps.length}`}</span>
        </div>
      </div>

      <div className="trace-overview">
        <span className="stats-label">当前阶段</span>
        <strong>{currentStep?.title ?? "等待开始"}</strong>
        <p>这里按真实执行顺序展示后端最终落盘的步骤，可直接对应主结果区里的结论、分析、时间线和证据。</p>
      </div>

      <div className="trace-list trace-list--open">
        {trace.steps.map((step, index) => {
          const isCurrent = index === currentIndex;
          const statusLabel = getStatusLabel(step);

          return (
            <article
              key={`${step.stage_key}-${index}`}
              className={`trace-step${isCurrent ? " trace-step--current" : ""}`}
            >
              <div className={`trace-step__index trace-step__index--${step.status}${isCurrent ? " is-current" : ""}`}>
                {index + 1}
              </div>

              <div className="trace-step__body">
                <div className="trace-step__header">
                  <div>
                    <span className="stats-label">Step {index + 1}</span>
                    <h3>{step.title}</h3>
                    <p className="trace-step__stage">{step.stage_key}</p>
                  </div>
                  <span className={`trace-pill trace-pill--${step.status}`}>{statusLabel}</span>
                </div>

                <p className="trace-step__summary">{sanitizeTraceCopy(step.summary, scoreLabel)}</p>
                {step.details.length > 0 ? (
                  <ul className="trace-step__details">
                    {step.details.map((detail) => (
                      <li key={detail}>{sanitizeTraceCopy(detail, scoreLabel)}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
