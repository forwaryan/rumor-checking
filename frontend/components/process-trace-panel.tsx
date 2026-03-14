import type { AnalyzeRequest, AnalysisStatus, PipelineTrace, PipelineTraceStep, Report } from "@/types/report";

interface ProcessTracePanelProps {
  report: Report | null;
  request: AnalyzeRequest | null;
  status: AnalysisStatus;
}

const statusLabel: Record<PipelineTraceStep["status"], string> = {
  completed: "已完成",
  warning: "需关注",
  skipped: "已跳过",
  error: "异常",
};

function preview(value: string, limit = 120) {
  const compact = value.trim().replace(/\s+/g, " ");
  return compact.length <= limit ? compact : `${compact.slice(0, limit - 3)}...`;
}

function buildPendingTrace(request: AnalyzeRequest): PipelineTrace {
  return {
    steps: [
      {
        stage_key: "input_received",
        title: "接收输入",
        status: "completed",
        summary: "当前输入已经提交到页面状态，准备进入 analyze 链路。",
        details: [`原始输入：${preview(request.raw_input)}`, `输入类型：${request.input_type}`],
      },
      {
        stage_key: "request_dispatch",
        title: "请求发出",
        status: "completed",
        summary: "前端已向后端发送 analyze 请求，正在等待返回。",
        details: ["当前页面还没有拿到 report，右侧链路会在返回后自动补齐。"],
      },
      {
        stage_key: "response_pending",
        title: "等待结果",
        status: "warning",
        summary: "后端尚未返回完整结果，因此其余步骤暂不可见。",
        details: [],
      },
    ],
  };
}

function buildFallbackTrace(report: Report, request: AnalyzeRequest | null): PipelineTrace {
  const requestInput = request?.raw_input?.trim() || report.event.summary || report.event.title;
  const decisiveCount = report.claim_results.filter((item) => item.verdict !== "insufficient").length;
  const diagnostics = report.retrieval_diagnostics;

  return {
    steps: [
      {
        stage_key: "input_received",
        title: "接收输入",
        status: "completed",
        summary: "页面已经记录本次输入，并开始构建分析链路。",
        details: [
          `原始输入：${preview(requestInput || "无")}`,
          `模式：${report.mode}`,
        ],
      },
      {
        stage_key: "retrieval_summary",
        title: "检索概况",
        status: diagnostics?.canonical_result_count ? "completed" : "warning",
        summary: diagnostics?.query
          ? `已生成检索 query，并拿到 ${diagnostics.canonical_result_count} 条 canonical 结果。`
          : "当前没有拿到完整检索细节，只能基于最终 report 反推链路。",
        details: diagnostics
          ? [
              `query：${preview(diagnostics.query || "无")}`,
              `provider：${diagnostics.provider_name ?? "unknown"}`,
              `cache：${diagnostics.cache_status ?? "unknown"}`,
            ]
          : [],
      },
      {
        stage_key: "claim_summary",
        title: "Claim 判定",
        status: decisiveCount ? "completed" : "warning",
        summary: `当前 report 共输出 ${report.claim_results.length} 条 claim，其中 ${decisiveCount} 条已经拿到非“证据不足”判定。`,
        details: report.claim_results.slice(0, 3).map((item) => `${item.verdict}：${preview(item.claim, 96)}`),
      },
      {
        stage_key: "timeline_summary",
        title: "时间线概况",
        status: report.timeline.length ? "completed" : "warning",
        summary: report.timeline.length
          ? `当前 report 还原了 ${report.timeline.length} 个时间线节点。`
          : "当前 report 还没有稳定时间线节点。",
        details: report.timeline.slice(0, 3).map((item) => `${item.node_type}：${preview(item.title, 96)}`),
      },
      {
        stage_key: "report_output",
        title: "报告输出",
        status: report.mode === "safe_mode" ? "warning" : "completed",
        summary: "页面其余卡片都基于当前 report 渲染。",
        details: [
          `来源：${report.provenance?.source_type ?? "unknown"}`,
          `总结：${preview(report.final_summary, 128)}`,
        ],
      },
    ],
  };
}

function resolveTrace(report: Report | null, request: AnalyzeRequest | null, status: AnalysisStatus): PipelineTrace | null {
  if (report?.pipeline_trace?.steps.length) {
    return report.pipeline_trace;
  }

  if (report) {
    return buildFallbackTrace(report, request);
  }

  if (request && status === "submitting") {
    return buildPendingTrace(request);
  }

  return null;
}

export function ProcessTracePanel({ report, request, status }: ProcessTracePanelProps) {
  const trace = resolveTrace(report, request, status);

  if (!trace) {
    return (
      <section className="panel panel--trace">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Pipeline</p>
            <h2>链路过程</h2>
          </div>
        </div>
        <p className="empty-state">
          这里会按步骤展示从输入问题、检索、收束、判定到最终 report 输出的整条链路，方便直接定位是哪一步出了问题。
        </p>
      </section>
    );
  }

  return (
    <section className="panel panel--trace">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Pipeline</p>
          <h2>链路过程</h2>
        </div>
      </div>

      <div className="trace-list">
        {trace.steps.map((step, index) => (
          <article key={`${step.stage_key}-${index}`} className="trace-step">
            <div className="trace-step__header">
              <div>
                <span className="stats-label">Step {index + 1}</span>
                <h3>{step.title}</h3>
                <p className="trace-step__stage">{step.stage_key}</p>
              </div>
              <span className={`trace-pill trace-pill--${step.status}`}>{statusLabel[step.status]}</span>
            </div>
            <p className="trace-step__summary">{step.summary}</p>
            {step.details.length > 0 ? (
              <ul className="trace-step__details">
                {step.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
