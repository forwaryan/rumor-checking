"use client";

import type { RunMetrics } from "@/types/report";

export interface RunMetricsPanelProps {
  metrics: RunMetrics;
  isOpen: boolean;
  onToggle: () => void;
}

const ROLE_LABEL: Record<string, string> = {
  normalize: "标准化",
  retrieval: "检索",
  retrieval_baidu: "百度",
  retrieval_xhs: "小红书",
  retrieval_toutiao: "今日头条",
  retrieval_weixin: "微信公众号",
  retrieval_merge: "合并",
  analysis: "分析",
  critic: "审查",
  report: "报告",
};

const SOURCE_LABEL: Record<string, string> = {
  baidu: "百度",
  xiaohongshu: "小红书",
  toutiao: "今日头条",
  sogou_weixin: "微信公众号",
};

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

const STATUS_LABEL: Record<string, string> = {
  completed: "完成",
  failed: "失败",
  skipped: "跳过",
};

export function RunMetricsPanel({ metrics, isOpen, onToggle }: RunMetricsPanelProps) {
  const sourceEntries = Object.entries(metrics.source_hits);
  const agents = [...metrics.agents].sort((a, b) => b.elapsed_ms - a.elapsed_ms);
  const modeLabel = metrics.mode === "parallel" ? "并行检索" : metrics.mode === "sequential" ? "串行检索" : metrics.mode;

  return (
    <div className="run-metrics">
      <button className="trace-toggle" onClick={onToggle}>
        <span>{isOpen ? "▼" : "▶"}</span>
        <span>运行统计 · {modeLabel} · {fmtMs(metrics.total_ms)}</span>
      </button>
      {isOpen && (
        <div className="run-metrics__body">
          <div className="run-metrics__stats">
            <div className="run-metrics__stat">
              <span className="run-metrics__stat-value">{fmtMs(metrics.total_ms)}</span>
              <span className="run-metrics__stat-label">总耗时</span>
            </div>
            <div className="run-metrics__stat">
              <span className="run-metrics__stat-value">{metrics.tokens.total.toLocaleString()}</span>
              <span className="run-metrics__stat-label">Token（{metrics.tokens.llm_calls} 次调用）</span>
            </div>
            <div className="run-metrics__stat">
              <span className="run-metrics__stat-value">{metrics.completed.length}</span>
              <span className="run-metrics__stat-label">Agent 完成{metrics.failed.length > 0 ? ` · ${metrics.failed.length} 失败` : ""}</span>
            </div>
            {metrics.time_exhausted && (
              <div className="run-metrics__stat run-metrics__stat--warn">
                <span className="run-metrics__stat-value">⏱</span>
                <span className="run-metrics__stat-label">触发时限软着陆</span>
              </div>
            )}
            {metrics.looped_back && (
              <div className="run-metrics__stat">
                <span className="run-metrics__stat-value">↻</span>
                <span className="run-metrics__stat-label">触发补检索</span>
              </div>
            )}
          </div>

          {sourceEntries.length > 0 && (
            <div className="run-metrics__section">
              <div className="run-metrics__section-title">各来源命中</div>
              <div className="run-metrics__sources">
                {sourceEntries.map(([key, count]) => (
                  <span key={key} className={`run-metrics__source${count === 0 ? " run-metrics__source--empty" : ""}`}>
                    {SOURCE_LABEL[key] ?? key}: <strong>{count}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}

          {agents.length > 0 && (
            <div className="run-metrics__section">
              <div className="run-metrics__section-title">各 Agent 耗时</div>
              <div className="run-metrics__agents">
                {agents.map((a) => (
                  <div key={a.role} className={`run-metrics__agent run-metrics__agent--${a.status}`}>
                    <span className="run-metrics__agent-name">{ROLE_LABEL[a.role] ?? a.role}</span>
                    <span className="run-metrics__agent-time">{fmtMs(a.elapsed_ms)}</span>
                    {a.status !== "completed" && (
                      <span className="run-metrics__agent-status">{STATUS_LABEL[a.status] ?? a.status}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
