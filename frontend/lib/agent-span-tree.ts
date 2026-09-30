import type { AgentTraceSpan } from "@/types/report";

export type TreeNode = { span: AgentTraceSpan; children: TreeNode[] };

/**
 * Restore start-time order from spans exported in completion order. Keep the
 * first record for duplicate IDs and detach invalid parent links so every
 * unique span remains reachable, even when an imported trace contains cycles.
 */
export function buildSpanTree(spans: readonly AgentTraceSpan[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const span of spans) {
    if (!byId.has(span.span_id)) byId.set(span.span_id, { span, children: [] });
  }

  const nodes = [...byId.values()].sort((left, right) => {
    const leftStart = Number.isFinite(left.span.start_time) ? left.span.start_time : Infinity;
    const rightStart = Number.isFinite(right.span.start_time) ? right.span.start_time : Infinity;
    if (leftStart !== rightStart) return leftStart < rightStart ? -1 : 1;
    // An ID tie-breaker keeps concurrent sibling ordering stable across exports.
    return left.span.span_id < right.span.span_id ? -1 : left.span.span_id > right.span.span_id ? 1 : 0;
  });
  const parents = new Map<TreeNode, TreeNode | undefined>();
  for (const node of nodes) {
    const parentId = node.span.parent_span_id;
    const parent = parentId === null ? undefined : byId.get(parentId);
    parents.set(node, parent === node ? undefined : parent);
  }

  // Follow parent chains iteratively: both deep traces and malformed cycles
  // can be handled without recursion or repeatedly scanning completed chains.
  const visited = new Set<TreeNode>();
  for (const node of nodes) {
    const path = new Set<TreeNode>();
    let cursor: TreeNode | undefined = node;
    while (cursor && !visited.has(cursor)) {
      if (path.has(cursor)) {
        parents.set(cursor, undefined);
        break;
      }
      path.add(cursor);
      cursor = parents.get(cursor);
    }
    for (const member of path) visited.add(member);
  }

  const roots: TreeNode[] = [];
  for (const node of nodes) {
    const parent = parents.get(node);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}
