"use client";

/**
 * Motivation vs Logic
 * Motivation: Long work is an MCP task. The meeting screen shows that status
 * and the per-artifact ledger without a second job API.
 * Logic: Render tasks/get fields and get_meeting artifact statuses. Cancel
 * calls tasks/cancel or cancel_meeting.
 */
import { artifactLabel, statusLabel } from "@/lib/format";
import { ARTIFACT_ORDER, type MeetingStatus, type TaskSnapshot } from "@/lib/types";

export function Progress({
  meeting,
  task,
  onCancelTask,
  onCancelMeeting,
  onRestore,
}: {
  meeting: MeetingStatus | null;
  task: TaskSnapshot | null;
  onCancelTask: () => void;
  onCancelMeeting: () => void;
  onRestore: () => void;
}) {
  const fraction = task?.progress;
  const reviewOutcome = meeting?.status === "needs_review";
  return (
    <section className="q-cards">
      <h2>{statusLabel(meeting?.status || task?.status || "") || "Waiting"}</h2>
      {reviewOutcome ? <p>The written brief stays held while items are still open.</p> : null}
      {task?.progressMessage ? <p>{task.progressMessage}</p> : null}
      {task?.error ? <p role="alert">{task.error}</p> : null}
      <div className="q-bar" aria-hidden="true">
        <span style={{ width: fraction === null || fraction === undefined ? "0%" : `${Math.max(0, Math.min(1, fraction)) * 100}%` }} />
      </div>
      <table className="q-table">
        <thead>
          <tr>
            <th>Part</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {ARTIFACT_ORDER.map((name) => (
            <tr key={name}>
              <td>{artifactLabel(name)}</td>
              <td>{statusLabel(meeting?.artifacts[name] ?? "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="q-inline">
        {task && task.status !== "completed" && task.status !== "cancelled" && task.status !== "failed" ? (
          <button className="q-btn-ghost" type="button" onClick={onCancelTask}>Stop</button>
        ) : null}
        {meeting ? <button className="q-btn-ghost" type="button" onClick={onCancelMeeting}>Cancel meeting</button> : null}
        {meeting ? <button className="q-btn-ghost" type="button" onClick={onRestore}>Restore original</button> : null}
      </div>
    </section>
  );
}
