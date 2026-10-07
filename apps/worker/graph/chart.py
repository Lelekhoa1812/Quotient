# Motivation vs Logic
# Motivation: The model names ids and an aggregation. It does not supply the number that gets plotted.
# Logic: Reject any JSON numeric literal before the fixed renderer computes count, sum, mean, min, max, or duration_union.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from errors import ChartRejected
from graph.union import union_length

AGGREGATIONS = ("count", "sum", "mean", "min", "max", "duration_union")
SUBJECTS = ("spans", "claims", "findings", "actions", "cells")
_CELL_AGGREGATIONS = ("sum", "mean", "min", "max")
_MODEL_FIELDS = ("ids", "aggregation", "subject", "field")


@dataclass(frozen=True)
class Table:
    aggregation: str
    ids: tuple[str, ...]
    values: tuple[float, ...]
    result: float


def reject_numeric_literals(query) -> dict:
    try:
        data = json.loads(query) if isinstance(query, str) else query
    except json.JSONDecodeError as exc:
        raise ChartRejected("chart query is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ChartRejected("chart query must be an object")
    if _has_number(data):
        raise ChartRejected("chart query contains a numeric literal")
    return data


# Bugs vs Fixes
# Bug: count accepted ids that are not on the graph, and a missing span or cell surfaced as KeyError.
# Fix: After the numeric-literal gate, resolve every id in the subject catalog and raise ChartRejected when one is absent.
def compute(
    query,
    *,
    cells: dict,
    spans: dict,
    claims: dict | None = None,
    findings: dict | None = None,
    actions: dict | None = None,
) -> Table:
    data = reject_numeric_literals(query)
    aggregation = data.get("aggregation")
    if aggregation not in AGGREGATIONS:
        raise ChartRejected(f"aggregation must be one of {', '.join(AGGREGATIONS)}")
    catalogs = {
        "cells": cells,
        "spans": spans,
        "claims": {} if claims is None else claims,
        "findings": {} if findings is None else findings,
        "actions": {} if actions is None else actions,
    }
    subject = data.get("subject")
    if subject is None:
        _reject_legacy_shape(data, aggregation)
        cell_ids, span_ids = _legacy_ids(data)
        _unique_strings(cell_ids, "cells")
        _unique_strings(span_ids, "spans")
    else:
        _reject_model_shape(data, aggregation, subject)
        named = _unique_strings(list(data.get("ids") or []), subject)
        if subject == "cells":
            cell_ids, span_ids = named, []
        elif subject == "spans":
            cell_ids, span_ids = [], named
        else:
            cell_ids, span_ids = [], []
            _require(named, catalogs[subject], subject)
    if aggregation == "duration_union":
        _require(span_ids, spans, "spans")
        intervals = []
        durations = []
        resolved = []
        for span_id in span_ids:
            start, end = _interval(spans[span_id], span_id)
            intervals.append((start, end))
            durations.append(float(end - start))
            resolved.append(span_id)
        return Table(aggregation, tuple(resolved), tuple(durations), float(union_length(intervals)))
    if aggregation == "count":
        if subject in {"claims", "findings", "actions"}:
            ids = _unique_strings(list(data.get("ids") or []), subject)
        else:
            _require(cell_ids, cells, "cells")
            _require(span_ids, spans, "spans")
            ids = [*cell_ids, *span_ids]
        return Table(aggregation, tuple(ids), tuple(1.0 for _ in ids), float(len(ids)))
    _require(cell_ids, cells, "cells")
    values = [_cell_value(cells, cell_id) for cell_id in cell_ids]
    if not values:
        raise ChartRejected("numeric aggregation has no cells")
    result = {
        "sum": sum(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }[aggregation]
    return Table(aggregation, tuple(cell_ids), tuple(values), float(result))


def _reject_legacy_shape(data: dict, aggregation: str) -> None:
    if aggregation == "duration_union" and data.get("cells"):
        raise ChartRejected("duration_union is only for spans")
    if aggregation in _CELL_AGGREGATIONS and data.get("span_ids"):
        raise ChartRejected("sum, mean, min, and max are only for cells")


def _reject_model_shape(data: dict, aggregation: str, subject: str) -> None:
    if subject not in SUBJECTS:
        raise ChartRejected(f"subject must be one of {', '.join(SUBJECTS)}")
    extra = set(data) - set(_MODEL_FIELDS)
    if extra:
        raise ChartRejected("chart query has unsupported fields")
    named = data.get("ids")
    if not isinstance(named, list) or not named:
        raise ChartRejected("chart query needs ids")
    if aggregation == "duration_union":
        if subject != "spans" or "field" in data:
            raise ChartRejected("duration_union is only for spans")
        return
    if aggregation in _CELL_AGGREGATIONS:
        if subject != "cells" or data.get("field") != "cell_value":
            raise ChartRejected("sum, mean, min, and max require subject cells and field cell_value")
        return
    if "field" in data:
        raise ChartRejected("count takes no field")


def _legacy_ids(data: dict) -> tuple[list, list]:
    cell_ids = list(data.get("cells") or [])
    span_ids = list(data.get("span_ids") or [])
    named = list(data.get("ids") or [])
    if named and not cell_ids and not span_ids:
        span_ids = named
    return cell_ids, span_ids


def _unique_strings(ids: list, label: str) -> list:
    seen = set()
    for item in ids:
        if not isinstance(item, str) or not item:
            raise ChartRejected(f"{label} ids must be strings")
        if item in seen:
            raise ChartRejected(f"duplicate {label} id {item}")
        seen.add(item)
    return ids


def _require(ids: list, catalog: dict, label: str) -> None:
    missing = [item for item in ids if item not in catalog]
    if missing:
        raise ChartRejected(f"missing {label}: {', '.join(missing)}")


def _interval(span, span_id: str) -> tuple[int, int]:
    if isinstance(span, dict):
        start, end = span.get("start_ms"), span.get("end_ms")
    else:
        start, end = getattr(span, "start_ms", None), getattr(span, "end_ms", None)
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        raise ChartRejected(f"span {span_id} has no interval")
    if end < start:
        raise ChartRejected(f"span {span_id} interval is inverted")
    return start, end


def _cell_value(cells: dict, cell_id: str) -> float:
    value = cells[cell_id]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChartRejected(f"cell {cell_id} is not a numeric workbook value")
    return float(value)


def render(table: Table) -> dict:
    return {
        "aggregation": table.aggregation,
        "ids": list(table.ids),
        "values": [float(value) for value in table.values],
        "result": float(table.result),
    }


def accept_plot(table: Table, plotted_values: list[float], plotted_result: float) -> bool:
    return list(plotted_values) == list(table.values) and float(plotted_result) == float(table.result)


def commit_plot(path: str | Path, table: Table, plotted_values: list[float], plotted_result: float) -> Path | None:
    target = Path(path)
    if not accept_plot(table, plotted_values, plotted_result):
        target.unlink(missing_ok=True)
        return None
    target.write_text(json.dumps(render(table)), encoding="utf-8")
    return target


def load_cells(path: str | Path) -> dict:
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True)
    cells: dict = {}
    try:
        for sheet in book.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        cells[f"{sheet.title}!{cell.coordinate}"] = cell.value
    finally:
        book.close()
    return cells


def _has_number(node) -> bool:
    if isinstance(node, bool):
        return False
    if isinstance(node, (int, float)):
        return True
    if isinstance(node, dict):
        return any(_has_number(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_number(value) for value in node)
    return False
