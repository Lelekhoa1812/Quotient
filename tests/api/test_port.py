"""The API process keeps the worker packages importable after the port loads."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def test_the_analysis_thread_can_import_bedrock_after_the_port_loads():
    root = Path(__file__).resolve().parents[2] / "apps" / "worker"
    saved = list(sys.path)
    sys.path[:] = [item for item in sys.path if Path(item).resolve() != root.resolve()]
    cached = [name for name in list(sys.modules) if name == "bedrock" or name.startswith("bedrock.")]
    removed = {name: sys.modules.pop(name) for name in cached}
    try:
        spec = importlib.util.spec_from_file_location("quotient_worker_port_check", root / "quotient" / "port.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._load_entrypoints()
        assert any(Path(item).resolve() == root.resolve() for item in sys.path)
        import bedrock.reason  # noqa: F401
    finally:
        sys.path[:] = saved
        sys.modules.update(removed)
