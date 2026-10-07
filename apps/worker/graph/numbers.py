# Motivation vs Logic
# Motivation: A published number, percent, currency amount, or clock time must occur in the cited span.
# Logic: Lex numbers and word-cardinals into quantities. A unit, direction, or unsettled word-form mismatch stays unresolved.

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_TOKEN = re.compile(
    r"\d{1,2}:\d{2}(?::\d{2})?|[$€£]-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|-?[$€£]?\d+(?:\.\d+)?%?|[A-Za-z]+(?:-[A-Za-z]+)?(?:'[A-Za-z]+)?|%"
)

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORDS = {**_ONES, **_TENS}
_UP = {"increase", "increased", "increasing", "up", "higher", "above", "gain", "gained", "grew", "rise", "rose", "rising"}
_DOWN = {"decrease", "decreased", "decreasing", "down", "lower", "below", "drop", "dropped", "fell", "fall", "falling", "decline", "declined"}
_UNSETTLED = {"couple", "dozen", "few"}
_CURRENCY = {"usd": "usd", "eur": "eur", "gbp": "gbp", "$": "usd", "€": "eur", "£": "gbp", "dollar": "usd", "dollars": "usd", "euro": "eur", "euros": "eur", "pound": "gbp", "pounds": "gbp"}


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    direction: int | None


@dataclass(frozen=True)
class NumberScan:
    quantities: tuple[Quantity, ...]
    unsettled: bool


def scan(text: str) -> NumberScan:
    tokens = _TOKEN.findall(text)
    quantities: list[Quantity] = []
    unsettled = False
    consumed: set[int] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        clock = re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", token)
        if clock:
            quantities.append(Quantity(value=Decimal(token.replace(":", "")), unit=f"clock:{token}", direction=_direction(tokens, index, consumed)))
            consumed.add(index)
            index += 1
            continue
        word, word_end, word_unset = _word_number(tokens, index)
        if word_unset:
            unsettled = True
            index += 1
            continue
        if word is not None:
            unit, consumed_until = _unit_after(tokens, word_end)
            direction = _direction(tokens, index, consumed | set(range(index, consumed_until)))
            quantities.append(Quantity(value=word, unit=unit, direction=direction))
            consumed.update(range(index, consumed_until))
            index = consumed_until
            continue
        number = _digit(token)
        if number is None:
            if token.lower() in _UNSETTLED:
                unsettled = True
            index += 1
            continue
        value, sign, prefix_unit, suffix_percent = number
        unit = "percent" if suffix_percent else (prefix_unit or "bare")
        consumed_until = index + 1
        if unit == "bare":
            unit, consumed_until = _unit_after(tokens, index + 1)
            if unit == "bare" and prefix_unit:
                unit = prefix_unit
        direction = -1 if sign else _direction(tokens, index, consumed | set(range(index, consumed_until)))
        if sign and _direction(tokens, index, consumed | set(range(index, consumed_until))) not in (None, -1):
            unsettled = True
        quantities.append(Quantity(value=value, unit=unit, direction=direction))
        consumed.update(range(index, consumed_until))
        index = consumed_until
    if _orphan_unit(tokens, consumed):
        unsettled = True
    return NumberScan(tuple(quantities), unsettled)


def grounded(claim: str, span: str) -> bool:
    claim_scan = scan(claim)
    if claim_scan.unsettled:
        return False
    span_scan = scan(span)
    for quantity in claim_scan.quantities:
        if not any(_same(quantity, other) for other in span_scan.quantities):
            return False
    return True


def _same(claim: Quantity, span: Quantity) -> bool:
    if claim.value != span.value or claim.unit != span.unit:
        return False
    if claim.direction is not None and claim.direction != span.direction:
        return False
    return True


def _digit(token: str) -> tuple[Decimal, bool, str | None, bool] | None:
    match = re.fullmatch(r"([$€£])?(-)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%)?", token)
    if not match:
        return None
    prefix, sign, whole, frac, percent = match.groups()
    value = Decimal(whole.replace(",", "") + (frac or ""))
    unit = _CURRENCY[prefix] if prefix else None
    return value, bool(sign), unit, bool(percent)


def _word_number(tokens: list[str], index: int) -> tuple[Decimal | None, int, bool]:
    token = tokens[index]
    if "-" in token:
        left, right = token.lower().split("-", 1)
        if left in _TENS and right in _ONES:
            return Decimal(_TENS[left] + _ONES[right]), index + 1, False
        if left in _WORDS:
            return None, index, True
        return None, index, False
    if token.lower() not in _WORDS and token.lower() not in {"hundred", "thousand"}:
        return None, index, False
    total = 0
    current = 0
    cursor = index
    seen = False
    while cursor < len(tokens):
        word = tokens[cursor].lower()
        if "-" in word:
            value, _end, unset = _word_number(tokens, cursor)
            if unset or value is None:
                break
            current += int(value)
            seen = True
            cursor += 1
            continue
        if word in _WORDS:
            current += _WORDS[word]
            seen = True
            cursor += 1
            continue
        if word == "hundred":
            current = (current or 1) * 100
            seen = True
            cursor += 1
            continue
        if word == "thousand":
            total += (current or 1) * 1000
            current = 0
            seen = True
            cursor += 1
            continue
        if word == "and" and seen:
            cursor += 1
            continue
        break
    if not seen:
        return None, index, False
    return Decimal(total + current), cursor, False


def _unit_after(tokens: list[str], index: int) -> tuple[str, int]:
    if index >= len(tokens):
        return "bare", index
    word = tokens[index].lower()
    if word in {"%", "percent", "percentage"}:
        return "percent", index + 1
    if word == "per" and index + 1 < len(tokens) and tokens[index + 1].lower() == "cent":
        return "percent", index + 2
    if word in _CURRENCY:
        return _CURRENCY[word], index + 1
    return "bare", index


def _direction(tokens: list[str], index: int, consumed: set[int]) -> int | None:
    found: list[int] = []
    for cursor in range(max(0, index - 4), min(len(tokens), index + 5)):
        if cursor in consumed and cursor != index:
            continue
        word = tokens[cursor].lower()
        if word in _UP:
            found.append(1)
        elif word in _DOWN:
            found.append(-1)
    if not found:
        return None
    if any(item != found[0] for item in found):
        return None
    return found[0]


def _orphan_unit(tokens: list[str], consumed: set[int]) -> bool:
    for index, token in enumerate(tokens):
        if index in consumed:
            continue
        if token.lower() in {"%", "percent", "percentage"}:
            return True
    return False
