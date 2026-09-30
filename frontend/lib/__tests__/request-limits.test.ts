import { afterEach, describe, expect, it, vi } from "vitest";
import { analysisInputError, MAX_ANALYSIS_INPUT_CHARACTERS, MAX_REQUEST_BODY_BYTES, requestBodyHeaderStatus } from "@/lib/request-limits";
import { analyzeReportStream, createAnalysisRun } from "@/lib/api-client";

afterEach(() => { vi.unstubAllGlobals(); });

describe("analysis input limits", () => {
  it("rejects oversized declared bodies before the rewrite proxy", () => {
    expect(requestBodyHeaderStatus(null)).toBeNull();
    expect(requestBodyHeaderStatus(String(MAX_REQUEST_BODY_BYTES))).toBeNull();
    expect(requestBodyHeaderStatus(String(MAX_REQUEST_BODY_BYTES + 1))).toBe(413);
    expect(requestBodyHeaderStatus("9".repeat(100))).toBe(413);
    expect(requestBodyHeaderStatus("-1")).toBe(400);
    expect(requestBodyHeaderStatus("invalid")).toBe(400);
  });

  it("counts Unicode characters, not UTF-16 code units", () => {
    expect(analysisInputError("😀".repeat(MAX_ANALYSIS_INPUT_CHARACTERS))).toBeNull();
    expect(analysisInputError("字".repeat(MAX_ANALYSIS_INPUT_CHARACTERS + 1))).toContain("100,000");
  });

  it("rejects oversized input before either API sends a request", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const request = { raw_input: "x".repeat(MAX_ANALYSIS_INPUT_CHARACTERS + 1), input_type: "text" as const };
    await expect(createAnalysisRun(request)).rejects.toThrow("输入最多");
    await expect(analyzeReportStream(request, () => {})).rejects.toThrow("输入最多");
    expect(fetch).not.toHaveBeenCalled();
  });
});
