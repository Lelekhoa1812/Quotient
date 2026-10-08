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
import { friendlyError } from "@/lib/present";
import { Player, type PlayerHandle } from "@/components/meeting/player";
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
  { view: "synthesis", label: "Brief", icon: TextQuote },
  { view: "board", label: "Key points", icon: LayoutGrid },
  { view: "transcript", label: "Transcript", icon: AudioLines },
  { view: "review", label: "To check", icon: Inbox },
  { view: "charts", label: "Insights", icon: BarChart3 },
  { view: "disagreements", label: "Audio vs video", icon: GitBranch },
  { view: "exports", label: "Downloads", icon: Download },
  { view: "progress", label: "Status", icon: Activity },
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
  const [loaded, setLoaded] = useState(false);
  const [libraryName, setLibraryName] = useState({ title: "", filename: "" });
  const taskId = searchParams.get("task");
  const task = useTask(taskId);

  const requested = searchParams.get("view");
  const finished = meeting?.status === "ready" || meeting?.status === "needs_review";
  const view: MeetingView = isView(requested) ? requested : finished ? "synthesis" : "progress";
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
        setLoaded(true);
      } catch (error) {
        if (cancel || error instanceof McpDisconnected) return;
        setNotice("This meeting could not be opened. Check your connection and reload the page.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [meetingId]);

  // Bugs vs Fixes
  // Bug: This effect depended on all search params and the graph, so every tab change or
  // reload() seeked the player back to the last clicked time.
  // Fix: Seek only when the "t" value itself is new. seek() records the value it sets.
  const requestedTime = searchParams.get("t");
  const handledTime = useRef<string | null>(null);
  useEffect(() => {
    if (!loaded || !requestedTime || handledTime.current === requestedTime) return;
    handledTime.current = requestedTime;
    const start = Number(requestedTime);
    if (Number.isFinite(start)) playerRef.current?.seek(start);
  }, [loaded, requestedTime]);

  // A meeting opened mid-analysis refreshes itself until it reaches a final status.
  const working = meeting?.status === "queued" || meeting?.status === "working";
  useEffect(() => {
    if (!loaded || !working) return;
    const timer = window.setInterval(() => {
      void mcp
        .getMeeting(meetingId)
        .then(async (status) => {
          setMeeting(status);
          if (status.status !== "queued" && status.status !== "working") setGraph(await mcp.readGraph(meetingId));
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [loaded, working, meetingId]);

  function setQuery(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set(key, value);
    router.replace(`/meetings/${meetingId}?${params.toString()}`, { scroll: false });
  }

  function seek(start: number) {
    playerRef.current?.seek(start);
    const value = String(Math.round(start));
    handledTime.current = value;
    setQuery("t", value);
  }

  const openToken = useRef(0);
  // Closing the evidence panel unmounts the control that opened it; give focus back to that control.
  const trigger = useRef<HTMLElement | null>(null);
  function rememberFocus() {
    if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
      trigger.current = document.activeElement;
    }
  }

  async function onOpenSentence(sentence: SynthesisSentence) {
    rememberFocus();
    const token = (openToken.current += 1);
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
    if (token !== openToken.current) return; // a later click superseded this one
    setPanel({ sentenceId: sentence.id, findings, span, citation, phase: "span" });
    const start = span?.start_ms ?? citation.start_ms ?? sentence.start_ms;
    if (start !== null) seek(start);
  }

  function onSeekSpan(span: Span) {
    rememberFocus();
    openToken.current += 1;
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
    rememberFocus();
    openToken.current += 1;
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

  // `notify` is false where the caller shows the error next to the control that failed.
  async function run(action: () => Promise<void>, notify = true) {
    setNotice("");
    try {
      await action();
    } catch (error) {
      if (notify) setNotice(friendlyError(error instanceof Error ? error.message : null, "That did not go through. Please try again."));
      throw error;
    }
    try {
      await reload();
    } catch {
      setNotice("Your change was saved, but the page could not refresh. Reload to see it.");
    }
  }

  function fire(action: () => Promise<void>) {
    void run(action).catch(() => undefined);
  }

  const selected = panel.phase !== "idle";

  return (
    <div className={selected ? "q-meet has-evidence" : "q-meet"}>
      <div className="q-dock">
        <div className="q-dock-head">
          <div>
            <h1>{meetingTitle(libraryName.title, libraryName.filename || meeting?.sourceName || "", meetingId)}</h1>
          </div>
          {meeting?.status ? (
            <p className={meeting.status === "needs_review" ? "q-outcome is-review" : "q-outcome"}>{statusLabel(meeting.status)}</p>
          ) : null}
        </div>
        <Player ref={playerRef} playback={graph.playback} loading={!loaded} status={meeting?.status ?? ""} />
        {panel.citation?.quote ? (
          <p className="q-quote"><span className="q-sr">Cited quote</span><mark>{panel.citation.quote}</mark></p>
        ) : null}
      </div>
      <nav className="q-nav" aria-label="Meeting sections">
        {NAV.filter((item) => item.view !== "disagreements" || graph.disagreements.length > 0 || view === "disagreements").map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.view} type="button" aria-current={view === item.view ? "page" : undefined} onClick={() => setQuery("view", item.view)}>
              <Icon size={16} aria-hidden="true" />
              {item.label}
              {item.view === "review" && meeting?.reviewCount ? <span className="q-badge" aria-label={`${meeting.reviewCount} items to check`}>{meeting.reviewCount}</span> : null}
            </button>
          );
        })}
      </nav>
      <main className="q-main">
        {notice ? <p className="q-notice" role="alert">{notice}</p> : null}
        {!loaded && !notice ? <p className="q-muted" role="status">Loading the meeting…</p> : null}
        {loaded && view === "progress" ? (
          <Progress
            meeting={meeting}
            task={task}
            onCancelTask={() => {
              if (taskId) fire(() => mcp.cancelTask(taskId));
            }}
            onCancelMeeting={() => fire(() => mcp.cancelMeeting(meetingId))}
          />
        ) : null}
        {loaded && view === "transcript" ? (
          <Transcript
            spans={graph.spans}
            observations={graph.observations}
            activeId={panel.span?.id ?? null}
            citation={panel.citation}
            onSeek={onSeekSpan}
            onReviseText={(span, text) => run(() => mcp.reviseText(meetingId, span.id, text), false)}
            onReviseSpeaker={(span, scope, displayName) => run(() => mcp.reviseSpeaker(meetingId, span.id, scope, displayName), false)}
          />
        ) : null}
        {loaded && view === "board" ? (
          <Boards
            dimension={dimension}
            findings={graph.findings}
            none={graph.none_in_transcript}
            notEvaluated={graph.not_evaluated}
            held={graph.held}
            unconfirmed={meeting?.reviewCount ?? 0}
            incomplete={graph.gaps.length > 0 || graph.spans.some((span) => span.kind === "untranscribed")}
            claims={graph.claims}
            actions={graph.actions}
            spans={graph.spans}
            onDimension={(next) => setQuery("dimension", next)}
            onSeekClaim={onSeekClaim}
            onSeekSpan={onSeekSpan}
            onAccept={(actionId) => fire(() => mcp.acceptAction(meetingId, actionId))}
          />
        ) : null}
        {loaded && view === "synthesis" ? (
          <Synthesis
            sentences={graph.synthesis}
            omissions={graph.synthesis_omissions}
            findings={graph.findings}
            activeId={panel.sentenceId}
            status={meeting?.status ?? null}
            reviewCount={meeting?.reviewCount ?? null}
            speechLines={graph.spans.filter((span) => span.kind === "speech" && (span.text.trim() || span.raw_text.trim())).length}
            onOpen={(sentence) => void onOpenSentence(sentence)}
            onGo={(next) => setQuery("view", next)}
          />
        ) : null}
        {loaded && view === "disagreements" ? (
          <Disagreements
            rows={graph.disagreements}
            onSeek={(spanId) => {
              const span = graph.spans.find((item) => item.id === spanId);
              if (span) onSeekSpan(span);
              else setNotice("That moment is not on this page.");
            }}
          />
        ) : null}
        {loaded && view === "review" ? (
          <Review
            claims={graph.claims}
            review={graph.review}
            reviewPresent={graph.review_present}
            meeting={meeting}
            gaps={graph.gaps}
            spans={graph.spans}
            onSeek={onSeekClaim}
            onSeekSpan={onSeekSpan}
          />
        ) : null}
        {loaded && view === "charts" ? (
          <Charts graph={graph} unconfirmed={meeting?.reviewCount ?? 0} onSeekSpan={onSeekSpan} onSeekMs={seek} />
        ) : null}
        {loaded && view === "exports" ? <Exports meetingId={meetingId} artifacts={graph.exports} renderedReady={meeting?.artifacts.exports === "ready"} /> : null}
      </main>
      {selected ? (
        <Inspector
          findings={panel.findings}
          span={panel.span}
          citation={panel.citation}
          phase={panel.phase}
          onClose={() => {
            setPanel(idlePanel);
            const target = trigger.current;
            if (target && document.contains(target)) requestAnimationFrame(() => target.focus());
          }}
        />
      ) : null}
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
