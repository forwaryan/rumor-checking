import { describe, expect, it, vi } from "vitest";
import { buildRecheckRequest, createRecheckSubmission, describeClaimChange, publicSourceUrl } from "@/lib/recheck";

describe("recheck input", () => {
  it("normalizes selected scope and sources without silently changing the original note", () => {
    expect(buildRecheckRequest([2, 0, 2], "https://example.org/source\n\nhttps://example.org/source", " 补充说明 ", 3, "same-id"))
      .toEqual({ claim_indices: [0, 2], source_urls: ["https://example.org/source"], note: "补充说明", request_id: "same-id" });
    expect(buildRecheckRequest([], "", "", 3, "all").claim_indices).toEqual([]);
  });
  it.each(["javascript:alert(1)", "file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a", "http://2130706433", "http://[::1]", "https://user:password@example.org/", "http://service.internal/"])("rejects private or unsafe sources: %s", (url) => {
    expect(publicSourceUrl(url)).toBeNull();
    expect(() => buildRecheckRequest([], url, "", 1, "id")).toThrow("公开");
  });
  it("rejects excessive sources, invalid scope, and excessive notes", () => {
    expect(() => buildRecheckRequest([], Array(6).fill("https://example.org/").join("\n"), "", 1, "id")).toThrow("5");
    for (const index of [-1, 2, 0.5, NaN]) expect(() => buildRecheckRequest([index], "", "", 2, "id")).toThrow("核查项");
    expect(() => buildRecheckRequest([], "", "字".repeat(2001), 1, "id")).toThrow("2000");
  });
  it("reuses the idempotency key after a failed attempt and rotates it when the payload changes", () => {
    const createId = vi.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
    const submit = createRecheckSubmission(createId);
    expect(submit([1, 0], "https://example.org", "说明", 2).request_id).toBe("first");
    expect(submit([0, 1], "https://example.org/", "说明", 2).request_id).toBe("first");
    expect(submit([0], "https://example.org/", "说明", 2).request_id).toBe("second");
    expect(createId).toHaveBeenCalledTimes(2);
  });
  it("explains unselected claims as not rechecked rather than removed", () => {
    expect(describeClaimChange({ claim: "其他事项", kind: "not_rechecked", before_verdict: "supported", after_verdict: null, added_evidence_urls: [], removed_evidence_urls: [] })).toContain("未复核");
    expect(describeClaimChange({ claim: "事项", kind: "changed", before_verdict: "insufficient", after_verdict: "supported", added_evidence_urls: [], removed_evidence_urls: [] })).toBe("证据不足 → 有证据支持");
  });
});
