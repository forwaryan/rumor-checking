import { describe, expect, it } from "vitest";
import { buildSpanTree, type TreeNode } from "@/lib/agent-span-tree";
import type { AgentTraceSpan } from "@/types/report";

function span(id: string, parent: string | null = null, start = 0): AgentTraceSpan {
  return {
    span_id: id, parent_span_id: parent, action: id, start_time: start, end_time: start + 1,
    duration_ms: 1000, success: true, error_type: null, error_message: null, token_usage: {}, metadata: {},
  };
}

function reachableIds(roots: TreeNode[]): string[] {
  const pending = [...roots];
  const ids = new Set<string>();
  while (pending.length > 0) {
    const node = pending.pop()!;
    // Fail immediately if a cycle or repeated attachment would loop the UI.
    expect(ids.has(node.span.span_id)).toBe(false);
    ids.add(node.span.span_id);
    pending.push(...node.children);
  }
  return [...ids].sort();
}

describe("agent span trees", () => {
  it("orders roots and siblings by start time despite completion-order exports", () => {
    const spans = [span("later", "parent", 4), span("early", "parent", 2), span("parent", null, 1), span("first", null, 0)];
    const roots = buildSpanTree(spans);
    expect(roots.map(({ span: item }) => item.span_id)).toEqual(["first", "parent"]);
    expect(roots[1].children.map(({ span: item }) => item.span_id)).toEqual(["early", "later"]);
    expect(spans.map((item) => item.span_id)).toEqual(["later", "early", "parent", "first"]);
  });

  it("uses stable ID ordering for equal times and places invalid timestamps last", () => {
    const spans = [span("z"), span("a"), span("invalid-z", null, NaN), span("invalid-a", null, Infinity)];
    const order = (input: AgentTraceSpan[]) => buildSpanTree(input).map(({ span: item }) => item.span_id);
    expect(order(spans)).toEqual(["a", "z", "invalid-a", "invalid-z"]);
    expect(order([...spans].reverse())).toEqual(order(spans));
  });

  it("keeps one node per duplicate ID without losing its children", () => {
    const original = span("parent");
    const roots = buildSpanTree([original, span("child", "parent"), { ...original, action: "duplicate" }]);
    expect(roots).toHaveLength(1);
    expect(roots[0].span).toBe(original);
    expect(reachableIds(roots)).toEqual(["child", "parent"]);
  });

  it("keeps missing-parent and self-parent spans visible with their descendants", () => {
    const roots = buildSpanTree([span("orphan", "missing"), span("self", "self"), span("child", "self")]);
    expect(roots.map(({ span: item }) => item.span_id)).toEqual(["orphan", "self"]);
    expect(reachableIds(roots)).toEqual(["child", "orphan", "self"]);
  });

  it("breaks disjoint parent cycles while retaining every unique span exactly once", () => {
    const spans = [span("a", "b"), span("b", "c"), span("c", "a"), span("d", "b"), span("e", "f"), span("f", "e"), span("g")];
    const roots = buildSpanTree(spans);
    expect(roots).toHaveLength(3);
    expect(reachableIds(roots)).toEqual(["a", "b", "c", "d", "e", "f", "g"]);
    expect(buildSpanTree([...spans].reverse())).toEqual(roots);
  });

  it("handles deep parent chains without recursive construction", () => {
    const spans = Array.from({ length: 15000 }, (_, index) => span(String(index), index === 14999 ? null : String(index + 1), index));
    const roots = buildSpanTree(spans);
    expect(roots).toHaveLength(1);
    expect(roots[0].span.span_id).toBe("14999");
    expect(reachableIds(roots)).toHaveLength(spans.length);
  });

  it("returns an empty tree for an empty export", () => {
    expect(buildSpanTree([])).toEqual([]);
  });
});
