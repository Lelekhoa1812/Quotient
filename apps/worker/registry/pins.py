# Motivation vs Logic
# Motivation: Sol and Luna pins are fixed by the plan. Meeting text must not choose a model.
# Logic: Compare registry model_role to this table at load. Sonic and Pegasus are not GPT pins.

from registry.ids import (
    CLAIM,
    COMPACTION,
    COUNTEREVIDENCE,
    CHART,
    COVERAGE,
    CROSSMODAL,
    DISSENT,
    SUPPLEMENT,
    ENTAILMENT_LUNA,
    ENTAILMENT_SOL,
    SYNTHESIS,
    lens_id,
)

# Sol: stakeholder, risk, dependency, cross_modal. Luna: the other six lenses.
LENS_ROLE = {
    "decision": "slm",
    "commitment": "slm",
    "temporal": "slm",
    "stakeholder": "llm",
    "cross_modal": "llm",
    "documentary": "slm",
    "risk": "llm",
    "gap": "slm",
    "dependency": "llm",
    "question": "slm",
}

PROMPT_ROLE = {
    COMPACTION: "slm",
    CLAIM: "slm",
    COUNTEREVIDENCE: "slm",
    ENTAILMENT_SOL: "llm",
    ENTAILMENT_LUNA: "slm",
    COVERAGE: "slm",
    SUPPLEMENT: "llm",
    CROSSMODAL: "llm",
    SYNTHESIS: "llm",
    DISSENT: "slm",
    CHART: "slm",
}

for _dimension, _role in LENS_ROLE.items():
    PROMPT_ROLE[lens_id(_dimension)] = _role
