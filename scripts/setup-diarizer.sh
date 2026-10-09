#!/usr/bin/env bash
# Motivation vs Logic
# Motivation: Speaker diarization (pyannote/speaker-diarization-3.1) needs torch 2.8 and
# pyannote.audio 3.4, which do not support the worker's Python 3.14.
# Logic: Build a separate Python 3.12 venv at .local/diarizer-venv (git-ignored) with pinned
# versions. The worker calls it as a subprocess (apps/worker/media/diarize.py). Model weights are
# downloaded on first use with HF_TOKEN from .env; the account must have accepted the terms of
# pyannote/segmentation-3.0 and pyannote/speaker-diarization-3.1 on Hugging Face.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${QUOTIENT_DIARIZER_BASE_PYTHON:-$(command -v python3.12 || true)}"
[[ -n "$PY" ]] || { echo "python3.12 is required (brew install python@3.12)" >&2; exit 1; }
VENV="${ROOT}/.local/diarizer-venv"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --disable-pip-version-check -q \
  "pyannote.audio==3.4.0" "torch==2.8.0" "torchaudio==2.8.0" "huggingface_hub<1.0" numpy
"$VENV/bin/python" -c "import pyannote.audio, torch; print('diarizer ready:', pyannote.audio.__version__, 'torch', torch.__version__)"
