"use client";

import type { Evidence, Report } from "@/types/report";
import { getSourceTierMeta } from "@/lib/report-utils";
import { buildEvidenceClaimAccents, type ClaimAccent } from "@/lib/claim-accent";

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
  // Optional accents from claims this evidence backs. Rendered as a small stack
  // of colored vertical bars on the card's left edge so a reader can trace the
  // evidence back to the claim(s) it supports.
  claimAccents?: ClaimAccent[];
  // When true, hides the "支撑核查点 #N" backlink chips. Set inside a claim's
  // own evidence panel — the reader already knows which claim they're in, and
  // the backlink would only offer a self-referential loop.
  hideClaimBacklink?: boolean;
}

export function EvidenceCard({ item, claimAccents, hideClaimBacklink = false }: EvidenceCardProps) {
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
