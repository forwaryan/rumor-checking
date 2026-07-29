"use client";

import type { ClaimResult } from "@/types/report";
import { getVerdictLabel, formatConfidence, formatProbability, getBasisLabel } from "@/lib/report-utils";
import { EvidenceCard } from "@/components/evidence-list";

export interface ClaimListProps {
  claims: ClaimResult[];
  isOpen: boolean;
  onToggle: () => void;
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
              return (
              <div key={`${claim.claim}-${i}`} className={`claim-item claim-item--${claim.verdict}`}>
                <div className="claim-item__text">{claim.claim}</div>
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
                      判定依据 · {claim.evidence.length} 条
                    </summary>
                    <div className="claim-item__evidence-body">
                      {claim.evidence.map((ev, j) => (
                        <EvidenceCard key={`${ev.url}-${j}`} item={ev} />
                      ))}
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
