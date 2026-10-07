# Motivation vs Logic
# Motivation: Audio figures describe this pipeline. They are hypotheses, not DER, JER, or WER, and not chart measures.
# Logic: Duration uses a union of overlapping intervals. Citation coverage counts supported decisions and actions.

from graph.union import union_length


def hypothesis_stats(spans: list) -> dict:
    speech = [span for span in spans if span.kind == "speech"]
    total = union_length([(span.start_ms, span.end_ms) for span in speech])
    grouped: dict[str, list] = {}
    for span in speech:
        grouped.setdefault(span.speaker_hypothesis_id or "unassigned", []).append(span)
    rows = []
    for hypothesis_id, group in sorted(grouped.items()):
        duration = union_length([(span.start_ms, span.end_ms) for span in group])
        rows.append(
            {
                "speaker_hypothesis_id": hypothesis_id,
                "duration_ms": duration,
                "duration_share": (duration / total) if total else 0.0,
                "turn_count": len(group),
                "hypotheses": True,
            }
        )
    return {"hypotheses": True, "chart_measure": False, "rows": rows}


def audio_figures(spans: list, duration_ms: int, claims: list) -> dict:
    speech = [span for span in spans if span.kind == "speech"]
    speech_ms = union_length([(span.start_ms, span.end_ms) for span in speech])
    overlap_ms = union_length(
        [(span.start_ms, span.end_ms) for span in spans if span.overlap or span.kind == "overlap"]
    )
    turns = len(speech)
    short = sum(1 for span in speech if span.end_ms - span.start_ms < 500)
    histogram: dict[int, int] = {}
    published = [
        claim
        for claim in claims
        if claim.status == "supported" and claim.kind in {"decision", "action"} and claim.start_ms is not None
    ]
    for claim in published:
        bucket = (claim.start_ms // 60000) * 60000
        histogram[bucket] = histogram.get(bucket, 0) + 1
    covered = sum(1 for claim in published if claim.span_id)
    return {
        "citation_coverage_decisions_actions": (covered / len(published)) if published else 1.0,
        "citation_time_histogram": histogram,
        "speech_fraction": (speech_ms / duration_ms) if duration_ms else 0.0,
        "overlap_fraction": (overlap_ms / duration_ms) if duration_ms else 0.0,
        "short_turn_fraction": (short / turns) if turns else 0.0,
    }
