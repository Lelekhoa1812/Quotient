# Motivation vs Logic
# Motivation: The diarizer returns anonymous voices (spk_0, spk_1, ...). A voice is named today only when
# someone says a name aloud, so many voices stay "Speaker N" even when the video shows the person's name
# on their tile. The same person can also be split across two diarizer ids.
# Logic: Match what the video shows (a name label, with the active-speaker mark when there is one) against
# when each diarizer voice talks. A voice takes a name only when the evidence is long enough, comes from more
# than one moment, and clearly beats every other name for that voice; a name claimed by two voices that
# never talk over each other means one person split in two, and they are merged. Names a person typed
# outrank everything here. Nothing in this module calls a model.

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Evidence is measured in seconds of a voice talking while a name is on screen.
MIN_SECONDS = 4.0
MIN_MOMENTS = 2  # distinct five-second stretches, so one brief flash of a label is not enough
MIN_SHARE = 0.55
MIN_LEAD = 1.4
WEAK_WEIGHT = 0.3  # a name label with no active-speaker mark: it may be the speaker, or only a tile on show
BUCKET_MS = 5000
SAME_PERSON_OVERLAP = 0.1  # two voices that talk over each other for more than this share are two people
# Folding one voice into another cannot be undone from the page, so it needs clear evidence for both voices.
MERGE_MIN_CONFIDENCE = 0.4
MERGE_MIN_SECONDS = 4.0
# A mark that is on a person all the time (a presenter pinned to the stage) says little about who is talking.
# It only counts as evidence when it discriminates: the share of a voice's talk that carries the mark has to
# beat the rate of the mark while that voice is silent.
MIN_PRECISION = 0.15
MIN_LIFT = 0.08
MERGE_LIFT = 0.08
LIFT_TIE = 0.1  # two voices closer than this are told apart by who talks much more
TALK_DOMINANCE = 3.0

_GENERIC = {
    "guest", "unknown", "participant", "user", "host", "co-host", "cohost", "presenter", "speaker", "attendee",
    "iphone", "ipad", "android", "phone", "caller", "you", "me", "meeting room", "conference room", "zoom user",
    "teams user", "organizer", "organiser", "panelist", "viewer", "audience",
}
_BOT = re.compile(r"notetaker|note taker|fireflies|otter\.?ai|read\.?ai|fathom|tl;?dv|avoma|grain|recorder|recording|transcri|assistant|\bbot\b|copilot", re.I)
_ORG_SPLIT = re.compile(r"\s*[|｜]\s*")
_PAREN = re.compile(r"\s*[\(\[][^)\]]*[\)\]]\s*")
_DEVICE = re.compile(r"\s*[’']s\s+(iphone|ipad|android|phone|macbook|laptop|galaxy|pixel)\b.*$", re.I)
_PHONE = re.compile(r"^\+?[\d\s().-]{6,}$")
_TITLES = re.compile(r"^(mr|mrs|ms|miss|dr|prof|sir)\.?\s+", re.I)

_PHONETIC_ALIASES = {
    frozenset({"lee", "ly"}),
    frozenset({"lee", "li"}),
    frozenset({"ly", "li"}),
    frozenset({"dan", "daniel"}),
    frozenset({"bill", "william"}),
    frozenset({"bob", "robert"}),
    frozenset({"jim", "james"}),
    frozenset({"mike", "michael"}),
    frozenset({"dave", "david"}),
    frozenset({"matt", "matthew"}),
    frozenset({"chris", "christopher"}),
    frozenset({"steve", "stephen"}),
    frozenset({"steve", "steven"}),
    frozenset({"jon", "john"}),
    frozenset({"tom", "thomas"}),
}


def clean_name(raw: object) -> str | None:
    """A person's name as shown on screen, or None when the text is not a name (a device, a phone number, a role)."""
    if not isinstance(raw, str):
        return None
    # A label cut short with an ellipsis (a small tile) is only the start of a name: not evidence of the whole.
    if raw.rstrip().endswith(("…", "...")):
        return None
    # "Ly Ha | Tomsoft": what follows the bar is the person's organisation.
    name = _DEVICE.sub("", _PAREN.sub(" ", _ORG_SPLIT.split(raw.strip())[0]))
    if _BOT.search(name):
        return None
    name = re.sub(r"\s+", " ", name).strip(" -–—:,.|")
    if not name or "@" in name or _PHONE.match(name) or sum(ch.isdigit() for ch in name) > 2:
        return None
    if name.casefold() in _GENERIC or len(name) < 2 or len(name.split()) > 4:
        return None
    if not any(ch.isalpha() for ch in name):
        return None
    if name == name.lower() or name == name.upper():
        name = name.title()
    return name


def _tokens(name: str) -> list[str]:
    return [token for token in re.split(r"\s+", _TITLES.sub("", name).casefold()) if token]


def _near(a: str, b: str) -> bool:
    """Equal, or one letter apart: a screen read can swap a letter ("Ha" for "Ho")."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 2:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def same_person(first: str, second: str) -> bool:
    """'Maddy' and 'Maddy Smith' are one person, and so are 'Ly Ha' and 'Ly Ho' (a misread letter);
    'Lee' and 'Ly Ho' (phonetic homophone); 'Maddy Smith' and 'Mark Smith' are not."""
    a, b = _tokens(first), _tokens(second)
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if long_[: len(short)] == short:
        return True
    if len(short) == 1 and (short[0] == long_[0] or frozenset({short[0], long_[0]}) in _PHONETIC_ALIASES):
        return True
    # Same first name (or phonetic alias), surname one letter apart (only when there is a surname on both sides).
    if len(a) >= 2 and len(b) >= 2:
        first_match = a[0] == b[0] or frozenset({a[0], b[0]}) in _PHONETIC_ALIASES
        if first_match and _near(a[-1], b[-1]):
            return True
    return False


def longer_form(first: str, second: str) -> str:
    return first if len(_tokens(first)) >= len(_tokens(second)) else second


@dataclass
class Identity:
    speaker: str
    name: str
    source: str  # "visual", "audio", "visual+audio", "user"
    confidence: float
    seconds: float = 0.0
    moments: int = 0
    merged: list[str] = field(default_factory=list)  # other diarizer ids that are this same person
    conflict: str | None = None  # a different name the other source gave


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _canonical_names(names: list[str]) -> dict[str, str]:
    """Map every spelling to one display form: the longest name that the shorter ones start, and among
    spellings of the same length the one the screen showed most often."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    forms: list[str] = []
    for name in sorted(counts, key=lambda item: (-len(_tokens(item)), -counts[item], item)):
        if not any(same_person(name, form) for form in forms):
            forms.append(name)
    return {name: next(form for form in forms if same_person(name, form)) for name in counts}


def resolve_visual(intervals: list[tuple[int, int, str]], sightings: list) -> tuple[list[Identity], list[tuple[str, str]]]:
    """Name voices from on-screen names. intervals: (start_ms, end_ms, voice id), from the diarizer's turns.
    sightings: objects with name, speaking, start_ms, end_ms. Returns the identities and (kept, merged) pairs."""
    named = [(item, clean_name(item.name)) for item in sightings]
    named = [(item, name) for item, name in named if name]
    if not named or not intervals:
        return [], []
    canon = _canonical_names([name for _, name in named])
    named = [(item, canon[name]) for item, name in named]
    talk: dict[str, int] = {}
    for start, end, voice in intervals:
        talk[voice] = talk.get(voice, 0) + (end - start)

    strong: dict[tuple[str, str], float] = {}
    raw: dict[tuple[str, str], float] = {}  # seconds of any kind, unweighted, for the lift measure
    moments: dict[tuple[str, str], set[str]] = {}
    for item, name in named:
        if not item.speaking:
            continue
        for start, end, voice in intervals:
            lo, hi = max(start, item.start_ms), min(end, item.end_ms)
            if hi > lo:
                key = (voice, name)
                strong[key] = strong.get(key, 0.0) + (hi - lo) / 1000
                raw[key] = raw.get(key, 0.0) + (hi - lo) / 1000
                moments.setdefault(key, set()).update(range(lo // BUCKET_MS, (hi - 1) // BUCKET_MS + 1))

    # A name label with no active-speaker mark counts for little, and only when it is the one name on show
    # for that stretch and one voice carries the talk: a speaker view, not a wall of tiles.
    buckets: dict[int, list[tuple[object, str]]] = {}
    for item, name in named:
        for bucket in range(item.start_ms // BUCKET_MS, (max(item.end_ms - 1, item.start_ms)) // BUCKET_MS + 1):
            buckets.setdefault(bucket, []).append((item, name))
    weak: dict[tuple[str, str], float] = {}
    for bucket, entries in buckets.items():
        names = {name for _, name in entries}
        if len(names) != 1 or any(item.speaking for item, _ in entries):
            continue
        lo, hi = bucket * BUCKET_MS, (bucket + 1) * BUCKET_MS
        per_voice: dict[str, int] = {}
        for start, end, voice in intervals:
            ms = _overlap(start, end, lo, hi)
            if ms > 0:
                per_voice[voice] = per_voice.get(voice, 0) + ms
        if not per_voice:
            continue
        voice, ms = max(per_voice.items(), key=lambda pair: pair[1])
        if ms < 0.7 * sum(per_voice.values()):
            continue
        key = (voice, next(iter(names)))
        weak[key] = weak.get(key, 0.0) + WEAK_WEIGHT * ms / 1000
        raw[key] = raw.get(key, 0.0) + ms / 1000
        moments.setdefault(key, set()).add(bucket)

    score = {key: strong.get(key, 0.0) + weak.get(key, 0.0) for key in set(strong) | set(weak)}
    span_seconds = max((end for _, end, _ in intervals), default=0) / 1000
    marked_total: dict[str, float] = {}
    for (voice, name), value in raw.items():
        marked_total[name] = marked_total.get(name, 0.0) + value
    candidates: dict[str, Identity] = {}
    lifts: dict[str, float] = {}
    for voice in {key[0] for key in score}:
        ranked = sorted(((value, key[1]) for key, value in score.items() if key[0] == voice), reverse=True)
        best, name = ranked[0]
        total = sum(value for value, _ in ranked)
        runner = ranked[1][0] if len(ranked) > 1 else 0.0
        count = len(moments.get((voice, name), ()))
        if best < MIN_SECONDS or count < MIN_MOMENTS or best / total < MIN_SHARE or (runner and best < MIN_LEAD * runner):
            continue
        talked = talk.get(voice, 0) / 1000
        silent = max(span_seconds - talked, 1.0)
        own = raw.get((voice, name), 0.0)
        precision = own / talked if talked else 0.0
        # The mark's rate elsewhere: all of it that fell outside this voice's talk, over the time it was silent.
        # (The mark's seconds are matched to turns, so a mark in this voice's own turns is `own`.)
        elsewhere = max(marked_total.get(name, 0.0) - own, 0.0) / silent
        lift = precision - elsewhere
        if precision < MIN_PRECISION or lift < MIN_LIFT:
            continue
        # Evidence that rests on a name label alone, with no active-speaker mark, caps the confidence.
        marked = strong.get((voice, name), 0.0) / best
        confidence = round((best / total) * min(1.0, best / 12.0) * (0.4 + 0.6 * marked) * min(1.0, 0.5 + lift), 3)
        candidates[voice] = Identity(voice, name, "visual", confidence, round(best, 1), count)
        lifts[voice] = lift

    # One name claimed by several voices: the voice the mark follows best keeps it; when two follow it about
    # equally (a person always on the stage), the one who talks far more does; otherwise nobody gets it.
    chosen: dict[str, Identity] = {}
    merges: list[tuple[str, str]] = []
    by_name: dict[str, list[Identity]] = {}
    for identity in candidates.values():
        by_name.setdefault(identity.name, []).append(identity)
    for name, group in by_name.items():
        group.sort(key=lambda item: (-lifts[item.speaker], -talk.get(item.speaker, 0)))
        keep = group[0]
        if len(group) == 1:
            chosen[keep.speaker] = keep
            continue
        # Voices that each follow the mark clearly, and never talk over each other, are one person split in two.
        sure = [item for item in group if lifts[item.speaker] >= MERGE_LIFT and item.confidence >= MERGE_MIN_CONFIDENCE and item.seconds >= MERGE_MIN_SECONDS]
        if len(sure) >= 2:
            sure.sort(key=lambda item: -talk.get(item.speaker, 0))
            head = sure[0]
            for other in sure[1:]:
                if _talk_over(intervals, head.speaker, other.speaker) <= SAME_PERSON_OVERLAP:
                    head.merged.append(other.speaker)
                    head.seconds = round(head.seconds + other.seconds, 1)
                    head.moments += other.moments
                    merges.append((head.speaker, other.speaker))
                    candidates.pop(other.speaker, None)
            chosen[head.speaker] = head
            continue
        dominant = max(group, key=lambda item: talk.get(item.speaker, 0))
        others = [item for item in group if item is not dominant]
        if all(talk.get(dominant.speaker, 0) >= TALK_DOMINANCE * talk.get(item.speaker, 1) for item in others):
            chosen[dominant.speaker] = dominant
        elif lifts[keep.speaker] - lifts[second.speaker] >= LIFT_TIE:
            chosen[keep.speaker] = keep
    return sorted(chosen.values(), key=lambda item: item.speaker), merges


def _talk_over(intervals: list[tuple[int, int, str]], first: str, second: str) -> float:
    a = [(s, e) for s, e, v in intervals if v == first]
    b = [(s, e) for s, e, v in intervals if v == second]
    shared = sum(_overlap(s1, e1, s2, e2) for s1, e1 in a for s2, e2 in b)
    smaller = min(sum(e - s for s, e in a), sum(e - s for s, e in b))
    return shared / smaller if smaller else 0.0


def clean_partial_name(raw: object) -> str | None:
    """A person's name as shown on screen, including labels ending in an ellipsis from small tiles."""
    if not isinstance(raw, str):
        return None
    trimmed = re.sub(r"[.…\s]+$", "", raw.strip())
    return clean_name(trimmed)


def reconcile(
    visual: list[Identity],
    audio: dict[str, str],
    locked: dict[str, str],
    intervals: list[tuple[int, int, str]] | None = None,
    merges_out: list[tuple[str, str]] | None = None,
) -> dict[str, Identity]:
    """One name per voice. A name a person typed wins. A name from the video and a name said aloud that agree
    are one stronger identity; when they differ the video wins only when its evidence is strong, and the
    other name is kept as a conflict so a person can look.
    Cross-voice unification: Voices representing the same person that do not talk over each other are
    merged into a single identity."""
    out: dict[str, Identity] = {}
    by_voice = {item.speaker: item for item in visual}
    for voice in set(by_voice) | set(audio) | set(locked):
        user, heard, seen = locked.get(voice), clean_name(audio.get(voice)), by_voice.get(voice)
        if user:
            out[voice] = Identity(voice, user, "user", 1.0, merged=seen.merged if seen else [])
        elif seen and heard:
            if same_person(seen.name, heard):
                out[voice] = Identity(voice, longer_form(seen.name, heard), "visual+audio", min(1.0, seen.confidence + 0.3),
                                      seen.seconds, seen.moments, seen.merged)
            elif seen.confidence >= 0.6:
                out[voice] = Identity(voice, seen.name, "visual", seen.confidence, seen.seconds, seen.moments, seen.merged, conflict=heard)
            else:
                out[voice] = Identity(voice, heard, "audio", 0.5, conflict=seen.name, merged=seen.merged)
        elif seen:
            out[voice] = seen
        elif heard:
            out[voice] = Identity(voice, heard, "audio", 0.5)

    # Cross-voice unification for same person
    groups: list[list[Identity]] = []
    for item in out.values():
        matched = False
        for grp in groups:
            if any(same_person(item.name, other.name) for other in grp):
                grp.append(item)
                matched = True
                break
        if not matched:
            groups.append([item])

    merged_pairs = merges_out if merges_out is not None else []
    talk_dur: dict[str, int] = {}
    if intervals:
        for s, e, v in intervals:
            talk_dur[v] = talk_dur.get(v, 0) + (e - s)

    for grp in groups:
        if len(grp) <= 1:
            continue
        # Dominant voice as head: user locked first, then voices with speech, then talk duration, then confidence
        grp.sort(
            key=lambda x: (
                x.source == "user",
                talk_dur.get(x.speaker, 0) > 0,
                talk_dur.get(x.speaker, 0),
                x.confidence,
                x.seconds,
            ),
            reverse=True,
        )
        head = grp[0]
        for other in grp[1:]:
            head.name = longer_form(head.name, other.name)
            head.confidence = max(head.confidence, other.confidence)
            if head.source != "user" and other.source in ("visual", "visual+audio"):
                head.source = "visual+audio" if head.source == "audio" else other.source
        for other in grp[1:]:
            can_merge = True
            if intervals:
                can_merge = _talk_over(intervals, head.speaker, other.speaker) <= SAME_PERSON_OVERLAP
            if can_merge:
                if other.speaker not in head.merged:
                    head.merged.append(other.speaker)
                head.merged.extend([m for m in other.merged if m not in head.merged and m != head.speaker])
                head.seconds = round(head.seconds + other.seconds, 1)
                head.moments += other.moments
                merged_pairs.append((head.speaker, other.speaker))
                other.name = head.name

    return out


def fuse_identities_model(
    spans: list,
    sightings: list,
    intervals: list[tuple[int, int, str]],
    locked_names: dict[str, str] | None = None,
    digest_speakers: list[dict] | None = None,
    reasoner: object | None = None,
    registry: object | None = None,
) -> tuple[dict[str, Identity], list[tuple[str, str]]]:
    """Fuse multi-modal identity cues using Bedrock Reasoner (meeting.identity.fuse.v1) when available,
    falling back to visual resolution and cross-voice reconciliation."""
    from registry.ids import IDENTITY_FUSE

    locked = dict(locked_names or {})
    audio_map: dict[str, str] = {}
    for entry in digest_speakers or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("name"), str):
            audio_map[entry["id"]] = entry["name"]

    # Visual resolution runs first so ground-truth video sightings are always captured
    visual_ids, visual_merges = resolve_visual(intervals, sightings)
    merges_list: list[tuple[str, str]] = list(visual_merges)
    combined_map: dict[str, Identity] = {v.speaker: v for v in visual_ids}

    # If Reasoner and Registry are supplied, attempt model-driven fusion
    if reasoner is not None and registry is not None and hasattr(reasoner, "complete"):
        try:
            # Build speech summaries per voice
            voice_data: dict[str, dict] = {}
            for start, end, voice in intervals:
                voice_data.setdefault(voice, {"duration_ms": 0, "samples": []})["duration_ms"] += (end - start)
            for span in spans:
                voice = getattr(span, "speaker_hypothesis_id", None)
                if isinstance(span, dict):
                    voice = span.get("speaker_hypothesis_id")
                    text = span.get("text") or span.get("raw_text") or ""
                else:
                    text = getattr(span, "text", "") or getattr(span, "raw_text", "")
                if voice and voice in voice_data and text.strip() and len(voice_data[voice]["samples"]) < 3:
                    if len(text.split()) >= 3:
                        voice_data[voice]["samples"].append(text.strip()[:150])

            voices_payload = [
                {
                    "id": v_id,
                    "duration_seconds": round(info["duration_ms"] / 1000, 1),
                    "sample_texts": info["samples"],
                    "candidate_name": locked.get(v_id) or audio_map.get(v_id),
                }
                for v_id, info in voice_data.items()
            ]

            sightings_payload = []
            seen_sightings = set()
            for s in sightings:
                name = clean_partial_name(getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None))
                if name and name not in seen_sightings:
                    seen_sightings.add(name)
                    speaking = getattr(s, "speaking", False) if not isinstance(s, dict) else s.get("speaking", False)
                    cue = getattr(s, "cue", "label") if not isinstance(s, dict) else s.get("cue", "label")
                    sightings_payload.append({"name": name, "speaking": bool(speaking), "cue": str(cue)})

            turn = reasoner.complete(
                prompt_id=IDENTITY_FUSE,
                role="slm",
                payload={
                    "voices": voices_payload,
                    "visual_sightings": sightings_payload,
                    "spoken_names": [{"id": k, "name": v} for k, v in audio_map.items()],
                    "user_locked": locked,
                },
            )
            output = turn.output if hasattr(turn, "output") else turn
            if isinstance(output, dict) and "identities" in output:
                for item in output.get("identities") or []:
                    vid = item.get("voice_id")
                    raw_name = item.get("name")
                    clean = clean_name(raw_name)
                    if vid and clean:
                        conf = min(1.0, max(0.0, float(item.get("confidence") or 0.8)))
                        model_id = Identity(
                            speaker=vid,
                            name=clean,
                            source="user" if vid in locked else "visual+audio",
                            confidence=conf,
                        )
                        if vid not in combined_map or conf >= combined_map[vid].confidence:
                            combined_map[vid] = model_id
                for m in output.get("merges") or []:
                    keep = m.get("keep_voice_id")
                    other = m.get("merge_voice_id")
                    if keep and other and keep != other:
                        if (keep, other) not in merges_list:
                            merges_list.append((keep, other))
        except Exception as exc:
            import sys
            print(f"identity model fusion fallback: {type(exc).__name__}", file=sys.stderr, flush=True)

    if locked:
        merges_list = [
            (keep, other)
            for keep, other in merges_list
            if not (
                keep in locked
                and other in locked
                and locked[keep].strip().lower() != locked[other].strip().lower()
            )
        ]
    reconciled = reconcile(list(combined_map.values()), audio_map, locked, intervals=intervals, merges_out=merges_list)
    return reconciled, merges_list
