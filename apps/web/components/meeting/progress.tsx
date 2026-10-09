"use client";

/**
 * Motivation vs Logic
 * Motivation: While a meeting is analysed, people want to know whether it is
 * working, roughly where it is, and whether it finished. Internal artifact names
 * and statuses mean nothing to them.
 * Logic: Render the task fields and the six artifact states as four plain steps.
 * The bar stays indeterminate while model work runs, because the number of calls
 * depends on the transcript. Stopping asks for confirmation. Server error text is
 * mapped to a sentence; the raw text stays in logs.
 */
import { useState } from "react";
import { statusLabel } from "@/lib/format";
import { ANALYSIS_STEPS, analysisStepIndex, friendlyError } from "@/lib/present";
import type { MeetingStatus, TaskSnapshot } from "@/lib/types";

function stepState(index: number, current: number, finished: boolean): "done" | "now" | "later" {
  if (finished) return "done";
  if (current < 0) return index === 0 ? "now" : "later";
  return index < current ? "done" : index === current ? "now" : "later";
}

export function Progress({
  meeting,
  task,
  onCancelTask,
  onCancelMeeting,
}: {
  meeting: MeetingStatus | null;
  task: TaskSnapshot | null;
  onCancelTask: () => void;
  onCancelMeeting: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const finished = meeting?.status === "ready" || meeting?.status === "needs_review";
  const inProgress = task?.status === "working" || meeting?.status === "queued" || meeting?.status === "working";
  const fraction = task?.progress ?? (finished ? 1 : null);
  const failed = meeting?.status === "failed" || task?.status === "failed";
  const stopped = meeting?.status === "cancelled" || task?.status === "cancelled";
  const message = task?.progressMessage || meeting?.progressMessage || task?.statusMessage || "";
  const headline = stopped
    ? "This analysis was stopped"
    : failed
    ? "The analysis could not finish"
    : finished
      ? meeting?.status === "ready"
        ? "The analysis is complete"
        : "The analysis is complete, with some points to check"
      : inProgress
        ? "Analysing the recording"
        : statusLabel(meeting?.status || task?.status || "") || "Waiting to start";
  const active = inProgress && !finished && !failed && !stopped;
  const current = analysisStepIndex(message);

  return (
    <section className="q-cards">
      <div>
        <h2>{headline}</h2>
        {active ? <p className="q-lede">This usually takes several minutes for a long recording. You can leave this page and come back.</p> : null}
        {message && !failed && !stopped ? <p className="q-muted" role="status">{message}</p> : null}
      </div>
      {failed ? (
        <p className="q-notice" role="alert">
          {friendlyError(task?.error || meeting?.failureMessage, "Something went wrong while analysing this recording.")} You can upload the recording again to retry.
        </p>
      ) : null}
      <div
        className={active ? "q-bar is-indeterminate" : "q-bar"}
        role="progressbar"
        aria-label="Analysis progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={active ? undefined : fraction === null || fraction === undefined ? 0 : Math.max(0, Math.min(1, fraction)) * 100}
      >
        <span style={active ? undefined : { width: fraction === null || fraction === undefined ? "0%" : `${Math.max(0, Math.min(1, fraction)) * 100}%` }} />
      </div>
      <ol className="q-steps">
        {ANALYSIS_STEPS.map((label, index) => {
          const state = failed || stopped ? "later" : stepState(index, current, finished);
          return (
            <li key={label} data-state={state}>
              <span className="q-step-mark" aria-hidden="true">{state === "done" ? "✓" : state === "now" ? "…" : ""}</span>
              {label}
              <span className="q-sr">{state === "done" ? " (done)" : state === "now" ? " (in progress)" : " (waiting)"}</span>
            </li>
          );
        })}
      </ol>
      {(meeting || task) && !finished && !failed && !stopped ? (
        confirming ? (
          <div className="q-inline" role="group" aria-label="Confirm stopping the analysis">
            <span>Stop the analysis? Work done so far will be lost.</span>
            <button
              className="q-btn"
              type="button"
              onClick={() => {
                setConfirming(false);
                if (task && task.status !== "completed" && task.status !== "cancelled" && task.status !== "failed") onCancelTask();
                onCancelMeeting();
              }}
            >
              Yes, stop
            </button>
            <button className="q-btn-ghost" type="button" onClick={() => setConfirming(false)}>Keep going</button>
          </div>
        ) : (
          <div className="q-inline">
            <button className="q-btn-ghost" type="button" onClick={() => setConfirming(true)}>Stop the analysis</button>
          </div>
        )
      ) : null}
    </section>
  );
}
