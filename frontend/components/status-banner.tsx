import { getModeMeta } from "@/lib/report-utils";
import type { AnalysisStatus, Report } from "@/types/report";

interface StatusBannerProps {
  status: AnalysisStatus;
  report: Report | null;
  errorMessage: string | null;
  fallbackMessage: string | null;
  onRetry: (() => void) | null;
}

function getStatusCopy(status: AnalysisStatus, report: Report | null) {
  if (report && (status === "complete" || status === "partial" || status === "safe_mode")) {
    const meta = getModeMeta(report.mode);
    return {
      title: `${meta.label} / ${meta.kicker}`,
      body: meta.summary,
    };
  }

  switch (status) {
    case "submitting":
      return {
        title: "正在分析输入",
        body: "系统会优先完成事件摘要和 claim 提取，再决定能否进入完整模式。",
      };
    case "error":
      return {
        title: "提交失败",
        body: "当前输入还没通过校验或请求未完成，请检查内容后重试。",
      };
    default:
      return {
        title: "准备就绪",
        body: "先看结论，再看传播链、claim 和证据。示例区已经准备好三档稳定回放。",
      };
  }
}

export function StatusBanner({ status, report, errorMessage, fallbackMessage, onRetry }: StatusBannerProps) {
  const copy = getStatusCopy(status, report);

  return (
    <section className={`status-banner status-banner--${status}`}>
      <div>
        <p className="eyebrow">Status Banner</p>
        <h3>{copy.title}</h3>
        <p>{copy.body}</p>
        {fallbackMessage ? <p className="status-banner__hint">{fallbackMessage}</p> : null}
        {errorMessage ? <p className="status-banner__error">{errorMessage}</p> : null}
      </div>
      {onRetry ? (
        <button type="button" className="button button--secondary" onClick={onRetry}>
          重试上一次请求
        </button>
      ) : null}
    </section>
  );
}
