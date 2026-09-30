import React, { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { AnalysisRun, AnalysisRunComparison, ClaimResult, Evidence, EvidenceSnapshot } from "@/types/report";
import { getEvidenceSnapshotView } from "@/lib/evidence-snapshot";
import { EvidenceCard } from "@/components/evidence-list";
import { ClaimList } from "@/components/claim-list";
import { RunVersions } from "@/components/recheck-panel";
import { parseReport } from "@/lib/api-client";

const snapshot: EvidenceSnapshot = {
  snapshot_id: "a".repeat(64), url: "https://example.org/source", kind: "page_text",
  text: "前😀原文𠮷后", text_sha256: "b".repeat(64), captured_at: "2026-09-13T10:00:00+00:00",
  acquisition: "fetched", extractor: "article-v1", truncated: false,
};
const evidence: Evidence = {
  title: "来源", url: snapshot.url, source_name: "发布方", published_at: "", snippet: "检索摘要",
  relevance_reason: "引用材料", source_tier: "A", snapshot_id: snapshot.snapshot_id,
  stance_quote: "原文𠮷", quote_status: "matched", quote_start: 2, quote_end: 5,
};

describe("evidence snapshot binding and quotation", () => {
  it("slices Python codepoint offsets rather than UTF-16 units", () => {
    const view = getEvidenceSnapshotView(evidence, [snapshot]);
    expect(view.snapshot).toBe(snapshot);
    expect(view.highlight).toEqual({ before: "前😀", quote: "原文𠮷", after: "后" });
    expect(view.warning).toBeNull();
  });

  it.each([[-1, 5], [2, 99], [5, 2], [2, 2], [2.5, 5], [NaN, 5], [2, Infinity], [null, 5], [2, null]])(
    "rejects invalid offsets %s..%s without searching for a replacement match", (start, end) => {
      const view = getEvidenceSnapshotView({ ...evidence, quote_start: start, quote_end: end }, [snapshot]);
      expect(view.snapshot).toBe(snapshot);
      expect(view.highlight).toBeNull();
      expect(view.warning).toBeTruthy();
    },
  );

  it("requires exact quotation equality with no whitespace or Unicode normalization", () => {
    for (const quote of ["原文", "原文𠮷 ", "假引文", ""]) {
      expect(getEvidenceSnapshotView({ ...evidence, stance_quote: quote }, [snapshot]).highlight).toBeNull();
    }
    expect(getEvidenceSnapshotView({ ...evidence, stance_quote: "é", quote_start: 0, quote_end: 2 },
      [{ ...snapshot, text: "e\u0301" }]).highlight).toBeNull();
  });

  it.each(["unmatched", "unavailable", "not_provided"] as const)("never highlights status %s even if the quote appears", (status) => {
    const view = getEvidenceSnapshotView({ ...evidence, quote_status: status }, [snapshot]);
    expect(view.highlight).toBeNull();
    expect(view.warning).toBeTruthy();
  });

  it("fails closed for URL, ID, hash format, or duplicate-ID mismatches", () => {
    for (const snapshots of [
      [{ ...snapshot, url: "https://other.example.org/", final_url: evidence.url }],
      [{ ...snapshot, snapshot_id: "c".repeat(64) }],
      [{ ...snapshot, text_sha256: "not-a-hash" }],
      [{ ...snapshot, kind: "html" } as unknown as EvidenceSnapshot],
      [snapshot, { ...snapshot, text: "different" }],
    ]) {
      const view = getEvidenceSnapshotView(evidence, snapshots);
      expect(view.snapshot).toBeNull();
      expect(view.highlight).toBeNull();
      expect(view.warning).toBeTruthy();
    }
  });

  it("keeps legacy evidence readable without claiming quotation verification", () => {
    const view = getEvidenceSnapshotView({ ...evidence, snapshot_id: undefined });
    expect(view.snapshot).toBeNull();
    expect(view.highlight).toBeNull();
    expect(view.warning).toContain("留存");
  });

  it("does not warn about absent quotations on otherwise valid snapshots", () => {
    const view = getEvidenceSnapshotView({ ...evidence, stance_quote: null, quote_status: "not_provided" }, [snapshot]);
    expect(view.snapshot).toBe(snapshot);
    expect(view.highlight).toBeNull();
    expect(view.warning).toBeNull();
  });
});

describe("evidence snapshot rendering", () => {
  beforeAll(() => { vi.stubGlobal("React", React); });
  afterAll(() => { vi.unstubAllGlobals(); });
  it.each(["matched", "unmatched"] as const)("renders backend JSON through API parsing with quote status %s", (status) => {
    const payload = JSON.parse(JSON.stringify({ evidence_snapshots: [snapshot],
      claim_results: [{ claim: "事项", claim_type: "fact", verdict: "refuted", confidence: "high",
        evidence: [{ ...evidence, quote_status: status, stance: "refutes" }] }] }));
    const report = parseReport(payload);
    const markup = renderToStaticMarkup(createElement(ClaimList, {
      claims: report.claim_results, snapshots: report.evidence_snapshots, isOpen: true, onToggle: () => {},
    }));
    expect(markup).toContain("网页正文（提取文本）");
    expect(markup).toContain(snapshot.text_sha256);
    if (status === "matched") expect(markup).toContain('<mark class="evidence-snapshot__quote">原文𠮷</mark>');
    else {
      expect(markup).toContain("引文未匹配");
      expect(markup).not.toContain("<mark");
    }
  });
  it("escapes retained HTML and highlights only the exact checked quotation", () => {
    const text = '<script>alert("x")</script>';
    const markup = renderToStaticMarkup(createElement(EvidenceCard, {
      item: { ...evidence, stance_quote: text, quote_start: 0, quote_end: text.length },
      snapshots: [{ ...snapshot, text }],
    }));
    expect(markup).not.toContain("<script>");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).toContain('<mark class="evidence-snapshot__quote">');
    expect(markup).toContain("不等于支持该声明");
  });

  it("labels cached search snippets and truncated text without presenting them as fetched full pages", () => {
    const markup = renderToStaticMarkup(createElement(EvidenceCard, {
      item: { ...evidence, quote_status: "unmatched" },
      snapshots: [{ ...snapshot, kind: "search_snippet", extractor: "search-snippet-v1", acquisition: "cached", truncated: true }],
    }));
    expect(markup).toContain("搜索摘要（非网页正文）");
    expect(markup).toContain("缓存");
    expect(markup).toContain("截断");
    expect(markup).toContain(snapshot.text_sha256);
    expect(markup).toContain(snapshot.captured_at);
    expect(markup).toContain("未匹配");
    expect(markup).not.toContain("<mark");
  });

  it("labels restored checkpoint text without inventing original extraction metadata", () => {
    const markup = renderToStaticMarkup(createElement(EvidenceCard, {
      item: evidence, snapshots: [{ ...snapshot, acquisition: "restored", extractor: "checkpoint-text-v1" }],
    }));
    expect(markup).toContain("恢复的留存内容");
    expect(markup).toContain("checkpoint-text-v1");
    expect(markup).toContain("并非本轮重新抓取");
  });

  it.each(["supported", "conflicting"] as const)("passes snapshots through %s claim evidence cards", (verdict) => {
    const claim: ClaimResult = { claim: "事项", verdict, claim_type: "fact", confidence: "high", notes: "",
      evidence: verdict === "conflicting" ? [evidence, { ...evidence, stance: "refutes" }] : [evidence] };
    const markup = renderToStaticMarkup(createElement(ClaimList, { claims: [claim], snapshots: [snapshot], isOpen: true, onToggle: () => {} }));
    expect(markup).toContain("网页正文（提取文本）");
    expect(markup).toContain('<mark class="evidence-snapshot__quote">原文𠮷</mark>');
  });

  it("keeps legacy cards readable and does not render an unverified quote as original text", () => {
    const markup = renderToStaticMarkup(createElement(EvidenceCard, { item: { ...evidence, snapshot_id: undefined } }));
    expect(markup).toContain("检索摘要");
    expect(markup).toContain("旧版报告");
    expect(markup).not.toContain("<mark");
    expect(markup).not.toContain(evidence.stance_quote);
  });

  it("shows source-text changes even when verdicts and citation URLs are unchanged", () => {
    const comparison: AnalysisRunComparison = { run_id: "new", parent_run_id: "old", changes: [],
      added_source_urls: [], removed_source_urls: [], changed_source_urls: [snapshot.url] };
    const markup = renderToStaticMarkup(createElement(RunVersions, {
      run: { run_id: "new", revision: 2, status: "completed" } as AnalysisRun,
      comparison, history: null, error: null, onSelect: () => {},
    }));
    expect(markup).toContain("留存原文变化");
    expect(markup).toContain(snapshot.url);
    expect(markup).not.toContain("没有变化");
    expect(markup).not.toContain("本版新增");
  });
});
