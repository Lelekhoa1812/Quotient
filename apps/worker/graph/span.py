# Motivation vs Logic
# Motivation: raw_text is the Sonic string. A human edit may change text and must leave raw_text in place.
# Logic: raw_text is a read-only property. edit_text writes text only.

from errors import ImmutableRawText


class Span:
    def __init__(
        self,
        *,
        id: str,
        meeting_id: str,
        kind: str,
        start_ms: int,
        end_ms: int,
        raw_text: str = "",
        text: str | None = None,
        coarse: bool = False,
        session_id: str | None = None,
        speaker_hypothesis_id: str | None = None,
        overlap: bool = False,
        omitted: bool = False,
    ):
        self.id = id
        self.meeting_id = meeting_id
        self.kind = kind
        self.start_ms = start_ms
        self.end_ms = end_ms
        self._raw_text = raw_text
        self.text = raw_text if text is None else text
        self.coarse = coarse
        self.session_id = session_id
        self.speaker_hypothesis_id = speaker_hypothesis_id
        self.overlap = overlap
        self.omitted = omitted
        self.overlap_likelihood: float | None = None

    @property
    def raw_text(self) -> str:
        return self._raw_text

    @raw_text.setter
    def raw_text(self, _value: str) -> None:
        raise ImmutableRawText("raw_text is the Sonic string and never changes")

    def edit_text(self, text: str) -> None:
        self.text = text
