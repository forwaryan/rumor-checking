import { ModePill } from "@/components/mode-pill";
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
            <p className="eyebrow">Event Card</p>
            <h2>事件概览与结论</h2>
          </div>
        </div>
        <p className="empty-state">
          提交输入后，这里会先显示一句话结论、事件摘要和当前模式，帮助演示时在 30 秒内讲清页面。
        </p>
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
          <p className="eyebrow">Event Card</p>
          <h2>{displayTitle}</h2>
        </div>
        <ModePill mode={report.mode} />
      </div>

      <p className="lede">{report.final_summary}</p>
      <p className="panel-copy">{displaySummary}</p>
      {displaySource.isDerived ? (
        <p className="event-card__note">页面已把泛化问法收束到更具体的公开事件对象。</p>
      ) : null}

      <div className="meta-row">
        <a href={displaySource.sourceUrl} target="_blank" rel="noreferrer">
          {displaySource.sourceName}
        </a>
        <span>{formatDisplayTime(displaySource.publishedAt)}</span>
      </div>

      <div className="tag-row">
        {report.event.keywords.map((keyword) => (
          <span key={keyword} className="tag">
            {keyword}
          </span>
        ))}
      </div>
    </section>
  );
}
