from pathlib import Path

from registry.ids import LENS_ORDER
from registry.load import Registry

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contracts"


def registry():
    return Registry(FIXTURES)


def dimensions():
    return {name: "none_in_transcript" for name in LENS_ORDER}
