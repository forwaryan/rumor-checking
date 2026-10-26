"use client";

import type { TimelineNode } from "@/types/report";
import { SectionHeader } from "@/components/section-header";

interface TimelineSectionProps {
  timeline: TimelineNode[];
  isOpen: boolean;
  onToggle: () => void;
}

function formatPublishedAt(iso: string): string {
  if (!iso) return "时间未知";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const y = parsed.getFullYear();
  const m = String(parsed.getMonth() + 1).padStart(2, "0");
  const d = String(parsed.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function TimelineSection({ timeline, isOpen, onToggle }: TimelineSectionProps) {
  if (timeline.length === 0) return null;
  return (
    <div className="section-card">
      <SectionHeader title="传播时间线" count={timeline.length} id="timeline-section" isOpen={isOpen} onToggle={onToggle} />
      <div id="timeline-section" className="section-card__body" hidden={!isOpen}>
        {isOpen && (
          <div className="timeline">
            {timeline.map((node, i) => (
              <div key={`${node.url}-${i}`} className={`timeline__node timeline__node--${node.node_type}`}>
                <div className="timeline__node-title">
                  {node.url ? (
                    <a href={node.url} target="_blank" rel="noreferrer">{node.title}</a>
                  ) : (
                    node.title
                  )}
                </div>
                <div className="timeline__node-meta">{node.source_name} · {formatPublishedAt(node.published_at)}</div>
                <div className="timeline__node-summary">{node.summary}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
