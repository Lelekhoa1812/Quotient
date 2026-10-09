import assert from "node:assert/strict";
import test from "node:test";
import { reconcileOrphans, type LibraryRecord } from "@/lib/library";

function row(extra: Partial<LibraryRecord>): LibraryRecord {
  return { meetingId: null, taskId: null, title: "", filename: "", status: "", reviewCount: null, createdAt: "2026-10-09T01:00:00Z", updatedAt: "2026-10-09T01:00:00Z", ...extra };
}

test("one upload is one row: the submission and the server's meeting merge, keeping the typed name", () => {
  const rows = [
    row({ taskId: "T1", title: "SBC UI Analysis", filename: "SBC.mp4", status: "working", createdAt: "2026-10-09T01:00:00Z" }),
    row({ meetingId: "M1", title: "SBC End of week", status: "working", createdAt: "2026-10-09T01:07:00Z" }),
  ];
  const out = reconcileOrphans(rows, (id) => (id === "M1" ? { taskId: "T1", sourceName: null } : null));
  assert.equal(out.length, 1);
  assert.deepEqual([out[0].meetingId, out[0].taskId, out[0].title, out[0].filename, out[0].createdAt], ["M1", "T1", "SBC UI Analysis", "SBC.mp4", "2026-10-09T01:00:00Z"]);
});

test("meetings no submission claims, and rows already linked, are left alone", () => {
  const rows = [row({ meetingId: "M1" }), row({ meetingId: "M2", taskId: "T2" }), row({ taskId: "T9", title: "Waiting" })];
  assert.equal(reconcileOrphans(rows, (id) => (id === "M2" ? { taskId: "T2", sourceName: null } : null)).length, 3);
});

test("a meeting whose task has no waiting submission stays a single row", () => {
  const out = reconcileOrphans([row({ meetingId: "M1" })], () => ({ taskId: "T-gone", sourceName: null }));
  assert.equal(out.length, 1);
  assert.equal(out[0].meetingId, "M1");
});

test("two uploads do not swallow each other", () => {
  const rows = [row({ taskId: "A", title: "First" }), row({ taskId: "B", title: "Second" }), row({ meetingId: "MA" }), row({ meetingId: "MB" })];
  const out = reconcileOrphans(rows, (id) => ({ taskId: id === "MA" ? "A" : "B", sourceName: null }));
  assert.deepEqual(out.map((item) => [item.meetingId, item.title]).sort(), [["MA", "First"], ["MB", "Second"]]);
});

test("an older server that reports no task still ties a submission to its meeting by the recording's name", () => {
  const rows = [
    row({ taskId: "T1", title: "SBC UI Analysis", filename: "SBC-End-of-week-Check-Point_2026-10-09.mp4" }),
    row({ meetingId: "M1", title: "SBC End of week Check Point 2026 10 09" }),
  ];
  const out = reconcileOrphans(rows, () => ({ taskId: null, sourceName: "SBC End of week Check Point 2026 10 09" }));
  assert.equal(out.length, 1);
  assert.deepEqual([out[0].meetingId, out[0].taskId, out[0].title], ["M1", "T1", "SBC UI Analysis"]);
});

test("two waiting submissions of the same file are not guessed between", () => {
  const rows = [
    row({ taskId: "T1", title: "First", filename: "weekly.mp4" }),
    row({ taskId: "T2", title: "Second", filename: "weekly.mp4" }),
    row({ meetingId: "M1" }),
  ];
  assert.equal(reconcileOrphans(rows, () => ({ taskId: null, sourceName: "weekly" })).length, 3);
});

test("a name chosen by the person survives the merge with the server's meeting", () => {
  const rows = [row({ taskId: "T1", title: "Quarterly planning", renamed: true, filename: "rec.mp4" }), row({ meetingId: "M1" })];
  const out = reconcileOrphans(rows, () => ({ taskId: "T1", sourceName: null }));
  assert.equal(out.length, 1);
  assert.deepEqual([out[0].title, out[0].renamed], ["Quarterly planning", true]);
});

test("the merged row carries the waiting submission's task, file name and start time", () => {
  const rows = [
    row({ taskId: "T1", title: "Weekly", filename: "weekly.mp4", createdAt: "2026-10-09T00:00:00Z" }),
    row({ meetingId: "M1", title: "M1", createdAt: "2026-10-09T09:00:00Z" }),
  ];
  const [only] = reconcileOrphans(rows, () => ({ taskId: "T1", sourceName: null }));
  assert.deepEqual([only.meetingId, only.taskId, only.title, only.filename, only.createdAt], ["M1", "T1", "Weekly", "weekly.mp4", "2026-10-09T00:00:00Z"]);
});
