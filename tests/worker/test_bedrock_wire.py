import pytest

from bedrock.wire import _SonicSession


def test_sonic_forbidden_response_has_safe_configuration_guidance():
    session = object.__new__(_SonicSession)
    session._status = 403
    session._model_id = "amazon.nova-2-5-sonic"
    session._error = "sonic HTTP 403"

    with pytest.raises(RuntimeError) as error:
        session._raise_status()

    message = str(error.value)
    assert "configured AWS identity" in message
    assert "Sonic model access" in message
    assert "bidirectional-stream permission" in message


def test_send_all_waits_for_a_busy_non_blocking_socket_instead_of_failing():
    import ssl

    from bedrock import wire

    class Busy:
        """Refuses the first write, then accepts at most 3 bytes at a time."""

        def __init__(self):
            self.refusals = 2
            self.received = bytearray()

        def send(self, view):
            if self.refusals:
                self.refusals -= 1
                raise ssl.SSLWantWriteError("busy")
            chunk = bytes(view[:3])
            self.received.extend(chunk)
            return len(chunk)

        def fileno(self):
            raise OSError  # forces the select() path to be patched out below

    sock = Busy()
    original = wire.select.select
    wire.select.select = lambda r, w, x, t: ([], [], [])
    try:
        wire._send_all(sock, b"abcdefgh")
    finally:
        wire.select.select = original
    assert bytes(sock.received) == b"abcdefgh"


def test_send_all_gives_up_after_its_deadline():
    import pytest
    import ssl

    from bedrock import wire

    class Never:
        def send(self, view):
            raise ssl.SSLWantWriteError("busy")

    original = wire.select.select
    wire.select.select = lambda r, w, x, t: ([], [], [])
    try:
        with pytest.raises(RuntimeError, match="send timed out"):
            wire._send_all(Never(), b"x", timeout=0.05)
    finally:
        wire.select.select = original


def test_send_all_waits_for_readability_when_tls_needs_to_read_first():
    import ssl

    from bedrock import wire

    class NeedsRead:
        def __init__(self):
            self.state = 0
            self.received = bytearray()

        def send(self, view):
            self.state += 1
            if self.state == 1:
                raise ssl.SSLWantReadError("read first")
            self.received.extend(bytes(view))
            return len(view)

    waited = []
    original = wire.select.select
    wire.select.select = lambda r, w, x, t: waited.append(("read" if r else "write")) or ([], [], [])
    try:
        sock = NeedsRead()
        wire._send_all(sock, b"hello")
    finally:
        wire.select.select = original
    assert waited == ["read"] and bytes(sock.received) == b"hello"
