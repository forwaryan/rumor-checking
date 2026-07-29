"use client";

import type { ClaimResult, Evidence } from "@/types/report";
import { getVerdictLabel, formatConfidence, formatProbability, getBasisLabel } from "@/lib/report-utils";
import { getClaimAccent, type ClaimAccent } from "@/lib/claim-accent";
import { splitEvidenceByStance } from "@/lib/evidence-stance";
import { EvidenceCard } from "@/components/evidence-list";

export interface ClaimListProps {
  claims: ClaimResult[];
  isOpen: boolean;
  onToggle: () => void;
}

// Only for `conflicting` claims: render evidence as two side-by-side columns —
// support on the left, rebuttal on the right — so the reader can see the
// disagreement at a glance instead of scanning a flat list where refuting
// snippets are visually identical to supporting ones. Non-conflicting claims
// keep the single-column layout because the split adds no signal there.
function ConflictEvidenceGrid({ evidence, accent }: { evidence: Evidence[]; accent: ClaimAccent }) {
  const { supporting, refuting } = splitEvidenceByStance(evidence);
  return (
    <div className="conflict-grid">
      <div className="conflict-grid__col conflict-grid__col--supports">
        <div className="conflict-grid__title">支持 · {supporting.length}</div>
        {supporting.length === 0 && <div className="conflict-grid__empty">当前没有明显支持证据。</div>}
        {supporting.map((ev, j) => (
          <EvidenceCard key={`s-${ev.url}-${j}`} item={ev} claimAccents={[accent]} hideClaimBacklink />
        ))}
      </div>
      <div className="conflict-grid__col conflict-grid__col--refutes">
        <div className="conflict-grid__title">反驳 · {refuting.length}</div>
        {refuting.length === 0 && <div className="conflict-grid__empty">当前没有明显反驳证据。</div>}
        {refuting.map((ev, j) => (
          <EvidenceCard key={`r-${ev.url}-${j}`} item={ev} claimAccents={[accent]} hideClaimBacklink />
        ))}
      </div>
    </div>
  );
}

export function ClaimList({ claims, isOpen, onToggle }: ClaimListProps) {
  if (claims.length === 0) return null;

  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          逐条核查
          <span className="section-card__badge">{claims.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          <div className="claim-list">
            {claims.map((claim, i) => {
              const prob = formatProbability(claim.truth_probability);
              const basisLabel = getBasisLabel(claim.probability_basis);
              const accent = getClaimAccent(i);
              const useConflictGrid = claim.verdict === "conflicting" && claim.evidence.length > 1;
              return (
              <div
                key={`${claim.claim}-${i}`}
                id={`claim-${i + 1}`}
                className={`claim-item claim-item--${claim.verdict}`}
                style={{ boxShadow: `inset 0 3px 0 0 ${accent.color}` }}
              >
                <div className="claim-item__text">
                  <span
                    className="claim-item__chip"
                    style={{ background: accent.color }}
                    aria-label={`断言 ${i + 1}`}
                    title={`断言 ${i + 1}`}
                  >
                    {i + 1}
                  </span>
                  {claim.claim}
                </div>
                <div className="claim-item__tags">
                  <span className={`claim-item__verdict claim-item__verdict--${claim.verdict}`}>
                    {getVerdictLabel(claim.verdict)} · {formatConfidence(claim.confidence)}
                  </span>
                  {prob && (
                    <span className="claim-item__prob" title={claim.probability_basis === "prior" ? "无直接检索证据，基于先验估计" : "基于检索证据的估计"}>
                      为真 {prob}{basisLabel ? ` · ${basisLabel}` : ""}
                    </span>
                  )}
                </div>
                {claim.notes && <div className="claim-item__notes">{claim.notes}</div>}
                {claim.evidence.length > 0 && (
                  <details className="claim-item__evidence">
                    <summary className="claim-item__evidence-summary">
                      判定依据 · {claim.evidence.length} 条{useConflictGrid ? " · 分栏对比" : ""}
                    </summary>
                    <div className="claim-item__evidence-body">
                      {useConflictGrid ? (
                        <ConflictEvidenceGrid evidence={claim.evidence} accent={accent} />
                      ) : (
                        claim.evidence.map((ev, j) => (
                          <EvidenceCard key={`${ev.url}-${j}`} item={ev} claimAccents={[accent]} hideClaimBacklink />
                        ))
                      )}
                    </div>
                  </details>
                )}
                {claim.correction && (
                  <div className="claim-item__correction">
                    <span className="claim-item__correction-label">纠正</span>
                    <table className="correction-table">
                      <tbody>
                        <tr>
                          <td className="correction-table__key">原文说</td>
                          <td className="correction-table__val correction-table__val--original">{claim.correction.original}</td>
                        </tr>
                        <tr>
                          <td className="correction-table__key">实际是</td>
                          <td className="correction-table__val correction-table__val--actual">{claim.correction.actual}</td>
                        </tr>
                        {claim.correction.source && (
                          <tr>
                            <td className="correction-table__key">依据</td>
                            <td className="correction-table__val correction-table__val--source">{claim.correction.source}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
