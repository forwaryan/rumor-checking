"use client";

import type { Evidence, EvidenceSnapshot, Report } from "@/types/report";
import { getSourceTierMeta } from "@/lib/report-utils";
import { buildEvidenceClaimAccents, type ClaimAccent } from "@/lib/claim-accent";
import { getEvidenceSnapshotView } from "@/lib/evidence-snapshot";

const acquisitionLabels: Record<EvidenceSnapshot["acquisition"], string> = {
  fetched: "本轮抓取", cached: "缓存内容", retrieved: "搜索返回", restored: "恢复的留存内容",
};

function SnapshotDetails({ item, snapshots }: { item: Evidence; snapshots?: EvidenceSnapshot[] }) {
  const { snapshot, highlight, warning } = getEvidenceSnapshotView(item, snapshots);
  if (!snapshot) return <p className="evidence-snapshot__notice">{warning}</p>;
  return <details className="evidence-snapshot">
    <summary>查看留存文本 · {snapshot.kind === "page_text" ? "网页正文（提取文本）" : "搜索摘要（非网页正文）"}{warning && " · 引文未核对"}</summary>
    <div className="evidence-snapshot__body">
      <dl className="evidence-snapshot__metadata">
        <div><dt>留档时间</dt><dd><time dateTime={snapshot.captured_at}>{snapshot.captured_at}</time></dd></div>
        <div><dt>获取方式</dt><dd>{acquisitionLabels[snapshot.acquisition]} · {snapshot.extractor}</dd></div>
        <div><dt>文本 SHA-256</dt><dd><code>{snapshot.text_sha256}</code></dd></div>
        {snapshot.final_url && snapshot.final_url !== snapshot.url && <div><dt>最终地址</dt><dd>{snapshot.final_url}</dd></div>}
      </dl>
      {snapshot.acquisition === "cached" && <p className="evidence-snapshot__notice">复用缓存内容，不代表本轮重新抓取了当前网页。</p>}
      {snapshot.acquisition === "restored" && <p className="evidence-snapshot__notice">从已留存状态恢复，并非本轮重新抓取。旧检查点可能没有原始提取器元信息。</p>}
      {snapshot.truncated && <p className="evidence-snapshot__warning">文本已截断，仅保留部分内容；未出现不能据此判断原网页没有。</p>}
      {warning && <p className="evidence-snapshot__warning" role="note">{warning}</p>}
      <p className="evidence-snapshot__notice">{highlight ? "引文已在留存文本中精确匹配。" : "留存文本供核对引用。"}文字存在不等于支持该声明。</p>
      <div className="evidence-snapshot__text" tabIndex={0} role="region" aria-label={`${item.source_name}留存文本`}>
        {highlight ? <>{highlight.before}<mark className="evidence-snapshot__quote">{highlight.quote}</mark>{highlight.after}</> : snapshot.text}
      </div>
    </div>
  </details>;
}

// Scroll to the claim card matched by index and briefly highlight it so a user
// coming from an evidence pill sees where they landed. Guarded because the ID
// only exists once ClaimList has rendered.
function jumpToClaim(oneBasedIndex: number) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(`claim-${oneBasedIndex}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("claim-item--flash");
  window.setTimeout(() => el.classList.remove("claim-item--flash"), 1400);
}

export interface EvidenceCardProps {
  item: Evidence;
  snapshots?: EvidenceSnapshot[];
  // Optional accents from claims this evidence backs. Rendered as a small stack
  // of colored vertical bars on the card's left edge so a reader can trace the
  // evidence back to the claim(s) it supports.
  claimAccents?: ClaimAccent[];
  // When true, hides the "支撑核查点 #N" backlink chips. Set inside a claim's
  // own evidence panel — the reader already knows which claim they're in, and
  // the backlink would only offer a self-referential loop.
  hideClaimBacklink?: boolean;
}

export function EvidenceCard({ item, snapshots, claimAccents, hideClaimBacklink = false }: EvidenceCardProps) {
  const tier = getSourceTierMeta(item.source_tier);
  const accents = claimAccents ?? [];
  const showBacklinks = !hideClaimBacklink && accents.length > 0;
  return (
    <div className="evidence-item">
      {accents.length > 0 && (
        <div className="evidence-item__accent-stack" aria-hidden="true">
          {accents.map((a) => (
            <span key={a.index} className="evidence-item__accent" style={{ background: a.color }} />
          ))}
        </div>
      )}
      <div className="evidence-item__source">
        <span>{item.source_name}</span>
        <span className={`tier-pill tier-pill--${tier.tone}`} tabIndex={0}>
          <span className="tier-pill__letter">{tier.tier}</span>
          <span className="tier-pill__label">{tier.shortLabel}</span>
          <span className="tier-pill__popover" role="tooltip">
            <span className="tier-pill__popover-title">{tier.tier} · {tier.label}</span>
            <span className="tier-pill__popover-hint">{tier.hint}</span>
            <span className="tier-pill__popover-source">当前来源：{item.source_name}</span>
          </span>
        </span>
      </div>
      <div className="evidence-item__title">
        <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
      </div>
      <div className="evidence-item__snippet">{item.snippet}</div>
      {item.relevance_reason && (
        <div className="evidence-item__relevance">
          <span className="evidence-item__relevance-label">相关性</span>
          {item.relevance_reason}
        </div>
      )}
      <SnapshotDetails item={item} snapshots={snapshots} />
      {showBacklinks && (
        <div className="evidence-item__backlinks">
          <span className="evidence-item__backlinks-label">支撑核查点</span>
          {accents.map((a) => {
            const claimOrdinal = a.index + 1;
            return (
              <button
                key={a.index}
                type="button"
                className="evidence-item__backlink"
                style={{ borderColor: a.color, color: a.color }}
                onClick={() => jumpToClaim(claimOrdinal)}
                title={`跳转到核查点 #${claimOrdinal}`}
              >
                #{claimOrdinal}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface EvidenceListProps {
  evidence: Evidence[];
  isOpen: boolean;
  onToggle: () => void;
  // When provided, the list precomputes claim-accent stripes so each card can
  // point back at the claim(s) it supports. Kept optional so callers that only
  // render "retrieval hits" (evidence not attached to any claim) can skip it.
  report?: Report | null;
}

export function EvidenceList({ evidence, isOpen, onToggle, report }: EvidenceListProps) {
  if (evidence.length === 0) return null;
  const accentMap = report ? buildEvidenceClaimAccents(report) : null;

  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          证据来源
          <span className="section-card__badge">{evidence.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          {evidence.map((item, i) => (
            <EvidenceCard
              key={`${item.url}-${i}`}
              item={item}
              snapshots={report?.evidence_snapshots}
              claimAccents={accentMap?.get(item.url)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export interface RetrievalHitsListProps {
  hits: Evidence[];
  isOpen: boolean;
  onToggle: () => void;
}

export function RetrievalHitsList({ hits, isOpen, onToggle }: RetrievalHitsListProps) {
  if (hits.length === 0) return null;

  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          检索命中（未被采信）
          <span className="section-card__badge">{hits.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          <div className="section-card__hint">这些是检索到、但没有被任何核查点当作判定证据的结果，仅供参考。</div>
          {hits.map((item, i) => (
            <EvidenceCard key={`${item.url}-${i}`} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
