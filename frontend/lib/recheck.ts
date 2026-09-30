import type { RecheckRequest } from "@/lib/api-client";
import type { ClaimChange } from "@/types/report";

export function publicSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password ||
      !hostname.includes(".") || hostname.endsWith(".localhost") || hostname.endsWith(".local") ||
      hostname.endsWith(".internal") || hostname.includes(":") || /^\d+\.\d+\.\d+\.\d+$/.test(hostname)) return null;
    return url.href;
  } catch { return null; }
}

export function buildRecheckRequest(indices: number[], sourceText: string, note: string, claimCount: number, requestId: string): RecheckRequest {
  const lines = sourceText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length > 5) throw new Error("最多提供 5 个公开网页链接。");
  const urls = lines.map(publicSourceUrl);
  if (urls.some((url) => !url)) throw new Error("请提供公开的 HTTP 或 HTTPS 网页链接，不支持本地地址或带账号密码的链接。");
  if (note.trim().length > 2000) throw new Error("补充说明最多 2000 字。");
  if (indices.some((index) => !Number.isSafeInteger(index) || index < 0 || index >= claimCount)) throw new Error("请选择当前报告中的核查项。");
  return { claim_indices: [...new Set(indices)].sort((first, second) => first - second), source_urls: [...new Set(urls as string[])], note: note.trim(), request_id: requestId };
}

export function createRecheckSubmission(createId = () => crypto.randomUUID()) {
  let previousBody = "";
  let requestId = "";
  return (indices: number[], sourceText: string, note: string, claimCount: number) => {
    const request = buildRecheckRequest(indices, sourceText, note, claimCount, "");
    const body = JSON.stringify(request);
    if (body !== previousBody) { requestId = createId(); previousBody = body; }
    return { ...request, request_id: requestId };
  };
}

const verdictLabels: Record<string, string> = { supported: "有证据支持", refuted: "有证据反驳", insufficient: "证据不足", conflicting: "证据冲突", unverifiable: "无法核实" };

export function describeClaimChange(change: ClaimChange): string {
  if (change.kind === "not_rechecked") return "本版未复核此项，原结论仍可在旧版查看";
  if (change.kind === "removed") return "本版未列出此项";
  const before = change.before_verdict ? verdictLabels[change.before_verdict] ?? change.before_verdict : "无原结论";
  const after = change.after_verdict ? verdictLabels[change.after_verdict] ?? change.after_verdict : "暂无结论";
  return change.kind === "added" ? `新增核查：${after}` : `${before} → ${after}`;
}

export const runStatusLabels: Record<string, string> = { queued: "等待核查", running: "核查中", completed: "已完成", failed: "核查失败", interrupted: "已中断", cancelled: "已停止" };
