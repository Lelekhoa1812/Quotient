# Motivation vs Logic
# Motivation: A downloaded brief has to show the diagram, including when the
# file is opened with scripts blocked. Flow, C4, and sequence are the shapes
# an architecture brief actually uses.
# Logic: Parse those three Mermaid grammars into boxes and arrows. HTML gets
# SVG. The PDF page gets the same layout in path operators. Any other header
# stays source for the client renderer.

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass

_FLOW = re.compile(r"^(flowchart|graph)\b(?:\s+(TB|TD|BT|LR|RL))?", re.IGNORECASE)
_C4 = re.compile(r"^C4(Context|Container|Component|Dynamic|Deployment)\b")
_SEQUENCE = re.compile(r"^sequenceDiagram\b")
_NODE = re.compile(
    r"^([A-Za-z_][\w-]*)\s*(?:\[([^\]]*)\]|\(\[([^\]]*)\]\)|\(\(([^)]*)\)\)|\(([^)]*)\)|\{([^}]*)\}|\[\[([^\]]*)\]\])?$"
)
_EDGE = re.compile(r"(-->|---|-\.->|==>|--x|--o)(?:\|([^|]*)\|)?")
_C4_NODE = re.compile(
    r'^(?:Person|Person_Ext|System|System_Ext|SystemDb|SystemQueue|Container|ContainerDb|'
    r'ContainerQueue|Component|ComponentDb)\(\s*([A-Za-z_][\w]*)\s*,\s*"([^"]*)"',
    re.IGNORECASE,
)
_C4_REL = re.compile(
    r'^(?:Rel|BiRel|Rel_Back|Rel_Neighbor|Rel_[DULR])\(\s*([A-Za-z_][\w]*)\s*,\s*'
    r'([A-Za-z_][\w]*)\s*,\s*"([^"]*)"',
    re.IGNORECASE,
)
_PART = re.compile(r"^(?:participant|actor)\s+([A-Za-z_][\w]*)(?:\s+as\s+(.+))?$", re.IGNORECASE)
_MSG = re.compile(
    r"^([A-Za-z_][\w]*)\s*(?:->>|-->>|->|-->|-x|--x|-\)|--\))\s*([A-Za-z_][\w]*)\s*:\s*(.*)$"
)
_SKIP = ("subgraph ", "style ", "classdef ", "class ", "direction ", "click ", "linkstyle ", "acctitle", "accdescr")


@dataclass(frozen=True)
class Box:
    label: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Arrow:
    x1: float
    y1: float
    x2: float
    y2: float
    label: str


def svg_for(source: str, marker: str) -> str | None:
    laid = layout(source)
    if laid is None:
        return None
    boxes, arrows, width, height = laid
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 {width:.1f} {height:.1f}" '
        f'width="{width:.0f}" height="{height:.0f}">',
        "<defs>",
        f'<marker id="{html.escape(marker)}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">',
        '<path d="M0,0 L8,4 L0,8 Z" fill="#125DE8"/>',
        "</marker>",
        "</defs>",
        f'<g fill="none" stroke="#125DE8" stroke-width="1.4" marker-end="url(#{html.escape(marker)})">',
    ]
    for arrow in arrows:
        parts.append(
            f'<line x1="{arrow.x1:.1f}" y1="{arrow.y1:.1f}" x2="{arrow.x2:.1f}" y2="{arrow.y2:.1f}"/>'
        )
    parts.append("</g>")
    for box in boxes:
        parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            'rx="0" fill="#ffffff" stroke="#125DE8" stroke-width="1.4"/>'
        )
        parts.append(
            f'<text x="{box.x + box.w / 2:.1f}" y="{box.y + box.h / 2 + 4:.1f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="13" fill="#001938">{html.escape(_fit(box.label, 42))}</text>'
        )
    for arrow in arrows:
        if not arrow.label:
            continue
        mid_x = (arrow.x1 + arrow.x2) / 2
        mid_y = (arrow.y1 + arrow.y2) / 2 - 6
        parts.append(
            f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" text-anchor="middle" font-family="sans-serif" '
            f'font-size="11" fill="#001938">{html.escape(_fit(arrow.label, 28))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def pdf_figure(
    source: str,
    *,
    left: float,
    right: float,
    top: float,
    max_height: float,
) -> tuple[str, float] | None:
    """Bugs vs Fixes

    Bug: Scale was capped at 1 and pinned to the top-left, so a narrow
    flowchart sat as a wireframe speck on an otherwise blank page.
    Fix: Fit the drawing in a full-width panel, center it, and fill the nodes.
    """

    laid = layout(source)
    if laid is None or max_height < 48:
        return None
    boxes, arrows, width, height = laid
    span = max(right - left, 1.0)
    pad = 22.0
    scale = min((span - pad * 2) / max(width, 1.0), (max_height - pad * 2) / max(height, 1.0))
    scale = min(max(scale, 0.35), 2.4)
    drawn_w = width * scale
    drawn_h = height * scale
    panel_h = drawn_h + pad * 2
    panel_bottom = top - panel_h
    origin_x = left + (span - drawn_w) / 2
    origin_top = top - pad
    font = max(11.0, min(15.0, 10.5 * scale))
    ops = [
        "0.957 0.969 0.984 rg",
        f"{left:.2f} {panel_bottom:.2f} {span:.2f} {panel_h:.2f} re f",
        "0.071 0.365 0.910 RG",
        "1.4 w",
    ]
    for box in boxes:
        box_left = origin_x + box.x * scale
        box_bottom = origin_top - (box.y + box.h) * scale
        box_w = box.w * scale
        box_h = box.h * scale
        label = _fit(box.label, 28)
        ops.append("1 1 1 rg")
        ops.append(f"{box_left:.2f} {box_bottom:.2f} {box_w:.2f} {box_h:.2f} re B")
        text_w = len(label) * font * 0.50
        text_x = box_left + max(6.0, (box_w - text_w) / 2)
        text_y = box_bottom + box_h * 0.34
        ops.append(f"BT /F1 {font:.1f} Tf 0 0.098 0.22 rg")
        ops.append(f"1 0 0 1 {text_x:.2f} {text_y:.2f} Tm ({_pdf(label)}) Tj ET")
        ops.append("0.071 0.365 0.910 RG")
    for arrow in arrows:
        x1 = origin_x + arrow.x1 * scale
        y1 = origin_top - arrow.y1 * scale
        x2 = origin_x + arrow.x2 * scale
        y2 = origin_top - arrow.y2 * scale
        ops.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
        ops.extend(_head(x1, y1, x2, y2, max(8.0, 5.5 * scale)))
        if arrow.label:
            ops.append("BT /F1 9 Tf 0 0.098 0.22 rg")
            ops.append(
                f"1 0 0 1 {(x1 + x2) / 2:.2f} {(y1 + y2) / 2 + 4:.2f} Tm ({_pdf(_fit(arrow.label, 24))}) Tj ET"
            )
            ops.append("0.071 0.365 0.910 RG")
    return "\n".join(ops), panel_h


def layout(source: str) -> tuple[list[Box], list[Arrow], float, float] | None:
    kind = _kind(source)
    if kind == "flow":
        return _flow(source)
    if kind == "c4":
        return _c4(source)
    if kind == "sequence":
        return _sequence(source)
    return None


def _kind(source: str) -> str | None:
    for line in _lines(source):
        if _FLOW.match(line):
            return "flow"
        if _C4.match(line):
            return "c4"
        if _SEQUENCE.match(line):
            return "sequence"
        return None
    return None


def _lines(source: str) -> list[str]:
    found = []
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        lowered = line.lower()
        if lowered == "end" or lowered.startswith(_SKIP) or lowered.startswith("%%{init"):
            continue
        if "javascript:" in lowered or "data:text/html" in lowered:
            continue
        found.append(line)
    return found


def _flow(source: str) -> tuple[list[Box], list[Arrow], float, float] | None:
    direction = "TD"
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for line in _lines(source):
        head = _FLOW.match(line)
        if head:
            if head.group(2):
                direction = head.group(2).upper()
            continue
        parsed_nodes, parsed_edges = _chain(line)
        if not parsed_nodes:
            continue
        for node_id, label in parsed_nodes:
            nodes.setdefault(node_id, label)
        edges.extend(parsed_edges)
    if not nodes:
        return None
    return _place(nodes, edges, direction)


def _c4(source: str) -> tuple[list[Box], list[Arrow], float, float] | None:
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for line in _lines(source):
        if _C4.match(line):
            continue
        node = _C4_NODE.match(line)
        if node:
            nodes[node.group(1)] = node.group(2).strip() or node.group(1)
            continue
        rel = _C4_REL.match(line)
        if rel:
            edges.append((rel.group(1), rel.group(2), rel.group(3).strip()))
            nodes.setdefault(rel.group(1), rel.group(1))
            nodes.setdefault(rel.group(2), rel.group(2))
    if not nodes:
        return None
    return _place(nodes, edges, "TD")


def _sequence(source: str) -> tuple[list[Box], list[Arrow], float, float] | None:
    labels: dict[str, str] = {}
    order: list[str] = []
    messages: list[tuple[str, str, str]] = []
    for line in _lines(source):
        if _SEQUENCE.match(line):
            continue
        part = _PART.match(line)
        if part:
            node_id = part.group(1)
            labels[node_id] = (part.group(2) or node_id).strip()
            if node_id not in order:
                order.append(node_id)
            continue
        message = _MSG.match(line)
        if message is None:
            continue
        left, right, text = message.group(1), message.group(2), message.group(3).strip()
        for node_id in (left, right):
            if node_id not in order:
                order.append(node_id)
                labels.setdefault(node_id, node_id)
        messages.append((left, right, text))
    if not order:
        return None
    boxes: list[Box] = []
    centers: dict[str, float] = {}
    column = max(150.0, max(_size(labels[node_id])[0] for node_id in order) + 28.0)
    for index, node_id in enumerate(order):
        width, height = _size(labels[node_id])
        x = 16 + index * column
        boxes.append(Box(labels[node_id], x, 12, width, height))
        centers[node_id] = x + width / 2
    arrows: list[Arrow] = []
    y = 78.0
    for left, right, text in messages:
        arrows.append(Arrow(centers[left], y, centers[right], y, text))
        y += 34.0
    width = 16 + len(order) * column
    return boxes, arrows, width, y


def _chain(line: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    matches = list(_EDGE.finditer(line))
    if not matches:
        node = _node(line.strip())
        return ([node] if node else []), []
    nodes: list[tuple[str, str]] = []
    cursor = 0
    for match in matches:
        node = _node(line[cursor:match.start()].strip())
        if node is None:
            return [], []
        nodes.append(node)
        cursor = match.end()
    tail = _node(line[cursor:].strip())
    if tail is None:
        return [], []
    nodes.append(tail)
    edges = [
        (nodes[index][0], nodes[index + 1][0], (match.group(2) or "").strip())
        for index, match in enumerate(matches)
    ]
    return nodes, edges


def _node(text: str) -> tuple[str, str] | None:
    match = _NODE.match(text)
    if match is None:
        return None
    label = next((group for group in match.groups()[1:] if group), match.group(1))
    return match.group(1), label.strip() or match.group(1)


def _place(
    nodes: dict[str, str],
    edges: list[tuple[str, str, str]],
    direction: str,
) -> tuple[list[Box], list[Arrow], float, float]:
    ids = list(nodes)
    layers = _layers(ids, [(src, dst) for src, dst, _label in edges])
    grouped: dict[int, list[str]] = {}
    for node_id, layer in layers.items():
        grouped.setdefault(layer, []).append(node_id)
    order = sorted(grouped)
    if direction == "RL":
        order = list(reversed(order))
    if direction == "BT":
        order = list(reversed(order))
    sizes = {node_id: _size(nodes[node_id]) for node_id in ids}
    positions: dict[str, tuple[float, float, float, float]] = {}
    gap_x = 40.0
    gap_y = 52.0
    if direction in {"LR", "RL"}:
        x = 16.0
        for layer in order:
            row = grouped[layer]
            column_w = max(sizes[node_id][0] for node_id in row)
            y = 16.0
            for node_id in row:
                width, height = sizes[node_id]
                positions[node_id] = (x + (column_w - width) / 2, y, width, height)
                y += height + 18.0
            x += column_w + gap_x
    else:
        y = 16.0
        widths = []
        for layer in order:
            row = grouped[layer]
            widths.append(sum(sizes[node_id][0] for node_id in row) + gap_x * (len(row) - 1))
        canvas = max(widths) if widths else 0.0
        for layer in order:
            row = grouped[layer]
            row_w = sum(sizes[node_id][0] for node_id in row) + gap_x * (len(row) - 1)
            x = 16.0 + max(0.0, (canvas - row_w) / 2)
            row_h = max(sizes[node_id][1] for node_id in row)
            for node_id in row:
                width, height = sizes[node_id]
                positions[node_id] = (x, y + (row_h - height) / 2, width, height)
                x += width + gap_x
            y += row_h + gap_y
    boxes = [Box(nodes[node_id], *positions[node_id]) for node_id in ids]
    arrows = []
    for src, dst, label in edges:
        if src not in positions or dst not in positions:
            continue
        x1, y1 = _border(positions[src], positions[dst])
        x2, y2 = _border(positions[dst], positions[src])
        arrows.append(Arrow(x1, y1, x2, y2, label))
    max_x = max(box.x + box.w for box in boxes) + 16.0
    max_y = max((box.y + box.h for box in boxes), default=16.0)
    max_y = max(max_y, max((arrow.y1 for arrow in arrows), default=0.0), max((arrow.y2 for arrow in arrows), default=0.0))
    return boxes, arrows, max_x, max_y + 16.0


def _layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    pending = set(ids)
    preds = {node_id: set() for node_id in ids}
    for src, dst in edges:
        if src in preds and dst in preds and src != dst:
            preds[dst].add(src)
    layers: dict[str, int] = {}
    index = 0
    while pending:
        ready = [node_id for node_id in ids if node_id in pending and preds[node_id].isdisjoint(pending)]
        if not ready:
            ready = [sorted(pending)[0]]
        for node_id in ready:
            layers[node_id] = index
        pending.difference_update(ready)
        index += 1
    return layers


def _size(label: str) -> tuple[float, float]:
    text = _fit(label, 42)
    return min(240.0, max(96.0, 7.2 * len(text) + 28.0)), 36.0


def _border(box: tuple[float, float, float, float], other: tuple[float, float, float, float]) -> tuple[float, float]:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    ox, oy = other[0] + other[2] / 2, other[1] + other[3] / 2
    dx, dy = ox - cx, oy - cy
    if dx == 0 and dy == 0:
        return cx, cy
    scale_x = (box[2] / 2) / abs(dx) if dx else 1e9
    scale_y = (box[3] / 2) / abs(dy) if dy else 1e9
    scale = min(scale_x, scale_y)
    return cx + dx * scale, cy + dy * scale


def _head(x1: float, y1: float, x2: float, y2: float, length: float = 8.0) -> list[str]:
    angle = math.atan2(y2 - y1, x2 - x1)
    spread = 0.45
    x3 = x2 - length * math.cos(angle - spread)
    y3 = y2 - length * math.sin(angle - spread)
    x4 = x2 - length * math.cos(angle + spread)
    y4 = y2 - length * math.sin(angle + spread)
    return [
        "0.071 0.365 0.910 rg",
        f"{x2:.2f} {y2:.2f} m {x3:.2f} {y3:.2f} l {x4:.2f} {y4:.2f} l h f",
    ]


def _fit(label: str, limit: int) -> str:
    text = " ".join(label.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _pdf(value: str) -> str:
    raw = value.encode("latin-1", "replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
