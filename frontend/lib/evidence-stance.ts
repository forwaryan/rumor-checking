import type { Evidence } from "@/types/report";

// Mirror of the DEBUNK markers used in VerdictCard/backend so an evidence card
// whose text explicitly says "辟谣 / 不实 / 官方否认" gets bucketed as refuting.
// This is the FALLBACK heuristic — the backend now tags evidence with `stance`
// when the LLM synthesis produces per-evidence stance entries.
const DEBUNK_MARKERS = [
  "辟谣",
  "否认",
  "不实",
  "不属实",
  "系谣言",
  "实为谣言",
  "造谣",
  "假消息",
  "假新闻",
  "谣言不实",
  "澄清",
];

function containsDebunkMarker(text: string): boolean {
  if (!text) return false;
  return DEBUNK_MARKERS.some((m) => text.includes(m));
}

function looksLikeRefutation(ev: Evidence): boolean {
  const haystack = `${ev.title ?? ""} ${ev.snippet ?? ""} ${ev.relevance_reason ?? ""}`;
  return containsDebunkMarker(haystack);
}

export interface SplitEvidence {
  supporting: Evidence[];
  refuting: Evidence[];
}

export function splitEvidenceByStance(evidence: Evidence[]): SplitEvidence {
  const supporting: Evidence[] = [];
  const refuting: Evidence[] = [];
  for (const ev of evidence) {
    // Prefer backend stance when available
    if (ev.stance === "refutes") {
      refuting.push(ev);
    } else if (ev.stance === "supports") {
      supporting.push(ev);
    } else if (ev.stance) {
      // ambiguous/irrelevant — default to supporting bucket for display
      supporting.push(ev);
    } else {
      // No backend stance — fall back to keyword heuristic
      if (looksLikeRefutation(ev)) {
        refuting.push(ev);
      } else {
        supporting.push(ev);
      }
    }
  }
  return { supporting, refuting };
}
