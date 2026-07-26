"use client";

import type { AnswerSuggestion, PossibilityItem } from "@/types/report";
import { formatProbability, getBasisLabel } from "@/lib/report-utils";

function getLikelihoodLabel(likelihood: string): string {
  switch (likelihood) {
    case "high": return "可能性高";
    case "medium": return "可能性中";
    default: return "可能性低";
  }
}

export interface PossibleAnswersProps {
  answers: AnswerSuggestion[];
  isOpen: boolean;
  onToggle: () => void;
}

export function PossibleAnswers({ answers, isOpen, onToggle }: PossibleAnswersProps) {
  if (answers.length === 0) return null;

  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          更可能的答案
          <span className="section-card__badge">{answers.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          <div className="section-card__hint">基于当前证据给出的更可能正确的说法，用来纠正被夸大或失真的部分。</div>
          <div className="answer-list">
            {answers.map((item, i) => (
              <div key={`${item.angle}-${i}`} className="answer-item">
                <span className="answer-item__angle">{item.angle}</span>
                <span className="answer-item__text">{item.answer}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export interface PossibilitiesDistributionProps {
  possibilities: PossibilityItem[];
  isOpen: boolean;
  onToggle: () => void;
}

export function PossibilitiesDistribution({ possibilities, isOpen, onToggle }: PossibilitiesDistributionProps) {
  if (possibilities.length === 0) return null;

  // Hide when all scenarios are purely speculative with no evidence backing
  if (possibilities.every(p => p.basis === "prior" || !p.basis)) return null;

  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          可能性分布
          <span className="section-card__badge">{possibilities.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          <div className="possibility-list">
            {possibilities.map((item, i) => {
              const prob = formatProbability(item.probability);
              const basisLabel = getBasisLabel(item.basis);
              const width = typeof item.probability === "number" ? Math.max(0, Math.min(100, item.probability)) : null;
              return (
                <div key={`${item.scenario}-${i}`} className="possibility-item">
                  <div className="possibility-item__head">
                    <span className="possibility-item__scenario">{item.scenario}</span>
                    <span className={`possibility-item__prob possibility-item__prob--${item.likelihood}`}>
                      {prob ?? getLikelihoodLabel(item.likelihood)}
                      {basisLabel ? ` · ${basisLabel}` : ""}
                    </span>
                  </div>
                  {width !== null && (
                    <div className="possibility-item__bar">
                      <div className={`possibility-item__bar-fill possibility-item__bar-fill--${item.likelihood}`} style={{ width: `${width}%` }} />
                    </div>
                  )}
                  {item.summary && <div className="possibility-item__summary">{item.summary}</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
