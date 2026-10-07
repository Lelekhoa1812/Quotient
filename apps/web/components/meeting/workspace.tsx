"use client";

/**
 * Motivation vs Logic
 * Motivation: One meeting route carries the player, the ten boards, and the
 * brief. A synthesis click has to seek without leaving the graph.
 * Logic: Load get_meeting and read_graph through the MCP client. The query
 * keeps view, dimension, and t. The inspector opens findings, then the span.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, AudioLines, BarChart3, Download, GitBranch, Inbox, LayoutGrid, TextQuote } from "lucide-react";
import { Player, type PlayerHandle } from "@/components/meeting/player";
import { Timeline } from "@/components/meeting/timeline";
import { Transcript } from "@/components/meeting/transcript";
import { Boards } from "@/components/meeting/boards";
import { Synthesis } from "@/components/meeting/synthesis";
import { Disagreements } from "@/components/meeting/disagreements";
import { Review } from "@/components/meeting/review";
import { Charts } from "@/components/meeting/charts";
import { Exports } from "@/components/meeting/exports";
import { Progress } from "@/components/meeting/progress";
import { Inspector } from "@/components/meeting/inspector";
import { meetingTitle, statusLabel } from "@/lib/format";
import { emptyGraph, firstCitation } from "@/lib/graph";
import { readLibrary } from "@/lib/library";
import { McpDisconnected, mcp } from "@/lib/mcp/client";
import {
  isDimension,
  isView,
  type Citation,
  type Claim,
  type Dimension,
  type Finding,
  type GraphPage,
  type MeetingStatus,
  type MeetingView,
  type Span,
  type SynthesisSentence,
  type TaskSnapshot,
} from "@/lib/types";

const NAV: { view: MeetingView; label: string; icon: typeof Activity }[] = [
  { view: "progress", label: "Progress", icon: Activity },
  { view: "transcript", label: "Transcript", icon: AudioLines },
  { view: "board", label: "Boards", icon: LayoutGrid },
  { view: "synthesis", label: "Synthesis", icon: TextQuote },
  { view: "disagreements", label: "Disagreements", icon: GitBranch },
  { view: "review", label: "Review", icon: Inbox },
  { view: "charts", label: "Charts", icon: BarChart3 },
  { view: "exports", label: "Exports", icon: Download },
];

type Panel = {
  sentenceId: string | null;
  findings: Finding[];
  span: Span | null;
  citation: Citation | null;
  phase: "idle" | "findings" | "span";
};

const idlePanel: Panel = { sentenceId: null, findings: [], span: null, citation: null, phase: "idle" };

export function Workspace({ meetingId }: { meetingId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const playerRef = useRef<PlayerHandle>(null);
  const [graph, setGraph] = useState<GraphPage>(emptyGraph);
  const [meeting, setMeeting] = useState<MeetingStatus | null>(null);
  const [panel, setPanel] = useState<Panel>(idlePanel);
  const [notice, setNotice] = useState("");
  const [libraryName, setLibraryName] = useState({ title: "", filename: "" });
  const taskId = searchParams.get("task");
  const task = useTask(taskId);

  const requested = searchParams.get("view");
  const view: MeetingView = isView(requested)
    ? requested
    : meeting && (meeting.status === "ready" || meeting.status === "needs_review")
      ? "synthesis"
      : "progress";
  const dimensionParam = searchParams.get("dimension");
  const dimension: Dimension = dimensionParam && isDimension(dimensionParam) ? dimensionParam : "decision";

  useEffect(() => {
    const row = readLibrary().find((item) => item.meetingId === meetingId);
    setLibraryName({ title: row?.title ?? "", filename: row?.filename ?? "" });
  }, [meetingId]);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        await mcp.connect();
        const [status, page] = await Promise.all([mcp.getMeeting(meetingId), mcp.readGraph(meetingId)]);
        if (cancel) return;
        setMeeting(status);
        setGraph(page);
      } catch (error) {
        if (cancel || error instanceof McpDisconnected) return;
        setNotice("This meeting could not be opened.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [meetingId]);

  useEffect(() => {
    const raw = searchParams.get("t");
    if (!raw) return;
    const start = Number(raw);
    if (!Number.isFinite(start)) return;
    playerRef.current?.seek(start);
  }, [searchParams, graph]);

  function setQuery(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set(key, value);
    router.replace(`/meetings/${meetingId}?${params.toString()}`, { scroll: false });
  }

  function seek(start: number) {
    playerRef.current?.seek(start);
    setQuery("t", String(Math.round(start)));
  }

  async function onOpenSentence(sentence: SynthesisSentence) {
    const findings = graph.findings.filter((finding) => sentence.finding_ids.includes(finding.id));
    setPanel({ sentenceId: sentence.id, findings, span: null, citation: null, phase: "findings" });
    if (sentence.start_ms !== null) seek(sentence.start_ms);
    const citation = firstCitation(findings, graph.claims);
    if (!citation) return;
    let span = graph.spans.find((item) => item.id === citation.span_id) ?? null;
    try {
      const fresh = await mcp.readSpan(meetingId, citation.span_id);
      if (fresh) span = fresh;
    } catch {
      // Keep the span already on the graph page.
    }
    setPanel({ sentenceId: sentence.id, findings, span, citation, phase: "span" });
    const start = span?.start_ms ?? citation.start_ms ?? sentence.start_ms;
    if (start !== null) seek(start);
  }

  function onSeekSpan(span: Span) {
    const citation = citationFor(graph.claims, span.id);
    setPanel((current) => ({
      sentenceId: current.sentenceId,
      findings: current.findings,
      span,
      citation,
      phase: "span",
    }));
    if (span.start_ms !== null) seek(span.start_ms);
  }

  function onSeekClaim(claim: Claim) {
    const citation = claim.citations.find((item) => item.start_ms !== null) ?? claim.citations[0] ?? null;
    if (!citation) return;
    const span = graph.spans.find((item) => item.id === citation.span_id) ?? null;
    setPanel({ sentenceId: null, findings: [], span, citation, phase: "span" });
    const start = span?.start_ms ?? citation.start_ms;
    if (start !== null) seek(start);
  }

  async function reload() {
    const [status, page] = await Promise.all([mcp.getMeeting(meetingId), mcp.readGraph(meetingId)]);
    setMeeting(status);
    setGraph(page);
  }

  async function run(action: () => Promise<void>) {
    setNotice("");
    try {
      await action();
      await reload();
    } catch (error) {
      setNotice("That action did not complete.");
    }
  }

  return (
    <div className="q-meet">
      <div className="q-dock">
        <div className="q-dock-head">
          <div>
            <h1>{meetingTitle(libraryName.title, libraryName.filename, meetingId)}</h1>
          </div>
          {meeting?.status ? (
            <p className={meeting.status === "needs_review" ? "q-outcome is-review" : "q-outcome"}>{statusLabel(meeting.status)}</p>
          ) : null}
        </div>
        {meeting?.status === "needs_review" ? (
          <p className="q-muted">The written brief is held until the open items are checked.</p>
        ) : null}
        <Player ref={playerRef} playback={graph.playback} />
        {panel.citation?.quote ? (
          <p className="q-quote"><span className="q-sr">Cited quote</span><mark>{panel.citation.quote}</mark></p>
        ) : null}
        <Timeline spans={graph.spans} seams={graph.seams} activeId={panel.span?.id ?? null} onSeek={onSeekSpan} />
      </div>
      <nav className="q-nav" aria-label="Meeting sections">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.view} type="button" aria-current={view === item.view ? "page" : undefined} onClick={() => setQuery("view", item.view)}>
              <Icon size={16} aria-hidden="true" />
              {item.label}
              {item.view === "review" && meeting?.reviewCount ? <span className="q-badge">{meeting.reviewCount}</span> : null}
            </button>
          );
        })}
      </nav>
      <main className="q-main">
        {notice ? <p role="alert">{notice}</p> : null}
        {view === "progress" ? (
          <Progress
            meeting={meeting}
            task={task}
            onCancelTask={() => {
              if (taskId) void run(() => mcp.cancelTask(taskId));
            }}
            onCancelMeeting={() => void run(() => mcp.cancelMeeting(meetingId))}
            onRestore={() => void run(() => mcp.restoreGraph(meetingId))}
          />
        ) : null}
        {view === "transcript" ? (
          <Transcript
            spans={graph.spans}
            seams={graph.seams}
            omissions={graph.omissions}
            rawTranscript={graph.rawTranscript}
            observations={graph.observations}
            speakers={graph.speakers}
            synthesis={graph.synthesis}
            activeId={panel.span?.id ?? null}
            citation={panel.citation}
            onSeek={onSeekSpan}
            onOpenSentence={(sentence) => void onOpenSentence(sentence)}
            onReviseText={(span, text) => run(() => mcp.reviseText(meetingId, span.id, text))}
            onReviseSpeaker={(span, scope, displayName) => run(() => mcp.reviseSpeaker(meetingId, span.id, scope, displayName))}
          />
        ) : null}
        {view === "board" ? (
          <Boards
            dimension={dimension}
            findings={graph.findings}
            none={graph.none_in_transcript}
            claims={graph.claims}
            actions={graph.actions}
            spans={graph.spans}
            onDimension={(next) => setQuery("dimension", next)}
            onSeekClaim={onSeekClaim}
            onSeekSpan={onSeekSpan}
            onAccept={(actionId) => void run(() => mcp.acceptAction(meetingId, actionId))}
          />
        ) : null}
        {view === "synthesis" ? (
          <Synthesis
            sentences={graph.synthesis}
            omissions={graph.synthesis_omissions}
            findings={graph.findings}
            activeId={panel.sentenceId}
            onOpen={(sentence) => void onOpenSentence(sentence)}
          />
        ) : null}
        {view === "disagreements" ? (
          <Disagreements
            rows={graph.disagreements}
            onSeek={(spanId) => {
              const span = graph.spans.find((item) => item.id === spanId);
              if (span) onSeekSpan(span);
              else setNotice("That moment is not on this page.");
            }}
          />
        ) : null}
        {view === "review" ? (
          <Review
            claims={graph.claims}
            review={graph.review}
            reviewPresent={graph.review_present}
            meeting={meeting}
            onSeek={onSeekClaim}
          />
        ) : null}
        {view === "charts" ? (
          <Charts
            charts={graph.charts}
            spanIds={graph.spans.map((span) => span.id)}
            onSeek={(spanId) => {
              const span = graph.spans.find((item) => item.id === spanId);
              if (span) onSeekSpan(span);
            }}
          />
        ) : null}
        {view === "exports" ? <Exports meetingId={meetingId} artifacts={graph.exports} /> : null}
      </main>
      <Inspector findings={panel.findings} span={panel.span} citation={panel.citation} phase={panel.phase} />
    </div>
  );
}

function citationFor(claims: Claim[], spanId: string): Citation | null {
  for (const claim of claims) {
    const hit = claim.citations.find((item) => item.span_id === spanId);
    if (hit) return hit;
  }
  return null;
}

function useTask(taskId: string | null): TaskSnapshot | null {
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  useEffect(() => {
    if (!taskId) return;
    setTask(mcp.taskSnapshot(taskId));
    mcp.watchTask(taskId);
    return mcp.subscribe(() => setTask(mcp.taskSnapshot(taskId)));
  }, [taskId]);
  return task;
}
