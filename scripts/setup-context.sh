#!/usr/bin/env bash
# Motivation vs Logic
# Motivation: Reference documents (Word, PowerPoint, Excel, PDF, EPUB, HTML) become Markdown with Microsoft
# MarkItDown. It pulls about 290 MB of parsers (pandas, lxml, onnxruntime) that the worker's own
# environment, and its pinned requirements, should not carry.
# Logic: Build a separate venv at .local/context-venv (git-ignored) with a pinned version and only the
# extras the supported formats need; the worker runs it as a subprocess with a timeout
# (apps/worker/context/convert.py). No audio, video, Azure or YouTube extras are installed, and the
# converter makes no network call. Works with Python 3.10 to 3.14.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${QUOTIENT_CONTEXT_BASE_PYTHON:-$(command -v python3 || true)}"
[[ -n "$PY" ]] || { echo "python3 is required" >&2; exit 1; }
VENV="${ROOT}/.local/context-venv"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --disable-pip-version-check -q "markitdown[pdf,docx,pptx,xlsx,xls]==0.1.8"
"$VENV/bin/python" -c "import markitdown; from markitdown import MarkItDown; MarkItDown(enable_plugins=False); print('context converter ready')"
