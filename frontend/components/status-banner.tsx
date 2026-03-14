import { ModePill } from "@/components/mode-pill";
import { getModeMeta, getReportProvenanceMeta, getTopLineAssessment } from "@/lib/report-utils";
import type { AnalysisStatus, Report, ReportProvenanceState } from "@/types/report";

interface StatusBannerProps {
  status: AnalysisStatus;
  report: Report | null;
  provenance: ReportProvenanceState | null;
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
        title: "正在联网核查",
        body: "系统会先完成检索、claim 收束和证据整理，再决定能否进入完整展示模式。",
      };
    case "error":
      return {
        title: "提交失败",
        body: "当前输入没有通过校验，或本次请求没有成功返回。",
      };
    default:
      return {
        title: "准备就绪",
        body: "提交后会先给出一句话结论，再展示证据、时间线和调试链路。",
      };
  }
}

export function StatusBanner({
  status,
  report,
  provenance,
  errorMessage,
  fallbackMessage,
  onRetry,
}: StatusBannerProps) {
  const copy = getStatusCopy(status, report);
  const provenanceMeta = status === "submitting" ? null : getReportProvenanceMeta(report, provenance);
  const topLine = report ? getTopLineAssessment(report) : null;

  return (
    <section className={`status-banner status-banner--${status}`}>
      <div className="status-banner__content">
        <p className="eyebrow">{report ? "Final Answer" : "Status Banner"}</p>
        <div className="status-banner__headline">
          <div>
            <h3>{topLine?.title ?? copy.title}</h3>
            <p>{topLine?.summary ?? copy.body}</p>
          </div>
          {report ? <ModePill mode={report.mode} /> : null}
        </div>

        {topLine ? (
          <>
            <div className="status-banner__fact-row">
              <span className="provenance-pill provenance-pill--subtle">{`置信度：${topLine.confidenceLabel}`}</span>
              <span className="provenance-pill provenance-pill--subtle">{`已纳入证据：${topLine.evidenceCount} 条`}</span>
              <span className="provenance-pill provenance-pill--subtle">{`可见来源：${topLine.sourceCount} 条`}</span>
            </div>
            {topLine.decisiveClaim ? (
              <div className="status-banner__claim-focus">
                <span className="stats-label">当前最关键的核查点</span>
                <strong>{topLine.decisiveClaim}</strong>
              </div>
            ) : null}
          </>
        ) : null}

        {report && provenanceMeta ? (
          <div className="status-banner__provenance">
            <div className="status-banner__provenance-heading">
              <p className="eyebrow">Result Provenance</p>
              <div className="status-banner__provenance-badges">
                <span className={`provenance-pill provenance-pill--${provenanceMeta.tone}`}>
                  {provenanceMeta.sourceLabel}
                </span>
                {provenanceMeta.fallbackLabel ? (
                  <span className="provenance-pill provenance-pill--subtle">{provenanceMeta.fallbackLabel}</span>
                ) : null}
                {provenanceMeta.detailBadges.map((badge) => (
                  <span key={badge} className="provenance-pill provenance-pill--subtle">
                    {badge}
                  </span>
                ))}
              </div>
            </div>
            <p className="status-banner__provenance-summary">{provenanceMeta.summary}</p>
            {provenanceMeta.caution ? (
              <p className="status-banner__provenance-note">{provenanceMeta.caution}</p>
            ) : null}
          </div>
        ) : null}

        {fallbackMessage ? <p className="status-banner__hint">{fallbackMessage}</p> : null}
        {errorMessage ? <p className="status-banner__error">{errorMessage}</p> : null}
      </div>

      {onRetry ? (
        <button type="button" className="button button--secondary" onClick={onRetry}>
          重新分析
        </button>
      ) : null}
    </section>
  );
}
