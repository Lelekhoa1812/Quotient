# Motivation vs Logic
# Motivation: The person chooses, in Settings, whether the text analysis runs on Amazon Bedrock or on NVIDIA NIM,
# and which NIM model does the easy work and which does the hard work. The worker needs one answer to "which
# model, with what limits, for this role" that does not depend on where the choice came from.
# Logic: A ModelPlan holds, per role (slm = fast bounded passes, llm = the long reasoning passes), the model, its
# output limit, the models to fall back to, whether it should think, and the input budget. Bedrock's plan is the
# pinned Haiku 5.5 release. NIM's plan comes from live probes of the real Quotient prompts (docs/model-routing.md)
# and may be overridden per meeting with a model from the proven list only.

from __future__ import annotations

import os
from dataclasses import dataclass

from bedrock import limits

PROVIDERS = ("bedrock", "nim")
DEFAULT_PROVIDER = "bedrock"
ROLES = ("slm", "llm")


@dataclass(frozen=True)
class RolePlan:
    model: str
    max_output_tokens: int
    fallbacks: tuple[str, ...] = ()
    thinking: bool | None = None  # None: the provider decides (Bedrock adaptive thinking)
    input_budget_tokens: int = limits.INPUT_TOKEN_BUDGET
    region: str = limits.REASON_REGION


@dataclass(frozen=True)
class NimModel:
    id: str
    label: str
    context: int
    max_output: int
    speed: str  # "fast" answers in seconds with thinking off; "slow" thinks for a minute
    notes: str


# Proven against Quotient's claim prompt and schema on 2026-11-11 (strict json_schema, 3 spans):
#   ultra  thinking off 5 s 3 claims | thinking on 25-28 s 6 claims
#   super  thinking off 2 s 3 claims | thinking on 60 s 5 claims
#   nano   thinking off 3 s 3 claims | thinking on 59 s 4 claims
#   laguna 2.5 s 3 claims (no thinking mode)
#   glm    thinking off 9-11 s 3-4 claims
# DeepSeek V4.1 Flash returned empty content or HTTP 500 and is not offered.
NIM_MODELS: dict[str, NimModel] = {
    m.id: m
    for m in (
        NimModel("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra 550B", 1_000_000, 65_536, "fast", "Best quality that answers in seconds with thinking off."),
        NimModel("nvidia/nemotron-3.5-super-vl-120b-a12b", "Nemotron 3.5 Super 120B", 1_000_000, 131_072, "fast", "Fast with thinking off; slow when it thinks."),
        NimModel("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "Nemotron 3 Nano Omni 30B", 256_000, 65_536, "slow", "Small context. Use as a fallback."),
        NimModel("poolside/laguna-xs-2.1", "Laguna XS 2.1", 262_144, 32_768, "fast", "Fastest, fewer claims per pass."),
        NimModel("z-ai/glm-5.3-flash", "GLM 5.3 Flash", 1_048_576, 32_768, "slow", "Reliable fallback with a long context."),
    )
}

_NIM_SLM = RolePlan(
    model="nvidia/nemotron-3-ultra-550b-a55b",
    max_output_tokens=16_384,
    fallbacks=("nvidia/nemotron-3.5-super-vl-120b-a12b", "poolside/laguna-xs-2.1", "z-ai/glm-5.3-flash"),
    thinking=False,
    input_budget_tokens=200_000,
    region="nvidia",
)
_NIM_LLM = RolePlan(
    model="nvidia/nemotron-3-ultra-550b-a55b",
    max_output_tokens=32_768,
    fallbacks=("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "nvidia/nemotron-3.5-super-vl-120b-a12b", "z-ai/glm-5.3-flash"),
    thinking=True,
    input_budget_tokens=200_000,
    region="nvidia",
)

_BEDROCK = {
    "llm": RolePlan(limits.SOL_MODEL, limits.SOL_MAX_OUTPUT_TOKENS, (limits.SOL_FALLBACK,), None, limits.INPUT_TOKEN_BUDGET, limits.REASON_REGION),
    "slm": RolePlan(limits.LUNA_MODEL, limits.LUNA_MAX_OUTPUT_TOKENS, (), None, limits.INPUT_TOKEN_BUDGET, limits.REASON_REGION),
}


def normalise_provider(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in PROVIDERS else ""


def default_provider() -> str:
    return normalise_provider(os.environ.get("QUOTIENT_MODEL_PROVIDER")) or DEFAULT_PROVIDER


def clean_overrides(value: object) -> dict[str, str]:
    """Only roles and NIM models this release knows. Anything else is dropped, never passed to a vendor."""
    if not isinstance(value, dict):
        return {}
    return {role: str(model) for role, model in value.items() if role in ROLES and str(model) in NIM_MODELS}


def plans(provider: str, overrides: dict | None = None) -> dict[str, RolePlan]:
    if provider != "nim":
        return dict(_BEDROCK)
    chosen = clean_overrides(overrides)
    result = {"slm": _NIM_SLM, "llm": _NIM_LLM}
    for role, model in chosen.items():
        base = result[role]
        spec = NIM_MODELS[model]
        chain = (base.model,) + tuple(m for m in base.fallbacks if m != model)
        # An override keeps the role's thinking choice; a model that cannot think just ignores it.
        result[role] = RolePlan(
            model=model,
            max_output_tokens=min(base.max_output_tokens, spec.max_output),
            fallbacks=tuple(m for m in chain if m != model),
            thinking=base.thinking,
            input_budget_tokens=min(base.input_budget_tokens, int(spec.context * 0.75)),
            region="nvidia",
        )
    return result


def transport_for(provider: str):
    """The transport that serves a provider's text models."""
    if provider == "nim":
        from bedrock.nim import NimTransport

        return NimTransport()
    from bedrock.wire import Transport

    return Transport()


def catalogue() -> dict:
    """What Settings shows: the providers, whether each is usable on this server, and the NIM models and defaults."""
    from bedrock import nim

    defaults = plans("nim")
    return {
        "default": default_provider(),
        "providers": [
            {"id": "bedrock", "label": "AWS Bedrock", "available": True, "models": {"slm": limits.LUNA_MODEL, "llm": limits.SOL_MODEL}},
            {"id": "nim", "label": "NVIDIA NIM", "available": nim.available(), "models": {role: defaults[role].model for role in ROLES}},
        ],
        "nim_models": [
            {"id": m.id, "label": m.label, "context": m.context, "max_output": m.max_output, "speed": m.speed, "notes": m.notes}
            for m in NIM_MODELS.values()
        ],
        "roles": {
            "slm": "Fast passes: statement extraction, evidence checks, coverage, most lenses, who-is-who.",
            "llm": "Long reasoning: entailment, supplementary findings, the walkaway digest and its review, risk and stakeholder lenses.",
        },
    }
