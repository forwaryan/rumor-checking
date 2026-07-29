"use client";

import type { Evidence } from "@/types/report";
import { getSourceTierMeta } from "@/lib/report-utils";

export function EvidenceCard({ item }: { item: Evidence }) {
  const tier = getSourceTierMeta(item.source_tier);
  return (
    <div className="evidence-item">
      <div className="evidence-item__source">
        <span>{item.source_name}</span>
        <span className={`tier-badge tier-badge--${tier.tone}`} title={tier.hint}>
          {tier.label}
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
    </div>
  );
}

export interface EvidenceListProps {
  evidence: Evidence[];
  isOpen: boolean;
  onToggle: () => void;
}

export function EvidenceList({ evidence, isOpen, onToggle }: EvidenceListProps) {
  if (evidence.length === 0) return null;

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
            <EvidenceCard key={`${item.url}-${i}`} item={item} />
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
