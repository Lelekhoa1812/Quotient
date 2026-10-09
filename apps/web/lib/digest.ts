/**
 * Motivation vs Logic
 * Motivation: The digest is the walkaway: what the recording was, what was decided, who does what,
 * what is still open, the figures, and where each topic is. The server has already grounded every
 * item; the portal must not invent or reorder meaning, only read it safely.
 * Logic: Parse defensively. An item missing its required text or moment is dropped, never padded.
 * Basis says how strongly an item is evidenced: confirmed, likely, or transcript (navigational).
 */
import { asArray, asFinite, asRecord, asString, stringList } from "@/lib/json";

export type Basis = "confirmed" | "likely" | "transcript";
export type ContentType = "meeting" | "presentation" | "lecture" | "discussion" | "interview" | "other";

export type DigestLine = { text: string; spanIds: string[]; basis: Basis; startMs: number | null };
export type Chapter = { title: string; gist: string; startMs: number; endMs: number; startSpanId: string };
export type Decision = { statement: string; status: "agreed" | "tentative" | "deferred"; by: string | null; spanIds: string[]; basis: Basis; startMs: number | null };
/** A due phrase is worth showing only when it names a time; "next" or "later" alone tells the reader nothing. */
const TIME_CUE = /\p{Nd}|\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|weeks?|weekends?|months?|years?|quarters?|morning|afternoon|evening|hours?|minutes?|days?|eod|eow|end of|sprints?|noon|midnight|midday|overnight|fortnights?|asap|immediately|right away|mon|tue|tues|wed|thu|thur|thurs|fri)\b/iu;
export function dueText(value: string | null): string | null {
  return value && TIME_CUE.test(value) ? value : null;
}

/** A first-person promise as speech-to-text writes it: "we will", "i'll", "i am going to". */
const PROMISE = /\b(?:i|we)(?:['’]ll|\s+will|\s+shall|\s+can|\s+am\s+going\s+to|\s+are\s+going\s+to|\s+gonna|['’](?:m|re)\s+(?:gonna|going\s+to))\b(?!['’]t|\s+never\b|\s+not(?!\s+only\b))/i;

/** True when the action's owner said, in a line the action cites, that they will do it. Nobody else has confirmed it, but it is more than a suggestion. */
export function promisedByOwner(action: { owner: string | null; spanIds: string[] }, spans: { id: string; speaker_hypothesis_id: string | null; text: string; raw_text: string }[]): boolean {
  if (!action.owner) return false;
  const cited = new Set(action.spanIds);
  return spans.some((span) => cited.has(span.id) && span.speaker_hypothesis_id === action.owner && PROMISE.test(span.text || span.raw_text || ""));
}

export type DigestAction = { task: string; owner: string | null; due: string | null; agreed: boolean; actionId: string | null; spanIds: string[]; basis: Basis; startMs: number | null };
export type Question = { question: string; askedBy: string | null; startMs: number | null; askedSpanId: string; answered: boolean; answer: string | null; answerMs: number | null; answerSpanId: string | null };
export type Position = { speaker: string | null; position: string; spanIds: string[]; startMs: number | null };
export type Disagreement = { topic: string; positions: Position[]; startMs: number | null };
export type Figure = { value: string; what: string; spanId: string; startMs: number | null };
export type Risk = { risk: string; spanIds: string[]; basis: Basis; startMs: number | null };
export type Concept = { term: string; explanation: string; spanIds: string[]; basis: Basis; startMs: number | null };
export type Speaker = { id: string; name: string; role: string | null };
export type Perspective = { speaker: string | null; position: string; spanIds: string[]; startMs: number | null };
export type Diagram = { kind: "flowchart" | "sequence"; title: string; mermaid: string; startMs: number | null };

export type Digest = {
  contentType: ContentType;
  title: string;
  summary: DigestLine[];
  /** Where things stand at the end: result, next step, what is unresolved. */
  outcome: DigestLine | null;
  /** Voices the transcript itself names (introductions, forms of address). */
  speakers: Speaker[];
  /** What each main participant argued or asked for (discussions, hearings, interviews). */
  perspectives: Perspective[];
  chapters: Chapter[];
  decisions: Decision[];
  actions: DigestAction[];
  questions: Question[];
  disagreements: Disagreement[];
  figures: Figure[];
  risks: Risk[];
  concepts: Concept[];
  diagram: Diagram | null;
};

const TYPES: ContentType[] = ["meeting", "presentation", "lecture", "discussion", "interview", "other"];

function basis(value: unknown): Basis {
  return value === "confirmed" || value === "likely" ? value : "transcript";
}

function rows<T>(value: unknown, parse: (record: Record<string, unknown>) => T | null): T[] {
  return asArray(value)
    .map((item) => {
      const record = asRecord(item);
      return record ? parse(record) : null;
    })
    .filter((item): item is T => item !== null);
}

export function parseDigest(value: unknown): Digest | null {
  const record = asRecord(value);
  if (!record) return null;
  const contentType = TYPES.includes(record.content_type as ContentType) ? (record.content_type as ContentType) : "other";
  const digest: Digest = {
    contentType,
    title: asString(record.title) ?? "",
    summary: rows(record.summary, (row) => {
      const text = asString(row.text);
      return text ? { text, spanIds: stringList(row.span_ids), basis: basis(row.basis), startMs: asFinite(row.start_ms) } : null;
    }),
    outcome: (() => {
      const row = asRecord(record.outcome);
      const text = row ? asString(row.text) : null;
      return row && text ? { text, spanIds: stringList(row.span_ids), basis: "transcript" as Basis, startMs: asFinite(row.start_ms) } : null;
    })(),
    speakers: rows(record.speakers, (row) => {
      const id = asString(row.id);
      const name = asString(row.name);
      return id && name ? { id, name, role: asString(row.role) } : null;
    }),
    perspectives: rows(record.perspectives, (row) => {
      const position = asString(row.position);
      return position ? { speaker: asString(row.speaker), position, spanIds: stringList(row.span_ids), startMs: asFinite(row.start_ms) } : null;
    }),
    chapters: rows(record.chapters, (row) => {
      const title = asString(row.title);
      const startMs = asFinite(row.start_ms);
      const endMs = asFinite(row.end_ms);
      if (!title || startMs === null || endMs === null) return null;
      return { title, gist: asString(row.gist) ?? "", startMs, endMs, startSpanId: asString(row.start_span_id) ?? "" };
    }),
    decisions: rows(record.decisions, (row) => {
      const statement = asString(row.statement);
      if (!statement) return null;
      const status = row.status === "agreed" || row.status === "deferred" ? row.status : "tentative";
      return { statement, status, by: asString(row.decided_by), spanIds: stringList(row.span_ids), basis: basis(row.basis), startMs: asFinite(row.start_ms) };
    }),
    actions: rows(record.actions, (row) => {
      const task = asString(row.task);
      if (!task) return null;
      return {
        task,
        owner: asString(row.assignee) ?? asString(row.owner),
        due: dueText(asString(row.due)),
        agreed: row.agreed === true,
        actionId: asString(row.action_id),
        spanIds: stringList(row.span_ids),
        basis: basis(row.basis),
        startMs: asFinite(row.start_ms),
      };
    }),
    questions: rows(record.open_questions, (row) => {
      const question = asString(row.question);
      const askedSpanId = asString(row.asked_span_id);
      if (!question || !askedSpanId) return null;
      return {
        question,
        askedBy: asString(row.asked_by),
        startMs: asFinite(row.start_ms),
        askedSpanId,
        answered: row.answered === true,
        answer: asString(row.answer),
        answerMs: asFinite(row.answer_ms),
        answerSpanId: asString(row.answer_span_id),
      };
    }),
    disagreements: rows(record.disagreements, (row) => {
      const topic = asString(row.topic);
      const positions = rows(row.positions, (item) => {
        const position = asString(item.position);
        return position ? { speaker: asString(item.speaker), position, spanIds: stringList(item.span_ids), startMs: asFinite(item.start_ms) } : null;
      });
      return topic && positions.length >= 2 ? { topic, positions, startMs: asFinite(row.start_ms) } : null;
    }),
    figures: rows(record.key_figures, (row) => {
      const value = asString(row.value);
      const what = asString(row.what);
      const spanId = asString(row.span_id);
      return value && what && spanId ? { value, what, spanId, startMs: asFinite(row.start_ms) } : null;
    }),
    risks: rows(record.risks, (row) => {
      const risk = asString(row.risk);
      return risk ? { risk, spanIds: stringList(row.span_ids), basis: basis(row.basis), startMs: asFinite(row.start_ms) } : null;
    }),
    concepts: rows(record.concepts, (row) => {
      const term = asString(row.term);
      return term
        ? { term, explanation: asString(row.explanation) ?? "", spanIds: stringList(row.span_ids), basis: basis(row.basis), startMs: asFinite(row.start_ms) }
        : null;
    }),
    diagram: (() => {
      const row = asRecord(record.diagram);
      const mermaid = row ? asString(row.mermaid) : null;
      if (!row || !mermaid) return null;
      return { kind: row.kind === "sequence" ? "sequence" : "flowchart", title: asString(row.title) ?? "", mermaid, startMs: asFinite(row.start_ms) };
    })(),
  };
  digest.chapters.sort((left, right) => left.startMs - right.startMs);
  return digest;
}

/** True when the digest has anything a reader would act on beyond the summary. */
export function hasOutcomes(digest: Digest): boolean {
  return digest.decisions.length + digest.actions.length + digest.questions.length + digest.disagreements.length > 0;
}

/** The chapter that contains a moment, for "you are here" in the player and transcript. */
export function chapterAt(chapters: Chapter[], ms: number): Chapter | null {
  let found: Chapter | null = null;
  for (const chapter of chapters) {
    if (chapter.startMs <= ms) found = chapter;
    else break;
  }
  return found;
}
