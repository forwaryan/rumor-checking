import { deriveAgentRun } from "@/lib/agent-run";
import type { AgentActionKind, AnalysisLiveEvent } from "@/types/report";

interface AgentRunPanelProps {
  events: AnalysisLiveEvent[];
}

const KIND_LABEL: Record<AgentActionKind, string> = {
  plan: "计划",
  tool_call: "调用工具",
  observation: "观察",
  decision: "决策",
  finalize: "产出",
};

function formatClock(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

// Human-readable extraction of a `key=value` / `key：value` detail line.
function readableDetail(detail: string): string {
  return detail.replace(/^([a-z_]+)[=：]/i, (_, key) => `${key}: `);
}

export function AgentRunPanel({ events }: AgentRunPanelProps) {
  const run = deriveAgentRun(events);

  if (!run.usedAgentOrchestrator) {
    return null;
  }

  const plannerLabel = run.planner === "llm" ? "LLM Planner" : run.planner === "rule" ? "规则 Planner" : "未知";

  return (
    <section className="panel panel--agent">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Agent Investigation</p>
          <h2>调查过程</h2>
        </div>
        <div className={`agent-planner-pill agent-planner-pill--${run.planner ?? "unknown"}`}>{plannerLabel}</div>
      </div>

      <p className="panel-copy">
        这里把本次分析当成一次受控调查来展示：agent 先计划，再调用工具、观察证据、决定要不要继续，最后产出报告。
      </p>

      <div className="agent-runbar">
        <span className="agent-meta-pill">动作 {run.actions.length}</span>
        <span className="agent-meta-pill">补检索轮次 {run.investigationRounds}</span>
        <span className="agent-meta-pill">抓取正文 {run.fetchedPages}</span>
        <span className="agent-meta-pill">Planner {plannerLabel}</span>
      </div>

      {run.actions.length === 0 ? (
        <p className="empty-state">当前没有可展示的调查动作。</p>
      ) : (
        <ol className="agent-action-list">
          {run.actions.map((action, index) => (
            <li
              key={`${action.stageKey}-${index}-${action.emittedAt}`}
              className={`agent-action agent-action--${action.kind} agent-action--${action.status}`}
            >
              <div className="agent-action__rail">
                <span className={`agent-action__kind agent-action__kind--${action.kind}`}>
                  {KIND_LABEL[action.kind]}
                </span>
              </div>
              <div className="agent-action__body">
                <div className="agent-action__header">
                  <h3>{action.title}</h3>
                  <span className={`agent-status-pill agent-status-pill--${action.status}`}>
                    {formatClock(action.emittedAt)}
                  </span>
                </div>
                <p className="agent-action__summary">{action.summary}</p>
                {action.details.length > 0 ? (
                  <ul className="agent-action__details">
                    {action.details.map((detail, detailIndex) => (
                      <li key={`${action.stageKey}-detail-${detailIndex}`}>
                        <code>{readableDetail(detail)}</code>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
