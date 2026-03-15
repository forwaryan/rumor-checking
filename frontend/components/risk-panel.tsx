import { getOverallCredibilityMeta, getScoreBreakdown } from "@/lib/report-high-score";
import { getReportProvenanceMeta, getVerificationScoreMeta } from "@/lib/report-utils";
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

const fixedRiskReminders = [
  "页面只基于当前 report 落盘结果展示，不代表平台级全量传播监控。",
  "观点、情绪化表达和事实 claim 会拆开看，不会因为整条新闻热门就一并判真。",
  "即使显示 live provenance，也只能按当前返回字段讲，不能夸大成实时全网能力。",
];

function collectCurrentLimits(report: Report, provenance: ReportProvenanceState | null) {
  const breakdown = getScoreBreakdown(report);
  const overallMeta = getOverallCredibilityMeta(report, provenance);
  const provenanceMeta = getReportProvenanceMeta(report, provenance);
  const items = [
    provenanceMeta?.fallbackLabel ? `当前状态：${provenanceMeta.fallbackLabel}` : null,
    provenanceMeta?.caution ?? null,
    overallMeta?.score === null ? "后端尚未返回整体可信度总分，需结合 claim、时间线和风险边界阅读。" : null,
    ...(breakdown?.limiting_factors ?? []),
    ...report.risks,
  ].filter((item): item is string => Boolean(item && item.trim().length > 0));

  return Array.from(new Set(items));
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
  const provenanceMeta = getReportProvenanceMeta(report, provenance);
  const currentLimits = collectCurrentLimits(report, provenance);

  return (
    <section className="panel panel--aside">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Boundary</p>
          <h2>风险</h2>
        </div>
      </div>

      <p className="panel-copy">{`当前处于${scoreMeta.modeLabel}区间。${getBoundaryCopy(scoreMeta.score)}`}</p>
      <div className="tag-row">
        <span className="provenance-pill provenance-pill--subtle">{`核查完成度：${scoreMeta.label}`}</span>
        {provenanceMeta ? <span className={`provenance-pill provenance-pill--${provenanceMeta.tone}`}>{provenanceMeta.sourceLabel}</span> : null}
      </div>

      <div className="risk-panel__section">
        <span className="panel-subheading">固定风险提示</span>
        <ul className="bullet-list">
          {fixedRiskReminders.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>

      <div className="risk-panel__section">
        <span className="panel-subheading">当前局限</span>
        <ul className="bullet-list">
          {currentLimits.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
