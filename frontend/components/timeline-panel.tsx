import { formatDisplayTime, sortTimeline } from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface TimelinePanelProps {
  report: Report | null;
}

function getEmptyCopy(mode: Report["mode"] | null) {
  if (mode === "safe_mode") {
    return "当前还不足以还原传播过程。";
  }

  if (mode === "partial_mode") {
    return "只拿到了部分关键节点。";
  }

  return "提交后，这里会按时间顺序展示关键节点。";
}

export function TimelinePanel({ report }: TimelinePanelProps) {
  const timeline = report ? sortTimeline(report.timeline) : [];

  return (
    <section className="panel panel--timeline">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Timeline</p>
          <h2>时间线</h2>
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
