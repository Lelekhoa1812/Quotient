import wave

import pytest

from media.clock import build_table, source_ms_of_sample
from media.compact import IndexedSpan, apply_omissions, payload_duration_ms, source_duration_ms
from media.idle import idle_spans
from media.overlap import Hypothesis, build_overlap, commercial_use_allowed
from media.pcm import ffmpeg_pcm_args, write_pcm
from media.probe import classify_file, classify_streams, model_plan
from media.vad import iter_windows, spans_from_probabilities


def test_ffprobe_classifies_audio_and_video_dict():
    assert classify_streams([{"codec_type": "audio"}]) == "audio"
    assert classify_streams([{"codec_type": "audio"}, {"codec_type": "video"}]) == "video"
    assert model_plan("audio") == frozenset({"sonic"})
    assert model_plan("video") == frozenset({"sonic", "pegasus"})


def test_ffprobe_and_pcm_keep_source_clock(tmp_path):
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x10" * 16000)
    assert classify_file(path) == "audio"
    dest = tmp_path / "tone.pcm"
    args = ffmpeg_pcm_args(path, dest)
    assert args.count("-ar") == 1 and "16000" in args
    assert "-ss" not in args
    assert write_pcm(path, dest) == 16000


def test_vad_windows_are_512_samples_at_16khz():
    with pytest.raises(ValueError, match="16 kHz"):
        iter_windows(b"\x00\x00" * 512, sample_rate=8000)
    windows = iter_windows(b"\x00\x00" * 512)
    assert len(windows) == 1 and len(windows[0]) == 1024
    spans = spans_from_probabilities([0.1, 0.9, 0.9, 0.1])
    assert [(span.kind, span.start_ms, span.end_ms) for span in spans] == [
        ("silence", 0, 32),
        ("speech", 32, 96),
        ("silence", 96, 128),
    ]
    assert spans[-1].end_ms == 128


def test_idle_spans_need_both_frame_delta_and_histogram():
    spans = idle_spans([0.1, 5.0, 0.1], [0.01, 0.9, 0.01], frame_ms=100, delta_max=1.0, hist_max=0.2)
    assert [span.kind for span in spans] == ["visual-idle", "visual-idle"]
    assert (spans[0].start_ms, spans[0].end_ms) == (0, 100)
    assert (spans[1].start_ms, spans[1].end_ms) == (200, 300)


def test_overlap_license_blocks_weights_before_download():
    blocked = {"called": False}

    def refuse():
        blocked["called"] = True
        return []

    class Row:
        def __init__(self):
            self.start_ms = 0
            self.end_ms = 32
            self.speaker_hypothesis_id = "preset"
            self.overlap_likelihood = None

    span = Row()
    block = build_overlap("---\nlicense: cc-by-nc-4.0\n---\n", refuse, [span], [0.8])
    assert blocked["called"] is False
    assert block["weights_downloaded"] is False
    assert block["fallback"] == "silero_speech_probability"
    assert span.speaker_hypothesis_id is None
    assert span.overlap_likelihood == 0.8
    assert commercial_use_allowed(None) is False
    assert commercial_use_allowed("proprietary") is False


def test_overlap_downloads_only_after_commercial_license():
    span_holder = {}

    class Row:
        def __init__(self):
            self.start_ms = 0
            self.end_ms = 32
            self.speaker_hypothesis_id = None
            self.overlap_likelihood = None

    span = Row()
    span_holder["span"] = span

    def allow():
        return [Hypothesis("h1", 0, 32, 0.4)]

    block = build_overlap("---\nlicense: cc-by-4.0\n---\n", allow, [span], [0.1])
    assert block["commercial_use"] is True
    assert block["weights_downloaded"] is True
    assert span.speaker_hypothesis_id == "h1"
    assert span.overlap_likelihood == 0.4


def test_compaction_never_drops_overlap_and_keeps_the_index():
    spans = [
        IndexedSpan("sil", "silence", 0, 1000),
        IndexedSpan("ov", "overlap", 1000, 2000, overlap=True),
        IndexedSpan("sp", "speech", 2000, 5000),
    ]
    indexed = apply_omissions(spans, ["sil", "ov", "sp"])
    by_id = {span.id: span for span in indexed}
    assert by_id["sil"].omitted is True
    assert by_id["ov"].omitted is False
    assert by_id["sp"].omitted is False
    assert {span.id for span in indexed} == {"sil", "ov", "sp"}
    assert by_id["ov"].start_ms == 1000 and by_id["ov"].end_ms == 2000
    assert payload_duration_ms(indexed) <= source_duration_ms(indexed)
    assert payload_duration_ms(indexed) == 4000


def test_sample_counts_map_through_omitted_silence():
    table = build_table(5000, [(1000, 2000)])
    assert source_ms_of_sample(0, table) == 0
    assert source_ms_of_sample(16000, table) == 2000
    assert source_ms_of_sample(table[-1].sample_end, table) == 5000


def test_a_picture_only_file_reports_no_audio_not_unreadable(tmp_path):
    import shutil
    import subprocess

    import pytest

    from errors import NoAudioTrack
    from media.pcm import write_pcm

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    source = tmp_path / "picture-only.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=64x64:r=5:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True,
    )
    with pytest.raises(NoAudioTrack):
        write_pcm(source, tmp_path / "out.pcm")
