import { formatDisplayTime } from "@/lib/report-utils";
import { ModePill } from "@/components/mode-pill";
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

  return (
    <section className="panel panel--feature">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Event Card</p>
          <h2>{report.event.title}</h2>
        </div>
        <ModePill mode={report.mode} />
      </div>

      <p className="lede">{report.final_summary}</p>
      <p className="panel-copy">{report.event.summary}</p>

      <div className="meta-row">
        <a href={report.event.source_url} target="_blank" rel="noreferrer">
          {report.event.source_name}
        </a>
        <span>{formatDisplayTime(report.event.published_at)}</span>
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
