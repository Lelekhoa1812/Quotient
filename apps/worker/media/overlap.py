# Motivation vs Logic
# Motivation: Overlap evidence must not download pyannote weights when the license forbids commercial use.
# Logic: Read the model-card SPDX id first. NC or unknown licenses record a block and keep Silero probabilities only.

from __future__ import annotations

from dataclasses import dataclass

PIPELINE = "pyannote/speaker-diarization-community-1"
LICENSE_URL = "https://huggingface.co/pyannote/speaker-diarization-community-1/raw/main/README.md"

COMMERCIAL_OK = frozenset(
    {
        "cc-by-4.0",
        "cc-by-3.0",
        "cc-by-2.0",
        "cc0-1.0",
        "mit",
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "unlicense",
        "isc",
    }
)


@dataclass(frozen=True)
class Hypothesis:
    id: str
    start_ms: int
    end_ms: int
    overlap_likelihood: float


def license_id_from_card(card: str) -> str | None:
    """Read the Hugging Face card's structured license field. Prose is not scanned."""
    text = card.lstrip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        front = text[3:end] if end != -1 else text[3:]
        for line in front.splitlines():
            if line.startswith("license:"):
                return line.split(":", 1)[1].strip().strip("\"'")
        return None
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        import json

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        license_id = data.get("license")
        return license_id if isinstance(license_id, str) else None
    return None


def commercial_use_allowed(license_id: str | None) -> bool:
    if not license_id:
        return False
    norm = license_id.strip().lower()
    if "nc" in norm.split("-"):
        return False
    return norm in COMMERCIAL_OK


def fetch_license(url: str = LICENSE_URL) -> str:
    from urllib.request import urlopen

    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def _overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def attach_hypotheses(spans: list, hypotheses: list[Hypothesis]) -> None:
    for span in spans:
        best = None
        best_overlap = 0
        for hypothesis in hypotheses:
            overlap = _overlap_ms(span.start_ms, span.end_ms, hypothesis.start_ms, hypothesis.end_ms)
            if overlap > best_overlap:
                best = hypothesis
                best_overlap = overlap
        if best is not None:
            span.speaker_hypothesis_id = best.id
            span.overlap_likelihood = best.overlap_likelihood


def silero_likelihood(span, probabilities: list[float], window_ms: int = 32) -> float:
    if not probabilities:
        return 0.0
    start = span.start_ms // window_ms
    end = max(start + 1, (span.end_ms + window_ms - 1) // window_ms)
    window = probabilities[start:end]
    return max(window) if window else 0.0


def build_overlap(license_card: str, download, spans: list, probabilities: list[float]) -> dict:
    """download() is the weight fetch. It runs only after the license allows commercial use."""
    license_id = license_id_from_card(license_card)
    allowed = commercial_use_allowed(license_id)
    block = {
        "pipeline": PIPELINE,
        "license": license_id,
        "commercial_use": allowed,
        "weights_downloaded": False,
        "fallback": None,
    }
    if not allowed:
        block["fallback"] = "silero_speech_probability"
        for span in spans:
            span.overlap_likelihood = silero_likelihood(span, probabilities)
            span.speaker_hypothesis_id = None
        return block
    hypotheses = download()
    block["weights_downloaded"] = True
    attach_hypotheses(spans, hypotheses)
    return block
