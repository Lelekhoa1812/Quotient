from graph.prose import _scrub


def test_a_node_called_link_or_click_is_kept_but_real_directives_and_styling_are_not():
    body = "flowchart LR\n  Link --> Gateway\n  Click[Click handler] --> Queue\n  click Gateway href \"https://x\"\n  click Queue callback \"tip\"\n  style Gateway fill:#f00\n  classDef hot fill:#f00\n  Gateway --> Queue"
    out = _scrub(body)
    assert "Link --> Gateway" in out and "Click[Click handler] --> Queue" in out and "Gateway --> Queue" in out
    for gone in ("href", "callback", "style Gateway", "classDef"):
        assert gone not in out


def test_comparisons_and_arrows_survive_but_html_and_scripts_do_not():
    out = _scrub('flowchart LR\n  Queue["p95 < 200ms"] --> Worker\n  A[x<y] --> B[z>w]\n  C["<b>bold</b> <script>alert(1)</script>"] --> D\n  E["javascript:alert(1)"] --> F\n  <!-- hidden --> G --> H')
    assert 'Queue["p95 < 200ms"] --> Worker' in out
    assert "A[x<y] --> B[z>w]" in out
    assert "<b>" not in out and "<script>" not in out and "bold" in out
    assert "javascript:" not in out
    assert "hidden" not in out and "G --> H" in out


def test_a_fourteen_node_architecture_flowchart_passes_through_unchanged():
    nodes = [f"N{i}[Service {i}]" for i in range(14)]
    body = "flowchart LR\n" + "\n".join(f"  {a} --> {b}" for a, b in zip(nodes, nodes[1:]))
    assert _scrub(body) == body
