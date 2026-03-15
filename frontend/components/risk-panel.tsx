import { getVerificationScoreMeta, getVerificationScoreRuleText } from "@/lib/report-utils";
import type { Report, ReportProvenanceState } from "@/types/report";

interface RiskPanelProps {
  report: Report | null;
  provenance: ReportProvenanceState | null;
}

function getBoundaryCopy(score: number) {
  if (score >= 8) {
      return "基于当前可检索公开来源的关键节点时间线，不代表平台级完整传播全貌。";
  }

  if (score >= 5) {
    return "部分链路仍缺证据，页面不会把局部结果伪装成完整复盘。";
  }

  return "当前只输出待核查点与边界说明，不对争议说法作过度确定判断。";
}

export function RiskPanel({ report, provenance }: RiskPanelProps) {
  if (!report) {
    return (
      <section className="panel panel--aside">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Boundary</p>
            <h2>风险与边界</h2>
          </div>
        </div>
        <p className="empty-state">
          这里会写清当前分数的边界、fallback 说明和继续核查建议，避免用户误以为系统“正常但很笨”。
        </p>
      </section>
    );
  }

  const scoreMeta = getVerificationScoreMeta(report, provenance);

  return (
    <section className="panel panel--aside">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Boundary</p>
          <h2>风险与边界</h2>
        </div>
      </div>

      <p className="panel-copy">{`当前处于${scoreMeta.modeLabel}区间。${getBoundaryCopy(scoreMeta.score)}`}</p>
      <p className="panel-copy">{scoreMeta.summary}</p>
      <p className="panel-copy panel-copy--compact">{`评分规则：${getVerificationScoreRuleText()}`}</p>

      <ul className="bullet-list">
        {report.risks.map((risk) => (
          <li key={risk}>{risk}</li>
        ))}
      </ul>

      <div className="stats-grid">
        <div>
          <span className="stats-label">核查完成度</span>
          <strong>{scoreMeta.label}</strong>
        </div>
        <div>
          <span className="stats-label">时间线节点</span>
          <strong>{report.timeline.length}</strong>
        </div>
        <div>
          <span className="stats-label">claim 数量</span>
          <strong>{report.claim_results.length}</strong>
        </div>
        <div>
          <span className="stats-label">来源数量</span>
          <strong>{report.sources.length}</strong>
        </div>
      </div>
    </section>
  );
}
