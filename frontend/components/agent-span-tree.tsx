"use client";

import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { getAgentTrace } from "@/lib/api-client";
import type { AgentTraceRecord } from "@/types/report";
import { llmSpanView, summarizeLlmSpans } from "@/lib/agent-span-view";
import { retrievalSpanView } from "@/lib/retrieval-span-view";
import { buildSpanTree, type TreeNode } from "@/lib/agent-span-tree";
import styles from "./agent-span-tree.module.css";

export interface AgentSpanTreeProps {
  runId: string;
  isOpen: boolean;
  onToggle: () => void;
}

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

const metric = (value: number | null) => value === null ? "未提供" : value.toLocaleString("zh-CN");

function Metrics({ title, items }: { title: string; items: [string, string][] }) {
  return <section className={styles.group} aria-label={title}>
    <h4>{title}</h4>
    <dl className={styles.metrics}>
      {items.map(([label, value]) => <div className={styles.metric} key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
  </section>;
}

function SpanRow({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(depth < 3);
  const childrenId = useId();
  const hasChildren = node.children.length > 0;
  const label = node.span.action;
  const status = node.span.success ? "ok" : node.span.error_type ? "err" : "warn";
  const model = typeof node.span.metadata?.model === "string" ? node.span.metadata.model : null;
  const llm = llmSpanView(node.span);
  const retrieval = retrievalSpanView(node.span);
  return (
    <div className={styles.node} style={{ "--span-depth": Math.min(depth, 4) } as CSSProperties}>
      <div className={`agent-span-row agent-span-row--${status} ${styles.row}`}>
        {hasChildren ? <button
          type="button"
          className={styles.toggle}
          onClick={() => setExpanded((v) => !v)}
          aria-label={`${expanded ? "收起" : "展开"} ${label} 的子调用`}
          aria-expanded={expanded}
          aria-controls={childrenId}
        >{expanded ? "▼" : "▶"}</button> : <span className={styles.leaf} aria-hidden="true">·</span>}
        <span className={styles.action}>{label}</span>
        <span className={styles.duration}>{fmtMs(node.span.duration_ms)}</span>
        {(llm || retrieval || model || node.span.error_type) && <div className={styles.tags}>
          {llm && <span className={styles.badge}>LLM · {llm.status}</span>}
          {retrieval && <span className={styles.badge}>检索 · {retrieval.status}</span>}
          {model && <span className={styles.model}>{model}</span>}
          {node.span.error_type && <span className={styles.error}>{node.span.error_type}</span>}
        </div>}
      </div>
      {llm && (
        <details className={styles.details}>
          <summary>
            <span>调用详情 · 输入 {metric(llm.tokens.prompt)} / 输出 {metric(llm.tokens.completion)} tokens
              {llm.attempt !== null && llm.attempt > 1 ? ` · 第 ${llm.attempt} 次尝试` : ""}</span>
          </summary>
          <Metrics title="Token 用量" items={[
            ["输入 tokens", metric(llm.tokens.prompt)], ["输出 tokens", metric(llm.tokens.completion)],
            ["缓存读取 tokens", metric(llm.tokens.cacheRead)], ["总 tokens", metric(llm.tokens.total)],
          ]} />
          <p className={styles.note}>
            {!llm.usageReported ? "上游未返回 usage，Token 消耗未知。" : "Token 数以本次上游返回的 usage 为准；缓存读取包含在输入中。"}
          </p>
          <Metrics title="响应与耗时" items={[
            ["调用耗时", fmtMs(node.span.duration_ms)],
            ["首内容时间", llm.firstTokenMs === null ? "未提供" : fmtMs(llm.firstTokenMs)],
            ["重试次数", llm.attempt === null ? "未提供" : String(Math.max(0, llm.attempt - 1))],
            ["响应字符", metric(llm.responseChars)], ["推理字符", metric(llm.reasoningChars)],
            ["响应工具调用数", metric(llm.toolCallCount)],
          ]} />
          <Metrics title="请求上下文" items={llm.context.map(({ label: fieldLabel, value }) => [fieldLabel, metric(value)])} />
          <p className={styles.note}>{llm.contextChange} 仅展示统计，不含提示词原文。</p>
          <Metrics title="调用标识" items={[
            ["提供方", llm.provider ?? "未提供"], ["阶段", llm.stage ?? "未提供"],
            ["调用 ID", llm.callId ?? "未提供"], ["HTTP 状态", metric(llm.statusCode)],
          ]} />
        </details>
      )}
      {retrieval && <details className={styles.details}>
        <summary>检索详情 · {retrieval.operation}{retrieval.provider ? ` · ${retrieval.provider}` : ""}{retrieval.cache ? ` · 缓存${retrieval.cache}` : ""}</summary>
        {retrieval.metrics.length > 0 && <Metrics title="检索结果" items={retrieval.metrics.map(({ label: name, value }) => [name, metric(value)])} />}
        {retrieval.filters.length > 0 && <Metrics title="过滤原因" items={retrieval.filters.map(({ label: name, value }) => [name, metric(value)])} />}
        {retrieval.softRelevanceFallback && <p className={styles.note}>相关性筛选未找到匹配项，保留候选供后续核验；不代表证据支持声明。</p>}
        {retrieval.fallbackUsed && <p className={styles.note}>本阶段使用了降级结果，请结合缓存状态和失败节点查看。</p>}
        {retrieval.evidenceGrade && <p className={styles.note}>证据覆盖等级 {retrieval.evidenceGrade}，仅表示材料充足程度，不代表事实判定。</p>}
        <p className={styles.note}>仅显示已记录的统计。各阶段可能处理同一批结果，不应将父子节点的数量相加。</p>
      </details>}
      {hasChildren && <div id={childrenId} hidden={!expanded}>
        {expanded && node.children.map((child) => <SpanRow key={child.span.span_id} node={child} depth={depth + 1} />)}
      </div>}
    </div>
  );
}

// A run switch resets the entire loading state and all expanded node state.
export function AgentSpanTree(props: AgentSpanTreeProps) {
  return <RunSpanTree key={props.runId} {...props} />;
}

function RunSpanTree({ runId, isOpen, onToggle }: AgentSpanTreeProps) {
  const [trace, setTrace] = useState<AgentTraceRecord | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "unavailable" | "error">("idle");
  const [revision, setRevision] = useState(0);
  const bodyId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    setState("loading");
    void getAgentTrace(runId, controller.signal)
      .then((record) => {
        if (controller.signal.aborted) return;
        setTrace(record);
        setState(record === null ? "unavailable" : "idle");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => controller.abort();
  }, [isOpen, runId, revision]);

  const spans = useMemo(() => {
    const unique = new Map<string, AgentTraceRecord["spans"][number]>();
    for (const span of trace?.spans ?? []) {
      if (!unique.has(span.span_id)) unique.set(span.span_id, span);
    }
    return [...unique.values()];
  }, [trace]);
  const roots = useMemo(() => buildSpanTree(spans), [spans]);
  const llmSummary = useMemo(() => summarizeLlmSpans(spans), [spans]);

  return (
    <div className="agent-span-tree">
      <button type="button" className={`trace-toggle ${styles.heading}`} onClick={onToggle} aria-expanded={isOpen} aria-controls={bodyId}>
        <span aria-hidden="true">{isOpen ? "▼" : "▶"}</span>
        <span>Agent 调用记录{trace ? ` · ${spans.length} 个节点` : ""}</span>
      </button>
      <div id={bodyId} hidden={!isOpen}>
        {isOpen && <div className="agent-span-tree__body" aria-busy={state === "loading"}>
          <div className={styles.toolbar}>
            <p className={styles.note}>按调用开始时间排列，展开检索节点查看结果变化，展开 LLM 查看用量和上下文。</p>
            <button type="button" className={styles.refresh} disabled={state === "loading"} onClick={() => setRevision((v) => v + 1)}>
              {state === "loading" ? "加载中…" : state === "error" || state === "unavailable" ? "重试加载" : "刷新记录"}
            </button>
          </div>
          <div role="status" aria-live="polite">
            {state === "loading" && <p className={styles.note}>{trace ? "正在更新调用记录…" : "正在加载调用记录…"}</p>}
            {state === "unavailable" && <div className="agent-span-tree__empty">暂无调用记录。记录可能尚未保存，或该任务未开启调用追踪。</div>}
            {state === "error" && <div className="agent-span-tree__empty">调用记录加载失败，请重试。{trace ? "下方保留上次加载的记录。" : ""}</div>}
          </div>
          {trace && <>
            <dl className={styles.overview}>
              {[
                ["总耗时", fmtMs(trace.duration_ms)],
                ["执行节点", `${trace.success_count} 成功 / ${trace.failure_count} 失败`],
                ["已报告 tokens", metric(trace.total_tokens)],
                ["LLM 请求尝试", metric(llmSummary.calls)],
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
            {llmSummary.calls > 0 && <p className={`${styles.coverage} ${llmSummary.reported < llmSummary.calls ? styles.incomplete : ""}`}>
              用量报告覆盖 {llmSummary.reported}/{llmSummary.calls}（{llmSummary.coverage}%）
              {llmSummary.reported < llmSummary.calls ? " · 部分消耗未知，已报告用量不代表完整消耗。" : " · 各字段以调用详情为准。"}
            </p>}
            {roots.length > 0 ? <div className="agent-span-tree__list">
              {roots.map((root) => <SpanRow key={root.span.span_id} node={root} depth={0} />)}
            </div> : <div className="agent-span-tree__empty">该任务的调用记录为空。</div>}
          </>}
        </div>}
      </div>
    </div>
  );
}
