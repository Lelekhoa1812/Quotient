/**
 * Motivation vs Logic
 * Motivation: read_graph pages are the only meeting payload. Screens cannot
 * reconstruct a brief from raw transcript text.
 * Logic: Unwrap structuredContent or one JSON text block, coerce each
 * collection by field type, and merge pages by id. Sentences without
 * finding ids are dropped. Dimensions outside the ten lenses are dropped.
 */

import { asArray, asFinite, asRecord, asString, stringList } from "@/lib/json";
import { parseDigest } from "@/lib/digest";
import {
  isDimension,
  type ActionItem,
  type ChartRow,
  type ChartTable,
  type Citation,
  type Claim,
  type DecisionStatus,
  type Dimension,
  type Disagreement,
  type ExportArtifact,
  type Finding,
  type ContextUse,
  type GraphPage,
  type MeetingContext,
  type MeetingStatus,
  type Playback,
  type RawTranscript,
  type ReviewCounts,
  type Seam,
  type SpeakerHypothesis,
  type Span,
  type SpeechOmission,
  type SynthesisOmission,
  type SynthesisSentence,
  type VideoObservation,
} from "@/lib/types";

export function unwrapTool(result: unknown): unknown {
  const record = asRecord(result);
  if (!record) return result;
  if (record.structuredContent && typeof record.structuredContent === "object") {
    return record.structuredContent;
  }
  for (const block of asArray(record.content)) {
    const text = asString(asRecord(block)?.text);
    if (!text) continue;
    try {
      return JSON.parse(text) as unknown;
    } catch {
      continue;
    }
  }
  return record;
}

export function emptyGraph(): GraphPage {
  return {
    spans: [],
    claims: [],
    findings: [],
    none_in_transcript: [],
    not_evaluated: [],
    held: {},
    synthesis: [],
    synthesis_omissions: [],
    actions: [],
    disagreements: [],
    omissions: [],
    gaps: [],
    review: [],
    review_present: false,
    charts: [],
    digest: null,
    captions: "",
    speakers: [],
    exports: [],
    seams: [],
    playback: { original: "", burned: "", sidecar: "" },
    rawTranscript: { audio: "", video: "" },
    observations: [],
    next_cursor: null,
  };
}

export function parseGraph(result: unknown, meetingId: string): GraphPage {
  const source = asRecord(unwrapTool(result)) ?? {};
  const graph = asRecord(source.graph) ?? source;
  const findings = asArray(graph.findings).map(parseFinding).filter((item): item is Finding => item !== null);
  const none = new Set<Dimension>([
    ...parseDimensions(graph.none_in_transcript),
    ...parseDimensions(asArray(graph.dimensions).filter((item) => asString(asRecord(item)?.state) === "none_in_transcript")),
  ]);
  for (const finding of findings) {
    if (finding.none_in_transcript) none.add(finding.dimension);
  }
  const notEvaluated = new Set<Dimension>([
    ...parseDimensions(graph.not_evaluated),
    ...parseDimensions(asArray(graph.dimensions).filter((item) => asString(asRecord(item)?.state) === "not_evaluated")),
  ]);
  for (const name of notEvaluated) none.delete(name);
  const held: Partial<Record<Dimension, number>> = {};
  for (const item of asArray(graph.dimensions)) {
    const row = asRecord(item);
    const name = asString(row?.dimension);
    const count = asFinite(row?.held_findings);
    if (name && isDimension(name) && count !== null && count > 0) held[name] = count;
  }
  const synthesisOmissions: SynthesisOmission[] = [];
  const speechOmissions: SpeechOmission[] = [];
  for (const item of [
    ...asArray(graph.synthesis_omissions),
    ...asArray(graph.dissent_omissions),
    ...asArray(graph.omissions),
  ]) {
    const record = asRecord(item);
    if (!record) continue;
    const findingId = asString(record.finding_id);
    const spanId = asString(record.span_id);
    if (findingId) {
      synthesisOmissions.push({ finding_id: findingId, reason: asString(record.reason) ?? "" });
    } else if (spanId) {
      speechOmissions.push({ span_id: spanId, reason: asString(record.reason) ?? "" });
    }
  }
  const reviewRecord = asRecord(graph.review);
  const reviewSource = reviewRecord ? reviewRecord.claims : (graph.review ?? graph.review_queue);
  return {
    spans: asArray(graph.spans).map(parseSpan).filter((item): item is Span => item !== null),
    claims: asArray(graph.claims).map(parseClaim).filter((item): item is Claim => item !== null),
    findings,
    none_in_transcript: [...none],
    not_evaluated: [...notEvaluated],
    held,
    synthesis: asArray(graph.synthesis).map(parseSentence).filter((item): item is SynthesisSentence => item !== null),
    synthesis_omissions: dedupeOmissions(synthesisOmissions),
    actions: asArray(graph.actions).map(parseAction).filter((item): item is ActionItem => item !== null),
    disagreements: asArray(graph.disagreements).map(parseDisagreement).filter((item): item is Disagreement => item !== null),
    omissions: speechOmissions,
    gaps: asArray(graph.gaps).flatMap((item, index) => {
      const record = asRecord(item);
      if (!record) return [];
      const spanIds = asArray(record.span_ids).map(asString).filter((id): id is string => id !== null);
      return spanIds.length ? [{ id: asString(record.gap_id) ?? `gap-${index + 1}`, spanIds, reason: asString(record.reason) ?? "" }] : [];
    }),
    review: asArray(reviewSource).map(parseClaim).filter((item): item is Claim => item !== null),
    review_present: reviewSource !== undefined,
    charts: asArray(graph.charts).map(parseChart).filter((item): item is ChartTable => item !== null),
    speakers: parseSpeakers(graph),
    exports: asArray(graph.exports).map((item) => parseExport(item, meetingId)).filter((item): item is ExportArtifact => item !== null),
    seams: asArray(graph.seams).map(parseSeam).filter((item): item is Seam => item !== null),
    playback: parsePlayback(graph.playback),
    digest: parseDigest(graph.digest),
    captions: (() => {
      const uri = asString(graph.captions);
      return uri && uri.startsWith("quotient://") ? uri : "";
    })(),
    rawTranscript: parseRawTranscript(graph),
    observations: parseObservations(graph),
    next_cursor: asString(graph.next_cursor) ?? asString(graph.nextCursor),
  };
}

export function mergeGraph(base: GraphPage, page: GraphPage): GraphPage {
  return {
    spans: dedupe(base.spans, page.spans),
    claims: dedupe(base.claims, page.claims),
    findings: dedupe(base.findings, page.findings),
    none_in_transcript: [...new Set([...base.none_in_transcript, ...page.none_in_transcript])],
    not_evaluated: [...new Set([...base.not_evaluated, ...page.not_evaluated])],
    held: { ...base.held, ...page.held },
    synthesis: dedupe(base.synthesis, page.synthesis),
    synthesis_omissions: dedupeOmissions([...base.synthesis_omissions, ...page.synthesis_omissions]),
    actions: dedupe(base.actions, page.actions),
    disagreements: dedupe(base.disagreements, page.disagreements),
    omissions: [...base.omissions, ...page.omissions],
    gaps: dedupe(base.gaps, page.gaps),
    review: page.review_present ? dedupe(base.review, page.review) : base.review,
    review_present: base.review_present || page.review_present,
    charts: dedupe(base.charts, page.charts),
    digest: base.digest ?? page.digest,
    captions: base.captions || page.captions,
    speakers: page.speakers.length > 0 ? page.speakers : base.speakers,
    exports: page.exports.length > 0 ? page.exports : base.exports,
    seams: dedupeSeams([...base.seams, ...page.seams]),
    playback: {
      original: page.playback.original || base.playback.original,
      burned: page.playback.burned || base.playback.burned,
      sidecar: page.playback.sidecar || base.playback.sidecar,
    },
    rawTranscript: {
      audio: page.rawTranscript.audio || base.rawTranscript.audio,
      video: page.rawTranscript.video || base.rawTranscript.video,
    },
    observations: dedupeObservations([...base.observations, ...page.observations]),
    next_cursor: page.next_cursor,
  };
}

export function parseMeetingStatus(result: unknown, fallbackId: string): MeetingStatus {
  const source = asRecord(unwrapTool(result)) ?? {};
  const meeting = asRecord(source.meeting) ?? source;
  const artifacts: Record<string, string> = {};
  const artifactRecord = asRecord(meeting.artifacts) ?? asRecord(meeting.artifact_status) ?? {};
  for (const [key, value] of Object.entries(artifactRecord)) {
    if (typeof value === "string") artifacts[key] = value;
  }
  const reviewCount = asFinite(meeting.review_queue_count) ?? asFinite(meeting.review_count);
  return {
    meetingId: asString(meeting.meeting_id) ?? asString(meeting.id) ?? fallbackId,
    status: asString(meeting.status) ?? "",
    promptRelease: asString(meeting.prompt_release) ?? "",
    reviewCount,
    reviewCounts: parseReviewCounts(meeting.review_counts),
    artifacts,
    progressMessage: asString(meeting.progress_message) ?? "",
    failureMessage: asString(meeting.failure_message) ?? "",
    updatedAt: asString(meeting.updated_at) ?? "",
    sourceName: asString(meeting.source_name) ?? "",
    taskId: asString(meeting.task_id) ?? "",
    headline: (() => {
      const row = asRecord(meeting.headline);
      if (!row) return null;
      return {
        title: asString(row.title) ?? "",
        contentType: asString(row.content_type) ?? "other",
        decisions: asFinite(row.decisions) ?? 0,
        actions: asFinite(row.actions) ?? 0,
        openQuestions: asFinite(row.open_questions) ?? 0,
        summary: asString(row.summary) ?? "",
      };
    })(),
    context: parseMeetingContext(meeting.context),
  };
}

/**
 * Motivation vs Logic
 * Motivation: A meeting analysed with reference material should say what it was given and what
 * became of each item. Older meetings, and a service that sends something odd, must not break the
 * overview.
 * Logic: Read purpose and items defensively. An item without a name is dropped; an unknown status
 * counts as pending; negative or non-numeric chars become null. Nothing usable returns null.
 */
export function parseMeetingContext(value: unknown): MeetingContext | null {
  const record = asRecord(value);
  if (!record) return null;
  const purpose = asString(record.purpose)?.trim() || null;
  const items: ContextUse[] = [];
  for (const entry of asArray(record.items)) {
    const item = asRecord(entry);
    const name = asString(item?.name)?.trim();
    if (!item || !name) continue;
    const status = asString(item.status);
    const chars = asFinite(item.chars);
    items.push({
      name,
      status: status === "ready" || status === "skipped" || status === "failed" ? status : "pending",
      reason: asString(item.reason)?.trim() || null,
      chars: chars !== null && chars >= 0 ? chars : null,
      summary: asString(item.summary)?.trim() || null,
    });
  }
  if (!purpose && items.length === 0) return null;
  return { purpose, items };
}

export function parseMeetingId(result: unknown): string | null {
  const source = asRecord(unwrapTool(result));
  if (!source) return null;
  if (typeof source.meeting_id === "string") return source.meeting_id;
  const meeting = asRecord(source.meeting);
  return asString(meeting?.meeting_id) ?? asString(meeting?.id);
}

export function firstCitation(findings: Finding[], claims: Claim[]): Citation | null {
  for (const finding of findings) {
    for (const claimId of finding.claim_ids) {
      const claim = claims.find((item) => item.id === claimId);
      if (!claim) continue;
      const timed = claim.citations.find((item) => item.start_ms !== null);
      return timed ?? claim.citations[0] ?? null;
    }
  }
  return null;
}

export function timelineSeams(spans: Span[], seams: Seam[]): Seam[] {
  const marks = [...seams];
  const ordered = spans
    .filter((span) => span.start_ms !== null)
    .slice()
    .sort((left, right) => (left.start_ms ?? 0) - (right.start_ms ?? 0));
  let previous: string | null = null;
  for (const span of ordered) {
    if (span.seam && span.start_ms !== null) {
      marks.push({ at_ms: span.start_ms, session_id: span.session_id ?? "" });
    }
    if (previous && span.session_id && span.session_id !== previous && span.start_ms !== null) {
      marks.push({ at_ms: span.start_ms, session_id: span.session_id });
    }
    if (span.session_id) previous = span.session_id;
  }
  return dedupeSeams(marks);
}

/**
 * Bugs vs Fixes
 * Bug: read_graph names rows span_id, claim_id, finding_id, sentence_id, and
 * action_id. A parser that kept only `id` dropped the provenance graph.
 * Fix: Accept either name. A dimension state of none_in_transcript stays on
 * the board. Chart results stay the numbers on the table.
 */
function entityId(record: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = asString(record[key]);
    if (value) return value;
  }
  return null;
}

function parseSpan(value: unknown): Span | null {
  const record = asRecord(value);
  const id = record ? entityId(record, "id", "span_id") : null;
  if (!record || !id) return null;
  const raw = asString(record.raw_text) ?? asString(record.text) ?? "";
  return {
    id,
    kind: asString(record.kind) ?? "speech",
    start_ms: asFinite(record.start_ms),
    end_ms: asFinite(record.end_ms),
    raw_text: raw,
    text: asString(record.text) ?? raw,
    coarse: record.coarse === true,
    overlap: record.overlap === true,
    session_id: asString(record.session_id),
    seam: record.seam === true,
    speaker_hypothesis_id: asString(record.speaker_hypothesis_id),
    speaker_label: asString(record.speaker_display) ?? asString(record.speaker_label) ?? asString(record.display_name),
  };
}

function parseCitation(value: unknown): Citation | null {
  const record = asRecord(value);
  if (!record) return null;
  const spanId = asString(record.span_id);
  if (!spanId) return null;
  return {
    span_id: spanId,
    quote: asString(record.quote) ?? "",
    relation: asString(record.relation) ?? "mentions",
    char_start: asFinite(record.char_start),
    char_end: asFinite(record.char_end),
    start_ms: asFinite(record.start_ms),
    end_ms: asFinite(record.end_ms),
    playback: asString(record.playback) ?? asString(record.playback_path) ?? "",
  };
}

function parseClaim(value: unknown): Claim | null {
  const record = asRecord(value);
  const id = record ? entityId(record, "id", "claim_id") : null;
  if (!record || !id) return null;
  const citations = asArray(record.citations).map(parseCitation).filter((item): item is Citation => item !== null);
  const single = parseCitation(record.citation);
  if (single) citations.push(single);
  const spanIds = stringList(record.span_ids);
  for (const citation of citations) {
    if (!spanIds.includes(citation.span_id)) spanIds.push(citation.span_id);
  }
  return {
    id,
    kind: asString(record.kind) ?? "observation",
    decision_status: parseDecision(record.decision_status),
    origin: record.origin === "human" ? "human" : "model",
    status: asString(record.status) ?? "",
    coarse: record.coarse === true,
    overlap: record.overlap === true,
    text: asString(record.text) ?? asString(record.statement) ?? "",
    span_ids: spanIds,
    citations,
    confidence:
      record.confidence === "confirmed" || record.confidence === "likely" || record.confidence === "contradicted"
        ? record.confidence
        : asString(record.status) === "supported"
          ? "confirmed"
          : "unverified",
  };
}

function parseDecision(value: unknown): DecisionStatus | null {
  if (value === "aligned" || value === "needs_discussion" || value === "disagreed" || value === "shelved") {
    return value;
  }
  return null;
}

function parseFinding(value: unknown): Finding | null {
  const record = asRecord(value);
  if (!record) return null;
  const dimension = asString(record.dimension);
  if (!dimension || !isDimension(dimension)) return null;
  const stance = record.stance === "supports" || record.stance === "conflicts" || record.stance === "unknown"
    ? record.stance
    : "unknown";
  return {
    id: entityId(record, "id", "finding_id") ?? `${dimension}:${asString(record.text) ?? "none"}`,
    dimension,
    stance,
    claim_ids: stringList(record.claim_ids),
    text: asString(record.text) ?? "",
    none_in_transcript: record.none_in_transcript === true,
  };
}

function parseSentence(value: unknown): SynthesisSentence | null {
  const record = asRecord(value);
  if (!record) return null;
  const findingIds = stringList(record.finding_ids);
  const text = asString(record.text) ?? asString(record.sentence);
  if (!text || findingIds.length === 0) return null;
  return {
    id: entityId(record, "id", "sentence_id") ?? findingIds.join("+"),
    text,
    finding_ids: findingIds,
    start_ms: asFinite(record.start_ms),
  };
}

function parseAction(value: unknown): ActionItem | null {
  const record = asRecord(value);
  const id = record ? entityId(record, "id", "action_id") : null;
  if (!record || !id) return null;
  const due = record.due_kind === "absolute" || record.due_kind === "relative" || record.due_kind === "none"
    ? record.due_kind
    : "none";
  return {
    id,
    statement: asString(record.statement) ?? asString(record.text) ?? "",
    owner_span_id: asString(record.owner_span_id),
    agreement_span_id: asString(record.agreement_span_id),
    due_kind: due,
    due_surface: asString(record.due_surface),
    due_span_id: asString(record.due_span_id),
    claim_ids: stringList(record.claim_ids),
    origin: record.origin === "human" ? "human" : "model",
    acceptance: record.acceptance === "accepted" ? "accepted" : "proposed",
  };
}

function parseDisagreement(value: unknown): Disagreement | null {
  const record = asRecord(value);
  if (!record) return null;
  const sonic = asString(record.sonic_span_id);
  const pegasus = asString(record.pegasus_id) ?? asString(record.pegasus_observation_id) ?? asString(record.observation_id);
  const statement = asString(record.statement) ?? asString(record.conflict);
  if (!sonic || !pegasus || !statement) return null;
  return { id: asString(record.id) ?? `${sonic}:${pegasus}`, sonic_span_id: sonic, pegasus_id: pegasus, statement };
}

function parseChart(value: unknown): ChartTable | null {
  const record = asRecord(value);
  if (!record || record.hypotheses === true) return null;
  const aggregation = asString(record.aggregation) ?? "";
  const result = asFinite(record.result);
  const paired = pairSeries(record.ids, record.values);
  const listed = parseRows(record.rows ?? record.data);
  const rows = listed.length > 0 ? listed : (paired ?? []);
  const title = asString(record.title);
  if (rows.length === 0 && result === null && !title && !aggregation) return null;
  const columns = stringList(record.columns);
  return {
    id: asString(record.id) ?? title ?? (aggregation || "chart"),
    title: title ?? (aggregation || "Chart"),
    aggregation,
    columns: columns.length > 0 ? columns : paired && listed.length === 0 ? ["Id", "Value"] : ["Label", "Value"],
    rows,
    result,
  };
}

function pairSeries(ids: unknown, values: unknown): ChartRow[] | null {
  const idList = asArray(ids);
  const valueList = asArray(values);
  if (idList.length === 0 || idList.length !== valueList.length) return null;
  const rows: ChartRow[] = [];
  for (let index = 0; index < idList.length; index += 1) {
    const label = idList[index];
    const value = valueList[index];
    if (typeof label !== "string" || typeof value !== "number" || !Number.isFinite(value)) return null;
    rows.push({ label, value, span_id: label });
  }
  return rows;
}

function parseRows(value: unknown): ChartRow[] {
  const rows: ChartRow[] = [];
  for (const item of asArray(value)) {
    if (Array.isArray(item)) {
      const label = item.find((cell) => typeof cell === "string");
      const numeric = item.find((cell) => typeof cell === "number" && Number.isFinite(cell));
      if (typeof label === "string" && typeof numeric === "number") {
        rows.push({ label, value: numeric, span_id: null });
      }
      continue;
    }
    const record = asRecord(item);
    if (!record) continue;
    const spanId = asString(record.span_id);
    if (typeof record.label === "string" && typeof record.value === "number" && Number.isFinite(record.value)) {
      rows.push({ label: record.label, value: record.value, span_id: spanId });
      continue;
    }
    let label: string | null = null;
    let numeric: number | null = null;
    for (const [key, cell] of Object.entries(record)) {
      if (key === "span_id") continue;
      if (label === null && typeof cell === "string") label = cell;
      if (numeric === null && typeof cell === "number" && Number.isFinite(cell)) numeric = cell;
    }
    if (label !== null && numeric !== null) rows.push({ label, value: numeric, span_id: spanId });
  }
  return rows;
}

function parseExport(value: unknown, meetingId: string): ExportArtifact | null {
  if (typeof value === "string") {
    return { name: value, label: value, mime_type: "", uri: exportUri(meetingId, value) };
  }
  const record = asRecord(value);
  if (!record) return null;
  const name = asString(record.name) ?? asString(record.filename);
  if (!name) return null;
  return {
    name,
    label: asString(record.label) ?? name,
    mime_type: asString(record.mime_type) ?? asString(record.mimeType) ?? "",
    uri: asString(record.uri) ?? exportUri(meetingId, name),
  };
}

function exportUri(meetingId: string, name: string): string {
  return `quotient://meetings/${meetingId}/exports/${name}`;
}

function parseRawTranscript(graph: Record<string, unknown>): RawTranscript {
  const record = asRecord(graph.raw_transcript) ?? asRecord(graph.rawTranscript);
  return {
    audio: asString(record?.audio) ?? "",
    video: asString(record?.video) ?? "",
  };
}

function parseObservations(graph: Record<string, unknown>): VideoObservation[] {
  const rows: VideoObservation[] = [];
  for (const bucket of [graph.observations, graph.video_observations, graph.visual_notes]) {
    for (const item of asArray(bucket)) {
      const record = asRecord(item);
      if (!record) continue;
      const statement = asString(record.statement) ?? asString(record.raw_text) ?? "";
      if (!statement.trim()) continue;
      rows.push({
        id: entityId(record, "span_id", "id", "observation_id"),
        statement,
        start_ms: asFinite(record.start_ms),
      });
    }
  }
  return dedupeObservations(rows);
}

function dedupeObservations(items: VideoObservation[]): VideoObservation[] {
  const map = new Map<string, VideoObservation>();
  for (const item of items) {
    const key = item.id ?? `${item.start_ms ?? "t"}:${item.statement}`;
    map.set(key, item);
  }
  return [...map.values()];
}

function parsePlayback(value: unknown): Playback {
  if (typeof value === "string") {
    return { original: mediaLocator(value), burned: "", sidecar: "" };
  }
  const record = asRecord(value) ?? {};
  return {
    original: mediaLocator(asString(record.original) ?? asString(record.source) ?? ""),
    burned: mediaLocator(asString(record.burned) ?? asString(record.burned_in) ?? ""),
    sidecar: mediaLocator(asString(record.sidecar) ?? asString(record.vtt) ?? ""),
  };
}

function mediaLocator(value: string): string {
  if (value.startsWith("quotient://") || value.startsWith("https://") || value.startsWith("http://")) return value;
  return "";
}

function parseSeam(value: unknown): Seam | null {
  const record = asRecord(value);
  if (!record) return null;
  const at = asFinite(record.at_ms) ?? asFinite(record.start_ms);
  if (at === null) return null;
  return { at_ms: at, session_id: asString(record.session_id) ?? "" };
}

function parseDimensions(value: unknown): Dimension[] {
  const found: Dimension[] = [];
  for (const item of asArray(value)) {
    if (typeof item === "string" && isDimension(item)) found.push(item);
    const record = asRecord(item);
    const dimension = asString(record?.dimension);
    const state = asString(record?.state);
    if (dimension && isDimension(dimension) && (state === null || state === "none_in_transcript" || state === "not_evaluated")) found.push(dimension);
  }
  return found;
}

function parseReviewCounts(value: unknown): ReviewCounts | null {
  const record = asRecord(value);
  if (!record) return null;
  return {
    unresolved: asFinite(record.unresolved),
    contradicted: asFinite(record.contradicted),
    numeric_failed: asFinite(record.numeric_failed),
  };
}

function parseSpeakers(graph: Record<string, unknown>): SpeakerHypothesis[] {
  const stats = asRecord(graph.hypothesis_stats);
  const buckets = [graph.speaker_hypotheses, graph.hypotheses, stats?.rows, asRecord(graph.speakers)?.rows];
  for (const item of asArray(graph.charts)) {
    const record = asRecord(item);
    if (record?.hypotheses === true) buckets.push(record.rows);
  }
  const rows: SpeakerHypothesis[] = [];
  const seen = new Set<string>();
  for (const bucket of buckets) {
    for (const item of asArray(bucket)) {
      const record = asRecord(item);
      if (!record) continue;
      const id = asString(record.speaker_hypothesis_id) ?? asString(record.id);
      if (!id || seen.has(id)) continue;
      const duration = asFinite(record.duration_ms);
      const share = asFinite(record.duration_share);
      const turns = asFinite(record.turn_count);
      if (duration === null && share === null && turns === null) continue;
      seen.add(id);
      rows.push({
        id,
        label: asString(record.speaker_display) ?? asString(record.speaker_label),
        duration_ms: duration,
        duration_share: share,
        turn_count: turns,
      });
    }
  }
  return rows;
}

function dedupe<T extends { id: string }>(left: T[], right: T[]): T[] {
  const map = new Map<string, T>();
  for (const item of [...left, ...right]) map.set(item.id, item);
  return [...map.values()];
}

function dedupeOmissions(items: SynthesisOmission[]): SynthesisOmission[] {
  const map = new Map<string, SynthesisOmission>();
  for (const item of items) map.set(item.finding_id, item);
  return [...map.values()];
}

function dedupeSeams(items: Seam[]): Seam[] {
  const map = new Map<number, Seam>();
  for (const item of items) map.set(item.at_ms, item);
  return [...map.values()];
}
