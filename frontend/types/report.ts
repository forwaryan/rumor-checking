export type OutputMode = "complete_mode" | "partial_mode" | "safe_mode";

export type InputType = "auto" | "text" | "url" | "question";

export type AnalysisStatus =
  | "idle"
  | "submitting"
  | "complete"
  | "partial"
  | "safe_mode"
  | "error";

export type EventSourceType = "input_normalized" | "url_extract" | "provider_enriched" | "retrieval_resolved";

export type ClaimSourceType = "rule" | "provider" | "provider_plus_rule";

export type EvidenceSourceType = "retrieval_live" | "retrieval_mock" | "request_mock" | "none";

export type TimelineSourceType = "retrieval" | "input_seed" | "none";

export type ReportSourceType =
  | "backend_live"
  | "backend_mock";

export type ReportSourceKind = ReportSourceType | "unknown";

export type ReportFallbackReason = "missing_provenance";

export type PipelineStepStatus = "completed" | "warning" | "skipped" | "error";

export type AnalysisLiveEventType =
  | "session"
  | "stage"
  | "api_call"
  | "retrieval"
  | "log"
  | "report"
  | "error"
  | "complete";

export type AnalysisLiveStatus = "running" | "completed" | "warning" | "skipped" | "error";

export interface ReportProvenance {
  source_type: ReportSourceType;
  event_source: EventSourceType;
  claim_source: ClaimSourceType;
  evidence_source: EvidenceSourceType;
  timeline_source: TimelineSourceType;
  retrieval_provider: string | null;
  retrieval_cache_status: string | null;
  provider_used: boolean;
  fallback_used: boolean;
  fallback_reasons: string[];
}

export interface ReportProvenanceState {
  sourceKind: ReportSourceKind;
  reportProvenance?: ReportProvenance | null;
  fallbackReason?: ReportFallbackReason;
}

export interface RetrievalDiagnostics {
  query: string;
  provider_name: string | null;
  cache_status: string | null;
  retrieved_at: string | null;
  raw_result_count: number;
  canonical_result_count: number;
  failure_detail: string | null;
}

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

export interface InvestigationStep {
  title: string;
  detail: string;
}

export interface PossibilityItem {
  scenario: string;
  likelihood: ConfidenceLevel;
  summary: string;
}

export interface Investigation {
  question: string;
  reframed_question: string;
  thinking_process: InvestigationStep[];
  possibilities: PossibilityItem[];
  final_conclusion: string;
}

export interface ContentCheckItem {
  claim: string;
  claim_type: ClaimType;
  verdict: Verdict;
  confidence: ConfidenceValue;
  reason: string;
}

export interface AnswerSuggestion {
  angle: string;
  answer: string;
}

export interface ContentCheck {
  likely_true: ContentCheckItem[];
  likely_false: ContentCheckItem[];
  controversial: ContentCheckItem[];
  opinions: ContentCheckItem[];
  uncertain: ContentCheckItem[];
  possible_answers: AnswerSuggestion[];
}

export interface PipelineTraceStep {
  stage_key: string;
  title: string;
  status: PipelineStepStatus;
  summary: string;
  details: string[];
}

export interface PipelineTrace {
  steps: PipelineTraceStep[];
}

export interface AnalysisLiveEventBase {
  type: AnalysisLiveEventType;
  emitted_at: string;
}

export interface AnalysisLiveSessionEvent extends AnalysisLiveEventBase {
  type: "session";
  run_id: string;
  trace_id: string;
  input_type: string;
  summary: string;
  preview: string;
}

export interface AnalysisLiveStageEvent extends AnalysisLiveEventBase {
  type: "stage";
  stage_key: string;
  title: string;
  status: AnalysisLiveStatus;
  summary: string;
  details: string[];
}

export interface AnalysisLiveApiCallEvent extends AnalysisLiveEventBase {
  type: "api_call";
  call_type: string;
  status: AnalysisLiveStatus;
  title: string;
  summary: string;
  details: string[];
  stage_key?: string | null;
}

export interface AnalysisLiveRetrievalEvent extends AnalysisLiveEventBase {
  type: "retrieval";
  stage_key: string;
  query_label: string;
  query: string;
  provider_name: string;
  summary: string;
  details: string[];
}

export interface AnalysisLiveLogEvent extends AnalysisLiveEventBase {
  type: "log";
  title: string;
  summary: string;
  details: string[];
  level: "info" | "warning" | "error";
  stage_key?: string | null;
}

export interface AnalysisLiveReportEvent extends AnalysisLiveEventBase {
  type: "report";
  run_id: string;
  summary: string;
  report: Report;
}

export interface AnalysisLiveErrorEvent extends AnalysisLiveEventBase {
  type: "error";
  run_id: string;
  code: string;
  message: string;
  status_code: number;
  details: string[];
}

export interface AnalysisLiveCompleteEvent extends AnalysisLiveEventBase {
  type: "complete";
  run_id: string;
  success: boolean;
  summary: string;
}

export type AnalysisLiveEvent =
  | AnalysisLiveSessionEvent
  | AnalysisLiveStageEvent
  | AnalysisLiveApiCallEvent
  | AnalysisLiveRetrievalEvent
  | AnalysisLiveLogEvent
  | AnalysisLiveReportEvent
  | AnalysisLiveErrorEvent
  | AnalysisLiveCompleteEvent;

export interface Report {
  mode: OutputMode;
  event: Event;
  timeline: TimelineNode[];
  claim_results: ClaimResult[];
  final_summary: string;
  risks: string[];
  sources: Evidence[];
  retrieval_hits?: Evidence[];
  retrieval_diagnostics?: RetrievalDiagnostics | null;
  investigation?: Investigation | null;
  content_check?: ContentCheck | null;
  pipeline_trace?: PipelineTrace | null;
  provenance?: ReportProvenance | null;
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

