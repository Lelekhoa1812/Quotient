"use client";

/**
 * Motivation vs Logic
 * Motivation: submit_meeting returns a task before a meeting id exists. The
 * portal has to show that task, including input_required for the upload.
 * Logic: Poll tasks/get from the shared client. When the result carries a
 * meeting id, replace the route with the meeting workspace.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Progress } from "@/components/meeting/progress";
import { mcp } from "@/lib/mcp/client";
import type { TaskSnapshot } from "@/lib/types";

export function TaskScreen({ taskId }: { taskId: string }) {
  const router = useRouter();
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    setTask(mcp.taskSnapshot(taskId));
    mcp.watchTask(taskId);
    return mcp.subscribe(() => setTask(mcp.taskSnapshot(taskId)));
  }, [taskId]);

  useEffect(() => {
    if (task?.status === "completed" && task.meetingId) {
      router.replace(`/meetings/${task.meetingId}`);
    }
  }, [task, router]);

  // A task this browser has never heard of (a mistyped or expired link) must not look like work in progress.
  useEffect(() => {
    if (task) {
      setMissing(false);
      return;
    }
    const timer = setTimeout(() => setMissing(true), 6000);
    return () => clearTimeout(timer);
  }, [task]);

  const staged = mcp.stagedFiles(taskId);

  if (missing && !task) {
    return (
      <main id="main" tabIndex={-1} className="q-main">
        <section className="q-panel">
          <h2>We can't find this analysis</h2>
          <p className="q-muted">The link may be old, or the analysis may have been cleared. Your meetings are listed on the Meetings page.</p>
          <Link className="q-btn-ghost" href="/">Back to Meetings</Link>
        </section>
      </main>
    );
  }

  return (
    <main id="main" tabIndex={-1} className="q-main">
      <Progress
        meeting={null}
        task={task}
        onCancelTask={() => void mcp.cancelTask(taskId)}
        onCancelMeeting={() => {
          if (task?.meetingId) void mcp.cancelMeeting(task.meetingId);
        }}
      />
      {task?.status === "input_required" ? (
        <section className="q-panel">
          <h2>This meeting still needs its recording</h2>
          {staged.length > 0 ? <p>{staged.map((file) => file.name).join(", ")}</p> : <p className="q-muted">The recording is no longer attached in this tab. Choose it again.</p>}
          <label className="q-btn-ghost">
            Choose the recording
            <input
              className="q-sr"
              type="file"
              multiple
              onChange={(event) => {
                const next = [...(event.target.files ?? [])];
                setFiles(next);
                if (next.length > 0) mcp.attachFiles(taskId, next);
              }}
            />
          </label>
          {files.length > 0 ? <p>{files.map((file) => file.name).join(", ")} attached</p> : null}
        </section>
      ) : null}
    </main>
  );
}
