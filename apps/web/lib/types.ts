/**
 * Motivation vs Logic
 * Motivation: Every portal screen is a projection of the provenance graph.
 * The view model has to name the same objects the graph records.
 * Logic: Keep the server's field names. Dimensions and stances are closed
 * unions. Absence is null or an empty string, never a fabricated owner.
 */

export const DIMENSIONS = [
  "decision",
  "commitment",
  "temporal",
  "stakeholder",
  "cross_modal",
  "documentary",
  "risk",
  "gap",
  "dependency",
  "question",
] as const;

export type Dimension = (typeof DIMENSIONS)[number];

export const DIMENSION_LABEL: Record<Dimension, string> = {
  decision: "Decision",
  commitment: "Commitment",
  temporal: "Temporal",
  stakeholder: "Stakeholder",
  cross_modal: "Cross-modal",
  documentary: "Documentary",
  risk: "Risk",
  gap: "Gap",
  dependency: "Dependency",
  question: "Question",
};

export function isDimension(value: string): value is Dimension {
  return (DIMENSIONS as readonly string[]).includes(value);
}

export type DecisionStatus = "aligned" | "needs_discussion" | "disagreed" | "shelved";

export type Span = {
  id: string;
  kind: string;
  start_ms: number | null;
  end_ms: number | null;
  raw_text: string;
  text: string;
  coarse: boolean;
  overlap: boolean;
  session_id: string | null;
  seam: boolean;
  speaker_hypothesis_id: string | null;
  speaker_label: string | null;
};

export type Citation = {
  span_id: string;
  quote: string;
  relation: string;
  char_start: number | null;
  char_end: number | null;
  start_ms: number | null;
  end_ms: number | null;
  playback: string;
};

export type Claim = {
  id: string;
  kind: string;
  decision_status: DecisionStatus | null;
  origin: "model" | "human";
  status: string;
  coarse: boolean;
  overlap: boolean;
  text: string;
  span_ids: string[];
  citations: Citation[];
};

export type Finding = {
  id: string;
  dimension: Dimension;
  stance: "supports" | "conflicts" | "unknown";
  claim_ids: string[];
  text: string;
  none_in_transcript: boolean;
};

export type SynthesisSentence = {
  id: string;
  text: string;
  finding_ids: string[];
  start_ms: number | null;
};

export type SynthesisOmission = {
  finding_id: string;
  reason: string;
};

export type ActionItem = {
  id: string;
  statement: string;
  owner_span_id: string | null;
  agreement_span_id: string | null;
  due_kind: "absolute" | "relative" | "none";
  due_surface: string | null;
  due_span_id: string | null;
  claim_ids: string[];
  origin: "model" | "human";
  acceptance: "proposed" | "accepted";
};

export type Disagreement = {
  id: string;
  sonic_span_id: string;
  pegasus_id: string;
  statement: string;
};

export type SpeechOmission = {
  span_id: string;
  reason: string;
};

export type ChartRow = {
  label: string;
  value: number;
  span_id: string | null;
};

export type ChartTable = {
  id: string;
  title: string;
  aggregation: string;
  columns: string[];
  rows: ChartRow[];
  result: number | null;
};

export type SpeakerHypothesis = {
  id: string;
  label: string | null;
  duration_ms: number | null;
  duration_share: number | null;
  turn_count: number | null;
};

export type ReviewCounts = {
  unresolved: number | null;
  contradicted: number | null;
  numeric_failed: number | null;
};

export type ExportArtifact = {
  name: string;
  label: string;
  mime_type: string;
  uri: string;
};

export type Seam = {
  at_ms: number;
  session_id: string;
};

export type Playback = {
  original: string;
  burned: string;
  sidecar: string;
};

export type RawTranscript = {
  audio: string;
  video: string;
};

export type VideoObservation = {
  id: string | null;
  statement: string;
  start_ms: number | null;
};

export type GraphPage = {
  spans: Span[];
  claims: Claim[];
  findings: Finding[];
  none_in_transcript: Dimension[];
  synthesis: SynthesisSentence[];
  synthesis_omissions: SynthesisOmission[];
  actions: ActionItem[];
  disagreements: Disagreement[];
  omissions: SpeechOmission[];
  review: Claim[];
  review_present: boolean;
  charts: ChartTable[];
  speakers: SpeakerHypothesis[];
  exports: ExportArtifact[];
  seams: Seam[];
  playback: Playback;
  rawTranscript: RawTranscript;
  observations: VideoObservation[];
  next_cursor: string | null;
};

export type MeetingStatus = {
  meetingId: string;
  status: string;
  promptRelease: string;
  reviewCount: number | null;
  reviewCounts: ReviewCounts | null;
  artifacts: Record<string, string>;
};

export type TaskSnapshot = {
  taskId: string;
  status: string;
  statusMessage: string;
  pollInterval: number;
  progress: number | null;
  progressMessage: string;
  meetingId: string | null;
  error: string | null;
};

export const ARTIFACT_ORDER = [
  "ledger",
  "claims",
  "counterevidence",
  "entailment",
  "coverage",
  "exports",
] as const;

export const VIEWS = [
  "progress",
  "transcript",
  "board",
  "synthesis",
  "disagreements",
  "review",
  "charts",
  "exports",
] as const;

export type MeetingView = (typeof VIEWS)[number];

export function isView(value: string | null): value is MeetingView {
  return value !== null && (VIEWS as readonly string[]).includes(value);
}
