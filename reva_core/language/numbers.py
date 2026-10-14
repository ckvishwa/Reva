"""Spoken English numbers to values.

Examples: "forty two", "one hundred and five", "fifteen hundred", "two point five".

Pure functions, no I/O. `parse_number_words` reads the longest number it can from the front of a
list and says how many words it used; `parse_digits` reads "1,200" and "12.50".
"""

from __future__ import annotations

import re
from decimal import Decimal

UNITS = {
    "zero": 0,
    "oh": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fourty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}
NUMBER_WORDS = frozenset(UNITS) | frozenset(TENS) | frozenset(SCALES) | {"point", "and", "a", "an"}

_DIGITS = re.compile(r"^\d[\d,]*(?:\.\d+)?$")


def is_digits(token: str) -> bool:
    return bool(_DIGITS.match(token))


def parse_digits(token: str) -> Decimal:
    return Decimal(token.replace(",", ""))


def _is_scale_ahead(words: list[str], i: int) -> bool:
    return i < len(words) and words[i] in ("hundred", "thousand", "million")


def parse_number_words(words: list[str]) -> tuple[Decimal, int] | None:
    """The number at the front of `words` and how many words it took, or None.

    "twelve fifty" is two numbers (12, 50): a teen is never extended by a tens word, and a tens word
    is only extended by a unit ("twenty five"). That rule is what keeps spoken prices separable.
    """
    total = 0
    current = 0
    i = 0
    used_any = False
    while i < len(words):
        word = words[i]
        if word in UNITS and word != "oh":
            value = UNITS[word]
            # a unit may follow nothing, a hundred/thousand, or a tens word ("twenty five");
            # a teen may not
            if current % 100 == 0 or (current % 10 == 0 and current % 100 >= 20 and value < 10):
                if current % 100 != 0 and value >= 10:
                    break
                current += value
                used_any = True
                i += 1
                continue
            break
        if word in TENS:
            if current % 100 == 0:
                current += TENS[word]
                used_any = True
                i += 1
                continue
            break
        if word in ("a", "an") and _is_scale_ahead(words, i + 1) and not used_any and current == 0:
            current = 1
            used_any = True
            i += 1
            continue
        if word == "hundred" and (used_any or current):
            current = (current or 1) * 100 if current < 100 else current * 100
            i += 1
            continue
        if word in ("thousand", "million") and (used_any or current or total):
            total += (current or 1) * SCALES[word]
            current = 0
            used_any = True
            i += 1
            continue
        if word == "and" and used_any and i + 1 < len(words) and _starts_number(words[i + 1]):
            # "one hundred and five": only after a hundred/thousand
            if i > 0 and words[i - 1] in ("hundred", "thousand", "million"):
                i += 1
                continue
            break
        break
    if not used_any:
        return None
    result = Decimal(total + current)
    # "two point five"
    if i + 1 < len(words) and words[i] == "point" and words[i + 1] in UNITS:
        digits = ""
        j = i + 1
        while j < len(words) and words[j] in UNITS and UNITS[words[j]] < 10:
            digits += str(UNITS[words[j]])
            j += 1
        if digits:
            return result + Decimal("0." + digits), j
    return result, i


def _starts_number(word: str) -> bool:
    return word in UNITS or word in TENS
