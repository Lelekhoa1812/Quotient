# Motivation vs Logic
# Motivation: The worker service scales from zero. A task that exits immediately
# trips the deployment circuit breaker the first time the queue has depth.
# Logic: Stay up and do not read the queue. The meeting loop still runs inside
# the API process, so consuming a stage message here would hide it until the
# dead-letter alarm.

from __future__ import annotations

import time


def main() -> None:
    print("quotient worker idle", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
