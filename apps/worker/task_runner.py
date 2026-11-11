# Motivation vs Logic
# Motivation: A Lambda stops after 15 minutes, and a transcript or recording of a real meeting takes longer to
# analyse. The analysis has to run somewhere with no time limit that costs nothing while idle.
# Logic: The Lambda that reads the work queue starts this module as a one-off Fargate task (ECS RunTask) with
# MEETING_ID set. It runs the same analysis the Lambda would, writes the finished meeting to storage, and exits,
# so nothing stays running between meetings. An error that escapes the analysis marks the meeting failed
# instead of leaving it "working" forever.

from __future__ import annotations

import os
import sys


def main() -> int:
    meeting_id = os.environ.get("MEETING_ID", "").strip()
    if not meeting_id:
        print("task runner: MEETING_ID is not set", file=sys.stderr, flush=True)
        return 2
    from quotient.worker.port import load_worker_port

    port = load_worker_port()
    print(f"long-job worker starting analysis for meeting {meeting_id}", file=sys.stderr, flush=True)
    code = 0
    try:
        port._analyze(meeting_id)
        print(f"long-job worker completed analysis for meeting {meeting_id}", file=sys.stderr, flush=True)
    except Exception as exc:  # _analyze records its own failures; this is for anything outside it
        print(f"long-job worker failed for meeting {meeting_id}: {type(exc).__name__}", file=sys.stderr, flush=True)
        fail = getattr(port, "_fail", None)
        if callable(fail):
            fail(meeting_id, "The analysis could not be completed. Please try again.")
        code = 1
    finally:
        flush = getattr(port, "flush_storage", None)
        if callable(flush):
            flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
