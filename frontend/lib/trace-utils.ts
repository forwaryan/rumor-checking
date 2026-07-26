/**
 * Utility functions for the execution trace timeline component.
 * These are only used by trace-timeline.tsx.
 */

export interface ParsedClaim {
  claim: string;
  verdict: string;
}

/** Extract model name from title like "调用 Agent synthesis (model=xxx)" */
export function extractModelFromTitle(title: string): string | null {
  const match = title.match(/\(model=([^)]+)\)/);
  return match ? match[1] : null;
}

/** Rough token estimate: for Chinese text ~1 token per char, for mixed divide by 4 */
export function estimateTokens(text: string | null): number | null {
  if (!text) return null;
  // Chinese characters are roughly 1-2 tokens each; ASCII ~4 chars per token.
  // Use a blended heuristic: chars / 4 gives a rough token count.
  return Math.ceil(text.length / 4);
}

/** Status label for LLM call badge */
export function getLlmStatusLabel(status: string): string {
  switch (status) {
    case "completed": return "completed";
    case "warning": return "warning";
    case "error": return "error";
    default: return "running";
  }
}

/** Try to parse the response text as a JSON object containing a claims array */
export function tryParseClaims(text: string | null): ParsedClaim[] | null {
  if (!text) return null;
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.claims) && parsed.claims.length > 0) {
      return parsed.claims
        .filter((c: unknown) => c && typeof c === "object" && typeof (c as Record<string, unknown>).claim === "string")
        .map((c: Record<string, unknown>) => ({
          claim: String(c.claim),
          verdict: typeof c.verdict === "string" ? c.verdict : "unknown",
        }));
    }
  } catch {
    // not valid JSON
  }
  return null;
}
