import { collectEvidence, formatDisplayTime } from "@/lib/report-utils";
import type { Evidence, Report } from "@/types/report";

interface EvidenceListProps {
  report: Report | null;
}

const fallbackReasonLabels: Record<string, string> = {
  retrieval_provider_unavailable: "\u68c0\u7d22 provider \u5f53\u524d\u4e0d\u53ef\u7528\u6216\u672a\u542f\u7528",
  real_retrieval_failed: "\u771f\u5b9e\u68c0\u7d22\u8bf7\u6c42\u672c\u6b21\u5931\u8d25",
  real_retrieval_empty: "\u771f\u5b9e\u68c0\u7d22\u8fd4\u56de 0 \u6761\u7ed3\u679c",
  retrieval_cache_only_miss: "\u4ec5\u7f13\u5b58\u6a21\u5f0f\u672a\u547d\u4e2d",
  url_fetch_timeout: "\u94fe\u63a5\u6293\u53d6\u8d85\u65f6",
  url_content_incomplete: "\u94fe\u63a5\u6b63\u6587\u4e0d\u5b8c\u6574",
  url_content_missing: "\u94fe\u63a5\u6b63\u6587\u7f3a\u5931",
  url_fetch_failed: "\u94fe\u63a5\u6293\u53d6\u5931\u8d25",
  url_content_unsupported: "\u5f53\u524d URL \u7c7b\u578b\u4e0d\u53d7\u652f\u6301",
  url_invalid: "URL \u65e0\u6548\u6216\u4e0d\u53ef\u8bbf\u95ee",
};

function sortEvidence(items: Evidence[]) {
  return [...items].sort((left, right) => {
    return new Date(right.published_at).getTime() - new Date(left.published_at).getTime();
  });
}

function formatFallbackReasons(report: Report | null) {
  const reasons = report?.provenance?.fallback_reasons ?? [];
  if (!reasons.length) {
    return "\u672c\u6b21\u672a\u8bb0\u5f55\u56de\u9000\u539f\u56e0";
  }

  return reasons.map((item) => fallbackReasonLabels[item] ?? item).join(" / ");
}

function formatNullable(value: string | null | undefined, fallback: string) {
  if (!value) {
    return fallback;
  }

  const trimmed = value.trim();
  return trimmed || fallback;
}

export function EvidenceList({ report }: EvidenceListProps) {
  const evidence = report ? collectEvidence(report) : [];
  const evidenceUrls = new Set(evidence.map((item) => item.url));
  const retrievalHits = report
    ? sortEvidence((report.retrieval_hits ?? []).filter((item) => !evidenceUrls.has(item.url)))
    : [];
  const diagnostics = report?.retrieval_diagnostics ?? null;
  const providerName = formatNullable(
    diagnostics?.provider_name ?? report?.provenance?.retrieval_provider,
    "unknown",
  );
  const cacheStatus = formatNullable(
    diagnostics?.cache_status ?? report?.provenance?.retrieval_cache_status,
    "not_used",
  );
  const fallbackSummary = formatFallbackReasons(report);

  return (
    <section className="panel panel--evidence">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2>{"\u8bc1\u636e\u4e0e\u68c0\u7d22\u547d\u4e2d"}</h2>
        </div>
      </div>

      {diagnostics ? (
        <>
          <div className="panel-subheading">{"\u68c0\u7d22\u8bca\u65ad"}</div>
          <article className="evidence-card evidence-card--raw-hit">
            <div className="meta-row">
              <span>{`provider: ${providerName}`}</span>
              <span>
                {diagnostics.retrieved_at
                  ? formatDisplayTime(diagnostics.retrieved_at)
                  : "\u672a\u8bb0\u5f55\u68c0\u7d22\u65f6\u95f4"}
              </span>
            </div>
            <h3>{"\u672c\u6b21\u68c0\u7d22\u4e0a\u4e0b\u6587"}</h3>
            <p className="evidence-reason">
              {"\u67e5\u8be2\u8bcd\uff1a"}
              <code>{formatNullable(diagnostics.query, "\u672a\u8bb0\u5f55 query")}</code>
            </p>
            <p className="evidence-reason">
              {"\u539f\u59cb\u547d\u4e2d / \u53bb\u91cd\u547d\u4e2d\uff1a"}
              {`${diagnostics.raw_result_count} / ${diagnostics.canonical_result_count}`}
            </p>
            <p className="evidence-reason">{"\u7f13\u5b58\u72b6\u6001\uff1a"}{cacheStatus}</p>
            <p className="evidence-reason">{"\u56de\u9000\u539f\u56e0\uff1a"}{fallbackSummary}</p>
            {diagnostics.failure_detail ? (
              <p className="evidence-reason">{"\u5931\u8d25\u8be6\u60c5\uff1a"}{diagnostics.failure_detail}</p>
            ) : null}
            {!retrievalHits.length && diagnostics.canonical_result_count === 0 ? (
              <p className="evidence-reason">
                {
                  "\u672c\u6b21\u6ca1\u6709\u53ef\u5c55\u793a\u7684 raw hits\uff0c\u6240\u4ee5\u4e0b\u65b9\u5217\u8868\u4f1a\u4fdd\u6301\u4e3a\u7a7a\u3002"
                }
              </p>
            ) : null}
          </article>
        </>
      ) : null}

      {evidence.length ? (
        <>
          <div className="panel-subheading">{"\u5df2\u8fdb\u5165\u8bc1\u636e\u94fe"}</div>
          <div className="evidence-grid">
            {evidence.map((item) => (
              <article key={item.url} className="evidence-card">
                <div className="meta-row">
                  <span className={`tier-pill tier-pill--${item.source_tier}`}>Tier {item.source_tier}</span>
                  <span>{formatDisplayTime(item.published_at)}</span>
                </div>
                <h3>{item.title}</h3>
                <p>{item.snippet}</p>
                <p className="evidence-reason">{"\u4e3a\u4f55\u76f8\u5173\uff1a"}{item.relevance_reason}</p>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.source_name}
                </a>
              </article>
            ))}
          </div>
        </>
      ) : null}

      {retrievalHits.length ? (
        <>
          <div className="panel-subheading">{"\u539f\u59cb\u68c0\u7d22\u547d\u4e2d"}</div>
          <div className="evidence-grid">
            {retrievalHits.map((item) => (
              <article key={item.url} className="evidence-card evidence-card--raw-hit">
                <div className="meta-row">
                  <span className={`tier-pill tier-pill--${item.source_tier}`}>Tier {item.source_tier}</span>
                  <span>{formatDisplayTime(item.published_at)}</span>
                </div>
                <h3>{item.title}</h3>
                <p>{item.snippet}</p>
                <p className="evidence-reason">{"\u547d\u4e2d\u8bf4\u660e\uff1a"}{item.relevance_reason}</p>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.source_name}
                </a>
              </article>
            ))}
          </div>
        </>
      ) : null}

      {!evidence.length && !retrievalHits.length ? (
        <p className="empty-state">
          {diagnostics
            ? "\u5f53\u524d\u8fd8\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u7a33\u5b9a\u6765\u6e90\u6216 raw hits\uff1b\u4e0a\u65b9\u68c0\u7d22\u8bca\u65ad\u4f1a\u8bf4\u660e\u8fd9\u6b21\u5230\u5e95\u67e5\u4e86\u4ec0\u4e48\u3001\u4e3a\u4ec0\u4e48\u6ca1\u62ff\u5230\u7ed3\u679c\u3002"
            : "\u8bc1\u636e\u5217\u8868\u4f1a\u6c47\u603b\u5df2\u8fdb\u5165\u8bc1\u636e\u94fe\u7684\u6765\u6e90\u548c\u539f\u59cb\u68c0\u7d22\u547d\u4e2d\uff1b\u82e5\u5f53\u524d\u6ca1\u6709\u53ef\u8ffd\u6eaf\u6765\u6e90\uff0c\u9875\u9762\u4f1a\u660e\u786e\u544a\u8bc9\u7528\u6237\u201c\u8bc1\u636e\u5c1a\u672a\u5efa\u7acb\u201d\u3002"}
        </p>
      ) : null}
    </section>
  );
}
