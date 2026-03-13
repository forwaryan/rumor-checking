export type OutputMode = "complete_mode" | "partial_mode" | "safe_mode";

export type InputType = "auto" | "text" | "url" | "question";

export type AnalysisStatus =
  | "idle"
  | "submitting"
  | "complete"
  | "partial"
  | "safe_mode"
  | "error";

export type TimelineNodeType =
  | "origin"
  | "amplification"
  | "peak"
  | "turn"
  | "clarification";

export type ClaimType = "fact" | "opinion" | "prediction" | "unverifiable";

export type Verdict = "supported" | "refuted" | "insufficient" | "conflicting";

export type ConfidenceLevel = "high" | "medium" | "low";

export type ConfidenceValue = ConfidenceLevel | number;

export type SourceTier = "S" | "A" | "B" | "C";

export interface Event {
  title: string;
  summary: string;
  source_url: string;
  source_name: string;
  published_at: string;
  keywords: string[];
  mode: OutputMode;
}

export interface TimelineNode {
  node_type: TimelineNodeType;
  title: string;
  url: string;
  source_name: string;
  published_at: string;
  summary: string;
  why_selected: string;
}

export interface Evidence {
  title: string;
  url: string;
  source_name: string;
  published_at: string;
  snippet: string;
  relevance_reason: string;
  source_tier: SourceTier;
}

export interface ClaimResult {
  claim: string;
  claim_type: ClaimType;
  verdict: Verdict;
  confidence: ConfidenceValue;
  evidence: Evidence[];
  notes: string;
}

export interface Report {
  mode: OutputMode;
  event: Event;
  timeline: TimelineNode[];
  claim_results: ClaimResult[];
  final_summary: string;
  risks: string[];
  sources: Evidence[];
}

export interface AnalyzeRequest {
  raw_input: string;
  input_type: InputType;
  request_context?: Record<string, unknown>;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "error";
  detail?: string;
}

export interface DemoCaseSummary {
  id: string;
  title: string;
  description: string;
  input_type: InputType;
  sample_input: string;
  mode: OutputMode;
}

export interface DemoCase extends DemoCaseSummary {
  report: Report;
}
