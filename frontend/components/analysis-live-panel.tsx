import type { AnalysisLiveEvent, AnalysisStatus } from "@/types/report";

interface AnalysisLivePanelProps {
  status: AnalysisStatus;
  isStreaming: boolean;
  startedAt: string | null;
  events: AnalysisLiveEvent[];
}

interface RenderedLiveItem {
  id: string;
  title: string;
  stageLabel: string;
  status: "running" | "completed" | "warning" | "skipped" | "error";
  summary: string;
  details: string[];
  emittedAt: string;
}

function formatClock(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function getLiveStateLabel(isStreaming: boolean, status: AnalysisStatus, events: AnalysisLiveEvent[]) {
  if (isStreaming) {
    return "实时执行中";
  }
  if (status === "error") {
    return "执行失败";
  }
  if (events.length > 0) {
    return "最近一次执行";
  }
  return "等待运行";
}

function getLiveStateTone(isStreaming: boolean, status: AnalysisStatus, events: AnalysisLiveEvent[]) {
  if (isStreaming) {
    return "pending";
  }
  if (status === "error") {
    return "error";
  }
  if (events.some((event) => event.type === "report")) {
    return "report";
  }
  return "pending";
}

function stageLabel(event: AnalysisLiveEvent) {
  switch (event.type) {
    case "session":
      return "session";
    case "stage":
      return event.stage_key;
    case "api_call":
      return event.stage_key || event.call_type;
    case "retrieval":
      return `${event.stage_key}:${event.query_label}`;
    case "log":
      return event.stage_key || event.level;
    case "report":
      return "report";
    case "error":
      return event.code;
    case "complete":
      return "complete";
    default:
      return "event";
  }
}

function renderStatus(event: AnalysisLiveEvent): RenderedLiveItem["status"] {
  switch (event.type) {
    case "session":
      return "running";
    case "stage":
      return event.status;
    case "api_call":
      return event.status;
    case "retrieval":
      return "completed";
    case "log":
      return event.level === "error" ? "error" : event.level === "warning" ? "warning" : "completed";
    case "report":
      return "completed";
    case "error":
      return "error";
    case "complete":
      return event.success ? "completed" : "error";
    default:
      return "completed";
  }
}

function titleForEvent(event: AnalysisLiveEvent) {
  switch (event.type) {
    case "session":
      return "任务已创建";
    case "stage":
      return event.title;
    case "api_call":
      return event.title;
    case "retrieval":
      return `检索结果 ${event.query_label}`;
    case "log":
      return event.title;
    case "report":
      return "最终 Report 已返回";
    case "error":
      return `错误 ${event.code}`;
    case "complete":
      return event.success ? "任务执行结束" : "任务执行中止";
    default:
      return "执行事件";
  }
}

function summaryForEvent(event: AnalysisLiveEvent) {
  switch (event.type) {
    case "session":
      return event.summary;
    case "stage":
      return event.summary;
    case "api_call":
      return event.summary;
    case "retrieval":
      return `${event.summary} query="${event.query}" provider=${event.provider_name}`;
    case "log":
      return event.summary;
    case "report":
      return event.summary;
    case "error":
      return event.message;
    case "complete":
      return event.summary;
    default:
      return "";
  }
}

function detailsForEvent(event: AnalysisLiveEvent) {
  switch (event.type) {
    case "session":
      return [
        `input_type=${event.input_type}`,
        `trace_id=${event.trace_id}`,
        `preview=${event.preview}`,
      ];
    case "stage":
      return event.details;
    case "api_call":
      return [`call_type=${event.call_type}`, ...event.details];
    case "retrieval":
      return event.details;
    case "log":
      return event.details;
    case "report":
      return [
        `mode=${event.report.mode}`,
        `claim_results=${event.report.claim_results.length}`,
        `timeline_nodes=${event.report.timeline.length}`,
      ];
    case "error":
      return [`status_code=${event.status_code}`, ...event.details];
    case "complete":
      return [`success=${event.success}`];
    default:
      return [];
  }
}

function toRenderedItems(events: AnalysisLiveEvent[]) {
  return events.map((event, index) => ({
    id: `${event.emitted_at}-${index}-${event.type}`,
    title: titleForEvent(event),
    stageLabel: stageLabel(event),
    status: renderStatus(event),
    summary: summaryForEvent(event),
    details: detailsForEvent(event),
    emittedAt: event.emitted_at,
  }));
}

export function AnalysisLivePanel({ status, isStreaming, startedAt, events }: AnalysisLivePanelProps) {
  const renderedItems = toRenderedItems(events);
  const latestItem = renderedItems[renderedItems.length - 1] || null;
  const apiCalls = events.filter((event) => event.type === "api_call").length;
  const retrievalCalls = events.filter((event) => event.type === "retrieval").length;
  const stageCount = new Set(events.filter((event) => event.type === "stage").map((event) => event.stage_key)).size;

  return (
    <section className="panel panel--trace">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Live Trace</p>
          <h2>执行过程直播</h2>
        </div>
        <div className={`trace-live-pill trace-live-pill--${getLiveStateTone(isStreaming, status, events)}`}>
          {getLiveStateLabel(isStreaming, status, events)}
        </div>
      </div>

      <p className="panel-copy">这里会持续显示后端阶段、外部 API 调用、检索命中和最终返回的结构化结果。</p>

      <div className="trace-runbar">
        <div className="trace-meta">
          <span className="trace-meta-pill">阶段 {stageCount}</span>
          <span className="trace-meta-pill">API {apiCalls}</span>
          <span className="trace-meta-pill">检索 {retrievalCalls}</span>
          <span className="trace-meta-pill">事件 {events.length}</span>
        </div>
        <div className="trace-meta">
          <span className="trace-meta-pill">开始 {startedAt ? formatClock(startedAt) : "--:--:--"}</span>
          <span className="trace-meta-pill">更新 {latestItem ? formatClock(latestItem.emittedAt) : "--:--:--"}</span>
        </div>
      </div>

      <div className="trace-overview">
        <span className="eyebrow">Current Focus</span>
        <strong>{latestItem ? latestItem.title : "还没有开始分析"}</strong>
        <p>{latestItem ? latestItem.summary : "点击“开始分析”后，这里会实时显示后端在做什么。"}</p>
      </div>

      {renderedItems.length === 0 ? (
        <p className="empty-state">暂无执行记录。</p>
      ) : (
        <div className="trace-list">
          {renderedItems.map((item, index) => {
            const isCurrent = index === renderedItems.length - 1;
            return (
              <article
                key={item.id}
                className={`trace-step${isCurrent ? " trace-step--current" : ""}${item.status === "running" ? " trace-step--pending" : ""}`}
              >
                <div className={`trace-step__index trace-step__index--${item.status}${isCurrent ? " is-current" : ""}`}>
                  {String(index + 1).padStart(2, "0")}
                </div>
                <div className="trace-step__body">
                  <div className="trace-step__header">
                    <div>
                      <p className="trace-step__stage">{item.stageLabel}</p>
                      <h3>{item.title}</h3>
                    </div>
                    <div className={`trace-status-pill trace-status-pill--${item.status}`}>
                      {formatClock(item.emittedAt)}
                    </div>
                  </div>
                  <p className="trace-step__summary">{item.summary}</p>
                  {item.details.length > 0 ? (
                    <ul className="trace-step__details">
                      {item.details.map((detail, detailIndex) => (
                        <li key={`${item.id}-detail-${detailIndex}`}>
                          <code>{detail}</code>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
