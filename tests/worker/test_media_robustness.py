import json
import subprocess

import pytest

from media import diarize, storage


def test_recorder_media_types_with_codec_parameters_are_accepted_and_signed_without_them():
    assert storage.media_type_allowed("video/webm;codecs=vp8,opus")
    assert storage.media_type_allowed(" Audio/MP4 ; codecs=mp4a ")
    assert storage.base_media_type("video/webm;codecs=vp8,opus") == "video/webm"
    assert not storage.media_type_allowed("application/pdf") and not storage.media_type_allowed(None)


class _FakeProcess:
    """Stands in for the diarizer: writes its turns file when started, then reports it finished."""

    returncode = 0
    pid = 0

    def __init__(self, command, payload):
        with open(command[-1], "w", encoding="utf-8") as handle:
            handle.write(payload)

    def wait(self, timeout=None):
        return 0


def _run_with_output(monkeypatch, payload):
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setattr(diarize, "_python", lambda: "/bin/true")
    monkeypatch.setattr(diarize.subprocess, "Popen", lambda command, **kwargs: _FakeProcess(command, payload))
    return diarize.diarize_pcm(b"\x00\x00" * 16000)


def test_diarizer_output_that_is_not_an_object_or_has_bad_rows_never_crashes(monkeypatch):
    assert _run_with_output(monkeypatch, "[]") is None
    assert _run_with_output(monkeypatch, json.dumps({"turns": "x"})) is None
    rows = [[0, 1000, "spk_0"], ["x", 5, "spk_0"], [0, 0, "spk_1"], [-5, 10, "spk_1"], [10, 20]]
    assert _run_with_output(monkeypatch, json.dumps({"turns": rows})) == [(0, 1000, "spk_0")]


def test_a_cancelled_meeting_stops_the_diarizer_and_everything_it_started(tmp_path, monkeypatch):
    import os
    import time

    marker = tmp_path / "pids"
    fake = tmp_path / "python"
    fake.write_text(f"#!/bin/sh\nsleep 60 &\necho $! > {marker}\nsleep 60\n")
    fake.chmod(0o755)
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setattr(diarize, "_python", lambda: str(fake))
    started = time.monotonic()
    stops = iter([False, False, True])
    result = diarize.diarize_pcm(b"\x00\x00" * 16000, timeout_s=120, should_stop=lambda: next(stops, True))
    assert result is None and time.monotonic() - started < 20  # it did not run to the end of its 60 seconds
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)  # the background child went with it


def test_a_diarizer_that_outlives_its_time_limit_is_killed(tmp_path, monkeypatch):
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\nsleep 60\n")
    fake.chmod(0o755)
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setattr(diarize, "_python", lambda: str(fake))
    assert diarize.diarize_pcm(b"\x00\x00" * 16000, timeout_s=1.5) is None
