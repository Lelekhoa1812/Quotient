"""Mermaid fences stay inside synthesis sentences only when the header is real."""

from graph.prose import normalize
from graph.synth import sentences_from


def test_plain_sentence_is_unchanged():
    assert normalize("The date is unresolved.") == "The date is unresolved."


def test_flowchart_stays_and_click_markup_is_removed():
    text = """The service split.

```mermaid
flowchart TD
  A[API] --> B[Store]
  click A "javascript:alert(1)"
  A["<img src=x onerror=alert(1)>"] --> B
```
"""
    cleaned = normalize(text)
    assert "The service split." in cleaned
    assert "flowchart TD" in cleaned
    assert "A[API] --> B[Store]" in cleaned
    assert "javascript:" not in cleaned
    assert "<img" not in cleaned
    assert "```mermaid" in cleaned


def test_unknown_diagram_header_is_dropped():
    text = "See this.\n\n```mermaid\nnotADiagram\n  A --> B\n```\n"
    cleaned = normalize(text)
    assert "See this." in cleaned
    assert "notADiagram" not in cleaned
    assert "```" not in cleaned


def test_non_mermaid_fence_stays_a_code_fence():
    text = "```python\nprint(1)\n```"
    assert "print(1)" in normalize(text)
    assert "```python" in normalize(text)


def test_c4_header_is_kept():
    text = """```mermaid
C4Context
  System(api, "API")
```"""
    cleaned = normalize(text)
    assert "C4Context" in cleaned
    assert 'System(api, "API")' in cleaned


def test_sentences_drop_an_empty_invalid_fence():
    rows = sentences_from(
        {"sentences": [{"text": "```mermaid\nnotADiagram\n```", "finding_ids": ["f1"]}]}
    )
    assert rows == []


def test_sentences_keep_a_real_diagram():
    rows = sentences_from(
        {
            "sentences": [
                {
                    "text": "```mermaid\nflowchart TD\n  A[API] --> B[Store]\n```",
                    "finding_ids": ["f1"],
                }
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0].finding_ids == ["f1"]
    assert "flowchart TD" in rows[0].text
