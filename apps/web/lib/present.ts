/**
 * Motivation vs Logic
 * Motivation: Contracts store machine values (none_in_transcript, cross_modal,
 * needs_discussion, duration_union). People should read ordinary words, and the
 * wording must not drift between screens.
 * Logic: One closed map per contract enum. The stored value never changes; only
 * its presentation does. An unmapped value renders a neutral fallback instead of
 * leaking the raw code, and is reported once in development so the map can grow.
 */
import type { DecisionStatus, Dimension } from "@/lib/types";

const warned = new Set<string>();

function pick(table: Record<string, string>, group: string, value: string | null | undefined, fallback: string): string {
  if (value === null || value === undefined || value === "") return fallback;
  const hit = table[value];
  if (hit !== undefined) return hit;
  if (process.env.NODE_ENV !== "production" && !warned.has(`${group}:${value}`)) {
    warned.add(`${group}:${value}`);
    console.warn(`present: no wording for ${group} "${value}"`);
  }
  return fallback;
}

const DIMENSION_TITLE: Record<Dimension, string> = {
  decision: "Decisions",
  commitment: "Commitments",
  temporal: "Dates and timing",
  stakeholder: "People and teams",
  cross_modal: "Audio and video",
  documentary: "Documents mentioned",
  risk: "Risks",
  gap: "Gaps",
  dependency: "Dependencies",
  question: "Questions raised",
};

const DIMENSION_ASK: Record<Dimension, string> = {
  decision: "What was decided?",
  commitment: "Who agreed to do what?",
  temporal: "What dates and deadlines came up?",
  stakeholder: "Who is affected or involved?",
  cross_modal: "Do the audio and the video agree?",
  documentary: "Which documents or slides were referred to?",
  risk: "What could go wrong?",
  gap: "What was flagged as missing or unclear?",
  dependency: "What depends on something else?",
  question: "What questions came up?",
};

export function dimensionTitle(value: string): string {
  return pick(DIMENSION_TITLE, "dimension", value, "Other");
}

export function dimensionQuestion(value: string): string {
  return pick(DIMENSION_ASK, "dimension", value, "");
}

/** True for topics whose findings can say "not answered" without having seen the later answer. */
export function isOpenPointTopic(dimension: string): boolean {
  return dimension === "question" || dimension === "gap";
}

export const OPEN_POINT_NOTE = "These were raised in the recording. Later parts of it may answer them, so check the transcript before treating one as still open.";

export const NOT_MENTIONED = "Not mentioned in the video";

const STANCE: Record<string, string> = {
  supports: "Supported by the recording",
  conflicts: "Conflicts with other evidence",
  unknown: "Not settled",
};

export function stanceText(value: string): string {
  return pick(STANCE, "stance", value, "Not settled");
}

const DECISION_STATUS: Record<DecisionStatus, string> = {
  aligned: "Agreed",
  needs_discussion: "Needs discussion",
  disagreed: "Disagreed",
  shelved: "Parked for later",
};

export function decisionStatusText(value: DecisionStatus | null): string {
  if (value === null) return "Outcome not stated";
  return pick(DECISION_STATUS, "decision_status", value, "Outcome not stated");
}

const CLAIM_STATUS: Record<string, string> = {
  supported: "Confirmed",
  unresolved: "Not yet confirmed",
  contradicted: "Contradicted",
  numeric_failed: "Numbers need checking",
  incomplete: "Incomplete",
  pending: "Waiting",
  unknown: "Not settled",
};

export function claimStatusText(value: string): string {
  return pick(CLAIM_STATUS, "claim_status", value, "Not settled");
}

const ORIGIN: Record<string, string> = {
  model: "Suggested from the recording",
  human: "Added by a person",
};

export function originText(value: string): string {
  return pick(ORIGIN, "origin", value, "Suggested from the recording");
}

const DUE_KIND: Record<string, string> = {
  absolute: "Specific date",
  relative: "Relative to the meeting",
  none: "No deadline mentioned",
};

export function dueKindText(value: string): string {
  return pick(DUE_KIND, "due_kind", value, "No deadline mentioned");
}

const AGGREGATION: Record<string, string> = {
  count: "Count",
  sum: "Total",
  mean: "Average",
  min: "Lowest",
  max: "Highest",
  duration_union: "Time covered",
};

export function aggregationText(value: string): string {
  return pick(AGGREGATION, "aggregation", value, "");
}

const EXPORT_LABEL: Record<string, string> = {
  "brief.pdf": "Brief (PDF)",
  "brief.html": "Brief (web page)",
  "actions.csv": "Actions (CSV)",
  "actions.xlsx": "Actions (Excel)",
  "captions.vtt": "Captions (VTT)",
  "captions.srt": "Captions (SRT)",
  "burned.mp4": "Video with captions",
  "graph.json": "Full data (JSON)",
};

export function exportLabel(name: string, fallback: string): string {
  return EXPORT_LABEL[name] ?? (fallback && fallback !== name ? fallback : name);
}

/** Speaker name as a person would read it; never a worker hypothesis id. */
export function speakerName(label: string | null | undefined, hypothesisId: string | null | undefined): string {
  if (label && label.trim()) return label.trim();
  if (hypothesisId) {
    const index = Number(hypothesisId.match(/(\d+)\s*$/)?.[1]);
    return Number.isFinite(index) ? `Speaker ${index + 1}` : "Unnamed speaker";
  }
  return "Unnamed speaker";
}

/**
 * Display names for voices, strongest first: a name a person typed (span.speaker_label), then the name the
 * analysis settled on (from the picture and from what was said, see `identities`), then a name the
 * transcript itself gave (the digest's speakers); otherwise "Speaker N". Never a guess.
 */
export function voiceNames(
  spans: { speaker_hypothesis_id: string | null; speaker_label: string | null }[],
  named: { id: string; name: string; role: string | null }[] = [],
  identities: Record<string, { name: string }> = {},
): Map<string, string> {
  const names = new Map<string, string>();
  const title = (name: string) => (name === name.toLowerCase() ? name.replace(/\b\p{L}/gu, (letter) => letter.toUpperCase()) : name);
  for (const speaker of named) {
    const shown = title(speaker.name);
    names.set(speaker.id, speaker.role ? `${shown} (${speaker.role})` : shown);
  }
  for (const [voice, identity] of Object.entries(identities)) {
    if (identity.name.trim()) names.set(voice, title(identity.name.trim()));
  }
  for (const span of spans) {
    if (span.speaker_hypothesis_id && span.speaker_label?.trim()) names.set(span.speaker_hypothesis_id, span.speaker_label.trim());
  }
  return names;
}

/**
 * Free text written by the analysis can mention a voice by its id ("spk_0 will ..."). Show a name when
 * the transcript gave one, "the speaker" when the recording has a single voice, else "Speaker N".
 */
export function readable(text: string, names: Map<string, string>, voices: number): string {
  return text.replace(/\bspk_(\d+)\b/gi, (_match, digits: string) => {
    const id = `spk_${digits}`;
    const named = names.get(id);
    if (named) return named;
    return voices <= 1 ? "the speaker" : `Speaker ${Number(digits) + 1}`;
  });
}

/** Duration in ms as m:ss or h:mm:ss, or "1 min 20 s" for prose. */
export function durationText(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return seconds > 0 && minutes < 10 ? `${minutes} min ${seconds} s` : `${minutes} min`;
  return `${seconds} s`;
}

export function percentText(share: number): string {
  const value = share <= 1 ? share * 100 : share;
  return `${value >= 10 ? Math.round(value) : Math.round(value * 10) / 10}%`;
}

export function countText(value: number): string {
  return new Intl.NumberFormat(undefined).format(value);
}

const SERVER_SENTENCES = new Set([
  "The analysis service did not accept this computer's sign-in. Sign in to AWS again, then start the analysis again.",
  "The analysis was interrupted too many times. Please upload the recording again.",
  "The recording could not be found.",
  "This file is not a readable audio or video recording.",
  "This recording has no audio, so there is nothing to transcribe.",
  "The analysis service declined this recording.",
  "The analysis took too long and was stopped. Please try again.",
  "The analysis could not be completed. Please try again.",
]);

const KNOWN_ERRORS: [RegExp, string][] = [
  [/CalledProcessError|ffprobe|ffmpeg/i, "This file is not a readable audio or video recording."],
  [/FileNotFoundError/i, "The recording could not be found."],
  [/blocked by our content filters/i, "The analysis service declined this recording."],
  [/validationException|SchemaRejected|schema/i, "The analysis could not be completed. Please try again."],
  [/timeout|timed out/i, "The analysis took too long. Please try again."],
  [/not on disk|not found|404/i, "The recording could not be found."],
];

/** User-safe sentence for a server failure; the raw text stays in logs. */
export function friendlyError(raw: string | null | undefined, fallback = "Something went wrong. Please try again."): string {
  if (!raw) return fallback;
  // Sentences the server composes itself pass through; anything else is mapped or replaced.
  if (SERVER_SENTENCES.has(raw.trim())) return raw.trim();
  for (const [pattern, text] of KNOWN_ERRORS) if (pattern.test(raw)) return text;
  return fallback;
}

/**
 * The worker reports its phase as a message. This maps each known message to one of five
 * user-facing steps; an unknown message returns -1 so the caller can fall back safely.
 */
export const ANALYSIS_STEPS = [
  "Transcribing the recording",
  "Finding statements and checking them against what was said",
  "Making sure nothing was missed",
  "Writing the brief and follow-up actions",
  "Final checks and charts",
] as const;

const STEP_MATCHERS: RegExp[] = [
  /^(preparing the media|streaming audio)/i,
  /^(compacting|checking audio against|extracting claims)/i,
  /^checking transcript coverage/i,
  /^(analy[sz]ing all|building the evidence|summari[sz]ing|extracting and grounding)/i,
  /^building charts/i,
];

export function analysisStepIndex(message: string): number {
  return STEP_MATCHERS.findIndex((pattern) => pattern.test(message.trim()));
}
