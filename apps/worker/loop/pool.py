# Motivation vs Logic
# Motivation: Blind lenses, the two entailment votes, and Pegasus parts do not
# read one another's prose, but the loop was issuing those calls one at a time.
# Logic: A bounded pool runs the calls and returns results in input order.
# QUOTIENT_WORKERS sets the width (default 10). Sonic sessions stay outside
# this pool because each handoff carries the previous transcript.

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor


def width() -> int:
    raw = os.environ.get("QUOTIENT_WORKERS", "10")
    try:
        value = int(raw)
    except ValueError:
        value = 10
    return max(1, min(value, 32))


def map_ordered[T, R](fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
    batch = list(items)
    if len(batch) <= 1:
        return [fn(item) for item in batch]
    workers = min(width(), len(batch))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quotient") as pool:
        return list(pool.map(fn, batch))
