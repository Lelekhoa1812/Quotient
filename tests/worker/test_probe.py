import subprocess
from pathlib import Path

from media.probe import probe, readable_duration_ms
from visual.frames import extract_frame


def _clip(path: Path, seconds: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


def test_a_complete_file_keeps_the_header_duration(tmp_path):
    path = tmp_path / "whole.mp4"
    _clip(path, 3)
    declared = int(round(float(probe(path)["format"]["duration"]) * 1000))
    assert abs(readable_duration_ms(path, declared) - declared) <= 1500


def test_a_truncated_file_stops_at_the_last_packet(tmp_path):
    full = tmp_path / "full.mp4"
    _clip(full, 8)
    cut = tmp_path / "cut.mp4"
    data = full.read_bytes()
    cut.write_bytes(data[: max(4096, len(data) // 3)])
    declared = int(round(float(probe(cut)["format"]["duration"]) * 1000))
    readable = readable_duration_ms(cut, declared)
    assert declared > 5000
    assert 0 < readable < declared - 1500


def test_extract_frame_writes_a_jpeg(tmp_path):
    path = tmp_path / "clip.mp4"
    _clip(path, 2)
    dest = tmp_path / "frame.jpg"
    extract_frame(path, 400, dest)
    assert dest.stat().st_size > 100
