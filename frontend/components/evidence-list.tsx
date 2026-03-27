import { collectEvidence, formatDisplayTime } from "@/lib/report-utils";
import type { Evidence, Report } from "@/types/report";

interface EvidenceListProps {
  report: Report | null;
}

function sortEvidence(items: Evidence[]) {
  return [...items].sort((left, right) => {
    return new Date(right.published_at).getTime() - new Date(left.published_at).getTime();
  });
}

export function EvidenceList({ report }: EvidenceListProps) {
  const evidence = report ? collectEvidence(report) : [];
  const evidenceUrls = new Set(evidence.map((item) => item.url));
  const retrievalHits = report
    ? sortEvidence((report.retrieval_hits ?? []).filter((item) => !evidenceUrls.has(item.url)))
    : [];
  const cards = evidence.length ? evidence : retrievalHits;

  return (
    <section className="panel panel--evidence">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2>证据来源</h2>
        </div>
      </div>

      {cards.length ? (
        <div className="evidence-grid">
          {cards.map((item) => (
            <article key={item.url} className="evidence-card">
              <div className="meta-row">
                <strong>{item.source_name}</strong>
                <span>{formatDisplayTime(item.published_at)}</span>
              </div>
              <h3>{item.title}</h3>
              <p>{item.snippet}</p>
              <p className="evidence-reason">{item.relevance_reason}</p>
              <a href={item.url} target="_blank" rel="noreferrer">
                查看来源
              </a>
            </article>
          ))}
        </div>
      ) : null}

      {!cards.length ? <p className="empty-state">当前还没有可展示的来源。</p> : null}
    </section>
  );
}
