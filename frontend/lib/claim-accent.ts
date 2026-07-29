import type { ClaimResult, Report } from "@/types/report";

// A hand-picked palette of accent colors used to visually link a claim to the
// evidence cards that back it. Colors intentionally avoid the reds/greens
// already spent on verdict tone so the accent reads as identity, not judgment.
// Kept short: rotating past ~8 claims would make the pattern noisy anyway; a
// wrap-around is safer than adding more low-contrast colors.
const CLAIM_ACCENTS = [
  "#5b8def",
  "#8b5cf6",
  "#0ea5a5",
  "#f97316",
  "#ec4899",
  "#eab308",
  "#14b8a6",
  "#a855f7",
] as const;

export interface ClaimAccent {
  color: string;
  index: number;
}

export function getClaimAccent(index: number): ClaimAccent {
  const safeIndex = ((index % CLAIM_ACCENTS.length) + CLAIM_ACCENTS.length) % CLAIM_ACCENTS.length;
  return { color: CLAIM_ACCENTS[safeIndex], index: safeIndex };
}

// Build a lookup so the top-level EvidenceList can draw the same accent stripe
// as ClaimList for cards that back at least one claim. A single evidence may be
// cited by multiple claims — we keep every accent so the card renders a stack
// of stripes rather than picking one arbitrarily.
export function buildEvidenceClaimAccents(report: Report): Map<string, ClaimAccent[]> {
  const map = new Map<string, ClaimAccent[]>();
  report.claim_results.forEach((claim: ClaimResult, i: number) => {
    const accent = getClaimAccent(i);
    for (const ev of claim.evidence) {
      if (!ev.url) continue;
      const bucket = map.get(ev.url) ?? [];
      // Guard against the same claim being listed twice against one evidence
      // (belt-and-braces — the backend usually dedupes, but this keeps the
      // stripe stack from looking accidentally thicker for one claim).
      if (!bucket.some((a) => a.index === accent.index)) {
        bucket.push(accent);
      }
      map.set(ev.url, bucket);
    }
  });
  return map;
}
