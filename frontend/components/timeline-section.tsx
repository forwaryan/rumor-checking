"use client";

import type { TimelineNode } from "@/types/report";

interface TimelineSectionProps {
  timeline: TimelineNode[];
  isOpen: boolean;
  onToggle: () => void;
}

export function TimelineSection({ timeline, isOpen, onToggle }: TimelineSectionProps) {
  if (timeline.length === 0) return null;
  return (
    <div className="section-card">
      <div className="section-card__header" onClick={onToggle}>
        <span className="section-card__title">
          传播时间线
          <span className="section-card__badge">{timeline.length}</span>
        </span>
        <span className={`section-card__arrow${isOpen ? " section-card__arrow--open" : ""}`}>&#9660;</span>
      </div>
      {isOpen && (
        <div className="section-card__body">
          <div className="timeline">
            {timeline.map((node, i) => (
              <div key={`${node.url}-${i}`} className={`timeline__node timeline__node--${node.node_type}`}>
                <div className="timeline__node-title">{node.title}</div>
                <div className="timeline__node-meta">{node.source_name} · {node.published_at || "时间未知"}</div>
                <div className="timeline__node-summary">{node.summary}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
