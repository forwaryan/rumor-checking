import { getVerificationScoreMeta } from "@/lib/report-utils";
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
            <h2>风险</h2>
          </div>
        </div>
        <p className="empty-state">这里会列出当前结论还不能忽略的风险。</p>
      </section>
    );
  }

  const scoreMeta = getVerificationScoreMeta(report, provenance);

  return (
    <section className="panel panel--aside">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Boundary</p>
          <h2>风险</h2>
        </div>
      </div>

      <p className="panel-copy">{`当前处于${scoreMeta.modeLabel}区间。${getBoundaryCopy(scoreMeta.score)}`}</p>
      <p className="panel-copy panel-copy--compact">{`核查完成度：${scoreMeta.label}`}</p>

      <ul className="bullet-list">
        {report.risks.map((risk) => (
          <li key={risk}>{risk}</li>
        ))}
      </ul>
    </section>
  );
}
