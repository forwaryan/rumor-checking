"use client";

import { useRef, useState } from "react";
import type { AnalysisRun, AnalysisRunHistory, AnalysisRunComparison, Report } from "@/types/report";
import type { RecheckRequest } from "@/lib/api-client";
import { createRecheckSubmission, describeClaimChange, publicSourceUrl, runStatusLabels } from "@/lib/recheck";

export function RunVersions({ run, history, comparison, error, onSelect }: {
  run: AnalysisRun; history: AnalysisRunHistory | null; comparison: AnalysisRunComparison | null;
  error: string | null; onSelect: (runId: string) => void;
}) {
  const changedSources = comparison?.changed_source_urls ?? [];
  return <section className="review-panel" aria-label="核查版本">
    <div className="review-panel__heading"><strong>第 {run.revision} 版 · {runStatusLabels[run.status]}</strong>
      {history && <label>查看版本 <select aria-label="查看核查版本" value={run.run_id} onChange={(event) => onSelect(event.target.value)}>
        {history.revisions.map((revision) => <option key={revision.run_id} value={revision.run_id}>第 {revision.revision} 版 · {runStatusLabels[revision.status]}</option>)}
      </select></label>}
      {run.parent_run_id && <button type="button" onClick={() => onSelect(run.parent_run_id!)}>查看上一版</button>}
    </div>
    {run.review_note && <p>本次补充说明：{run.review_note}</p>}
    {error && <p role="status">{error}</p>}
    {comparison && <details open><summary>与上一版比较</summary>
      {comparison.changes.length === 0 && changedSources.length === 0 && <p>已复核项的判定与引用链接没有变化。</p>}
      <ul>{comparison.changes.map((change, index) => <li key={`${index}-${change.claim}`}><strong>{change.claim}</strong><p>{describeClaimChange(change)}</p>
        {change.added_evidence_urls.map((url) => <p key={url}>新增证据：{publicSourceUrl(url) ? <a href={url} target="_blank" rel="noopener noreferrer">{url}</a> : "链接不可用"}</p>)}
        {change.removed_evidence_urls.length > 0 && <p>不再引用 {change.removed_evidence_urls.length} 条原证据，原链接保留在上一版。</p>}
      </li>)}</ul>
      {comparison.added_source_urls.length > 0 && <p>本版新增 {comparison.added_source_urls.length} 个来源。</p>}
      {comparison.removed_source_urls.length > 0 && <p>本版移除 {comparison.removed_source_urls.length} 个来源，仍可在上一版查看。</p>}
      {changedSources.length > 0 && <div>
        <p>留存原文变化：{changedSources.length} 个相同来源链接的留存文本发生变化，不代表结论必然改变。</p>
        <ul>{changedSources.map((url) => <li key={url}>{publicSourceUrl(url)
          ? <a href={url} target="_blank" rel="noopener noreferrer">{url}</a> : "链接不可用"}</li>)}</ul>
      </div>}
    </details>}
  </section>;
}

export function RecheckPanel({ report, disabled, onSubmit }: { report: Report; disabled: boolean; onSubmit: (request: RecheckRequest) => Promise<void> }) {
  const [indices, setIndices] = useState<number[]>([]);
  const [sources, setSources] = useState("");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submissionRef = useRef(createRecheckSubmission());
  const busyRef = useRef(false);
  async function submit() {
    if (busyRef.current || disabled) return;
    busyRef.current = true; setPending(true); setError(null);
    try { await onSubmit(submissionRef.current(indices, sources, note, report.claim_results.length)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "复核暂时无法开始，请重试。"); }
    finally { busyRef.current = false; setPending(false); }
  }
  return <section className="review-panel" aria-label="补充证据并复核"><details>
    <summary>对结论有异议？补充证据并复核</summary>
    <p>选择需要复核的事项；不选择则复核全部。旧报告会保留，补充链接仍需核实。</p>
    <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
      <fieldset disabled={disabled || pending}><legend>复核范围</legend>
        {report.claim_results.map((claim, index) => <div key={`${index}-${claim.claim}`}><label className="review-panel__claim">
          <input type="checkbox" checked={indices.includes(index)} onChange={(event) => setIndices((current) => event.target.checked ? [...current, index] : current.filter((item) => item !== index))} />{claim.claim}
        </label>{claim.evidence_gaps?.map((gap, gapIndex) => <p className="review-panel__gap" key={gapIndex}>待补证：{gap.description}</p>)}</div>)}
      </fieldset>
      <label>公开网页链接（选填，每行一个，最多 5 个）<textarea value={sources} disabled={disabled || pending} onChange={(event) => setSources(event.target.value)} rows={3} placeholder="https://…" /></label>
      <p>留空时沿用上一版补充的链接；填写时以本次链接为准，旧证据仍可在上一版查看。</p>
      <label>补充说明（选填，最多 2000 字）<textarea value={note} maxLength={2000} disabled={disabled || pending} onChange={(event) => setNote(event.target.value)} rows={3} /></label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={disabled || pending}>{pending ? "正在创建复核…" : "补证复核，生成新版"}</button>
    </form>
  </details></section>;
}
