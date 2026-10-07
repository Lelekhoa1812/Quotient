import json

import pytest

from bedrock.limits import PEGASUS_MAX_OUTPUT_TOKENS, PEGASUS_MODEL, PEGASUS_REGION
from support import registry
from errors import TimestampOutside
from pegasus.client import PegasusClient, build_body, classify_observations
from pegasus.parts import pack_scenes


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def invoke(self, *, model_id, region, body):
        assert model_id == PEGASUS_MODEL
        assert region == PEGASUS_REGION
        assert body["maxOutputTokens"] == PEGASUS_MAX_OUTPUT_TOKENS
        assert "base64String" not in json.dumps(body)
        self.bodies.append(body)
        return self.responses.pop(0)


def test_scene_parts_stay_under_fifty_minutes():
    minute = 60_000
    short = pack_scenes([(0, 10 * minute)])
    assert len(short) == 1 and short[0].duration_ms == 10 * minute
    split = pack_scenes([(0, 40 * minute), (40 * minute, 80 * minute)])
    assert [part.duration_ms for part in split] == [40 * minute, 40 * minute]
    long = pack_scenes([(0, 70 * minute)])
    assert [part.duration_ms for part in long] == [50 * minute, 20 * minute]
    assert all(part.duration_ms <= 50 * minute for part in long)


def test_length_continuation_discards_the_partial_object():
    partial = '{"observations": ['
    complete = json.dumps(
        {
            "observations": [
                {"statement": "the slide changes", "start_ms": 0, "end_ms": 1000},
                {"statement": "a light flickered"},
            ],
            "notes": ["uncited flicker"],
        }
    )
    transport = Transport(
        [
            {"finishReason": "length", "message": partial},
            {"finishReason": "stop", "message": complete},
        ]
    )
    client = PegasusClient(registry(), transport)
    parts = pack_scenes([(600_000, 605_000)])
    result = client.analyze(parts, lambda part: "s3://axion-meeting-staging-media/part0.mp4", "m")
    assert len(transport.bodies) == 2
    assert all(body["maxOutputTokens"] == 4096 for body in transport.bodies)
    assert transport.bodies[0]["inputPrompt"] == registry().prompt("meeting.pegasus.v1").body
    assert transport.bodies[1]["inputPrompt"] == registry().prompt("meeting.pegasus.continue.v1").body
    assert partial not in transport.bodies[1]["inputPrompt"]
    assert transport.bodies[0]["mediaSource"]["s3Location"]["bucketOwner"] == "255834078973"
    assert "additionalProperties" not in json.dumps(transport.bodies[0]["responseFormat"])
    assert len(result.observations) == 1
    assert (result.observations[0].start_ms, result.observations[0].end_ms) == (600_000, 601_000)
    assert result.observations[0].can_support_claim is True
    assert len(result.notes) == 2
    assert all(note.can_support_claim is False for note in result.notes)


def test_vendor_max_cannot_be_lowered_and_times_must_sit_inside_the_part():
    with pytest.raises(ValueError, match="4096"):
        build_body("prompt", {}, "s3://bucket/video.mp4", max_output_tokens=2048)
    part = pack_scenes([(0, 1000)])[0]
    with pytest.raises(TimestampOutside):
        classify_observations(
            {"observations": [{"statement": "late", "start_ms": 0, "end_ms": 5000}]},
            part,
            "m",
        )
