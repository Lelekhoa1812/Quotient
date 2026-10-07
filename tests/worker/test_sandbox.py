import json
import sys
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from chart.sandbox import (
    PLOT_LIBRARIES,
    aggregation_chart,
    commit_svg,
    fence,
    import_plot_library,
    portal_charts,
    render_svg,
    write_plots,
)
from errors import ChartRejected
from graph.chart import compute
from graph.span import Span
from graph.state import Claim, Finding
from graph.union import union_length
from registry.ids import LENS_ORDER


def _span(span_id, kind, start_ms, end_ms, speaker, overlap=False):
    return Span(
        id=span_id,
        meeting_id="m",
        kind=kind,
        start_ms=start_ms,
        end_ms=end_ms,
        raw_text=span_id,
        text=span_id,
        speaker_hypothesis_id=speaker,
        overlap=overlap,
    )


def _claim(claim_id, status):
    return Claim(
        id=claim_id,
        meeting_id="m",
        kind="observation",
        proposition=claim_id,
        paraphrase=claim_id,
        quote=claim_id,
        status=status,
    )


def _finding(finding_id, dimension):
    return Finding(id=finding_id, dimension=dimension, stance="supports", claim_ids=["c-pub"], text=finding_id)


def graph():
    return {
        "spans": [
            _span("s1", "speech", 0, 10000, "h1"),
            _span("s2", "speech", 8000, 12000, "h1", overlap=True),
            _span("s3", "speech", 11000, 15000, "h2"),
            _span("s4", "overlap", 14000, 16000, "h2", overlap=True),
            _span("v1", "visual", 0, 1000, None),
        ],
        "claims": [
            _claim("c-pub", "supported"),
            _claim("c-open", "unresolved"),
            _claim("c-con", "contradicted"),
        ],
        "findings": [
            _finding("f1", "decision"),
            _finding("f2", "risk"),
            _finding("f3", "decision"),
        ],
        "actions": [
            SimpleNamespace(id="a1", acceptance="proposed"),
            SimpleNamespace(id="a2", acceptance="accepted"),
            SimpleNamespace(id="a3", acceptance="proposed"),
        ],
    }


def _by_id(charts):
    return {chart["id"]: chart for chart in charts}


class _Script(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        found = dict(attrs)
        if tag == "script" and found.get("id") == "quotient-charts":
            self.capture = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


def test_portal_series_are_the_worker_table(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "sandbox-test-credential")
    charts = portal_charts(graph())
    found = _by_id(charts)
    assert list(found) == [
        "counts-by-dimension",
        "hypothesis-duration",
        "hypothesis-duration-share",
        "hypothesis-turn-count",
        "action-acceptance",
        "review-queue-vs-published",
        "timeline-density",
    ]
    counts = {row["label"]: row["value"] for row in found["counts-by-dimension"]["rows"]}
    assert list(counts)[: len(LENS_ORDER)] == list(LENS_ORDER)
    assert counts["decision"] == 2
    assert counts["risk"] == 1
    assert counts["commitment"] == 0
    h1 = union_length([(0, 10000), (8000, 12000)])
    h2 = union_length([(11000, 15000), (14000, 16000)])
    total = union_length([(0, 10000), (8000, 12000), (11000, 15000), (14000, 16000)])
    duration = {row["label"]: row for row in found["hypothesis-duration"]["rows"]}
    share = {row["label"]: row for row in found["hypothesis-duration-share"]["rows"]}
    turns = {row["label"]: row for row in found["hypothesis-turn-count"]["rows"]}
    assert duration["h1"]["value"] == h1
    assert duration["h2"]["value"] == h2
    assert share["h1"]["value"] == h1 / total
    assert share["h2"]["value"] == h2 / total
    assert turns["h1"]["value"] == 2
    assert turns["h2"]["value"] == 2
    assert duration["h2"]["ids"] == ["s3", "s4"]
    assert share["h2"]["ids"] == ["s3", "s4"]
    assert turns["h2"]["ids"] == ["s3", "s4"]
    for chart in (found["hypothesis-duration"], found["hypothesis-duration-share"], found["hypothesis-turn-count"]):
        assert chart["hypotheses"] is True
        assert "hypothesis" in chart["title"].casefold()
    acceptance = {row["label"]: row["value"] for row in found["action-acceptance"]["rows"]}
    assert acceptance == {"proposed": 2, "accepted": 1}
    review = {row["label"]: row["value"] for row in found["review-queue-vs-published"]["rows"]}
    assert review == {"review_queue": 2, "published": 1}
    density = [(row["label"], row["value"]) for row in found["timeline-density"]["rows"]]
    assert density == [("s1", 2), ("s2", 3), ("s3", 3), ("s4", 2)]
    assert "s4" in {row["label"] for row in found["timeline-density"]["rows"]}
    assert "v1" not in {row["label"] for row in found["timeline-density"]["rows"]}
    blob = json.dumps(charts).casefold()
    for banned in ("wpm", "filler", "sentiment", "keyword"):
        assert banned not in blob
    html_path = write_plots(charts, tmp_path)
    page = html_path.read_text(encoding="utf-8")
    parser = _Script()
    parser.feed(page)
    assert json.loads("".join(parser.parts)) == json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "charts.json").read_text(encoding="utf-8")) == charts
    assert "sandbox-test-credential" not in page
    assert "http" not in page
    assert "src=" not in page


def test_missing_ids_and_numeric_literals_fail_closed(tmp_path):
    spans = {"s1": _span("s1", "speech", 0, 10, "h1")}

    class Boom(dict):
        def __contains__(self, key):
            raise AssertionError("catalog was read")

        def __getitem__(self, key):
            raise AssertionError("catalog was read")

    with pytest.raises(ChartRejected, match="numeric literal"):
        compute(
            {"ids": ["s1"], "aggregation": "count", "subject": "spans", "limit": 1},
            cells={},
            spans=Boom(),
        )
    with pytest.raises(ChartRejected, match="missing"):
        compute(
            {"ids": ["gone"], "aggregation": "duration_union", "subject": "spans"},
            cells={},
            spans=spans,
        )
    with pytest.raises(ChartRejected, match="missing"):
        compute(
            {"ids": ["f-missing"], "aggregation": "count", "subject": "findings"},
            cells={},
            spans={},
            findings={},
        )
    with pytest.raises(ChartRejected, match="duration_union is only for spans"):
        compute(
            {"ids": ["c-pub"], "aggregation": "duration_union", "subject": "claims"},
            cells={},
            spans={},
            claims={"c-pub": _claim("c-pub", "supported")},
        )
    with pytest.raises(ChartRejected, match="duplicate"):
        compute(
            {"ids": ["s1", "s1"], "aggregation": "count", "subject": "spans"},
            cells={},
            spans=spans,
        )
    assert list(tmp_path.iterdir()) == []


def test_cell_aggregations_render_the_worker_result(tmp_path):
    cells = {"Sheet1!A1": 10, "Sheet1!A2": 30}
    ids = ["Sheet1!A1", "Sheet1!A2"]
    expected = {"sum": 40.0, "mean": 20.0, "min": 10.0, "max": 30.0}
    charts = []
    for aggregation, result in expected.items():
        table = compute(
            {"ids": ids, "aggregation": aggregation, "subject": "cells", "field": "cell_value"},
            cells=cells,
            spans={},
        )
        assert table.result == result
        assert list(table.values) == [10.0, 30.0]
        charts.append(aggregation_chart(table, chart_id=f"cell-{aggregation}", title=aggregation))
    html_path = write_plots(charts, tmp_path)
    assert html_path.is_file()
    for aggregation, result in expected.items():
        svg = (tmp_path / f"cell-{aggregation}.svg").read_text(encoding="utf-8")
        assert f'data-value="{json.dumps(result)}"' in svg
    with pytest.raises(ChartRejected, match="missing"):
        compute(
            {"ids": ["Sheet1!Z9"], "aggregation": "mean", "subject": "cells", "field": "cell_value"},
            cells=cells,
            spans={},
        )
    with pytest.raises(ChartRejected, match="cell_value"):
        compute(
            {"ids": ids, "aggregation": "sum", "subject": "cells"},
            cells=cells,
            spans={},
        )


def test_plot_rejects_a_value_that_differs_from_the_table(tmp_path):
    chart = portal_charts(graph())[0]
    svg = render_svg(chart)
    assert svg
    drawn = tmp_path / "counts-by-dimension.svg"
    assert commit_svg(drawn, chart, svg) == drawn
    first = chart["rows"][0]["value"]
    needle = f'data-value="{json.dumps(float(first))}"'
    bad = svg.replace(needle, 'data-value="999.0"', 1)
    assert commit_svg(drawn, chart, bad) is None
    assert not drawn.exists()


def test_sandbox_blocks_credentials_dotenv_and_network_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "sandbox-test-credential")
    secret = tmp_path / ".env"
    secret.write_text("AWS_SECRET_ACCESS_KEY=sandbox-test-credential\n", encoding="utf-8")
    with fence():
        assert "AWS_SECRET_ACCESS_KEY" not in __import__("os").environ
        with pytest.raises(ChartRejected, match="cannot read .env"):
            open(secret, encoding="utf-8")
        with pytest.raises(ChartRejected, match="cannot read .env"):
            secret.read_text(encoding="utf-8")
        with pytest.raises(ChartRejected, match="cannot import"):
            import dotenv  # noqa: F401
    assert secret.read_text(encoding="utf-8").strip().endswith("sandbox-test-credential")
    saved_socket = sys.modules.pop("socket", None)
    try:
        with fence():
            with pytest.raises(ChartRejected, match="cannot import"):
                import socket  # noqa: F401
    finally:
        if saved_socket is not None:
            sys.modules["socket"] = saved_socket


def test_plot_libraries_stay_uninstalled_and_unimported():
    for name in sorted(PLOT_LIBRARIES):
        with pytest.raises(ChartRejected, match="not installed"):
            import_plot_library(name)
    with pytest.raises(ChartRejected, match="cannot import"):
        import_plot_library("boto3")
    with pytest.raises(ChartRejected, match="cannot import"):
        import_plot_library("socket")
