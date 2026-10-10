# Motivation vs Logic
# Motivation: A video model given a whole window of a meeting returned placeholder people and made-up table
# contents, and stamped nearly every screen at the start of its window. What is on a slide, in a shared
# application, or on a name tile has to be read from the picture itself, with its time known exactly.
# Logic: Sample frames at an even interval, read each one on its own with a vision model that may only copy
# what is legible, and turn the readings into screens (a frame that repeats the one before extends it) and
# name sightings (a name with the active-speaker mark is evidence about who is talking). A frame that cannot
# be read is skipped, never guessed; names that look like placeholders are dropped in code as a second guard.

from __future__ import annotations

import base64
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from errors import NotInvocable, SchemaRejected
from loop.pool import map_ordered
from pegasus.client import SCREEN_KINDS, Screen, Sighting
from registry.check import validate_json
from registry.ids import FRAME

FRAME_INTERVAL_MS = 8_000
MAX_FRAMES = 160
FRAME_WIDTH = 1280
FRAME_TIMEOUT_SECONDS = 120
SAME_SCREEN = 0.88  # text similarity above which two neighbouring frames show the same thing

_PLACEHOLDER = re.compile(
    r"^(john|jane|jon)\s+(doe|smith)$|^(bob|alice|mary)\s+(johnson|smith)$|^lorem\b|^(user|name|participant)\s*\d*$|^(presenter|host|speaker)$",
    re.I,
)


def frame_times(duration_ms: int, interval_ms: int = FRAME_INTERVAL_MS, limit: int = MAX_FRAMES) -> tuple[list[int], int]:
    """Times (ms) of the frames to read: the middle of each interval, so a frame stands for the stretch around it.
    The interval widens for a long recording so the number of frames stays under the limit."""
    if duration_ms <= 0:
        return [], interval_ms
    interval = max(interval_ms, -(-duration_ms // limit))
    # Stay clear of the very end: a seek to the last frame of a file can fail.
    last = max(0, duration_ms - 1000)
    return [min(last, start + interval // 2) for start in range(0, duration_ms, interval)], interval


def extract_frame(path: Path, at_ms: int, dest: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{at_ms / 1000:.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "4", str(dest),
        ],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=FRAME_TIMEOUT_SECONDS,
    )
    return dest


def _request(prompt, schema: dict, image: bytes, model: str, region: str, cap: int) -> dict:
    encoded = base64.b64encode(image).decode("ascii")
    return {
        "model": model,
        "region": region,
        "max_output_tokens": cap,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": prompt.body}]},
            {"role": "user", "content": [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}"}]},
        ],
        "text": {"format": {"type": "json_schema", "name": "meeting_frame_v1", "schema": schema, "strict": True}},
    }


_URL = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|au|net|org|io)(?:/\S*)?", re.I)
_UNREADABLE = re.compile(r"\[unreadable\]|\w*\.\.\.|…", re.I)
SAME_TITLE_OVERLAP = 0.4  # the same page shown again: the same heading and most of the same words
OTHER_TITLE_OVERLAP = 0.85


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _words(*texts: str) -> set[str]:
    """The words of a reading that say what the screen is: no URLs (a model misreads them differently every
    time) and no unreadable fragments, so the same page read twice compares as the same page."""
    joined = " ".join(texts)
    joined = _UNREADABLE.sub(" ", _URL.sub(" ", joined))
    return {word for word in re.findall(r"[a-z0-9$%#][a-z0-9$%#.,'-]{2,}", joined.casefold())}


def _clean_title(title: str) -> str:
    return _norm(_UNREADABLE.sub(" ", title))


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def _same_screen(left: dict, right: dict) -> bool:
    words_a, words_b = _words(left["title"], left["text"]), _words(right["title"], right["text"])
    if not words_a and not words_b:
        return _norm(left["details"]) == _norm(right["details"])
    same_title = bool(_clean_title(left["title"])) and _clean_title(left["title"]) == _clean_title(right["title"])
    return _overlap(words_a, words_b) >= (SAME_TITLE_OVERLAP if same_title else OTHER_TITLE_OVERLAP)


def _quality(reading: dict) -> tuple[int, int]:
    """Cleaner is better, then fuller: the fewest unreadable marks, then the most text."""
    text = reading["text"]
    return (-len(_UNREADABLE.findall(text)), len(text))


def merge_readings(readings: list[tuple[int, dict]], interval_ms: int, duration_ms: int, meeting_id: str) -> tuple[list[Screen], list[Sighting]]:
    """readings: (frame time ms, validated frame object) in time order."""
    half = interval_ms // 2
    screens: list[dict] = []
    sightings: list[Sighting] = []
    for at, reading in readings:
        start, end = max(0, at - half), min(duration_ms, at + half)
        shown = reading["screen"]
        if shown["shown"] and (shown["text"].strip() or shown["details"].strip() or shown["title"].strip()):
            last = screens[-1] if screens else None
            # A screen is the same one if it carries on from the previous frame (nothing between them).
            if last is not None and start - last["end"] <= interval_ms and _same_screen(last, shown):
                last["end"] = end
                # Keep the cleanest, fullest reading of it: the same page is read a little differently each time.
                if _quality(shown) > _quality(last):
                    last.update(text=shown["text"], details=shown["details"] or last["details"], title=shown["title"] or last["title"], kind=shown["kind"])
            else:
                screens.append({**{k: shown[k] for k in ("kind", "title", "text", "details")}, "start": start, "end": end})
        for person in reading["people"]:
            name = person["name"].strip()
            if not name or _PLACEHOLDER.match(name):
                continue
            sightings.append(
                Sighting(
                    id=f"{meeting_id}-frame-{at}-{len(sightings)}",
                    name=name,
                    speaking=person["speaking"] is True,
                    cue=person["cue"],
                    start_ms=start,
                    end_ms=end,
                )
            )
    rows = [
        Screen(
            id=f"{meeting_id}-screen-f{index}",
            kind=item["kind"] if item["kind"] in SCREEN_KINDS else "other",
            title=re.sub(r"\s*\[unreadable\]?", "", item["title"]).strip(" |-")[:200],
            text=item["text"].strip()[:4000],
            details=item["details"].strip()[:3000],
            start_ms=item["start"],
            end_ms=item["end"],
        )
        for index, item in enumerate(screens)
    ]
    return rows, sightings


class FrameReader:
    def __init__(self, registry, transport, *, model: str, fallback: str | None, region: str, cap: int):
        self.registry = registry
        self.transport = transport
        self.model, self.fallback, self.region, self.cap = model, fallback, region, cap

    def read(self, path: Path, duration_ms: int, meeting_id: str, should_stop=None) -> tuple[list[Screen], list[Sighting], int]:
        """Returns screens, sightings and how many frames could not be read."""
        readings, interval, failed = self.read_frames(path, duration_ms, should_stop)
        screens, sightings = merge_readings(readings, interval, duration_ms, meeting_id)
        return screens, sightings, failed

    def read_frames(self, path: Path, duration_ms: int, should_stop=None) -> tuple[list[tuple[int, dict]], int, int]:
        """The raw frame readings (time, object) in time order, the interval between frames, and how many failed.
        Kept apart from merging so a saved reading can be merged again when the merge rules improve."""
        times, interval = frame_times(duration_ms)
        prompt = self.registry.prompt(FRAME)
        schema = self.registry.schema_for(FRAME)
        with tempfile.TemporaryDirectory(prefix="quotient-frames-") as scratch:
            def one(at: int):
                if should_stop is not None and should_stop():
                    return at, None
                try:
                    image = extract_frame(path, at, Path(scratch) / f"f{at}.jpg").read_bytes()
                    request = _request(prompt, schema, image, self.model, self.region, self.cap)

                    def ask():
                        try:
                            return self.transport.respond(request)
                        except NotInvocable:
                            if not self.fallback:
                                raise
                            return self.transport.respond({**request, "model": self.fallback})

                    try:
                        response = ask()
                    except TimeoutError:
                        response = ask()  # one model read can time out on a busy host; a second try is cheap
                    return at, validate_json(response.get("output_text", ""), schema)
                except (SchemaRejected, NotInvocable, RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
                    print(f"frame {at} skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
                    return at, None

            results = map_ordered(one, times)
        readings = [(at, data) for at, data in results if data is not None]
        return readings, interval, len(results) - len(readings)
