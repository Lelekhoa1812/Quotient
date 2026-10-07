# Motivation vs Logic
# Motivation: Synthesis cites findings, not spans, and a conflict that was dropped twice stays on the graph.
# Logic: The synthesis payload is the finding set. Dissent ids return once; a second drop becomes a synthesis omission.

from graph.prose import normalize
from graph.state import Finding, Sentence, SynthesisOmission


def synthesis_payload(findings: list[Finding], dropped_ids: list[str] | None = None) -> dict:
    payload = {
        "findings": [
            {
                "id": finding.id,
                "dimension": finding.dimension,
                "stance": finding.stance,
                "text": finding.text,
                "claim_ids": list(finding.claim_ids),
            }
            for finding in findings
        ]
    }
    if dropped_ids:
        payload["dropped_ids"] = list(dropped_ids)
    return payload


# Motivation vs Logic
# Motivation: A mermaid fence rides inside the sentence. Markup in that fence is not prose.
# Logic: normalize keeps a known mermaid header and drops click, init, and javascript lines.
def sentences_from(output: dict) -> list[Sentence]:
    sentences = []
    for item in output.get("sentences") or []:
        text = normalize(item.get("text") or "")
        if not text.strip():
            continue
        sentences.append(Sentence(text=text, finding_ids=list(item.get("finding_ids") or [])))
    return sentences


def dissent_payload(findings: list[Finding], sentences: list[Sentence]) -> dict:
    return {
        "findings": synthesis_payload(findings)["findings"],
        "sentences": [{"text": sentence.text, "finding_ids": list(sentence.finding_ids)} for sentence in sentences],
    }


def dropped_ids(output: dict) -> list[str]:
    dropped = output.get("dropped_finding_ids")
    if dropped is None:
        dropped = output.get("dropped_ids") or []
    softened = output.get("softened_finding_ids")
    if softened is None:
        softened = output.get("softened_ids") or []
    return list(dict.fromkeys([*dropped, *softened]))


def synthesis_omissions(finding_ids: list[str]) -> list[SynthesisOmission]:
    return [SynthesisOmission(finding_id=finding_id, reason="dropped_twice") for finding_id in finding_ids]
