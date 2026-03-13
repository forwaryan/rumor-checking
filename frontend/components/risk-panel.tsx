import { getModeMeta } from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface RiskPanelProps {
  report: Report | null;
}

function getBoundaryCopy(mode: Report["mode"]) {
  switch (mode) {
    case "complete_mode":
      return "基于当前可检索公开来源的关键节点时间线，不代表平台级完整传播全貌。";
    case "partial_mode":
      return "部分链路仍缺证据，页面不会把局部结果伪装成完整复盘。";
    default:
      return "当前只输出待核查点与边界说明，不对争议说法作过度确定判断。";
  }
}

export function RiskPanel({ report }: RiskPanelProps) {
  if (!report) {
    return (
      <section className="panel panel--aside">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Risk Panel</p>
            <h2>风险与边界</h2>
          </div>
        </div>
        <p className="empty-state">
          这里会显式写清当前模式的边界、fallback 说明和继续核查建议，避免用户误以为系统“正常但很笨”。
        </p>
      </section>
    );
  }

  const meta = getModeMeta(report.mode);

  return (
    <section className="panel panel--aside">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Risk Panel</p>
          <h2>{meta.kicker}</h2>
        </div>
      </div>

      <p className="panel-copy">{getBoundaryCopy(report.mode)}</p>

      <ul className="bullet-list">
        {report.risks.map((risk) => (
          <li key={risk}>{risk}</li>
        ))}
      </ul>

      <div className="stats-grid">
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
