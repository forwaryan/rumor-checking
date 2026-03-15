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
          <p className="eyebrow">Claim Review</p>
          <h2>逐条核查点</h2>
        </div>
      </div>

      {report?.claim_results.length ? (
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>核查点</th>
                <th>判断</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {report.claim_results.map((claim) => (
                <tr key={claim.claim}>
                  <td>
                    <strong>{claim.claim}</strong>
                  </td>
                  <td>
                    <span className={`tag tag--verdict tag--${claim.verdict}`}>
                      {`${getVerdictLabel(claim.verdict)} · ${formatConfidence(claim.confidence)}`}
                    </span>
                  </td>
                  <td>{claim.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-state">当前还没有可展示的逐条核查点。</p>
      )}
    </section>
  );
}
