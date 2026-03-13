import { formatDisplayTime, sortTimeline } from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface TimelinePanelProps {
  report: Report | null;
}

function getEmptyCopy(mode: Report["mode"] | null) {
  if (mode === "safe_mode") {
    return "传播链暂不足以完整还原，当前页面只保留边界化提示。";
  }

  if (mode === "partial_mode") {
    return "只拿到了部分关键节点，页面不会把它包装成完整时间线。";
  }

  return "提交输入后，这里会按 origin -> amplification -> peak -> turn -> clarification 展开关键来源时间线。";
}

export function TimelinePanel({ report }: TimelinePanelProps) {
  const timeline = report ? sortTimeline(report.timeline) : [];

  return (
    <section className="panel panel--timeline">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Timeline Panel</p>
          <h2>关键来源时间线</h2>
        </div>
      </div>

      {timeline.length ? (
        <ol className="timeline-list">
          {timeline.map((node) => (
            <li key={`${node.url}-${node.published_at}`} className="timeline-item">
              <div className={`node-badge node-badge--${node.node_type}`}>{node.node_type}</div>
              <div className="timeline-copy">
                <div className="meta-row">
                  <strong>{node.title}</strong>
                  <span>{formatDisplayTime(node.published_at)}</span>
                </div>
                <p>{node.summary}</p>
                <p className="timeline-why">入选原因：{node.why_selected}</p>
                <a href={node.url} target="_blank" rel="noreferrer">
                  {node.source_name}
                </a>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-state">{getEmptyCopy(report?.mode ?? null)}</p>
      )}
    </section>
  );
}
