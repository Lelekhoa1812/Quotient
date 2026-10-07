"""Motivation vs Logic

Motivation: Caption tracks and the text exports are projections of the graph.
Burned video stays on the worker because it needs the source object and ffmpeg.
Logic: This module renders JSON, HTML, CSV, a minimal PDF, a minimal XLSX, and
WebVTT/SRT from an already gated partner view. It does not call a model.
"""

from __future__ import annotations

import csv
import html
import io
import json
import zipfile

from quotient.export.captions import srt, webvtt
from quotient.export.diagram import pdf_figure
from quotient.export.markup import mermaid_script, pdf_pieces, render_markdown

EXPORTS: tuple[tuple[str, str], ...] = (
    ("graph.json", "application/json"),
    ("brief.html", "text/html; charset=utf-8"),
    ("brief.pdf", "application/pdf"),
    ("actions.csv", "text/csv; charset=utf-8"),
    ("actions.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("captions.vtt", "text/vtt; charset=utf-8"),
    ("captions.srt", "application/x-subrip"),
    ("burned.mp4", "video/mp4"),
)

LOCAL_EXPORTS = frozenset(name for name, _mime in EXPORTS if name != "burned.mp4")
_TEXT_EXPORTS = frozenset({"graph.json", "brief.html", "actions.csv", "captions.vtt", "captions.srt"})
_ACTION_HEADER = (
    "statement",
    "acceptance",
    "owner_display",
    "due_kind",
    "due_surface",
    "due_date",
    "claim_ids",
)


def mime_for(name: str) -> str | None:
    for export_name, mime in EXPORTS:
        if export_name == name:
            return mime
    return None


def render_local(name: str, projected: dict) -> tuple[str, bytes] | None:
    mime = mime_for(name)
    if mime is None or name not in LOCAL_EXPORTS:
        return None
    if name == "graph.json":
        body = json.dumps(projected["graph"], ensure_ascii=False, indent=2).encode("utf-8")
    elif name == "brief.html":
        body = _html(projected["brief"]).encode("utf-8")
    elif name == "brief.pdf":
        body = _pdf(_pdf_blocks(projected["brief"]))
    elif name == "actions.csv":
        body = _csv(projected["graph"]["actions"]).encode("utf-8")
    elif name == "actions.xlsx":
        body = _xlsx(projected["graph"]["actions"])
    elif name == "captions.vtt":
        body = webvtt(projected["graph"]["spans"]).encode("utf-8")
    elif name == "captions.srt":
        body = srt(projected["graph"]["spans"]).encode("utf-8")
    else:
        return None
    return mime, body


def is_text(name: str) -> bool:
    return name in _TEXT_EXPORTS


def _html(brief: dict) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head><meta charset=\"utf-8\"><title>Quotient brief</title>",
        "<style>",
        "body{font:16px/1.5 sans-serif;max-width:42rem;margin:2rem auto;color:#001938;background:#fff;padding:0 1rem}",
        "figure.diagram{margin:1rem 0} svg{max-width:100%;height:auto}",
        "pre{overflow:auto;background:#f4f7fb;padding:.75rem}",
        "h1{font-size:1.6rem;margin:0 0 1.25rem}",
        "p.cite{margin:.25rem 0 1.25rem;font-size:.85rem}",
        "</style></head>",
        "<body>",
        "<h1>Brief</h1>",
    ]
    if brief.get("withheld"):
        parts.append("<p>The brief is withheld. Unpublished claims stay in the review queue.</p>")
        parts.append("</body></html>")
        return "\n".join(parts)
    script = False
    for sentence in brief.get("synthesis") or []:
        playback = str(sentence.get("playback") or "")
        fragment, needs_script = render_markdown(str(sentence.get("text") or ""))
        script = script or needs_script
        parts.append(fragment)
        clock = _clock(playback)
        if clock and playback:
            href = html.escape(playback, quote=True)
            parts.append(f'<p class="cite"><a href="{href}">{html.escape(clock)}</a></p>')
    for action in brief.get("actions") or []:
        label = html.escape(str(action.get("acceptance") or "proposed"))
        statement = html.escape(str(action.get("statement") or ""))
        owner = html.escape(str(action.get("owner_display") or "not stated"))
        parts.append(f"<p>{label}: {statement} ({owner})</p>")
    for omission in brief.get("omissions") or []:
        reason = html.escape(str(omission.get("reason") or ""))
        parts.append(f"<p>Omission: {reason}</p>")
    if script:
        parts.append(mermaid_script())
    parts.append("</body></html>")
    return "\n".join(parts)


def _clock(playback: object) -> str | None:
    if not isinstance(playback, str) or "t=" not in playback:
        return None
    digits = playback.split("t=", 1)[1].split("&", 1)[0]
    if not digits.isdigit():
        return None
    seconds = int(digits) // 1000
    return f"At {seconds // 60}:{seconds % 60:02d}"


def _pdf_blocks(brief: dict) -> list[tuple[str, str]]:
    """Bugs vs Fixes

    Bug: The page led with every empty dimension and a raw playback path, then
    parked the diagram on a following blank page.
    Fix: Title, the sentence in reading order, the figure under that sentence,
    and a clock citation. Empty dimensions stay off the page.
    """

    blocks: list[tuple[str, str]] = [("title", "Brief")]
    if brief.get("withheld"):
        blocks.append(("p", "The brief is withheld. Unpublished claims stay in the review queue."))
        return blocks
    for sentence in brief.get("synthesis") or []:
        prose, figures = pdf_pieces(str(sentence.get("text") or ""))
        blocks.extend(prose)
        blocks.extend(("figure", source) for source in figures)
        clock = _clock(sentence.get("playback"))
        if clock:
            blocks.append(("cite", clock))
        blocks.append(("gap", ""))
    actions = [action for action in brief.get("actions") or [] if isinstance(action, dict)]
    if actions:
        blocks.append(("heading", "Actions"))
        for action in actions:
            blocks.append(
                (
                    "p",
                    f"{action.get('acceptance') or 'proposed'}: {action.get('statement') or ''} ({action.get('owner_display') or 'not stated'})",
                )
            )
    for omission in brief.get("omissions") or []:
        if isinstance(omission, dict) and omission.get("reason"):
            blocks.append(("p", f"Omission: {omission.get('reason')}"))
    return blocks


def _pdf_streams(blocks: list[tuple[str, str]]) -> list[bytes]:
    left, right, top, bottom = 54.0, 558.0, 740.0, 64.0
    pages: list[list[str]] = [[]]
    y = top

    def esc(line: str) -> str:
        raw = line.encode("cp1252", "replace").decode("latin-1")
        return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def new_page() -> None:
        nonlocal y
        pages.append([])
        y = top

    def room(height: float) -> None:
        nonlocal y
        if y - height < bottom:
            new_page()

    def text(line: str, size: float, font: str, gap: float, indent: float = 0.0) -> None:
        nonlocal y
        room(size + gap)
        y -= size
        ink = "0.35 0.42 0.50" if font == "cite" else "0 0.098 0.22"
        face = "F2" if font in {"F2", "title"} else "F1"
        if font == "cite":
            face = "F1"
        pages[-1].append(
            f"BT /{face} {size:.1f} Tf {ink} rg 1 0 0 1 {left + indent:.2f} {y:.2f} Tm ({esc(line)}) Tj ET"
        )
        y -= gap

    def wrap(line: str, width: int) -> list[str]:
        words = line.split()
        if not words:
            return []
        rows: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if len(trial) > width:
                rows.append(current)
                current = word
            else:
                current = trial
        rows.append(current)
        return rows

    for kind, body in blocks:
        if kind == "gap":
            y -= 8
            continue
        if kind == "figure":
            max_height = y - bottom
            if max_height < 200:
                new_page()
                max_height = y - bottom
            drawn = pdf_figure(body, left=left, right=right, top=y, max_height=min(max_height, 460))
            if drawn is None:
                continue
            ops, used = drawn
            pages[-1].append(ops)
            y -= used + 16
            continue
        if kind == "title":
            text(body, 20, "F2", 8)
            rule = y - 4
            pages[-1].append(f"0.071 0.365 0.910 RG 1.2 w {left:.2f} {rule:.2f} m {right:.2f} {rule:.2f} l S")
            y = rule - 16
            continue
        if kind == "heading":
            text(body, 13, "F2", 8)
            continue
        if kind == "cite":
            text(body, 9, "cite", 10)
            continue
        prefix = "• " if kind == "bullet" else ""
        indent = 14.0 if kind == "bullet" else 0.0
        for row in wrap(prefix + body, 78 if kind == "bullet" else 84):
            text(row, 11, "F1", 4, indent if row.startswith("• ") else 0.0)
        y -= 6
    streams = ["\n".join(ops).encode("latin-1") for ops in pages if ops]
    return streams or [b""]


def _pdf(blocks: list[tuple[str, str]]) -> bytes:
    streams = _pdf_streams(blocks)
    # Bugs vs Fixes
    # Bug: One text object dumped every line until the margin, then each figure
    # was a separate unscaled page.
    # Fix: Object 3 is Helvetica and object 4 is Helvetica-Bold. Each page is a
    # page object plus the content stream built by the flowing layout.
    objects: dict[int, bytes] = {
        3: b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        4: b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n",
    }
    page_ids: list[int] = []
    next_id = 5
    for stream in streams:
        page_id = next_id
        stream_id = next_id + 1
        next_id += 2
        page_ids.append(page_id)
        objects[page_id] = (
            f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {stream_id} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >> endobj\n"
        ).encode("ascii")
        objects[stream_id] = (
            f"{stream_id} 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    objects[2] = (
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >> endobj\n"
    ).encode("ascii")
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    chunks = [header]
    offsets = [0]
    cursor = len(header)
    for number in range(1, max(objects) + 1):
        blob = objects[number]
        offsets.append(cursor)
        chunks.append(blob)
        cursor += len(blob)
    xref_at = cursor
    xref = [b"xref\n", f"0 {len(offsets)}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return b"".join(chunks + xref + [trailer])


def _action_rows(actions: list[dict]) -> list[list[str]]:
    rows = [list(_ACTION_HEADER)]
    for action in actions:
        rows.append(
            [
                str(action.get("statement") or ""),
                str(action.get("acceptance") or ""),
                str(action.get("owner_display") or "not stated"),
                str(action.get("due_kind") or ""),
                str(action.get("due_surface") or ""),
                "" if action.get("due_date") is None else str(action.get("due_date")),
                " ".join(action.get("claim_ids") or []),
            ]
        )
    return rows


def _csv(actions: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(_action_rows(actions))
    return buffer.getvalue()


def _xlsx(actions: list[dict]) -> bytes:
    rows = _action_rows(actions)
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row):
            ref = f"{chr(ord('A') + col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{_xml(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Actions" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return blob.getvalue()


def _xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
