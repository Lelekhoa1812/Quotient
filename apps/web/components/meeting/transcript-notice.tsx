"use client";

/**
 * Motivation vs Logic
 * Motivation: A meeting made from a transcript has no recording to play. The page should say plainly
 * what the meeting was made from, in the place the player would otherwise take.
 * Logic: One line from transcriptNotice (format, speakers, words). When the times were estimated from
 * the word count rather than read from the file, a second line says so. Nothing here plays or seeks.
 */
import { FileText } from "lucide-react";
import { transcriptNotice } from "@/lib/graph";
import type { MeetingSource } from "@/lib/types";

export function TranscriptNotice({ source }: { source: MeetingSource }) {
  const { line, estimate } = transcriptNotice(source);
  return (
    <div className="q-transcript-note" role="status">
      <FileText size={16} aria-hidden="true" />
      <div>
        <p>{line}</p>
        {estimate ? <p className="q-muted">{estimate}</p> : null}
      </div>
    </div>
  );
}
