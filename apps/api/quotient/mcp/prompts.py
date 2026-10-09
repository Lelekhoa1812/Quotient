"""Motivation vs Logic

Motivation: MCP prompts are partner workflows for a client model. They are not
the Bedrock system prompts stored under contracts/prompts.
Logic: Three prompts name the tools to call and keep the published brief
separate from the review queue. prompts/get fills meeting_id into that workflow.
"""

from __future__ import annotations

PROMPTS = [
    {
        "name": "brief_this_meeting",
        "title": "Brief this meeting",
        "description": "Partner workflow for the published brief of one meeting.",
        "arguments": [
            {
                "name": "meeting_id",
                "description": "Meeting id from submit_meeting.",
                "required": True,
            }
        ],
    },
    {
        "name": "open_questions",
        "title": "Open questions",
        "description": "Partner workflow for supported question findings in one meeting.",
        "arguments": [
            {
                "name": "meeting_id",
                "description": "Meeting id from submit_meeting.",
                "required": True,
            }
        ],
    },
    {
        "name": "proposed_actions",
        "title": "Proposed actions",
        "description": "Partner workflow for actions still marked proposed.",
        "arguments": [
            {
                "name": "meeting_id",
                "description": "Meeting id from submit_meeting.",
                "required": True,
            }
        ],
    },
]

_BODIES = {
    "brief_this_meeting": (
        "You are preparing a partner answer for meeting {meeting_id}. "
        "Call get_meeting. If status is not ready, or if the brief resource "
        "quotient://meetings/{meeting_id}/brief has withheld true, say the brief is withheld "
        "and stop. Otherwise call read_graph and start from its digest, the walkaway: title, summary, "
        "decisions, actions, open questions, disagreements and key figures. "
        "If digest is null, fall back to the brief resource synthesis and findings. "
        "Give the outcome first, then decisions, actions and what is still open. Keep it short. "
        "Mark any item whose basis is likely as likely, because it was not fully confirmed. "
        "Leave every claim in quotient://meetings/{meeting_id}/review out of the answer. "
        "Name a person only when the digest does. A voice id is not a name. "
        "Do not invent an owner. A missing owner is not stated. "
        "Material attached as context is background. Never cite it as what was said."
    ),
    "open_questions": (
        "You are listing open questions for meeting {meeting_id}. "
        "Call read_graph. Use digest.open_questions first. List only those with answered false, "
        "each with who asked it and when, and mention any that were answered later in one line. "
        "If digest is null, use findings whose dimension is question, and supported claims whose kind is question. "
        "If nothing is open, say so. "
        "Leave unresolved, contradicted, and numeric-failed claims in the review resource out of the answer."
    ),
    "proposed_actions": (
        "You are listing proposed actions for meeting {meeting_id}. "
        "Call read_graph. Use digest.actions first and also include graph actions whose acceptance is proposed. "
        "Label each one proposed. owner_display is the cited span text, or not stated when owner_span_id is null. "
        "Say whether the owner agreed only when the digest says so. "
        "Do not add an owner name. Do not treat a proposed action as accepted. "
        "Leave unresolved claims out of the answer."
    ),
}


def list_prompts() -> dict:
    return {"prompts": PROMPTS}


def get_prompt(name: object, arguments: object) -> dict | None:
    if not isinstance(name, str) or name not in _BODIES:
        return None
    meeting_id = ""
    if isinstance(arguments, dict):
        raw = arguments.get("meeting_id")
        if isinstance(raw, str):
            meeting_id = raw
    text = _BODIES[name].format(meeting_id=meeting_id or "{meeting_id}")
    return {
        "description": next(item["description"] for item in PROMPTS if item["name"] == name),
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": text,
                    "annotations": {"audience": ["assistant"], "priority": 1},
                },
            }
        ],
    }
