# Motivation vs Logic
# Motivation: Sentence text may carry a mermaid fence. The fence is diagram
# source, and a click or markup line inside it must not survive the gate.
# Logic: Keep a fence whose first statement is a mermaid header. Drop click,
# init, and javascript lines. Leave every other sentence byte unchanged.

from __future__ import annotations

import re

# Mermaid header tokens. This is the diagram grammar, not a topic list.
_HEADERS = frozenset(
    {
        "flowchart",
        "graph",
        "sequenceDiagram",
        "classDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        "erDiagram",
        "journey",
        "gantt",
        "pie",
        "mindmap",
        "timeline",
        "quadrantChart",
        "requirementDiagram",
        "gitGraph",
        "C4Context",
        "C4Container",
        "C4Component",
        "C4Dynamic",
        "C4Deployment",
        "block-beta",
        "architecture-beta",
        "kanban",
        "xychart-beta",
        "sankey-beta",
        "packet-beta",
        "radar-beta",
    }
)

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*([^`~\n]*)$")
# An HTML tag or comment, not a comparison: "<200ms" and "x < y" are labels, and `A --> B` is an arrow.
_TAG = re.compile(r"<(?:/?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*?)?(?<!-)/?|!--.*?--)>")
# Mermaid directives that attach behaviour or styling. A node that happens to be called "Link" or "Click"
# (`Link --> Gateway`) is a node, not a directive.
_DIRECTIVE = re.compile(r"^(?:click|link|callback)\s+[\w-]+\s*(?:$|href\b|call\b|callback\b|[\"'])", re.I)
_STYLING = re.compile(r"^(?:style|classdef|linkstyle|class)\s+[\w,.-]+\s", re.I)


def normalize(text: str) -> str:
    if "```" not in text and "~~~" not in text:
        return text
    lines = text.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        match = _FENCE.match(lines[index])
        if match is None:
            output.append(lines[index])
            index += 1
            continue
        marker = match.group(1)
        info = match.group(2).strip()
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip() != marker:
            body.append(lines[index])
            index += 1
        if index < len(lines):
            index += 1
        if info == "mermaid":
            cleaned = _scrub("\n".join(body))
            if cleaned:
                output.append("```mermaid")
                output.extend(cleaned.split("\n"))
                output.append("```")
            continue
        output.append(f"{marker}{info}" if info else marker)
        output.extend(body)
        output.append(marker)
    return "\n".join(output)


def _scrub(body: str) -> str | None:
    kept: list[str] = []
    header: str | None = None
    for line in body.split("\n"):
        cleaned = _line(line)
        if cleaned is None:
            continue
        if cleaned.strip() and header is None and not cleaned.strip().startswith("%%"):
            token = cleaned.split(None, 1)[0]
            if token not in _HEADERS:
                return None
            header = token
        kept.append(cleaned.rstrip())
    if header is None:
        return None
    while kept and kept[0] == "":
        kept.pop(0)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept)


def _line(line: str) -> str | None:
    stripped = line.strip()
    lowered = stripped.lower()
    if lowered.startswith("%%{init") or _DIRECTIVE.match(stripped) or _STYLING.match(stripped):
        return None
    if "javascript:" in lowered or "data:text/html" in lowered:
        return None
    return _TAG.sub("", line)
