# Motivation vs Logic
# Motivation: The brief sentence is markdown, and a mermaid fence has to appear
# as a diagram in the downloaded file, in the same place it sits in the prose.
# Logic: Split fences before paragraphs. Drawn diagrams become inline SVG.
# Any other mermaid header stays a mermaid block for the client renderer.

from __future__ import annotations

import html
import re

from quotient.export.diagram import layout, svg_for

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*([^`~\n]*)$")
_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)")
_MERMAID = """<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.esm.min.mjs";
mermaid.initialize({ startOnLoad: true, securityLevel: "strict", theme: "neutral" });
</script>
"""


def render_markdown(text: str) -> tuple[str, bool]:
    parts: list[str] = []
    script = False
    for kind, body in _blocks(text):
        if kind == "mermaid":
            marker = f"q-arrow-{len(parts)}"
            drawn = svg_for(body, marker)
            if drawn:
                parts.append(f'<figure class="diagram">{drawn}</figure>')
            else:
                script = True
                parts.append(f'<pre class="mermaid">{html.escape(body)}</pre>')
            continue
        if kind == "code":
            parts.append(f"<pre><code>{html.escape(body)}</code></pre>")
            continue
        if kind == "heading":
            parts.append(f"<h2>{_inline(body)}</h2>")
            continue
        if kind == "ul":
            items = "".join(f"<li>{_inline(item)}</li>" for item in body.split("\n"))
            parts.append(f"<ul>{items}</ul>")
            continue
        if kind == "ol":
            items = "".join(f"<li>{_inline(item)}</li>" for item in body.split("\n"))
            parts.append(f"<ol>{items}</ol>")
            continue
        parts.append("<p>" + "<br>".join(_inline(line) for line in body.split("\n")) + "</p>")
    return "\n".join(parts), script


def mermaid_script() -> str:
    return _MERMAID


def pdf_pieces(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Bugs vs Fixes

    Bug: List markers were stripped, so a brief sentence became bare lines and
    the diagram was detached from them.
    Fix: Keep heading, bullet, and paragraph runs. Return drawable mermaid
    source in order. An undrawable fence stays as source lines.
    """

    runs: list[tuple[str, str]] = []
    figures: list[str] = []
    for kind, body in _blocks(text):
        if kind == "mermaid":
            if layout(body) is None:
                runs.append(("p", "Diagram"))
                runs.extend(("p", line) for line in body.splitlines() if line.strip())
            else:
                figures.append(body)
            continue
        if kind == "heading":
            runs.append(("heading", _plain(body)))
            continue
        if kind in {"ul", "ol"}:
            runs.extend(("bullet", _plain(line)) for line in body.splitlines() if line.strip())
            continue
        for line in body.splitlines():
            visible = _plain(line)
            if visible:
                runs.append(("p", visible))
    return runs, figures


def _blocks(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        match = _FENCE.match(lines[index])
        if match:
            marker = match.group(1)
            info = match.group(2).strip()
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index].strip() != marker:
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            kind = "mermaid" if info == "mermaid" else "code"
            blocks.append((kind, "\n".join(body).strip("\n")))
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and _FENCE.match(lines[index]) is None:
            paragraph.append(lines[index])
            index += 1
        if paragraph:
            blocks.append(_paragraph(paragraph))
        while index < len(lines) and not lines[index].strip():
            index += 1
    return blocks


def _paragraph(lines: list[str]) -> tuple[str, str]:
    if all(re.match(r"^[-*] ", line) for line in lines):
        return "ul", "\n".join(line[2:] for line in lines)
    if all(re.match(r"^\d+\. ", line) for line in lines):
        return "ol", "\n".join(re.sub(r"^\d+\. ", "", line) for line in lines)
    heading = re.match(r"^#{1,3} (.+)$", lines[0])
    if heading and len(lines) == 1:
        return "heading", heading.group(1)
    return "p", "\n".join(lines)


def _plain(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def _inline(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _INLINE.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]))
        token = match.group(0)
        if token.startswith("`"):
            parts.append(f"<code>{html.escape(token[1:-1])}</code>")
        elif token.startswith("**"):
            parts.append(f"<strong>{html.escape(token[2:-2])}</strong>")
        else:
            parts.append(f"<em>{html.escape(token[1:-1])}</em>")
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)
