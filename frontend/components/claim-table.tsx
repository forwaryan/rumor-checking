import { formatConfidence, getVerdictLabel } from "@/lib/report-utils";
import type { Report } from "@/types/report";

interface ClaimTableProps {
  report: Report | null;
}

export function ClaimTable({ report }: ClaimTableProps) {
  return (
    <section className="panel panel--claims">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Claim Table</p>
          <h2>claim 核查表</h2>
        </div>
      </div>

      {report?.claim_results.length ? (
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>类型</th>
                <th>Verdict</th>
                <th>Confidence</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {report.claim_results.map((claim) => (
                <tr key={claim.claim}>
                  <td>
                    <strong>{claim.claim}</strong>
                    <span className="cell-subtle">证据 {claim.evidence.length} 条</span>
                  </td>
                  <td>
                    <span className={`tag tag--soft tag--${claim.claim_type}`}>{claim.claim_type}</span>
                  </td>
                  <td>
                    <span className={`tag tag--verdict tag--${claim.verdict}`}>
                      {getVerdictLabel(claim.verdict)}
                    </span>
                  </td>
                  <td>{formatConfidence(claim.confidence)}</td>
                  <td>{claim.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-state">
          没有 claim 时，页面会保持空态提示；在 safe mode 下，也不会为了“看起来完整”强塞结论表。
        </p>
      )}
    </section>
  );
}
