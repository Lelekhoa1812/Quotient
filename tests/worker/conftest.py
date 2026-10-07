import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "apps" / "worker"))

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contracts"


def registry():
    from registry.load import Registry

    return Registry(FIXTURES)


def dimensions():
    from registry.ids import LENS_ORDER

    return {name: "none_in_transcript" for name in LENS_ORDER}
