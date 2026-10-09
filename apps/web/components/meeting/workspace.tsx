"use client";

/**
 * Motivation vs Logic
 * Motivation: One screen per meeting: the recording on the left (always in view, captioned,
 * navigable by topic), and on the right what a reader needs, in order: the walkaway first, the
 * transcript second, the evidence behind it third, downloads behind an icon.
 * Logic: Load get_meeting and read_graph through the MCP client. The query keeps view and t.
 * Retired views (boards, synthesis, charts, disagreements) open the overview, which now carries
 * their useful content. Playback time is lifted here so the transcript follows the recording.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, AudioLines, BarChart3, Download, Inbox, Sparkles, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { friendlyError } from "@/lib/present";
import { Player, type PlayerHandle } from "@/components/meeting/player";
import { Transcript } from "@/components/meeting/transcript";
import { SameVoiceDialog } from "@/components/meeting/same-voice";
import { Overview } from "@/components/meeting/overview";
import { Insights } from "@/components/meeting/insights";
import { Review } from "@/components/meeting/review";
import { Exports } from "@/components/meeting/exports";
import { Progress } from "@/components/meeting/progress";
import { Inspector } from "@/components/meeting/inspector";
import { meetingTitle, statusLabel } from "@/lib/format";
import { durationText, speakerName, voiceNames } from "@/lib/present";
import { emptyGraph, firstCitation } from "@/lib/graph";
import { hideLibrary, readLibrary } from "@/lib/library";
import { McpDisconnected, mcp } from "@/lib/mcp/client";
import {
  isView,
  type Citation,
  type Claim,
  type Finding,
  type GraphPage,
  type MeetingStatus,
  type MeetingView,
  type Span,
  type SynthesisSentence,
  type TaskSnapshot,
} from "@/lib/types";

const NAV: { view: MeetingView; label: string; icon: typeof Activity }[] = [
  { view: "overview", label: "Overview", icon: Sparkles },
  { view: "insights", label: "Insights", icon: BarChart3 },
  { view: "transcript", label: "Transcript", icon: AudioLines },
  { view: "review", label: "Evidence", icon: Inbox },
];

// Views that used to exist open the overview, which now carries what was useful in them.
const RETIRED = new Set<MeetingView>(["board", "synthesis", "disagreements"]);

/** A rename that would give two voices the same name, waiting for the reader to say whether they are one person. */
type VoiceClash = {
  name: string;
  anchor: Span;
  other: Span;
  resolve: (outcome: void | PromiseLike<void>) => void;
};

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
  const [clash, setClash] = useState<VoiceClash | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [libraryName, setLibraryName] = useState({ title: "", filename: "" });
  const taskId = searchParams.get("task");
  const task = useTask(taskId);

  const requested = searchParams.get("view");
  const finished = meeting?.status === "ready" || meeting?.status === "needs_review";
  const asked: MeetingView | null = isView(requested) ? (requested === "charts" ? "insights" : RETIRED.has(requested) ? "overview" : requested) : null;
  const view: MeetingView = asked ?? (finished || !meeting ? "overview" : "progress");
  const [nowMs, setNowMs] = useState(0);

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
    playerRef.current?.seek(start, true); // a person asked to hear this moment
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

  /**
   * Renames a whole voice. If another voice already has that name, asks first: merge the two,
   * differ (the renamed voice becomes "<name> (ex)"), or cancel. Resolves once that is settled.
   */
  function renameVoice(anchor: Span, displayName: string): Promise<void> {
    const name = displayName.trim();
    const voice = anchor.speaker_hypothesis_id;
    const labelOf = (span: Span) => (span.speaker_hypothesis_id && names.get(span.speaker_hypothesis_id)) || speakerName(null, span.speaker_hypothesis_id);
    const other = voice
      ? graph.spans.find((span) => span.speaker_hypothesis_id && span.speaker_hypothesis_id !== voice && labelOf(span).toLowerCase() === name.toLowerCase())
      : undefined;
    if (!voice || !other) return run(() => mcp.reviseSpeaker(meetingId, anchor.id, "hypothesis", name));
    return new Promise<void>((resolve) => setClash({ name, anchor, other, resolve }));
  }

  function decideClash(choice: "merge" | "differ" | "cancel") {
    const current = clash;
    if (!current) return;
    setClash(null);
    if (choice === "cancel") {
      current.resolve();
      return;
    }
    if (choice === "merge") {
      current.resolve(run(() => mcp.mergeSpeakers(meetingId, current.anchor.id, current.other.id, current.name)));
      return;
    }
    const differName = /\(ex\)$/i.test(current.name) ? current.name : `${current.name} (ex)`;
    current.resolve(run(() => mcp.reviseSpeaker(meetingId, current.anchor.id, "hypothesis", differName)));
  }

  const selected = panel.phase !== "idle";
  const digest = graph.digest;
  const title = digest?.title || meetingTitle(libraryName.title, libraryName.filename || meeting?.sourceName || "", meetingId);
  const speakers = new Set(graph.spans.map((span) => span.speaker_hypothesis_id).filter(Boolean)).size;
  const spokenMs = Math.max(0, ...graph.spans.map((span) => span.end_ms ?? 0));
  const playAt = (ms: number) => seek(ms);
  const names = voiceNames(graph.spans, digest?.speakers ?? []);

  return (
    <div className="q-review">
      <aside className="q-stage" aria-label="Recording">
        <div className="q-stage-head">
          <h1>{title}</h1>
          <p className="q-stage-meta">
            {meeting?.status ? (
              <span className={meeting.status === "needs_review" ? "q-outcome is-review" : "q-outcome"}>{statusLabel(meeting.status)}</span>
            ) : null}
            {spokenMs > 0 ? <span>{durationText(spokenMs)}</span> : null}
            {speakers >= 2 ? <span>{speakers} speakers</span> : null}
          </p>
        </div>
        <Player
          ref={playerRef}
          playback={graph.playback}
          captions={graph.captions}
          chapters={digest?.chapters ?? []}
          loading={!loaded}
          status={meeting?.status ?? ""}
          onTime={setNowMs}
        />
        {panel.citation?.quote ? (
          <p className="q-quote"><span className="q-sr">Cited quote</span><mark>{panel.citation.quote}</mark></p>
        ) : null}
        <p className="q-keys q-faint">Space play/pause · J/L ±10 s · ←/→ ±5 s · C captions</p>
      </aside>
      <div id="main" tabIndex={-1} className="q-pane-right">
        <div className="q-tabbar">
          <nav className="q-tabs-main" aria-label="Meeting sections">
            {NAV.map((item) => {
              const Icon = item.icon;
              const on = view === item.view;
              return (
                <button key={item.view} type="button" aria-current={on ? "page" : undefined} className={on ? "q-maintab is-on" : "q-maintab"} onClick={() => setQuery("view", item.view)}>
                  <Icon size={15} aria-hidden="true" />
                  {item.label}
                  {item.view === "review" && meeting?.reviewCount ? <span className="q-count" aria-label={`${meeting.reviewCount} statements not confirmed`}>{meeting.reviewCount}</span> : null}
                </button>
              );
            })}
          </nav>
          <div className="q-tab-tools">
            {working || view === "progress" ? (
              <button type="button" className={view === "progress" ? "q-icon-btn is-on" : "q-icon-btn"} title="Analysis status" aria-label="Analysis status" onClick={() => setQuery("view", "progress")}>
                <Activity size={16} aria-hidden="true" />
              </button>
            ) : null}
            <button type="button" className={view === "exports" ? "q-icon-btn is-on" : "q-icon-btn"} title="Downloads" aria-label="Downloads" onClick={() => setQuery("view", "exports")}>
              <Download size={16} aria-hidden="true" />
            </button>
            <button type="button" className="q-icon-btn" title="Delete meeting" aria-label="Delete meeting" onClick={() => setConfirmRemove(true)}>
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
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
          {loaded && view === "overview" ? (
            <Overview
              digest={digest}
              names={names}
              spans={graph.spans}
              claims={graph.claims}
              actions={graph.actions}
              synthesis={graph.synthesis}
              status={meeting?.status ?? null}
              context={meeting?.context ?? null}
              onPlay={playAt}
              onAccept={(actionId) => fire(() => mcp.acceptAction(meetingId, actionId))}
              onGo={(next) => setQuery("view", next)}
              onRenameVoice={(voiceId, displayName) => {
                const anchor = graph.spans.find((span) => span.speaker_hypothesis_id === voiceId);
                if (!anchor) return Promise.resolve();
                return renameVoice(anchor, displayName);
              }}
            />
          ) : null}
          {loaded && view === "insights" ? <Insights spans={graph.spans} claims={graph.claims} digest={digest} names={names} onPlay={playAt} /> : null}
          {loaded && view === "transcript" ? (
            <Transcript
              spans={graph.spans}
              names={names}
              observations={graph.observations}
              chapters={digest?.chapters ?? []}
              nowMs={nowMs}
              activeId={panel.span?.id ?? null}
              citation={panel.citation}
              onSeek={onSeekSpan}
              onReviseText={(span, text) => run(() => mcp.reviseText(meetingId, span.id, text), false)}
              onReviseSpeaker={(span, scope, displayName) =>
                scope === "hypothesis" ? renameVoice(span, displayName) : run(() => mcp.reviseSpeaker(meetingId, span.id, scope, displayName), false)
              }
            />
          ) : null}
          {loaded && view === "review" ? (
            <Review
              claims={graph.claims}
              names={names}
              review={graph.review}
              reviewPresent={graph.review_present}
              meeting={meeting}
              gaps={graph.gaps}
              spans={graph.spans}
              onSeek={onSeekClaim}
              onSeekSpan={onSeekSpan}
            />
          ) : null}
          {loaded && view === "exports" ? <Exports meetingId={meetingId} artifacts={graph.exports} renderedReady={meeting?.artifacts.exports === "ready"} /> : null}
        </main>
      </div>
      <ConfirmDialog
        open={confirmRemove}
        title="Delete this meeting from your list?"
        message="The recording and its analysis are not deleted."
        confirmLabel="Delete"
        cancelLabel="Keep"
        onConfirm={() => {
          setConfirmRemove(false);
          hideLibrary({ meetingId, taskId });
          router.push("/");
        }}
        onCancel={() => setConfirmRemove(false)}
      />
      <SameVoiceDialog
        open={clash !== null}
        name={clash?.name ?? ""}
        onMerge={() => decideClash("merge")}
        onDiffer={() => decideClash("differ")}
        onCancel={() => decideClash("cancel")}
      />
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
