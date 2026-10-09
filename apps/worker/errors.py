# Motivation vs Logic
# Motivation: Trust-boundary failures must name the missing registry id or the gate that closed.
# Logic: Typed errors carry the id, model, or claim status. They never include credentials or prompt bodies.


class RegistryMissing(FileNotFoundError):
    """A plan registry id or its file is not on disk."""


class PinMismatch(ValueError):
    """The registry model role does not match the locked plan pin."""


class SchemaRejected(ValueError):
    """Decoded model output failed draft-2020-12 validation or was truncated JSON."""


class DimensionSkipped(RuntimeError):
    """A meeting finished without one of the ten blinded lenses."""


class ImmutableRawText(AttributeError):
    """raw_text is the Sonic string and cannot be replaced."""


class ChartRejected(ValueError):
    """A chart query contained a numeric literal or an unknown aggregation."""


class InputTooLarge(ValueError):
    """Assembled model input exceeded the 272K-token short-context budget."""


class TimestampOutside(ValueError):
    """A cited time lies outside the source or the scene part that produced it."""


class NotInvocable(RuntimeError):
    def __init__(self, model_id: str, code: str):
        self.model_id = model_id
        self.code = code
        super().__init__(f"{model_id} rejected the call ({code})")


class NoSpeech(RuntimeError):
    """The recording is long enough to hold speech but nothing was transcribed."""


class AnalysisCancelled(Exception):
    """The meeting was cancelled while its analysis was running. Not a failure."""


class NoAudioTrack(ValueError):
    """The recording has no audio stream, so there is nothing to transcribe."""
