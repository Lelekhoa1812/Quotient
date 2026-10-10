/**
 * Motivation vs Logic
 * Motivation: The Overview used to list topics, screens, ideas, questions and figures as separate blocks, so a reader had to work out
 * for themselves which screen illustrated which idea and which question belonged to which stretch of the meeting.
 * Logic: Put each item where it happened. Every topic (chapter) becomes one timeline of what was shown, which questions were answered,
 * which ideas were explained and which figures were stated, in time order. Placement is plain arithmetic on the item's start time, never
 * a model's guess. Items that need action (open questions, actions, risks) stay in their own sections near the top and only point back
 * to their topic, so nothing appears twice.
 */
import type { Chapter, Concept, Diagram, Digest, Figure, Question } from "@/lib/digest";
import type { ScreenCard } from "@/lib/screens";

export type StoryRow =
  | { kind: "screen"; ms: number; card: ScreenCard }
  | { kind: "folded"; ms: number; cards: ScreenCard[] }
  | { kind: "answer"; ms: number; question: Question }
  | { kind: "idea"; ms: number; concept: Concept }
  | { kind: "figure"; ms: number; figure: Figure }
  | { kind: "diagram"; ms: number; diagram: Diagram };

export type Topic = {
  index: number;
  chapter: Chapter;
  rows: StoryRow[];
  counts: { screens: number; answered: number; open: number; actions: number; ideas: number };
};

/** A screen that appears this close before a boundary belongs to the topic that is starting (the chapter strip lags the picture). */
export const BOUNDARY_SLACK_MS = 5000;

const ORDER: Record<StoryRow["kind"], number> = { screen: 0, folded: 1, answer: 2, idea: 3, figure: 4, diagram: 5 };

/** The topic a moment falls in: the last chapter that has started by then. Before the first chapter it is the first. */
export function topicIndex(chapters: Chapter[], ms: number | null): number | null {
  if (chapters.length === 0 || ms === null) return null;
  let found = 0;
  for (let index = 0; index < chapters.length; index += 1) {
    if (chapters[index].startMs <= ms) found = index;
  }
  return found;
}

function screenTopic(chapters: Chapter[], startMs: number): number | null {
  const own = topicIndex(chapters, startMs);
  if (own === null) return null;
  const next = chapters[own + 1];
  return next && next.startMs - startMs <= BOUNDARY_SLACK_MS && next.startMs > startMs ? own + 1 : own;
}

export function buildStoryline(digest: Digest, cards: ScreenCard[]): Topic[] {
  const topics: Topic[] = digest.chapters.map((chapter, index) => ({
    index,
    chapter,
    rows: [],
    counts: { screens: 0, answered: 0, open: 0, actions: 0, ideas: 0 },
  }));
  if (topics.length === 0) return topics;
  const put = (index: number | null, row: StoryRow) => {
    if (index !== null) topics[index].rows.push(row);
  };

  const folded = new Map<number, ScreenCard[]>();
  for (const card of cards) {
    const index = screenTopic(digest.chapters, card.startMs);
    if (index === null) continue;
    if (card.folded) {
      folded.set(index, [...(folded.get(index) ?? []), card]);
    } else {
      put(index, { kind: "screen", ms: card.startMs, card });
      topics[index].counts.screens += 1;
    }
  }
  for (const [index, group] of folded) put(index, { kind: "folded", ms: group[0].startMs, cards: group });

  for (const question of digest.questions) {
    const index = topicIndex(digest.chapters, question.startMs);
    if (index === null) continue;
    if (question.answered) {
      put(index, { kind: "answer", ms: question.startMs ?? 0, question });
      topics[index].counts.answered += 1;
    } else {
      topics[index].counts.open += 1;
    }
  }
  for (const concept of digest.concepts) {
    const index = topicIndex(digest.chapters, concept.startMs);
    put(index, { kind: "idea", ms: concept.startMs ?? 0, concept });
    if (index !== null) topics[index].counts.ideas += 1;
  }
  for (const figure of digest.figures) put(topicIndex(digest.chapters, figure.startMs), { kind: "figure", ms: figure.startMs ?? 0, figure });
  if (digest.diagram) put(topicIndex(digest.chapters, digest.diagram.startMs), { kind: "diagram", ms: digest.diagram.startMs ?? 0, diagram: digest.diagram });
  for (const action of digest.actions) {
    const index = topicIndex(digest.chapters, action.startMs);
    if (index !== null) topics[index].counts.actions += 1;
  }

  for (const topic of topics) topic.rows.sort((left, right) => left.ms - right.ms || ORDER[left.kind] - ORDER[right.kind]);
  return topics;
}
