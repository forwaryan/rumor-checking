import {
  formatDisplayTime,
  getDisplayEventSource,
  getDisplayEventSummary,
  getDisplayEventTitle,
} from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface EventCardProps {
  report: Report | null;
}

export function EventCard({ report }: EventCardProps) {
  if (!report) {
    return (
      <section className="panel panel--feature">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Result Snapshot</p>
            <h2>事件概览</h2>
          </div>
        </div>
        <p className="empty-state">提交后，这里会显示事件摘要和一句话结论。</p>
      </section>
    );
  }

  const displayTitle = getDisplayEventTitle(report);
  const displaySummary = getDisplayEventSummary(report);
  const displaySource = getDisplayEventSource(report);

  return (
    <section className="panel panel--feature">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Result Snapshot</p>
          <h2>{displayTitle}</h2>
        </div>
      </div>

      <p className="lede">{report.final_summary}</p>
      <p className="panel-copy">{displaySummary}</p>

      <div className="meta-row">
        <a href={displaySource.sourceUrl} target="_blank" rel="noreferrer">
          {displaySource.sourceName}
        </a>
        <span>{formatDisplayTime(displaySource.publishedAt)}</span>
      </div>
    </section>
  );
}
