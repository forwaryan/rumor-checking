import { getModeMeta } from "@/lib/report-utils";
import type { OutputMode } from "@/types/report";

interface ModePillProps {
  mode: OutputMode;
}

export function ModePill({ mode }: ModePillProps) {
  const meta = getModeMeta(mode);

  return <span className={`mode-pill mode-pill--${mode}`}>{meta.label}</span>;
}
