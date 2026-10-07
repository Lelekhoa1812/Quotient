# Motivation vs Logic
# Motivation: Worker stages address prompts by the plan's registry ids, never by inlined text.
# Logic: Constants are ids only. Bodies and JSON Schemas stay in contracts/ and are loaded by id.

SONIC = "meeting.sonic.v1"
PEGASUS = "meeting.pegasus.v1"
PEGASUS_CONTINUE = "meeting.pegasus.continue.v1"
COMPACTION = "meeting.compaction.v1"
CROSSMODAL = "meeting.crossmodal.v1"
CLAIM = "meeting.claim.v1"
COUNTEREVIDENCE = "meeting.counterevidence.v1"
ENTAILMENT_SOL = "meeting.entailment.v1"
ENTAILMENT_LUNA = "meeting.entailment_luna.v1"
COVERAGE = "meeting.coverage.v1"
SUPPLEMENT = "meeting.supplement.v1"
SYNTHESIS = "meeting.synthesis.v1"
DISSENT = "meeting.dissent.v1"
CHART = "meeting.chart.v1"
REVIEW_SORT = "meeting.review_sort.v1"
ACTION = "meeting.action.v1"
GRAPH = "meeting.graph.v1"

LENS_ORDER = (
    "decision",
    "commitment",
    "temporal",
    "stakeholder",
    "cross_modal",
    "documentary",
    "risk",
    "gap",
    "dependency",
    "question",
)


def lens_id(dimension: str) -> str:
    return f"meeting.lens_{dimension}.v1"
