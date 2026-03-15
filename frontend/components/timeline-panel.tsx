import { getIndependentSourceCount, getTimelineConfidence } from "@/lib/report-high-score";
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
  const timelineConfidence = getTimelineConfidence(report);
  const independentSourceCount = getIndependentSourceCount(report);

  return (
    <section className="panel panel--timeline">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Timeline</p>
          <h2>时间线</h2>
        </div>
      </div>

      {report ? (
        <>
          <p className="panel-copy">这条链路解释“消息是怎么传开的”，不直接等于真假判断。</p>
          <div className="tag-row">
            <span className="provenance-pill provenance-pill--subtle">
              {timelineConfidence === null ? "传播链完成度：待返回" : `传播链完成度：${Math.round(timelineConfidence)}/100`}
            </span>
            <span className="provenance-pill provenance-pill--subtle">{`关键节点：${timeline.length} 个`}</span>
            {independentSourceCount !== null ? (
              <span className="provenance-pill provenance-pill--subtle">{`独立来源：${independentSourceCount} 个`}</span>
            ) : null}
          </div>
        </>
      ) : null}

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
                <p className="timeline-why">{`为何入选：${node.why_selected}`}</p>
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
