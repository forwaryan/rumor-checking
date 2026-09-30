import type { AgentTraceSpan } from "@/types/report";

const operations = {
  round: "整轮检索", query: "搜索请求", cache: "缓存读取", selection: "筛选与去重",
  supplement: "补充来源", official_boost: "官方来源检索",
} as const;
const statuses = {
  ok: "完成", empty: "无结果", error: "失败", unavailable: "不可用",
  miss: "未命中", skipped: "已跳过", partial: "部分失败",
} as const;
const cacheStatuses = {
  hit: "命中", stale_hit: "使用过期缓存", miss: "未命中", bypassed: "已绕过",
  not_used: "未使用", write_only: "已写入", mixed: "混合",
} as const;
const providers = {
  kimi: "LLM 搜索", llm: "LLM 搜索", llm_web_search: "LLM 搜索", gdelt: "GDELT",
  playwright: "浏览器搜索", xhs: "小红书", xiaohongshu: "小红书", toutiao: "头条",
  sogou_weixin: "搜狗微信", piyao: "辟谣平台", mock: "离线数据", off: "已关闭",
  skipped: "已跳过", other: "其他来源",
} as const;
const counts = {
  query_count: "计划查询数", query_chars: "查询字符数", raw_result_count: "原始结果数",
  selected_result_count: "保留结果数", canonical_result_count: "去重后结果数",
  filtered_result_count: "过滤结果数", duplicate_count: "合并重复数",
  independent_source_count: "独立来源数", high_trust_source_count: "高信任来源数",
  failure_count: "失败次数", added_result_count: "新增结果数",
} as const;
const filters = {
  filtered_noise_count: "噪声结果", filtered_navigation_count: "导航页",
  filtered_disjoint_count: "主题不符", filtered_relevance_count: "相关性不足",
} as const;

function label<T extends Record<string, string>>(options: T, value: unknown): string | null {
  return typeof value === "string" && Object.hasOwn(options, value) ? options[value] : null;
}
function readCounts(fields: Record<string, string>, meta: Record<string, unknown>) {
  return Object.entries(fields).flatMap(([key, fieldLabel]) => {
    const value = meta[key];
    return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
      ? [{ key, label: fieldLabel, value }] : [];
  });
}

/** Render only the retrieval observer's bounded metadata contract, never arbitrary payloads. */
export function retrievalSpanView(span: AgentTraceSpan) {
  const meta = span.metadata;
  if (meta?.observability_type !== "retrieval") return null;
  const operation = label(operations, meta.operation);
  if (!operation) return null;
  return {
    operation,
    provider: label(providers, meta.provider),
    status: label(statuses, meta.status) ?? "未知",
    cache: label(cacheStatuses, meta.cache_status),
    metrics: readCounts(counts, meta),
    filters: readCounts(filters, meta),
    softRelevanceFallback: meta.soft_relevance_fallback === true,
    fallbackUsed: meta.fallback_used === true,
    evidenceGrade: typeof meta.evidence_grade === "string" && /^[ABCD]$/.test(meta.evidence_grade) ? meta.evidence_grade : null,
  };
}
