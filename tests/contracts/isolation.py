# Motivation vs Logic
# Motivation: The publish gate loads only the versioned registry, and application trees must not carry prompt or schema bodies.
# Logic: Load contracts/registry.json, compile every draft 2020-12 schema, assert the plan pins, and scan apps/ for those bodies.

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
PROMPTS = CONTRACTS / "prompts"
SCHEMAS = CONTRACTS / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
# Motivation vs Logic
# Motivation: meeting.pegasus.continue.v1 carries an extra name segment the single-token id pattern rejects.
# Logic: Allow one optional dotted segment so the continuation id still has to match its registry route.
ID_RE = re.compile(r"^meeting\.[a-z0-9_]+(?:\.[a-z0-9_]+)?\.v1$")

PINS = {
    "compaction": "slm",
    "claim": "slm",
    "counterevidence": "slm",
    "entailment": "llm",
    "entailment_luna": "slm",
    "coverage": "slm",
    "supplement": "llm",
    "lens_decision": "slm",
    "lens_commitment": "slm",
    "lens_temporal": "slm",
    "lens_stakeholder": "llm",
    "lens_cross_modal": "llm",
    "lens_documentary": "slm",
    "lens_risk": "llm",
    "lens_gap": "slm",
    "lens_dependency": "llm",
    "lens_question": "slm",
    "synthesis": "llm",
    "digest": "llm",
    "digest_review": "llm",
    "answer_check": "slm",
    "screen_use": "llm",
    "dissent": "slm",
    "chart": "slm",
    # Motivation vs Logic
    # Motivation: The worker imports Sonic, Pegasus, the length continuation, and the Sol cross-modal pass by id.
    # Logic: Pin those routes to sonic, pegasus, or llm so isolation fails closed when a file is absent.
    "sonic": "sonic",
    "pegasus": "pegasus",
    "pegasus.continue": "pegasus",
    "crossmodal": "llm",
    "frame": "llm",
    # Motivation vs Logic
    # Motivation: Jev only sorts the review queue and is not a Sol or Luna role.
    # Logic: Leave model_role unset so the pin set stays llm, slm, sonic, and pegasus.
    "review_sort": None,
}

SOL_LENSES = {"stakeholder", "risk", "dependency", "cross_modal"}
LUNA_LENSES = {"decision", "commitment", "temporal", "documentary", "gap", "question"}
DIMENSIONS = SOL_LENSES | LUNA_LENSES
SKIP_DIRS = {"node_modules", ".venv", ".git", "__pycache__", "derivatives", "graphify-out"}
TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".toml",
    ".ini",
    ".css",
    ".html",
}


def load_registry() -> dict:
    return json.loads((CONTRACTS / "registry.json").read_text(encoding="utf-8"))


def routes_by_id(registry: dict) -> dict[str, dict]:
    routes = registry["routes"]
    ids = [route["route"] for route in routes]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate route ids")
    return {route["route"]: route for route in routes}


def load_prompt(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError(f"{path} did not load as a mapping")
    return loaded


def load_schema(schema_id: str) -> dict:
    return json.loads((SCHEMAS / f"{schema_id}.json").read_text(encoding="utf-8"))


def compile_schema(document: dict) -> jsonschema.Draft202012Validator:
    if document.get("$schema") != DRAFT:
        raise AssertionError("schema is not draft 2020-12")
    jsonschema.Draft202012Validator.check_schema(document)
    return jsonschema.Draft202012Validator(document)


def norm(text: str) -> str:
    return " ".join(text.split())


def needles_from_text(text: str) -> list[str]:
    found: list[str] = []
    collapsed = norm(text)
    if len(collapsed) >= 80:
        found.append(collapsed)
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) >= 80:
            found.append(stripped)
    return found


def contract_needles() -> list[str]:
    needles: list[str] = []
    for path in sorted(PROMPTS.glob("*.yaml")):
        needles.extend(needles_from_text(load_prompt(path)["body"]))
    for path in sorted(SCHEMAS.glob("*.json")):
        needles.extend(needles_from_text(path.read_text(encoding="utf-8")))
    return needles


def embedded(root: Path, needles: list[str]) -> list[str]:
    apps = root / "apps"
    if not apps.exists():
        return []
    hits: list[str] = []
    for path in apps.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:1024]:
            continue
        text = data.decode("utf-8", errors="replace")
        collapsed = norm(text)
        if any(needle in text or needle in collapsed for needle in needles):
            hits.append(f"{path} contains a contract body")
    return hits


def dimension_roles(routes: dict[str, dict]) -> dict[str, str]:
    found: dict[str, str] = {}
    for route, entry in routes.items():
        dimension = entry.get("dimension")
        if dimension is None:
            continue
        if route != f"lens_{dimension}":
            raise AssertionError(f"{route} does not match dimension {dimension}")
        found[dimension] = entry["model_role"]
    return found


def accepts(schema_id: str, instance: object) -> None:
    compile_schema(load_schema(schema_id)).validate(instance)


def rejects(schema_id: str, instance: object) -> None:
    validator = compile_schema(load_schema(schema_id))
    try:
        validator.validate(instance)
    except jsonschema.ValidationError:
        return
    raise AssertionError(f"{schema_id} accepted {instance!r}")


def test_registry_pins() -> None:
    registry = load_registry()
    if registry["release"] != "meeting.v1":
        raise AssertionError(registry["release"])
    routes = routes_by_id(registry)
    if set(routes) != set(PINS):
        raise AssertionError(sorted(set(routes) ^ set(PINS)))
    for route, role in PINS.items():
        entry = routes[route]
        prompt_id = f"meeting.{route}.v1"
        if entry["active"] is not True or entry["version"] != 1:
            raise AssertionError(route)
        if role is None:
            if entry.get("model_role") is not None:
                raise AssertionError((route, entry.get("model_role")))
        elif entry["model_role"] != role or entry["model_role"] not in {"llm", "slm", "sonic", "pegasus"}:
            raise AssertionError((route, entry["model_role"]))
        if entry["prompt_id"] != prompt_id or entry["schema_id"] != prompt_id:
            raise AssertionError(entry)
        if entry["prompt"] != f"prompts/{prompt_id}.yaml":
            raise AssertionError(entry["prompt"])
        if entry["schema"] != f"schemas/{prompt_id}.json":
            raise AssertionError(entry["schema"])
        if not ID_RE.fullmatch(prompt_id):
            raise AssertionError(prompt_id)
    if routes["entailment"]["pass"] != "entailment" or routes["entailment_luna"]["pass"] != "entailment":
        raise AssertionError("entailment pass pin")
    if routes["coverage"]["pass"] != "coverage" or routes["supplement"]["pass"] != "coverage":
        raise AssertionError("coverage pass pin")


def test_model_profiles() -> None:
    registry = load_registry()
    llm = registry["models"]["llm"]
    slm = registry["models"]["slm"]
    if llm["inference_profile"] != "global.openai.gpt-6.1-sol":
        raise AssertionError(llm["inference_profile"])
    if llm["fallback_inference_profile"] != "global.openai.gpt-6-sol":
        raise AssertionError(llm["fallback_inference_profile"])
    if llm["max_output_tokens"] != 131072 or llm["region"] != "ap-southeast-2":
        raise AssertionError(llm)
    if slm["inference_profile"] != "global.openai.gpt-6-luna":
        raise AssertionError(slm["inference_profile"])
    if slm["fallback_inference_profile"] is not None:
        raise AssertionError(slm["fallback_inference_profile"])
    if slm["max_output_tokens"] != 128000 or slm["region"] != "ap-southeast-2":
        raise AssertionError(slm)
    cache = registry["prompt_cache"]
    if cache != {
        "mode": "explicit",
        "ttl": "30m",
        "min_prefix_tokens": 1024,
        "max_breakpoints": 4,
        "assembled_input_token_ceiling": 272000,
    }:
        raise AssertionError(cache)


def test_skipped_dimension_fails() -> None:
    routes = routes_by_id(load_registry())
    found = dimension_roles(routes)
    if set(found) != DIMENSIONS:
        raise AssertionError(sorted(DIMENSIONS ^ set(found)))
    for dimension in SOL_LENSES:
        if found[dimension] != "llm":
            raise AssertionError(dimension)
    for dimension in LUNA_LENSES:
        if found[dimension] != "slm":
            raise AssertionError(dimension)
    skipped = {route: entry for route, entry in routes.items() if route != "lens_gap"}
    if set(dimension_roles(skipped)) == DIMENSIONS:
        raise AssertionError("a missing dimension was not detected")


TOOL_NAMES = {"open_span", "read_context"}


def test_prompt_files_match_registry() -> None:
    routes = routes_by_id(load_registry())
    expected = {f"{entry['prompt_id']}.yaml" for entry in routes.values()}
    on_disk = {path.name for path in PROMPTS.glob("*.yaml")}
    if on_disk != expected:
        raise AssertionError(sorted(on_disk ^ expected))
    for entry in routes.values():
        prompt = load_prompt(PROMPTS / f"{entry['prompt_id']}.yaml")
        if prompt["id"] != entry["prompt_id"] or prompt["version"] != 1:
            raise AssertionError(prompt["id"])
        if prompt.get("model_role") != entry.get("model_role") or prompt["schema"] != entry["schema_id"]:
            raise AssertionError(entry["route"])
        breakpoints = prompt["cache_breakpoints"]
        if len(breakpoints) != 1:
            raise AssertionError(entry["route"])
        breakpoint = breakpoints[0]
        if breakpoint["after"] != ["system", "tools", "schema"]:
            raise AssertionError(breakpoint["after"])
        if breakpoint["mode"] != "explicit" or breakpoint["ttl"] != "30m":
            raise AssertionError(breakpoint)
        if [stage["id"] for stage in prompt["stages"]] != ["reason", "fill"]:
            raise AssertionError(prompt["stages"])
        if [stage["output"] for stage in prompt["stages"]] != ["text", "schema"]:
            raise AssertionError(prompt["stages"])
        if not isinstance(prompt["body"], str) or len(prompt["body"].strip()) < 80:
            raise AssertionError(entry["route"])
        if not isinstance(prompt["tools"], list):
            raise AssertionError(entry["route"])
        for tool in prompt["tools"]:
            if tool["name"] not in TOOL_NAMES:
                raise AssertionError(tool["name"])
            # read_context is reference-document access; only the two walkaway passes may declare it.
            if tool["name"] == "read_context" and entry["route"] not in {"digest", "digest_review"}:
                raise AssertionError((entry["route"], tool["name"]))
            parameters = dict(tool["parameters"])
            parameters["$schema"] = DRAFT
            compile_schema(parameters)


def test_schemas_compile() -> None:
    routes = routes_by_id(load_registry())
    expected = {f"{entry['schema_id']}.json" for entry in routes.values()}
    on_disk = {path.name for path in SCHEMAS.glob("*.json")}
    if on_disk != expected:
        raise AssertionError(sorted(on_disk ^ expected))
    for entry in routes.values():
        document = load_schema(entry["schema_id"])
        if not str(document["$id"]).endswith(f"/{entry['schema_id']}.json"):
            raise AssertionError(document["$id"])
        compile_schema(document)


def test_registry_is_an_index() -> None:
    raw = norm((CONTRACTS / "registry.json").read_text(encoding="utf-8"))
    for path in PROMPTS.glob("*.yaml"):
        if norm(load_prompt(path)["body"]) in raw:
            raise AssertionError(path.name)
    for path in SCHEMAS.glob("*.json"):
        if norm(path.read_text(encoding="utf-8")) in raw:
            raise AssertionError(path.name)


def test_lenses_are_blind() -> None:
    for dimension in DIMENSIONS:
        prompt = load_prompt(PROMPTS / f"meeting.lens_{dimension}.v1.yaml")
        body = prompt["body"]
        if re.search(rf"\b{re.escape(dimension)}\b", body) is None:
            raise AssertionError(dimension)
        for other in DIMENSIONS - {dimension}:
            if re.search(rf"\b{re.escape(other)}\b", body):
                raise AssertionError((dimension, other))
        schema_text = (SCHEMAS / f"meeting.lens_{dimension}.v1.json").read_text(encoding="utf-8")
        for other in DIMENSIONS - {dimension}:
            if re.search(rf"\b{re.escape(other)}\b", schema_text):
                raise AssertionError((dimension, other))


def test_prompt_rules() -> None:
    def body(name: str) -> str:
        return load_prompt(PROMPTS / name)["body"]

    if "Never omit an overlap span." not in body("meeting.compaction.v1.yaml"):
        raise AssertionError("compaction")
    claim = body("meeting.claim.v1.yaml")
    if "Do not emit character offsets." not in claim or "An ambiguous sentence is a gap." not in claim:
        raise AssertionError("claim")
    if "Upload filenames and form fields are not name sources." not in claim:
        raise AssertionError("claim names")
    for name in ("meeting.entailment.v1.yaml", "meeting.entailment_luna.v1.yaml"):
        prompt = load_prompt(PROMPTS / name)
        if prompt["input"]["include"] != ["paraphrase", "cited_span_texts"]:
            raise AssertionError(prompt["input"])
        if prompt["input"]["exclude"] != ["extractor_sentence", "draft_brief"]:
            raise AssertionError(prompt["input"])
        if prompt["tools"] != []:
            raise AssertionError(name)
        if "Neutral is not support." not in prompt["body"] or "draft brief" not in prompt["body"]:
            raise AssertionError(name)
        if "original sentence" not in prompt["body"]:
            raise AssertionError(name)
    if "same pack" not in body("meeting.entailment_luna.v1.yaml"):
        raise AssertionError("luna pack")
    synthesis = load_prompt(PROMPTS / "meeting.synthesis.v1.yaml")
    if "raw_transcript" not in synthesis["input"]["exclude"]:
        raise AssertionError(synthesis["input"])
    if "The raw transcript is not in this call." not in synthesis["body"]:
        raise AssertionError("synthesis transcript")
    if "Do not average two stakeholder findings into one sentence." not in synthesis["body"]:
        raise AssertionError("synthesis average")
    if "The fence info string is mermaid." not in synthesis["body"]:
        raise AssertionError("synthesis mermaid")
    if "Most sentences have none." not in synthesis["body"]:
        raise AssertionError("synthesis mermaid scarce")
    if "Do not try to make the lenses agree." not in body("meeting.dissent.v1.yaml"):
        raise AssertionError("dissent")
    if "Do not emit a numeric literal." not in body("meeting.chart.v1.yaml"):
        raise AssertionError("chart")
    if "Do not add a claim." not in body("meeting.coverage.v1.yaml"):
        raise AssertionError("coverage")
    supplement = body("meeting.supplement.v1.yaml")
    if "re-enters counterevidence and entailment" not in supplement:
        raise AssertionError("supplement")
    if "There is no owner string." not in body("meeting.lens_commitment.v1.yaml"):
        raise AssertionError("commitment")
    sonic = body("meeting.sonic.v1.yaml")
    if "The clock is samples." not in sonic or "Do not emit character offsets." not in sonic:
        raise AssertionError("sonic")
    if "16 kHz" not in sonic or "timestamp" not in sonic.lower():
        raise AssertionError("sonic clock")
    pegasus = body("meeting.pegasus.v1.yaml")
    if "Do not splice a partial object." not in pegasus or "4096" not in pegasus or "2000" not in pegasus:
        raise AssertionError("pegasus")
    continued = body("meeting.pegasus.continue.v1.yaml")
    if "Do not repair a partial JSON value." not in continued:
        raise AssertionError("pegasus continue repair")
    if "Do not concatenate a partial JSON value." not in continued:
        raise AssertionError("pegasus continue concatenate")
    cross = body("meeting.crossmodal.v1.yaml")
    if "not a second transcript" not in cross or "sonic_span_id" not in cross:
        raise AssertionError("crossmodal")
    review = load_prompt(PROMPTS / "meeting.review_sort.v1.yaml")
    if "model_role" in review:
        raise AssertionError("review_sort model_role")
    criteria = review.get("criteria")
    if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
        raise AssertionError("review_sort criteria")
    if "entailment" not in review["body"] or "character offset" not in review["body"]:
        raise AssertionError("review_sort body")


def test_schema_rejects_plan_failures() -> None:
    accepts(
        "meeting.claim.v1",
        {
            "claims": [
                {
                    "proposition": "The team ships on Friday.",
                    "kind": "decision",
                    "quote": "We ship on Friday.",
                    "span_ids": ["span-1"],
                    "decision_status": None,
                }
            ],
            "gaps": [{"span_ids": ["span-2"], "reason": "The referent is ambiguous."}],
        },
    )
    rejects(
        "meeting.claim.v1",
        {
            "claims": [
                {
                    "proposition": "The team ships on Friday.",
                    "kind": "decision",
                    "quote": "We ship on Friday.",
                    "span_ids": ["span-1"],
                    "decision_status": None,
                    "char_start": 0,
                }
            ],
            "gaps": [],
        },
    )
    rejects(
        "meeting.claim.v1",
        {
            "claims": [
                {
                    "proposition": "Alex will send the note.",
                    "kind": "action",
                    "quote": "I will send the note.",
                    "span_ids": ["span-1"],
                    "decision_status": None,
                    "owner": "Alex",
                }
            ],
            "gaps": [],
        },
    )
    accepts(
        "meeting.counterevidence.v1",
        {"searched_ids": ["span-2"], "finding": {"kind": "empty"}},
    )
    rejects(
        "meeting.counterevidence.v1",
        {"searched_ids": [], "finding": {"kind": "empty"}},
    )
    for schema_id in ("meeting.entailment.v1", "meeting.entailment_luna.v1"):
        accepts(schema_id, {"label": "neutral"})
        rejects(schema_id, {"label": "mentions"})
    accepts("meeting.synthesis.v1", {"sentences": [{"text": "The date is unresolved.", "finding_ids": ["f1"]}]})
    rejects("meeting.synthesis.v1", {"sentences": [{"text": "The date is unresolved.", "finding_ids": []}]})
    rejects(
        "meeting.synthesis.v1",
        {"sentences": [{"text": "The date is unresolved.", "finding_ids": ["f1"], "span_id": "span-1"}]},
    )
    accepts("meeting.chart.v1", {"ids": ["cell-1"], "aggregation": "sum", "subject": "cells", "field": "cell_value"})
    accepts("meeting.chart.v1", {"ids": ["span-1"], "aggregation": "duration_union", "subject": "spans"})
    accepts("meeting.chart.v1", {"ids": ["claim-1"], "aggregation": "count", "subject": "claims"})
    rejects("meeting.chart.v1", {"ids": ["claim-1"], "aggregation": "count", "subject": "claims", "value": 15})
    rejects("meeting.chart.v1", {"ids": [15], "aggregation": "count", "subject": "claims"})
    rejects("meeting.chart.v1", {"ids": ["span-1"], "aggregation": "sum", "subject": "spans"})
    accepts("meeting.lens_gap.v1", {"dimension": "gap", "disposition": "none_in_transcript"})
    rejects(
        "meeting.lens_gap.v1",
        {"dimension": "gap", "disposition": "none_in_transcript", "findings": []},
    )
    rejects(
        "meeting.lens_risk.v1",
        {
            "dimension": "risk",
            "disposition": "findings",
            "findings": [
                {
                    "statement": "The launch date can slip.",
                    "stance": "supports",
                    "claim_ids": ["claim-1"],
                    "decision_status": "aligned",
                }
            ],
        },
    )
    action = {
        "statement": "Send the note.",
        "owner_span_id": None,
        "agreement_span_id": None,
        "due_kind": "relative",
        "due_surface": "by next Friday",
        "due_span_id": "span-9",
        "claim_ids": ["claim-1"],
        "acceptance": "proposed",
    }
    commitment = {
        "dimension": "commitment",
        "disposition": "findings",
        "findings": [
            {
                "statement": "The note will be sent.",
                "stance": "supports",
                "claim_ids": ["claim-1"],
            }
        ],
        "actions": [action],
    }
    accepts("meeting.lens_commitment.v1", commitment)
    owned = dict(action)
    owned["owner"] = "Alex"
    rejects("meeting.lens_commitment.v1", {**commitment, "actions": [owned]})
    iso_relative = dict(action)
    iso_relative["due_surface"] = "2026-10-07"
    rejects("meeting.lens_commitment.v1", {**commitment, "actions": [iso_relative]})
    dated = dict(action)
    dated["due_kind"] = "absolute"
    dated["due_surface"] = "2026-10-07"
    accepts("meeting.lens_commitment.v1", {**commitment, "actions": [dated]})
    undated = dict(action)
    undated["due_kind"] = "none"
    undated["due_surface"] = None
    undated["due_span_id"] = None
    accepts("meeting.lens_commitment.v1", {**commitment, "actions": [undated]})
    extra_iso = dict(action)
    extra_iso["due_iso"] = "2026-10-07"
    rejects("meeting.lens_commitment.v1", {**commitment, "actions": [extra_iso]})
    accepts("meeting.sonic.v1", {})
    rejects("meeting.sonic.v1", {"char_start": 0})
    rejects("meeting.sonic.v1", {"start_ms": 0})
    accepts(
        "meeting.pegasus.v1",
        {
            "observations": [
                {"statement": "the slide changes", "start_ms": 0, "end_ms": 1000},
                {"statement": "a light flickered"},
            ],
            "notes": ["uncited flicker"],
        },
    )
    accepts(
        "meeting.pegasus.continue.v1",
        {"observations": [{"statement": "the slide changes", "start_ms": 0, "end_ms": 1000}]},
    )
    rejects(
        "meeting.pegasus.v1",
        {"observations": [{"statement": "the slide changes", "start_ms": 0, "end_ms": 1000, "char_start": 0}]},
    )
    accepts(
        "meeting.crossmodal.v1",
        {"relation": "agreement", "sonic_span_id": "s1", "observation_id": "o1"},
    )
    accepts(
        "meeting.crossmodal.v1",
        {
            "relation": "disagreement",
            "sonic_span_id": "s1",
            "observation_id": "o1",
            "statement": "speech says ship and the slide says wait",
        },
    )
    rejects(
        "meeting.crossmodal.v1",
        {"relation": "disagreement", "sonic_span_id": "s1", "observation_id": "o1"},
    )
    rejects(
        "meeting.crossmodal.v1",
        {
            "relation": "agreement",
            "sonic_span_id": "s1",
            "observation_id": "o1",
            "merged": "one smoothed sentence",
        },
    )


def test_apps_does_not_embed_contract_bodies() -> None:
    hits = embedded(ROOT, contract_needles())
    if hits:
        raise AssertionError("\n".join(hits))


def test_scanner_flags_embedded_prompt_body() -> None:
    body = "Quotient compaction rule " + ("span-table " * 12)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        apps = root / "apps" / "worker"
        apps.mkdir(parents=True)
        (apps / "loop.py").write_text(f'BODY = """{body}"""\n', encoding="utf-8")
        if not embedded(root, needles_from_text(body)):
            raise AssertionError("scanner missed an embedded body")
        empty = root / "empty"
        empty.mkdir()
        if embedded(empty, needles_from_text(body)):
            raise AssertionError("scanner flagged a tree with no apps/")


def main() -> None:
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
