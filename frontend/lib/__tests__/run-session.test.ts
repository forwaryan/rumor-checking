import { describe, expect, it, vi } from "vitest";
import { buildAnalysisRequest, createRunSession, runLocation, selectRunTarget, waitForReconnect } from "@/lib/run-session";
import { parseReport } from "@/lib/api-client";
import type { AnalysisLiveEvent, AnalysisRun } from "@/types/report";

const runId = "a".repeat(32);
const request = { raw_input: "待核查的问题", input_type: "auto" as const };
const report = parseReport({ mode: "safe_mode", claim_results: [{ claim: "待核查", verdict: "insufficient" }] });
const completed = { type: "complete", run_id: runId, success: true, summary: "完成", emitted_at: "2026-09-13T00:00:00Z" } satisfies AnalysisLiveEvent;

function run(status: AnalysisRun["status"] = "running"): AnalysisRun {
  return {
    run_id: runId, status, mode: "deep", last_event_id: 0,
    created_at: "2026-09-13T00:00:00Z", updated_at: "2026-09-13T00:00:00Z",
    input_preview: "待核查", raw_input: request.raw_input, report: status === "completed" ? report : null,
    error: null, resumable: status === "interrupted",
  };
}

function dependencies() {
  return {
    create: vi.fn().mockResolvedValue(run()),
    get: vi.fn().mockResolvedValue(run("completed")),
    resume: vi.fn().mockResolvedValue(run()),
    stream: vi.fn().mockResolvedValue(undefined),
    wait: vi.fn().mockResolvedValue(undefined),
  };
}

function observer() {
  return { onRun: vi.fn(), onEvent: vi.fn() };
}

describe("analysis run session", () => {
  it("prefers the run URL and never includes raw input in persisted locations", () => {
    expect(selectRunTarget(`?q=private&run=${runId}`)).toEqual({ runId });
    expect(selectRunTarget("?q=待核查&mode=deep&model=selected")).toEqual({
      request: { raw_input: "待核查", input_type: "auto", request_context: { mode: "deep", model: "selected" } },
    });
    expect(selectRunTarget("?q=%20")).toBeNull();
    expect(runLocation("/analyze", runId)).toBe(`/analyze?run=${runId}`);
    expect(runLocation("/analyze")).toBe("/analyze");
  });

  it("creates only once across effect cleanup and reattachment", async () => {
    const api = dependencies();
    let resolveCreation!: (value: AnalysisRun) => void;
    api.create.mockImplementation(() => new Promise<AnalysisRun>((resolve) => { resolveCreation = resolve; }));
    const session = createRunSession({ request }, api);
    const firstController = new AbortController();
    const stale = observer();
    const first = session.watch(stale, firstController.signal);
    const aborted = expect(first).rejects.toMatchObject({ name: "AbortError" });
    firstController.abort();
    const current = observer();
    const second = session.watch(current, new AbortController().signal);
    resolveCreation(run());
    await aborted;
    expect(await second).toMatchObject({ status: "completed" });
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(stale.onRun).not.toHaveBeenCalled();
    expect(current.onRun).toHaveBeenCalled();
  });

  it("reconnects using the accepted cursor and drops duplicate events", async () => {
    const api = dependencies();
    api.get.mockResolvedValueOnce(run()).mockResolvedValueOnce(run("completed"));
    api.stream.mockImplementationOnce(async (_id, _after, emit) => {
      emit(1, completed);
      throw new TypeError("network lost");
    }).mockImplementationOnce(async (_id, _after, emit) => {
      emit(1, completed);
      emit(2, null);
      emit(3, completed);
    });
    const seen = observer();
    const result = await createRunSession({ request }, api).watch(seen, new AbortController().signal);
    expect(result.status).toBe("completed");
    expect(api.stream.mock.calls.map((call) => call[1])).toEqual([0, 1]);
    expect(seen.onEvent).toHaveBeenCalledTimes(2);
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.resume).not.toHaveBeenCalled();
  });

  it("keeps the cursor before a sequence gap and rereads the missing report", async () => {
    const api = dependencies();
    api.get.mockResolvedValueOnce(run()).mockResolvedValueOnce(run("completed"));
    const reportEvent = { type: "report", report, run_id: runId, emitted_at: "", summary: "" } satisfies AnalysisLiveEvent;
    api.stream.mockImplementationOnce(async (_id, _after, emit) => {
      emit(1, null);
      emit(3, completed);
    }).mockImplementationOnce(async (_id, _after, emit) => {
      emit(2, reportEvent);
      emit(3, completed);
    });
    const seen = observer();
    const result = await createRunSession({ request }, api).watch(seen, new AbortController().signal);
    expect(result.status).toBe("completed");
    expect(api.stream.mock.calls.map((call) => call[1])).toEqual([0, 1]);
    expect(seen.onEvent.mock.calls.map((call) => call[0].type)).toEqual(["report", "complete"]);
    expect(api.create).toHaveBeenCalledTimes(1);
  });

  it("restores a completed insufficient-evidence report without creating or streaming", async () => {
    const api = dependencies();
    const result = await createRunSession({ runId }, api).watch(observer(), new AbortController().signal);
    expect(result.report?.claim_results[0].verdict).toBe("insufficient");
    expect(result.status).toBe("completed");
    expect(api.create).not.toHaveBeenCalled();
    expect(api.stream).not.toHaveBeenCalled();
  });

  it("uses the complete restored question for a new deep run after refreshing a fast report", async () => {
    const api = dependencies();
    const rawInput = "这是一段超过预览长度、必须完整保留的问题。".repeat(20);
    api.get.mockResolvedValueOnce({ ...run("completed"), mode: "fast", raw_input: rawInput, input_preview: rawInput.slice(0, 140) });
    const restored = await createRunSession({ runId }, api).watch(observer(), new AbortController().signal);
    expect(restored.raw_input.length).toBeGreaterThan(140);
    expect(restored.mode).toBe("fast");
    const deepRequest = buildAnalysisRequest(restored.raw_input, "deep", { model: "selected", searchSources: ["official"] });
    await createRunSession({ request: deepRequest }, api).watch(observer(), new AbortController().signal);
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.create).toHaveBeenCalledWith({
      raw_input: rawInput,
      input_type: "auto",
      request_context: { mode: "deep", model: "selected", search_sources: ["official"] },
    });
    expect(runLocation("/", restored.run_id)).not.toContain(rawInput);
  });

  it("replays a completed run from zero when the snapshot has no report", async () => {
    const api = dependencies();
    api.get.mockResolvedValue({ ...run("completed"), report: null, last_event_id: 2 });
    api.stream.mockImplementation(async (_id, _after, emit) => {
      emit(1, { type: "report", report, run_id: runId, emitted_at: "", summary: "" });
      emit(2, completed);
    });
    const result = await createRunSession({ runId }, api).watch(observer(), new AbortController().signal);
    expect(result.report).toBe(report);
    expect(api.stream.mock.calls[0][1]).toBe(0);
  });

  it.each(["failed", "interrupted"] as const)("does not restart a %s run", async (status) => {
    const api = dependencies();
    api.get.mockResolvedValue(run(status));
    const result = await createRunSession({ runId }, api).watch(observer(), new AbortController().signal);
    expect(result.status).toBe(status);
    expect(api.create).not.toHaveBeenCalled();
    expect(api.resume).not.toHaveBeenCalled();
    expect(api.stream).not.toHaveBeenCalled();
  });

  it("resumes only on an explicit action and retains the same run id", async () => {
    const api = dependencies();
    api.get.mockResolvedValueOnce(run("interrupted")).mockResolvedValueOnce(run("completed"));
    const session = createRunSession({ runId }, api);
    await session.watch(observer(), new AbortController().signal);
    const result = await session.watch(observer(), new AbortController().signal, true);
    expect(result.run_id).toBe(runId);
    expect(api.resume).toHaveBeenCalledTimes(1);
    expect(api.resume).toHaveBeenCalledWith(runId);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("bounds reconnect attempts and permits reconnecting later without a new run", async () => {
    const api = dependencies();
    api.get.mockResolvedValue(run());
    api.stream.mockRejectedValue(new TypeError("offline"));
    const session = createRunSession({ runId }, api);
    await expect(session.watch(observer(), new AbortController().signal)).rejects.toThrow("任务编号已保留");
    expect(api.stream).toHaveBeenCalledTimes(4);
    expect(api.wait).toHaveBeenCalledTimes(3);
    api.get.mockResolvedValue(run("completed"));
    expect((await session.watch(observer(), new AbortController().signal)).status).toBe("completed");
    expect(api.create).not.toHaveBeenCalled();
  });

  it("isolates callbacks after an old subscription is aborted", async () => {
    const api = dependencies();
    let emitOld!: (eventId: number, event: AnalysisLiveEvent) => void;
    let finishOld!: () => void;
    api.stream.mockImplementationOnce((_id, _after, emit) => new Promise<void>((resolve) => {
      emitOld = emit;
      finishOld = resolve;
    }));
    const session = createRunSession({ request }, api);
    const stale = observer();
    const controller = new AbortController();
    const oldWatch = session.watch(stale, controller.signal);
    const aborted = expect(oldWatch).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(api.stream).toHaveBeenCalledTimes(1));
    controller.abort();
    const current = observer();
    await session.watch(current, new AbortController().signal);
    expect(() => emitOld(1, completed)).toThrow();
    finishOld();
    await aborted;
    expect(stale.onEvent).not.toHaveBeenCalled();
    expect(current.onRun).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  });
});

describe("reconnect delay cancellation", () => {
  it("does not register timers or listeners for an already-aborted signal", async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      controller.abort();
      const addListener = vi.spyOn(controller.signal, "addEventListener");
      await expect(waitForReconnect(400, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
      expect(vi.getTimerCount()).toBe(0);
      expect(addListener).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears both the timer and the listener when aborted during the delay", async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      const removeListener = vi.spyOn(controller.signal, "removeEventListener");
      const waiting = waitForReconnect(400, controller.signal);
      const aborted = expect(waiting).rejects.toMatchObject({ name: "AbortError" });
      expect(vi.getTimerCount()).toBe(1);
      controller.abort();
      await aborted;
      expect(vi.getTimerCount()).toBe(0);
      expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
    } finally {
      vi.useRealTimers();
    }
  });

  it("removes the abort listener after a successful delay", async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      const removeListener = vi.spyOn(controller.signal, "removeEventListener");
      const waiting = waitForReconnect(400, controller.signal);
      await vi.advanceTimersByTimeAsync(400);
      await waiting;
      expect(vi.getTimerCount()).toBe(0);
      expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
    } finally {
      vi.useRealTimers();
    }
  });
});
