# Motivation vs Logic
# Motivation: Prompt text and JSON Schemas are authority in contracts/, addressed by registry id.
# Logic: Resolve ids through registry.json, read the pointed-at file, and raise RegistryMissing when either is absent.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from errors import PinMismatch, RegistryMissing
from registry.pins import PROMPT_ROLE


def default_root() -> Path:
    """Repo contracts/ directory. Does not create it."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / "registry.json"
        if candidate.is_file():
            return candidate.parent
    return here.parents[3] / "contracts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    model_role: str | None
    body: str
    tools: list = field(default_factory=list)
    cache_breakpoints: int = 1
    schema_id: str | None = None
    criteria: tuple = ()
    question: str = ""


class Registry:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else default_root()
        self.path = self.root / "registry.json"
        if not self.path.is_file():
            raise RegistryMissing(
                f"contracts registry is not on disk at {self.path}. "
                "Quotient loads prompts and schemas only through contracts/registry.json."
            )
        self.document = json.loads(self.path.read_text(encoding="utf-8"))
        self._prompts, self._schemas = _index(self.document)
        named = self.document.get("release")
        self.release = named if isinstance(named, str) and named else hashlib.sha256(self.path.read_bytes()).hexdigest()

    def prompt(self, prompt_id: str, *, expected_role: str | None = None) -> Prompt:
        entry = self._entry("prompts", prompt_id)
        path = self._file(entry, prompt_id, "prompt")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("body"), str) or not data["body"].strip():
            raise RegistryMissing(
                f"prompt file for {prompt_id} at {path} has no body. "
                "The worker does not substitute prompt text."
            )
        role = data.get("model_role", entry.get("model_role"))
        raw_criteria = data.get("criteria") or ()
        if not isinstance(raw_criteria, list):
            raw_criteria = ()
        question = data.get("question") if isinstance(data.get("question"), str) else ""
        loaded = Prompt(
            id=prompt_id,
            version=int(data.get("version", entry.get("version", 1))),
            model_role=role,
            body=data["body"],
            tools=list(data.get("tools") or entry.get("tools") or []),
            cache_breakpoints=_breakpoints(data.get("cache_breakpoints", entry.get("cache_breakpoints", 1))),
            schema_id=entry.get("schema") or data.get("schema"),
            criteria=tuple(item for item in raw_criteria if isinstance(item, str)),
            question=question,
        )
        expected = expected_role if expected_role is not None else PROMPT_ROLE.get(prompt_id)
        if expected is not None and loaded.model_role != expected:
            raise PinMismatch(
                f"{prompt_id} is pinned to model_role {expected!r} but the registry file says {loaded.model_role!r}."
            )
        return loaded

    def schema(self, schema_id: str) -> dict:
        entry = self._entry("schemas", schema_id)
        path = self._file(entry, schema_id, "schema")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RegistryMissing(f"schema {schema_id} at {path} is not a JSON object.")
        return data

    def schema_for(self, prompt_id: str) -> dict:
        loaded = self.prompt(prompt_id)
        if not loaded.schema_id:
            raise RegistryMissing(
                f"registry prompt {prompt_id} does not name a schema id. "
                "Add a schema field on that registry entry."
            )
        return self.schema(loaded.schema_id)

    def versions(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for block in (self._prompts, self._schemas):
            for entry_id, entry in block.items():
                if isinstance(entry, dict) and "version" in entry:
                    found[entry_id] = int(entry["version"])
        return found

    def _entry(self, kind: str, entry_id: str) -> dict:
        block = self._prompts if kind == "prompts" else self._schemas
        if not isinstance(block, dict) or entry_id not in block:
            raise RegistryMissing(
                f"contracts registry has no {kind} entry {entry_id!r} under {self.path}. "
                "Import this plan id in contracts/registry.json. The worker will not inline a substitute."
            )
        entry = block[entry_id]
        if not isinstance(entry, dict):
            raise RegistryMissing(f"registry {kind} entry {entry_id!r} is not an object.")
        return entry

    def _file(self, entry: dict, entry_id: str, kind: str) -> Path:
        name = entry.get("file") or entry.get("path")
        if not name:
            raise RegistryMissing(
                f"registry {kind} {entry_id!r} has no file path. Point it at contracts/{kind}/."
            )
        path = (self.root / name).resolve()
        if not path.is_file():
            raise RegistryMissing(
                f"registry {kind} {entry_id!r} points at {path}, which is not on disk."
            )
        return path


def _breakpoints(value) -> int:
    if isinstance(value, list):
        return len(value) or 1
    return int(value or 1)


def _index(document: dict) -> tuple[dict, dict]:
    routes = document.get("routes")
    if isinstance(routes, list):
        prompts: dict = {}
        schemas: dict = {}
        for route in routes:
            if not isinstance(route, dict) or not route.get("active", True):
                continue
            prompt_id = route.get("prompt_id")
            if not prompt_id:
                continue
            prompts[prompt_id] = {
                "version": route.get("version", 1),
                "file": route.get("prompt") or route.get("file"),
                "model_role": route.get("model_role"),
                "schema": route.get("schema_id"),
            }
            schema_id = route.get("schema_id")
            if schema_id:
                schemas[schema_id] = {
                    "version": route.get("version", 1),
                    "file": route.get("schema") or route.get("file"),
                }
        return prompts, schemas
    prompts = document.get("prompts") if isinstance(document.get("prompts"), dict) else {}
    schemas = document.get("schemas") if isinstance(document.get("schemas"), dict) else {}
    return prompts, schemas
