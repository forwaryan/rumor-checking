import { getClaimSummaryBuckets } from "@/lib/report-high-score";
import { formatConfidence, getVerdictLabel } from "@/lib/report-utils";
import type { ContentCheck, ContentCheckItem, Report } from "@/types/report";

interface ContentCheckPanelProps {
  report: Report | null;
}

const bucketCopy = [
  {
    key: "likely_true",
    title: "更像真的",
    empty: "当前还没有能稳定支持的部分。",
    tone: "true",
  },
  {
    key: "likely_false",
    title: "更像加料或不成立",
    empty: "当前还没有被明确反驳的部分。",
    tone: "false",
  },
  {
    key: "controversial",
    title: "公开来源在打架",
    empty: "当前没有明显冲突项。",
    tone: "controversial",
  },
  {
    key: "opinions",
    title: "观点或判断",
    empty: "当前没有明显评价性表述。",
    tone: "opinion",
  },
  {
    key: "uncertain",
    title: "仍待核查",
    empty: "当前没有额外待核查项。",
    tone: "uncertain",
  },
] as const;

function buildFallbackContentCheck(report: Report): ContentCheck {
  const likelyTrue = report.claim_results
    .filter((item) => item.claim_type === "fact" && item.verdict === "supported")
    .map((item) => ({
      claim: item.claim,
      claim_type: item.claim_type,
      verdict: item.verdict,
      confidence: item.confidence,
      reason: item.notes,
    }));
  const likelyFalse = report.claim_results
    .filter((item) => item.claim_type === "fact" && item.verdict === "refuted")
    .map((item) => ({
      claim: item.claim,
      claim_type: item.claim_type,
      verdict: item.verdict,
      confidence: item.confidence,
      reason: item.notes,
    }));
  const controversial = report.claim_results
    .filter((item) => item.verdict === "conflicting")
    .map((item) => ({
      claim: item.claim,
      claim_type: item.claim_type,
      verdict: item.verdict,
      confidence: item.confidence,
      reason: item.notes,
    }));
  const opinions = report.claim_results
    .filter((item) => item.claim_type === "opinion")
    .map((item) => ({
      claim: item.claim,
      claim_type: item.claim_type,
      verdict: item.verdict,
      confidence: item.confidence,
      reason: item.notes,
    }));
  const uncertain = report.claim_results
    .filter((item) => item.claim_type !== "opinion" && item.verdict === "insufficient")
    .map((item) => ({
      claim: item.claim,
      claim_type: item.claim_type,
      verdict: item.verdict,
      confidence: item.confidence,
      reason: item.notes,
    }));

  const possibleAnswers = report.mode === "safe_mode"
    ? [
        {
          angle: "直接回答",
          answer: "目前还不能把这句话整体判真或判假，只能先拆成更细的说法逐项核查。",
        },
        {
          angle: "继续较真",
          answer: "要继续往下核查，最好补姓名、原帖链接、截图原文或明确时间点。",
        },
      ]
    : [
        {
          angle: "直接回答",
          answer: report.final_summary,
        },
      ];

  return {
    likely_true: likelyTrue,
    likely_false: likelyFalse,
    controversial,
    opinions,
    uncertain,
    possible_answers: possibleAnswers,
  };
}

function renderItems(items: ContentCheckItem[], emptyText: string, tone: string) {
  if (!items.length) {
    return <p className="content-check__empty">{emptyText}</p>;
  }

  return (
    <div className="content-check__list">
      {items.map((item) => (
        <article key={`${item.claim}-${item.verdict}`} className={`content-check__item content-check__item--${tone}`}>
          <div className="meta-row">
            <strong>{item.claim}</strong>
            <span className={`tag tag--verdict tag--${item.verdict}`}>{getVerdictLabel(item.verdict)}</span>
          </div>
          <p>{item.reason}</p>
          <span className="cell-subtle">置信度 {formatConfidence(item.confidence)}</span>
        </article>
      ))}
    </div>
  );
}

export function ContentCheckPanel({ report }: ContentCheckPanelProps) {
  if (!report) {
    return (
      <section className="panel panel--content-check">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Content Check</p>
            <h2>内容核查</h2>
          </div>
        </div>
        <p className="empty-state">这里会把一句话拆成几类可核查内容。</p>
      </section>
    );
  }

  const contentCheck = report.content_check ?? buildFallbackContentCheck(report);
  const summaryBuckets = getClaimSummaryBuckets(report);

  return (
    <section className="panel panel--content-check">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Content Check</p>
          <h2>内容核查</h2>
        </div>
      </div>

      <div className="claim-summary-strip">
        {summaryBuckets.map((bucket) => (
          <article key={bucket.key} className={`claim-summary-card claim-summary-card--${bucket.tone}`}>
            <span>{bucket.label}</span>
            <strong>{bucket.count}</strong>
            <p>{bucket.helper}</p>
          </article>
        ))}
      </div>

      <div className="content-check-grid">
        {bucketCopy.map((bucket) => (
          <div key={bucket.key} className="content-check__block">
            <h3>{bucket.title}</h3>
            {renderItems(contentCheck[bucket.key], bucket.empty, bucket.tone)}
          </div>
        ))}
      </div>

      {contentCheck.possible_answers.length ? (
        <div className="content-check__answers">
          <h3>推荐回答方式</h3>
          <div className="content-check__answer-list">
            {contentCheck.possible_answers.map((item) => (
              <article key={`${item.angle}-${item.answer}`} className="content-check__answer-card">
                <strong>{item.angle}</strong>
                <p>{item.answer}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
