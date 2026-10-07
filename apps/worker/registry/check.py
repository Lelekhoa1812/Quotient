# Motivation vs Logic
# Motivation: A truncated or off-schema object must fail closed instead of being repaired.
# Logic: Draft 2020-12 validation runs on the decoded object. JSON decode errors are the same failure.

import json

from jsonschema import Draft202012Validator

from errors import SchemaRejected


def loads_object(payload: str) -> dict:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SchemaRejected("truncated or invalid JSON failed validation") from exc
    if not isinstance(data, dict):
        raise SchemaRejected("model output must be a JSON object")
    return data


def validate(instance: dict, schema: dict) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
    if errors:
        path = "/".join(str(part) for part in errors[0].absolute_path) or "root"
        raise SchemaRejected(f"{errors[0].message} at {path}")


def validate_json(payload: str, schema: dict) -> dict:
    data = loads_object(payload)
    validate(data, schema)
    return data
