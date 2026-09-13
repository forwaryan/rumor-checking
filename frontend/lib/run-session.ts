import {
  ApiClientError,
  createAnalysisRun,
  getAnalysisRun,
  resumeAnalysisRun,
  streamAnalysisRunEvents,
} from "@/lib/api-client";
import type { AnalysisLiveEvent, AnalysisRun, AnalyzeRequest, Report } from "@/types/report";

export type RunTarget = { runId: string } | { request: AnalyzeRequest };
type RunObserver = {
  onRun: (run: AnalysisRun) => void;
  onEvent: (event: AnalysisLiveEvent) => void;
};

export function buildAnalysisRequest(
  rawInput: string,
  mode: "fast" | "deep",
  options: { model?: string; searchSources?: string[] } = {},
): AnalyzeRequest {
  return {
    raw_input: rawInput,
    input_type: "auto",
    request_context: {
      mode,
      ...(mode === "deep" && options.model ? { model: options.model } : {}),
      ...(options.searchSources?.length ? { search_sources: options.searchSources } : {}),
    },
  };
}

export function selectRunTarget(search: string): RunTarget | null {
  const params = new URLSearchParams(search);
  const runId = params.get("run")?.trim();
  if (runId) return { runId };
  const query = params.get("q")?.trim();
  if (!query) return null;
  const mode = params.get("mode") === "deep" ? "deep" : "fast";
  const model = params.get("model")?.trim();
  return { request: buildAnalysisRequest(query, mode, { model }) };
}

export function runLocation(pathname: string, runId?: string): string {
  return runId ? `${pathname}?${new URLSearchParams({ run: runId })}` : pathname;
}

export function waitForReconnect(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, delay);
    const cancel = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", cancel);
      reject(signal.reason);
    };
    signal.addEventListener("abort", cancel, { once: true });
  });
}

const defaultDependencies = {
  create: createAnalysisRun,
  get: getAnalysisRun,
  resume: resumeAnalysisRun,
  stream: streamAnalysisRunEvents,
  wait: waitForReconnect,
};

export function createRunSession(target: RunTarget, dependencies = defaultDependencies) {
  let creation: Promise<AnalysisRun> | undefined;
  let resumption: Promise<AnalysisRun> | undefined;
  let runId = "runId" in target ? target.runId : "";
  let cursor = 0;
  let subscription = 0;
  let receivedReport: Report | null = null;

  return {
    async watch(observer: RunObserver, signal: AbortSignal, resume = false): Promise<AnalysisRun> {
      const currentSubscription = ++subscription;
      const assertCurrent = () => {
        signal.throwIfAborted();
        if (currentSubscription !== subscription) throw new DOMException("Subscription replaced", "AbortError");
      };
      assertCurrent();
      let run: AnalysisRun;
      if (resume && runId) {
        resumption ??= dependencies.resume(runId).finally(() => { resumption = undefined; });
        run = await resumption;
      } else if ("request" in target && !runId) {
        creation ??= dependencies.create(target.request);
        run = await creation;
      } else {
        run = await dependencies.get(runId, signal);
      }
      assertCurrent();
      runId = run.run_id;
      observer.onRun(run);
      for (let attempt = 0; attempt <= 3; attempt++) {
        assertCurrent();
        if (run.status === "failed" || run.status === "interrupted") return run;
        if (run.status === "completed" && run.report) return run;
        try {
          await dependencies.stream(runId, cursor, (eventId, event) => {
            assertCurrent();
            if (eventId <= cursor) return;
            if (eventId !== cursor + 1) throw new ApiClientError("核查事件序号不连续，正在重新连接。");
            cursor = eventId;
            if (event?.type === "report") receivedReport = event.report;
            if (event) observer.onEvent(event);
          }, signal);
        } catch (error) {
          assertCurrent();
          if (error instanceof ApiClientError && error.status && error.status >= 400 && error.status < 500) throw error;
        }
        assertCurrent();
        try {
          run = await dependencies.get(runId, signal);
          assertCurrent();
          if (run.status === "completed" && !run.report && receivedReport) run = { ...run, report: receivedReport };
          observer.onRun(run);
          if (run.status === "failed" || run.status === "interrupted" || (run.status === "completed" && run.report)) return run;
        } catch (error) {
          assertCurrent();
          if (error instanceof ApiClientError && error.status && error.status >= 400 && error.status < 500) throw error;
        }
        if (attempt < 3) await dependencies.wait(400 * 2 ** attempt, signal);
      }
      throw new ApiClientError("暂时无法连接核查任务。任务编号已保留，可重新连接查看进度。");
    },
  };
}

export type RunSession = ReturnType<typeof createRunSession>;
