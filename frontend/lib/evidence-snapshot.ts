import type { Evidence, EvidenceSnapshot } from "@/types/report";

export interface EvidenceSnapshotView {
  snapshot: EvidenceSnapshot | null;
  highlight: { before: string; quote: string; after: string } | null;
  warning: string | null;
}

const HASH_FORMAT = /^[0-9a-f]{64}$/;
const ACQUISITIONS = new Set(["fetched", "cached", "retrieved", "restored"]);
const EXTRACTORS = new Set(["article-v1", "tag-strip-v1", "search-snippet-v1", "browser-text-v1", "checkpoint-text-v1"]);

export function getEvidenceSnapshotView(item: Evidence, snapshots: readonly EvidenceSnapshot[] = []): EvidenceSnapshotView {
  if (!item.snapshot_id) {
    return { snapshot: null, highlight: null, warning: "未提供留存文本，无法核对引文；旧版报告可能没有快照。" };
  }
  const matches = snapshots.filter((candidate) => candidate?.snapshot_id === item.snapshot_id);
  const snapshot = matches[0];
  if (matches.length !== 1 || !snapshot || !HASH_FORMAT.test(item.snapshot_id) ||
    snapshot.url !== item.url || !HASH_FORMAT.test(snapshot.text_sha256) ||
    typeof snapshot.text !== "string" || !snapshot.text ||
    !["page_text", "search_snippet"].includes(snapshot.kind) ||
    !ACQUISITIONS.has(snapshot.acquisition) || !EXTRACTORS.has(snapshot.extractor) ||
    typeof snapshot.captured_at !== "string" || !Number.isFinite(Date.parse(snapshot.captured_at)) ||
    typeof snapshot.truncated !== "boolean") {
    return { snapshot: null, highlight: null, warning: "快照缺失、格式或来源绑定异常，无法核对留存文本。" };
  }
  if (!item.stance_quote && item.quote_status !== "matched" && item.quote_status !== "unmatched") {
    return { snapshot, highlight: null, warning: null };
  }
  if (item.quote_status !== "matched") {
    return { snapshot, highlight: null, warning: item.quote_status === "unmatched"
      ? "引文未匹配留存文本，不作原文高亮，也不能将该引文当成已核对原文。"
      : "引文尚未完成原文核对，不作高亮。" };
  }
  const start = item.quote_start;
  const end = item.quote_end;
  const characters = Array.from(snapshot.text);
  if (typeof start !== "number" || typeof end !== "number" || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) ||
    start < 0 || end <= start || end > characters.length ||
    characters.slice(start, end).join("") !== item.stance_quote) {
    return { snapshot, highlight: null, warning: "引文位置或文字核对未通过，不作原文高亮。" };
  }
  return {
    snapshot, warning: null,
    highlight: { before: characters.slice(0, start).join(""), quote: characters.slice(start, end).join(""), after: characters.slice(end).join("") },
  };
}
