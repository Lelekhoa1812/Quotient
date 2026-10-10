/**
 * Motivation vs Logic
 * Motivation: A screen card knows its page and its figures. The reading — what that screen was for in the
 * talk, and where the screen and the talk disagree — is written later and stored apart, keyed by screen id.
 * Logic: Join on the card's merged ids, or on a start time that falls inside the card. Prefer a reading
 * that cites the talk. Keep at most two distinct readings and two difference sentences, so a merged page
 * does not become a second transcript.
 */
import type { ScreenUse } from "@/lib/digest";
import type { ScreenCard } from "@/lib/screens";

export function attachReadings(cards: ScreenCard[], uses: ScreenUse[]): ScreenCard[] {
  if (uses.length === 0) return cards;
  return cards.map((card) => {
    const hits = uses.filter((use) => card.ids.includes(use.id) || (use.startMs !== null && use.startMs >= card.startMs && use.startMs < card.endMs));
    if (hits.length === 0) return card;
    const spoken = hits.filter((use) => use.spanIds.length > 0);
    const chosen = spoken.length > 0 ? spoken : hits;
    const reading = [...new Set(chosen.map((use) => use.reading))].slice(0, 2).join(" ");
    const differs = [...new Set(hits.map((use) => use.differs).filter((item): item is string => Boolean(item)))].slice(0, 2).join(" ");
    return { ...card, reading, differs: differs || null };
  });
}
