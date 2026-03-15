import { getVerificationScoreMeta } from "@/lib/report-utils";
import type { Report, ReportProvenanceState } from "@/types/report";

interface ScorePillProps {
  report: Report;
  provenance: ReportProvenanceState | null;
}

export function ScorePill({ report, provenance }: ScorePillProps) {
  const scoreMeta = getVerificationScoreMeta(report, provenance);

  return (
    <span
      className={`score-pill score-pill--${scoreMeta.tone}`}
      title={scoreMeta.summary}
      aria-label={`当前核查完成度 ${scoreMeta.label}，${scoreMeta.summary}`}
    >
      {`核查 ${scoreMeta.label}`}
    </span>
  );
}
