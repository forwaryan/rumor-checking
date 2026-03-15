import { getOverallCredibilityMeta } from "@/lib/report-high-score";
import { getReportProvenanceMeta, getTopLineAssessment, getVerificationScoreMeta } from "@/lib/report-utils";
import type { AnalysisStatus, Report, ReportProvenanceState } from "@/types/report";

interface StatusBannerProps {
  status: AnalysisStatus;
  report: Report | null;
  provenance: ReportProvenanceState | null;
  errorMessage: string | null;
  onRetry: (() => void) | null;
}

function getStatusCopy(status: AnalysisStatus, report: Report | null) {
  if (report && (status === "complete" || status === "partial" || status === "safe_mode")) {
    return {
      title: "结果已生成",
      body: "页面会按核查完成度、证据和边界信息展示当前结果。",
    };
  }

  switch (status) {
    case "submitting":
      return {
        title: "正在联网核查",
        body: "系统会并行整理内容核查和传播链，再输出一句话结论、双主流程完成度和风险边界。",
      };
    case "error":
      return {
        title: "提交失败",
        body: "当前输入没有通过校验，或本次请求没有成功返回。",
      };
    default:
      return {
        title: "准备就绪",
        body: "提交后会先给出一句话结论，再展示整体可信度、传播链、内容核查和证据。",
      };
  }
}

export function StatusBanner({
  status,
  report,
  provenance,
  errorMessage,
  onRetry,
}: StatusBannerProps) {
  const copy = getStatusCopy(status, report);
  const topLine = report ? getTopLineAssessment(report) : null;
  const scoreMeta = report ? getVerificationScoreMeta(report, provenance) : null;
  const overallMeta = getOverallCredibilityMeta(report, provenance);
  const provenanceMeta = getReportProvenanceMeta(report, provenance);

  return (
    <section className={`status-banner status-banner--${status}`}>
      <div className="status-banner__content">
        <p className="eyebrow">{report ? "Final Answer" : "Status Banner"}</p>
        <div className="status-banner__headline">
          <div>
            <h3>{topLine?.title ?? copy.title}</h3>
            <p>{topLine?.summary ?? scoreMeta?.summary ?? copy.body}</p>
          </div>
        </div>

        {topLine ? (
          <>
            <div className="status-banner__fact-row">
              {overallMeta ? (
                <span className="provenance-pill provenance-pill--subtle">{`整体可信度：${overallMeta.scoreLabel} · ${overallMeta.label}`}</span>
              ) : null}
              {scoreMeta ? (
                <span className="provenance-pill provenance-pill--subtle">{`核查完成度：${scoreMeta.label}`}</span>
              ) : null}
              <span className="provenance-pill provenance-pill--subtle">{`置信度：${topLine.confidenceLabel}`}</span>
              <span className="provenance-pill provenance-pill--subtle">{`已纳入证据：${topLine.evidenceCount} 条`}</span>
            </div>
            {topLine.decisiveClaim ? (
              <div className="status-banner__claim-focus">
                <span className="stats-label">当前最关键的核查点</span>
                <strong>{topLine.decisiveClaim}</strong>
              </div>
            ) : null}
          </>
        ) : null}

        {provenanceMeta ? (
          <div className="status-banner__provenance">
            <div className="status-banner__provenance-heading">
              <div className="status-banner__provenance-badges">
                <span className={`provenance-pill provenance-pill--${provenanceMeta.tone}`}>{provenanceMeta.sourceLabel}</span>
                {provenanceMeta.fallbackLabel ? (
                  <span className="provenance-pill provenance-pill--subtle">{provenanceMeta.fallbackLabel}</span>
                ) : null}
                {provenanceMeta.detailBadges.map((badge) => (
                  <span key={badge} className="provenance-pill provenance-pill--subtle">
                    {badge}
                  </span>
                ))}
              </div>
              <p className="status-banner__provenance-summary">{provenanceMeta.summary}</p>
              {provenanceMeta.caution ? <p className="status-banner__provenance-note">{provenanceMeta.caution}</p> : null}
            </div>
          </div>
        ) : null}

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
