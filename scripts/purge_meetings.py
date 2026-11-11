#!/usr/bin/env python3
"""Remove named test meetings from the shared store. Dry run unless --apply is given.

Usage:
  scripts/purge_meetings.py --bucket axion-meeting-staging-artifacts --key state/meetings.json ID [ID ...]
  scripts/purge_meetings.py --bucket ... --key ... --apply ID [ID ...]

A backup of the stored document is written to .local/run/ before anything changes. Meetings that are still queued or
working are refused, and a meeting that is already gone is reported, not treated as an error.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "worker"))

from quotient import purge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("ids", nargs="+")
    args = parser.parse_args()

    document = purge.fetch(args.bucket, args.key)
    new_document, removed, refused, missing = purge.plan(document, args.ids)
    print(f"stored meetings: {len(document.get('meetings') or [])}")
    print(f"would remove: {removed or 'none'}")
    print(f"refused (still running): {refused or 'none'}")
    print(f"not found (already gone): {missing or 'none'}")
    if not args.apply:
        print("dry run: nothing changed. Add --apply to remove them.")
        return 0
    if not removed:
        print("nothing to remove")
        return 0
    saved = purge.backup(document, ROOT / ".local" / "run")
    print(f"backup written: {saved}")
    purge.store(args.bucket, args.key, new_document)
    print(f"removed {len(removed)} meeting(s); stored meetings now {len(new_document['meetings'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
