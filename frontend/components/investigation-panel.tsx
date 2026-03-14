import type { Investigation, Report } from "@/types/report";

interface InvestigationPanelProps {
  report: Report | null;
}

const likelihoodLabel = {
  high: "高可能",
  medium: "中等可能",
  low: "低可能",
} as const;

function buildFallbackInvestigation(report: Report): Investigation {
  const decisiveClaim = report.claim_results.find((item) => item.verdict !== "insufficient");
  const decisiveCount = report.claim_results.filter((item) => item.verdict !== "insufficient").length;
  const verdictSummary = report.claim_results.length
    ? `当前共拆出 ${report.claim_results.length} 条 claim，其中 ${decisiveCount} 条已经拿到非“证据不足”的判定。`
    : "当前还没有稳定的 claim 判断，只能先保留边界。";

  return {
    question: report.event.summary,
    reframed_question: decisiveClaim?.claim ?? report.event.title,
    thinking_process: [
      {
        title: "先看页面正在核查什么",
        detail: `当前事件锚点是“${report.event.title}”，页面会先把输入收束到这个对象上继续分析。`,
      },
      {
        title: "再看可确认的核查结果",
        detail: verdictSummary,
      },
      {
        title: "最后看传播链还原程度",
        detail: report.timeline.length
          ? `当前已经还原出 ${report.timeline.length} 个时间线节点，可以继续沿传播链复核。`
          : "当前还没有稳定时间线，所以这仍然不是完整传播复盘。",
      },
    ],
    possibilities: [
      {
        scenario: "当前 report 已经给出一版较稳的边界化结果",
        likelihood: report.mode === "complete_mode" ? "high" : report.mode === "partial_mode" ? "medium" : "low",
        summary: report.final_summary,
      },
      {
        scenario: "仍有部分细节需要继续补证",
        likelihood: report.mode === "safe_mode" ? "high" : "medium",
        summary: report.risks[0] ?? "当前页面仍保留边界，不把局部结果伪装成完整事实。",
      },
    ],
    final_conclusion: report.final_summary,
  };
}

export function InvestigationPanel({ report }: InvestigationPanelProps) {
  if (!report) {
    return (
      <section className="panel panel--investigation">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Investigation</p>
            <h2>核实拆解</h2>
          </div>
        </div>
        <p className="empty-state">
          这里会把一句话先收束成可核查命题，再展示核查要点、可能情况和最后结论，避免用户自己从零拼接推理链。
        </p>
      </section>
    );
  }

  const investigation = report.investigation ?? buildFallbackInvestigation(report);

  return (
    <section className="panel panel--investigation">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Investigation</p>
          <h2>核实拆解</h2>
        </div>
      </div>

      <div className="investigation-overview">
        <article className="investigation-card">
          <span className="stats-label">原始问题</span>
          <p>{investigation.question}</p>
        </article>
        <article className="investigation-card">
          <span className="stats-label">收束命题</span>
          <p>{investigation.reframed_question}</p>
        </article>
      </div>

      <div className="investigation-grid">
        <div className="investigation-block">
          <h3>核查要点</h3>
          <div className="investigation-step-grid">
            {investigation.thinking_process.map((step) => (
              <article key={step.title} className="investigation-step-card">
                <strong>{step.title}</strong>
                <p>{step.detail}</p>
              </article>
            ))}
          </div>
        </div>

        <div className="investigation-block">
          <h3>可能情况</h3>
          <div className="possibility-grid">
            {investigation.possibilities.map((item) => (
              <article key={item.scenario} className="possibility-card">
                <div className="meta-row">
                  <strong>{item.scenario}</strong>
                  <span className={`possibility-pill possibility-pill--${item.likelihood}`}>
                    {likelihoodLabel[item.likelihood]}
                  </span>
                </div>
                <p>{item.summary}</p>
              </article>
            ))}
          </div>
        </div>
      </div>

      <div className="conclusion-callout">
        <span className="stats-label">最后结论</span>
        <p>{investigation.final_conclusion}</p>
      </div>
    </section>
  );
}
