import { describe, expect, it } from "vitest";
import { getOverallVerdict } from "@/components/verdict-card";
import type { Report } from "@/types/report";

function reportFor(verdicts: Array<"supported" | "insufficient" | "refuted">, label?: Report["overall_credibility_label"]): Report {
  return {
    claim_results: verdicts.map((verdict, index) => ({
      claim: index === 0 ? "京东近期大规模裁员。" : "互联网行业近年来发生过裁员。",
      claim_type: "fact" as const,
      verdict,
      confidence: "low" as const,
      evidence: [],
      notes: "",
    })),
    overall_credibility_label: label,
  } as unknown as Report;
}

describe("overall verdict headline", () => {
  it("keeps the original claim unresolved when only context is supported", () => {
    expect(getOverallVerdict(reportFor(["insufficient", "supported"], "insufficient_evidence"))).toBe("insufficient");
  });

  it("keeps direct support and refutation decisive", () => {
    expect(getOverallVerdict(reportFor(["supported", "insufficient"]))).toBe("supported");
    expect(getOverallVerdict(reportFor(["refuted", "insufficient"]))).toBe("refuted");
  });
});
