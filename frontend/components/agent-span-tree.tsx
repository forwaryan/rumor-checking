"use client";

import { useEffect, useState } from "react";
import { getAgentTrace } from "@/lib/api-client";
import type { AgentTraceRecord, AgentTraceSpan } from "@/types/report";

export interface AgentSpanTreeProps {
  runId: string;
  isOpen: boolean;
  onToggle: () => void;
}

type TreeNode = { span: AgentTraceSpan; children: TreeNode[] };

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

// Build a parent → children map keyed by span_id. Spans with no parent (or a
// dangling parent_span_id that wasn't recorded) become roots so nothing is
// dropped silently. Preserves record order within siblings — that's the same
// order the exporter appended completed spans, which reads as "chronological
// within the same parent."
function buildTree(spans: AgentTraceSpan[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const span of spans) byId.set(span.span_id, { span, children: [] });
  const roots: TreeNode[] = [];
  for (const span of spans) {
    const node = byId.get(span.span_id);
    if (!node) continue;
    const parentId = span.parent_span_id;
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function SpanRow({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const label = node.span.action;
  const status = node.span.success ? "ok" : node.span.error_type ? "err" : "warn";
  const modeMeta = typeof node.span.metadata?.model === "string" ? (node.span.metadata.model as string) : null;
  return (
    <div>
      <div className={`agent-span-row agent-span-row--${status}`} style={{ paddingLeft: `${depth * 16}px` }}>
        <button
          type="button"
          className="agent-span-row__toggle"
          onClick={() => hasChildren && setExpanded((v) => !v)}
          disabled={!hasChildren}
          aria-label={hasChildren ? (expanded ? "collapse" : "expand") : "leaf"}
        >
          {hasChildren ? (expanded ? "▼" : "▶") : "·"}
        </button>
        <span className="agent-span-row__action">{label}</span>
        {modeMeta && <span className="agent-span-row__model">{modeMeta}</span>}
        <span className="agent-span-row__duration">{fmtMs(node.span.duration_ms)}</span>
        {node.span.error_type && <span className="agent-span-row__error">{node.span.error_type}</span>}
      </div>
      {hasChildren && expanded && (
        <div>
          {node.children.map((child) => (
            <SpanRow key={child.span.span_id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function AgentSpanTree({ runId, isOpen, onToggle }: AgentSpanTreeProps) {
  const [trace, setTrace] = useState<AgentTraceRecord | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "unavailable" | "error">("idle");

  useEffect(() => {
    if (!isOpen) return;
    if (trace && trace.run_id === runId) return;
    let active = true;
    setState("loading");
    void getAgentTrace(runId)
      .then((record) => {
        if (!active) return;
        if (record === null) {
          setState("unavailable");
          setTrace(null);
        } else {
          setState("idle");
          setTrace(record);
        }
      })
      .catch(() => {
        if (!active) return;
        setState("error");
      });
    return () => {
      active = false;
    };
  }, [isOpen, runId, trace]);

  const spanCount = trace?.span_count ?? 0;
  const roots = trace ? buildTree(trace.spans) : [];

  return (
    <div className="agent-span-tree">
      <button className="trace-toggle" onClick={onToggle}>
        <span>{isOpen ? "▼" : "▶"}</span>
        <span>Agent Span 树 · {spanCount > 0 ? `${spanCount} spans` : "点开加载"}</span>
      </button>
      {isOpen && (
        <div className="agent-span-tree__body">
          {state === "loading" && <div className="agent-span-tree__empty">加载中…</div>}
          {state === "unavailable" && (
            <div className="agent-span-tree__empty">
              该 run 没有 trace 文件。检查 AGENT_TRACE_ENABLED 是否开启。
            </div>
          )}
          {state === "error" && (
            <div className="agent-span-tree__empty">加载 trace 出错。</div>
          )}
          {state === "idle" && trace && roots.length > 0 && (
            <>
              <div className="agent-span-tree__summary">
                总耗时 {fmtMs(trace.duration_ms)} · 成功 {trace.success_count} · 失败 {trace.failure_count} · tokens {trace.total_tokens}
              </div>
              <div className="agent-span-tree__list">
                {roots.map((root) => (
                  <SpanRow key={root.span.span_id} node={root} depth={0} />
                ))}
              </div>
            </>
          )}
          {state === "idle" && trace && roots.length === 0 && (
            <div className="agent-span-tree__empty">trace 无 spans。</div>
          )}
        </div>
      )}
    </div>
  );
}
