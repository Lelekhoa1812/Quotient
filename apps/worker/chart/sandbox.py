# Motivation vs Logic
# Motivation: The portal needs several meeting series, and every plotted number has to be the worker table.
# Logic: Specs carry ids and count or duration_union. The worker resolves those ids on the graph, including overlap spans, and draws only that table. Speaker series are titled as hypotheses. The plot fence has no AWS credentials, no .env read, and no network import.

from __future__ import annotations

import html
import importlib.util
import io
import json
import os
import sys
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

from errors import ChartRejected
from graph.chart import AGGREGATIONS, Table, _interval, compute
from registry.ids import LENS_ORDER

PORTAL_FIELDS = ("id", "title", "aggregation", "columns", "rows")
ROW_VALUE = "value"
PLOT_LIBRARIES = frozenset(
    {
        "matplotlib",
        "plotly",
        "pandas",
        "numpy",
        "seaborn",
        "networkx",
        "scipy",
        "pillow",
        "PIL",
        "altair",
        "squarify",
    }
)
_PLOT_MODULE = {
    "matplotlib": "matplotlib",
    "plotly": "plotly",
    "pandas": "pandas",
    "numpy": "numpy",
    "seaborn": "seaborn",
    "networkx": "networkx",
    "scipy": "scipy",
    "pillow": "PIL",
    "PIL": "PIL",
    "altair": "altair",
    "squarify": "squarify",
}
_BLOCKED_IMPORTS = frozenset(
    {
        "boto3",
        "botocore",
        "requests",
        "urllib",
        "http",
        "socket",
        "dotenv",
        "subprocess",
    }
)
_ACCEPTANCE = ("proposed", "accepted")
_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def portal_charts(graph: dict) -> list[dict]:
    catalogs = index_graph(graph)
    timed = _timed_spans(catalogs["spans"])
    return [
        _counts_by_dimension(catalogs),
        _hypothesis_duration(catalogs, timed),
        _hypothesis_share(catalogs, timed),
        _hypothesis_turns(catalogs, timed),
        _action_acceptance(catalogs),
        _review_versus_published(catalogs),
        _timeline_density(catalogs, timed),
    ]


def aggregation_chart(table: Table, *, chart_id: str, title: str) -> dict:
    _file_stem(chart_id)
    if table.aggregation not in AGGREGATIONS:
        raise ChartRejected(f"aggregation must be one of {', '.join(AGGREGATIONS)}")
    return _chart(
        chart_id,
        title,
        table.aggregation,
        [{"label": table.aggregation, "value": float(table.result), "ids": list(table.ids)}],
    )


def import_plot_library(name: str):
    root = name.split(".", 1)[0]
    if root not in PLOT_LIBRARIES:
        raise ChartRejected(f"sandbox cannot import {name}")
    module_name = _PLOT_MODULE[root]
    if importlib.util.find_spec(module_name) is None:
        raise ChartRejected(f"{name} is not installed")
    return importlib.import_module(module_name if root == "pillow" else name)


def write_plots(charts: list[dict], directory: str | Path) -> Path:
    folder = Path(directory)
    seen = set()
    for chart in charts:
        _validate_chart(chart)
        if chart["id"] in seen:
            raise ChartRejected(f"duplicate chart id {chart['id']}")
        seen.add(chart["id"])
    drawings = []
    for chart in charts:
        svg = render_svg(chart)
        if not svg_matches(svg, chart):
            raise ChartRejected("plotted values differ from the worker table")
        drawings.append((chart["id"], svg))
    payload = json.dumps(charts).replace("<", "\\u003c")
    html_path = folder / "charts.html"
    written: list[Path] = []
    try:
        with fence():
            folder.mkdir(parents=True, exist_ok=True)
            for chart_id, svg in drawings:
                path = commit_svg(folder / f"{chart_id}.svg", _chart_by_id(charts, chart_id), svg)
                if path is None:
                    raise ChartRejected("plotted values differ from the worker table")
                written.append(path)
            table_path = folder / "charts.json"
            table_path.write_text(payload, encoding="utf-8")
            written.append(table_path)
            html_path.write_text(_html_page(payload, drawings), encoding="utf-8")
            written.append(html_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return html_path


def render_svg(chart: dict) -> str:
    _validate_chart(chart)
    rows = chart["rows"]
    peak = max((abs(float(row["value"])) for row in rows), default=0.0)
    title = html.escape(str(chart["title"]), quote=True)
    parts = [
        f'<svg role="img" aria-label="{title}" data-aggregation="{html.escape(str(chart["aggregation"]), quote=True)}">',
        f"<title>{title}</title>",
    ]
    for index, row in enumerate(rows):
        value = float(row["value"])
        width = 0.0 if peak == 0.0 else (abs(value) / peak) * 360.0
        y = 28 + index * 28
        label = html.escape(str(row["label"]), quote=True)
        encoded = html.escape(json.dumps(value), quote=True)
        parts.append(
            f'<rect data-label="{label}" data-value="{encoded}" x="180" y="{y}" width="{width}" height="16"/>'
        )
        parts.append(f'<text x="0" y="{y + 12}">{label}</text>')
        parts.append(f'<text x="560" y="{y + 12}">{encoded}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_matches(svg_text: str, chart: dict) -> bool:
    parser = _Values()
    parser.feed(svg_text)
    expected = [(str(row["label"]), float(row["value"])) for row in chart["rows"]]
    return parser.rows == expected


def commit_svg(path: str | Path, chart: dict, svg_text: str) -> Path | None:
    target = Path(path)
    if not svg_matches(svg_text, chart):
        target.unlink(missing_ok=True)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg_text, encoding="utf-8")
    return target


@contextmanager
def fence():
    saved_env = {}
    for key in list(os.environ):
        if key.startswith("AWS_") or key.startswith("BEDROCK_"):
            saved_env[key] = os.environ.pop(key)
    saved_open = builtins_open()
    saved_io_open = io.open
    saved_os_open = os.open
    blocker = _ImportBlocker()
    sys.meta_path.insert(0, blocker)
    builtins = sys.modules["builtins"]

    def guarded_open(file, *args, **kwargs):
        _reject_secret_path(file)
        return saved_open(file, *args, **kwargs)

    def guarded_io_open(file, *args, **kwargs):
        _reject_secret_path(file)
        return saved_io_open(file, *args, **kwargs)

    def guarded_os_open(file, flags, *args, **kwargs):
        _reject_secret_path(file)
        return saved_os_open(file, flags, *args, **kwargs)

    builtins.open = guarded_open
    io.open = guarded_io_open
    os.open = guarded_os_open
    try:
        yield
    finally:
        builtins.open = saved_open
        io.open = saved_io_open
        os.open = saved_os_open
        if blocker in sys.meta_path:
            sys.meta_path.remove(blocker)
        os.environ.update(saved_env)


def index_graph(graph: dict) -> dict:
    if not isinstance(graph, dict):
        raise ChartRejected("graph must be an object")
    cells = graph.get("cells") or {}
    if not isinstance(cells, dict):
        raise ChartRejected("cells must be an object")
    return {
        "cells": cells,
        "spans": _catalog(graph.get("spans") or [], "spans"),
        "claims": _catalog(graph.get("claims") or [], "claims"),
        "findings": _catalog(graph.get("findings") or [], "findings"),
        "actions": _catalog(graph.get("actions") or [], "actions"),
    }


class _ImportBlocker:
    def find_spec(self, fullname, path, target=None):
        root = fullname.split(".", 1)[0]
        if root in _BLOCKED_IMPORTS:
            raise ChartRejected(f"sandbox cannot import {fullname}")
        return None


class _Values(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, float]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "rect":
            return
        found = dict(attrs)
        if "data-value" not in found:
            return
        self.rows.append((found.get("data-label", ""), float(json.loads(found["data-value"]))))


def _counts_by_dimension(catalogs: dict) -> dict:
    grouped = {name: [] for name in LENS_ORDER}
    extras: dict[str, list[str]] = {}
    for ident, finding in catalogs["findings"].items():
        dimension = _field(finding, "dimension")
        if not isinstance(dimension, str) or not dimension:
            raise ChartRejected(f"finding {ident} has no dimension")
        if dimension in grouped:
            grouped[dimension].append(ident)
        else:
            extras.setdefault(dimension, []).append(ident)
    rows = [_count_row(name, grouped[name], "findings", catalogs) for name in LENS_ORDER]
    for name in sorted(extras):
        rows.append(_count_row(name, extras[name], "findings", catalogs))
    return _chart("counts-by-dimension", "Counts by dimension", "count", rows)


def _hypothesis_duration(catalogs: dict, timed: list[tuple[str, object]]) -> dict:
    rows = []
    for hypothesis_id, ids in _speaker_groups(timed):
        table = _measured(ids, "duration_union", "spans", catalogs)
        rows.append({"label": hypothesis_id, "value": float(table.result), "ids": list(ids)})
    return _hypothesis_chart("hypothesis-duration", "Hypothesis duration", "duration_union", rows)


def _hypothesis_share(catalogs: dict, timed: list[tuple[str, object]]) -> dict:
    all_ids = [ident for ident, _span in timed]
    total = _measured(all_ids, "duration_union", "spans", catalogs)
    rows = []
    for hypothesis_id, ids in _speaker_groups(timed):
        duration = _measured(ids, "duration_union", "spans", catalogs)
        share = 0.0 if total.result == 0.0 else float(duration.result) / float(total.result)
        rows.append({"label": hypothesis_id, "value": share, "ids": list(ids)})
    return _hypothesis_chart("hypothesis-duration-share", "Hypothesis duration share", "duration_union", rows)


def _hypothesis_turns(catalogs: dict, timed: list[tuple[str, object]]) -> dict:
    rows = []
    for hypothesis_id, ids in _speaker_groups(timed):
        table = _measured(ids, "count", "spans", catalogs)
        rows.append({"label": hypothesis_id, "value": float(table.result), "ids": list(ids)})
    return _hypothesis_chart("hypothesis-turn-count", "Hypothesis turn count", "count", rows)


def _action_acceptance(catalogs: dict) -> dict:
    grouped = {name: [] for name in _ACCEPTANCE}
    for ident, action in catalogs["actions"].items():
        acceptance = _field(action, "acceptance")
        if acceptance not in grouped:
            raise ChartRejected(f"action {ident} acceptance is not proposed or accepted")
        grouped[acceptance].append(ident)
    rows = [_count_row(name, grouped[name], "actions", catalogs) for name in _ACCEPTANCE]
    return _chart("action-acceptance", "Action acceptance", "count", rows)


def _review_versus_published(catalogs: dict) -> dict:
    review = []
    published = []
    for ident, claim in catalogs["claims"].items():
        status = _field(claim, "status")
        if status == "supported":
            published.append(ident)
        elif isinstance(status, str) and status:
            review.append(ident)
        else:
            raise ChartRejected(f"claim {ident} has no status")
    rows = [
        _count_row("review_queue", review, "claims", catalogs),
        _count_row("published", published, "claims", catalogs),
    ]
    return _chart("review-queue-vs-published", "Review queue and published claims", "count", rows)


def _timeline_density(catalogs: dict, timed: list[tuple[str, object]]) -> dict:
    intervals = {ident: _interval(span, ident) for ident, span in timed}
    ordered = sorted(timed, key=lambda item: (intervals[item[0]][0], item[0]))
    rows = []
    for ident, _span in ordered:
        start, end = intervals[ident]
        ids = [ident]
        for other, other_span in ordered:
            if other == ident:
                continue
            other_start, other_end = intervals[other]
            if start < other_end and other_start < end:
                ids.append(other)
        table = _measured(ids, "count", "spans", catalogs)
        rows.append({"label": ident, "value": float(table.result), "ids": ids})
    return _chart("timeline-density", "Timeline density", "count", rows)


def _speaker_groups(timed: list[tuple[str, object]]) -> list[tuple[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for ident, span in timed:
        hypothesis_id = _field(span, "speaker_hypothesis_id") or "unassigned"
        if not isinstance(hypothesis_id, str) or not hypothesis_id:
            raise ChartRejected(f"span {ident} speaker hypothesis is not a string")
        grouped.setdefault(hypothesis_id, []).append(ident)
    return [(hypothesis_id, grouped[hypothesis_id]) for hypothesis_id in sorted(grouped)]


def _timed_spans(spans: dict) -> list[tuple[str, object]]:
    timed = []
    for ident, span in spans.items():
        kind = _field(span, "kind")
        if kind in {"speech", "overlap"} or bool(_field(span, "overlap")):
            timed.append((ident, span))
    return timed


def _count_row(label: str, ids: list[str], subject: str, catalogs: dict) -> dict:
    table = _measured(ids, "count", subject, catalogs)
    return {"label": label, "value": float(table.result), "ids": list(ids)}


def _measured(ids: list[str], aggregation: str, subject: str, catalogs: dict) -> Table:
    if not ids:
        return Table(aggregation, (), (), 0.0)
    return compute(
        {"ids": list(ids), "aggregation": aggregation, "subject": subject},
        cells=catalogs["cells"],
        spans=catalogs["spans"],
        claims=catalogs["claims"],
        findings=catalogs["findings"],
        actions=catalogs["actions"],
    )


def _hypothesis_chart(chart_id: str, title: str, aggregation: str, rows: list[dict]) -> dict:
    if "hypothesis" not in title.casefold():
        raise ChartRejected("speaker charts must be titled as hypotheses")
    chart = _chart(chart_id, title, aggregation, rows)
    chart["hypotheses"] = True
    return chart


def _chart(chart_id: str, title: str, aggregation: str, rows: list[dict]) -> dict:
    return {
        "id": chart_id,
        "title": title,
        "aggregation": aggregation,
        "columns": ["label", "value"],
        "rows": rows,
    }


def _catalog(items, kind: str) -> dict:
    if not isinstance(items, list):
        raise ChartRejected(f"{kind} must be a list")
    catalog = {}
    for index, item in enumerate(items):
        ident = _identity(item, kind, index)
        if ident in catalog:
            raise ChartRejected(f"duplicate {kind} id {ident}")
        catalog[ident] = item
    return catalog


def _identity(item, kind: str, index: int) -> str:
    if isinstance(item, dict):
        found = item.get("id") or item.get("action_id")
    else:
        found = getattr(item, "id", None) or getattr(item, "action_id", None)
    if isinstance(found, str) and found:
        return found
    if kind == "actions":
        return f"action-{index}"
    raise ChartRejected(f"{kind} object has no id")


def _field(item, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _validate_chart(chart: dict) -> None:
    if not isinstance(chart, dict):
        raise ChartRejected("chart must be an object")
    for field in PORTAL_FIELDS:
        if field not in chart:
            raise ChartRejected(f"chart is missing {field}")
    _file_stem(str(chart["id"]))
    if chart["aggregation"] not in AGGREGATIONS:
        raise ChartRejected(f"aggregation must be one of {', '.join(AGGREGATIONS)}")
    if chart["columns"] != ["label", "value"]:
        raise ChartRejected("chart columns must be label and value")
    if not isinstance(chart["rows"], list):
        raise ChartRejected("chart rows must be a list")
    for row in chart["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("label"), str):
            raise ChartRejected("chart row needs a label")
        if isinstance(row.get("value"), bool) or not isinstance(row.get("value"), (int, float)):
            raise ChartRejected("chart row value must be the worker number")


def _file_stem(chart_id: str) -> None:
    if not chart_id or any(char not in _ID_CHARS for char in chart_id):
        raise ChartRejected("chart id cannot be a path")


def _chart_by_id(charts: list[dict], chart_id: str) -> dict:
    for chart in charts:
        if chart["id"] == chart_id:
            return chart
    raise ChartRejected(f"missing chart {chart_id}")


def _html_page(payload: str, drawings: list[tuple[str, str]]) -> str:
    blocks = [
        "<!DOCTYPE html>",
        '<meta charset="utf-8">',
        "<title>Quotient charts</title>",
        f'<script type="application/json" id="quotient-charts">{payload}</script>',
    ]
    for _chart_id, svg in drawings:
        blocks.append(svg)
    return "\n".join(blocks)


def _reject_secret_path(file) -> None:
    if isinstance(file, int):
        return
    try:
        name = os.fspath(file)
    except TypeError:
        return
    path = Path(name)
    filename = path.name
    if filename == ".env" or filename.startswith(".env."):
        raise ChartRejected("sandbox cannot read .env")
    if ".aws" in path.parts:
        raise ChartRejected("sandbox cannot read AWS credentials")


def builtins_open():
    return sys.modules["builtins"].open
