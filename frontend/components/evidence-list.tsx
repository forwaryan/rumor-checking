import { collectEvidence, formatDisplayTime } from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface EvidenceListProps {
  report: Report | null;
}

export function EvidenceList({ report }: EvidenceListProps) {
  const evidence = report ? collectEvidence(report) : [];

  return (
    <section className="panel panel--evidence">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Evidence List</p>
          <h2>证据与来源</h2>
        </div>
      </div>

      {evidence.length ? (
        <div className="evidence-grid">
          {evidence.map((item) => (
            <article key={item.url} className="evidence-card">
              <div className="meta-row">
                <span className={`tier-pill tier-pill--${item.source_tier}`}>Tier {item.source_tier}</span>
                <span>{formatDisplayTime(item.published_at)}</span>
              </div>
              <h3>{item.title}</h3>
              <p>{item.snippet}</p>
              <p className="evidence-reason">为何相关：{item.relevance_reason}</p>
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.source_name}
              </a>
            </article>
          ))}
        </div>
      ) : (
        <p className="empty-state">
          证据列表会汇总 claim 级证据和顶层 sources；若当前没有可追溯来源，页面会明确告诉用户“证据尚未建立”。
        </p>
      )}
    </section>
  );
}
