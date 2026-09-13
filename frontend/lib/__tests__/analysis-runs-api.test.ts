import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createAnalysisRun,
  getAnalysisRun,
  parseAnalysisRun,
  parseAnalysisRunEvent,
  resumeAnalysisRun,
  streamAnalysisRunEvents,
} from "@/lib/api-client";

const runId = "a".repeat(32);
const snapshot = {
  run_id: runId, status: "running", mode: "deep", last_event_id: 2,
  created_at: "2026-09-13T00:00:00Z", updated_at: "2026-09-13T00:00:00Z",
  input_preview: "待核查", raw_input: "待核查的问题", report: null, error: null, resumable: false,
};

afterEach(() => { vi.unstubAllGlobals(); });

describe("analysis run API", () => {
  it("uses the create, read and explicit resume routes", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => Response.json(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    const request = { raw_input: "private input", input_type: "auto" as const };
    await createAnalysisRun(request);
    const controller = new AbortController();
    await getAnalysisRun(runId, controller.signal);
    await resumeAnalysisRun(runId);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/analysis-runs");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify(request) });
    expect(fetchMock.mock.calls[1][0]).toBe(`/api/v1/analysis-runs/${runId}`);
    expect(fetchMock.mock.calls[1][1].signal).toBe(controller.signal);
    expect(fetchMock.mock.calls[2][0]).toBe(`/api/v1/analysis-runs/${runId}/resume`);
    expect(fetchMock.mock.calls[2][1].method).toBe("POST");
  });

  it("rejects malformed ids and hides raw server failures", async () => {
    expect(() => parseAnalysisRun({ ...snapshot, run_id: "../secret" })).toThrow("任务响应格式无效");
    expect(() => getAnalysisRun("../secret")).toThrow("任务编号无效");
    expect(() => resumeAnalysisRun("../secret")).toThrow("任务编号无效");
    expect(parseAnalysisRun({ ...snapshot, status: "failed", error: "secret credentials" }).error).not.toContain("secret");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private traceback", { status: 500 })));
    await expect(getAnalysisRun(runId)).rejects.toThrow("暂时无法读取核查任务");
  });

  it("retains the full original input separately from the shortened preview", () => {
    const rawInput = "需要完整核查的原始问题。".repeat(30);
    const parsed = parseAnalysisRun({ ...snapshot, raw_input: rawInput, input_preview: rawInput.slice(0, 140) });
    expect(parsed.raw_input).toBe(rawInput);
    expect(parsed.raw_input.length).toBeGreaterThan(parsed.input_preview.length);
  });

  it("parses event envelopes and permits future event types without losing the cursor", () => {
    expect(parseAnalysisRunEvent({ type: "heartbeat" })).toBeNull();
    expect(parseAnalysisRunEvent({ event_id: 4, event: { type: "future" } })).toEqual({ event_id: 4, event: null });
    expect(parseAnalysisRunEvent({ event_id: 5, event: { type: "error", message: "private traceback", details: ["secret"] } })?.event).toMatchObject({
      message: "此次核查未能完成。", details: [],
    });
    expect(() => parseAnalysisRunEvent({ event_id: 0, event: { type: "complete" } })).toThrow("事件格式无效");
    expect(() => parseAnalysisRunEvent({ event_id: 1.5, event: {} })).toThrow("事件格式无效");
  });

  it("reads split UTF-8, heartbeat and trailing envelopes with a GET cursor", async () => {
    const text = [
      JSON.stringify({ type: "heartbeat" }),
      JSON.stringify({ event_id: 3, event: { type: "stage", title: "核查中", status: "running" } }),
      JSON.stringify({ event_id: 4, event: { type: "complete", success: true } }),
    ].join("\n");
    const bytes = new TextEncoder().encode(text);
    const response = new Response(new ReadableStream({
      start(controller) {
        for (let index = 0; index < bytes.length; index += 5) controller.enqueue(bytes.slice(index, index + 5));
        controller.close();
      },
    }));
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetchMock);
    const onEvent = vi.fn();
    await streamAnalysisRunEvents(runId, 2, onEvent, new AbortController().signal);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/analysis-runs/${runId}/events?after=2`);
    expect(fetchMock.mock.calls[0][1].method).toBeUndefined();
    expect(onEvent).toHaveBeenNthCalledWith(1, 3, expect.objectContaining({ title: "核查中" }));
    expect(onEvent).toHaveBeenNthCalledWith(2, 4, expect.objectContaining({ type: "complete", success: true }));
  });

  it("cancels a pending read when the subscription is aborted", async () => {
    const cancel = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel })));
    vi.stubGlobal("fetch", fetchMock);
    const onEvent = vi.fn();
    const controller = new AbortController();
    const stream = streamAnalysisRunEvents(runId, 0, onEvent, controller.signal);
    const aborted = expect(stream).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    controller.abort();
    await aborted;
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(onEvent).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
