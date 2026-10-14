"""Normalize a final transcript into typed values (ARD-450 §3.1, AR-LANG-002).

Deterministic and model-free. English only (Telugu and code-mixed input arrive in R3).

* Spoken numbers, money and percentages: "twelve bucks" -> USD 12.00 (1200 minor units).
* Dates, times and durations relative to the device clock and time zone passed in as `now`:
  "tomorrow at 7" -> a date and a time; "for forty minutes" -> `PT40M`.
* **Ambiguity is preserved, never guessed away.** "two fifty" is $2.50 or $250; "at 7" is 07:00 or
  19:00; "next Friday" is this coming Friday or the one after; "wednesday" said on a Wednesday is
  today or next week. Every reading is kept with a score, in order, and the resolution step asks.
* Filler and recognizer noise ("uh", "can I please", "like,") is removed from the text used for
  matching and reported in `fillers_removed`; the transcript itself is never changed.

Nothing here decides what the person wants (that is the rule or planner stage) and nothing here
writes or authorizes anything. `to_frame` wraps the result in an NluFrame
(contracts/nlu-frame.schema.json)
whose intent is the placeholder `unrouted.pending` until a rule or the planner fills it in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from reva_core.language.numbers import (
    NUMBER_WORDS,
    UNITS,
    is_digits,
    parse_digits,
    parse_number_words,
)

UNROUTED_INTENT = "unrouted.pending"
MAX_CANDIDATES = 5

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
}
CURRENCY_WORDS = {
    "dollar": "USD",
    "dollars": "USD",
    "buck": "USD",
    "bucks": "USD",
    "usd": "USD",
    "euro": "EUR",
    "euros": "EUR",
}
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
_NOT_A_COUNT_BEFORE_ONE = frozenset(
    {
        "the",
        "this",
        "that",
        "which",
        "every",
        "each",
        "another",
        "any",
        "no",
        "a",
        "an",
        "last",
        "next",
    }
)
MONEY_CUES = frozenset(
    {"spent", "spend", "paid", "pay", "cost", "costs", "worth", "price", "for", "of", "charged"}
)
DURATION_UNITS = {
    "second": "S",
    "seconds": "S",
    "sec": "S",
    "secs": "S",
    "minute": "M",
    "minutes": "M",
    "min": "M",
    "mins": "M",
    "hour": "H",
    "hours": "H",
    "hr": "H",
    "hrs": "H",
    "day": "D",
    "days": "D",
    "week": "W",
    "weeks": "W",
}
_SECONDS = {"S": 1, "M": 60, "H": 3600, "D": 86400, "W": 604800}


@dataclass(frozen=True)
class Reading:
    id: str
    label: str
    value: dict[str, Any]
    score: float


@dataclass(frozen=True)
class TypedValue:
    kind: str
    phrase: str
    readings: tuple[Reading, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.readings) > 1

    @property
    def value(self) -> dict[str, Any]:
        """The first (most likely) reading."""
        return self.readings[0].value


@dataclass(frozen=True)
class Normalized:
    transcript: str
    cleaned: str
    fillers_removed: tuple[str, ...]
    values: tuple[TypedValue, ...]
    language: str = "en"
    _debug: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


# ------------------------------------------------------------------------------------ fillers

_FILLERS = [
    re.compile(r"\b(?:can|could|would|will)\s+(?:i|you|we)(?:\s+please)?\b", re.I),
    re.compile(r"\b(?:uh+m*|um+|erm|er|ah|hmm+|uhm)\b", re.I),
    re.compile(r"\byou know\b", re.I),
    re.compile(r"\bi mean\b", re.I),
    re.compile(r"\bplease\b", re.I),
    re.compile(r"(?:(?<=,)|^)\s*like\s*,", re.I),
    re.compile(r",\s*like\b(?=\s*,)", re.I),
]


def clean_fillers(text: str) -> tuple[str, tuple[str, ...]]:
    removed: list[tuple[int, str]] = []
    cleaned = text
    for pattern in _FILLERS:
        # record what each pass removes, in the order they appear in the original
        for match in pattern.finditer(cleaned):
            removed.append((text.lower().find(match.group().strip(" ,").lower()), match.group()))
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s*,\s*(?:,\s*)+", ", ", cleaned)
    cleaned = re.sub(r"^[\s,]+|[\s,]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).replace(" ,", ",")
    removed.sort(key=lambda pair: pair[0])
    return cleaned, tuple(piece.strip(" ,") for _, piece in removed if piece.strip(" ,"))


# ----------------------------------------------------------------------------------- tokens


@dataclass(frozen=True)
class Tok:
    text: str
    lower: str
    kind: str  # "num" | "word" | "sym" | "iso"
    start: int
    end: int
    value: Decimal | None = None
    count: int = 1  # source tokens a fused number used


_TOKEN = re.compile(
    r"\d{4}-\d{2}-\d{2}"  # iso date
    r"|\d[\d,]*(?:\.\d+)?"  # digits
    r"|[A-Za-z]+(?:'[A-Za-z]+)?"  # words
    r"|[$€£%:]"  # symbols that matter
    r"|[^\s]"  # anything else
)


def _prepare(text: str) -> str:
    # "7 p.m." / "7 P.M." -> "7 pm"
    text = re.sub(
        r"(?<![A-Za-z])([ap])\.\s?m\.?", lambda m: m.group(1).lower() + "m", text, flags=re.I
    )
    return text


def tokenize(text: str) -> list[Tok]:
    raw: list[Tok] = []
    for match in _TOKEN.finditer(text):
        piece = match.group()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", piece):
            raw.append(Tok(piece, piece, "iso", match.start(), match.end()))
        elif is_digits(piece):
            raw.append(Tok(piece, piece, "num", match.start(), match.end(), parse_digits(piece)))
        elif piece[0].isalpha():
            raw.append(Tok(piece, piece.lower(), "word", match.start(), match.end()))
        else:
            raw.append(Tok(piece, piece, "sym", match.start(), match.end()))
    return _fuse_numbers(raw)


def _fuse_numbers(raw: list[Tok]) -> list[Tok]:
    out: list[Tok] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok.kind == "word" and tok.lower in NUMBER_WORDS:
            words = [t.lower if t.kind == "word" else "" for t in raw[i : i + 12]]
            parsed = parse_number_words(words)
            if parsed is not None:
                value, used = parsed
                out.append(
                    Tok(
                        " ".join(t.text for t in raw[i : i + used]),
                        "#",
                        "num",
                        tok.start,
                        raw[i + used - 1].end,
                        value,
                        used,
                    )
                )
                i += used
                continue
        out.append(tok)
        i += 1
    return out


# ---------------------------------------------------------------------------------- helpers


def _money_value(amount: Decimal, currency: str) -> dict[str, Any]:
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": f"{quantized:.2f}",
        "amount_minor": int(quantized * 100),
        "currency": currency,
    }


def _money_label(amount: Decimal, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}.get(currency, currency + " ")
    return f"{symbol}{amount.quantize(Decimal('0.01')):,.2f}"


def _number_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".")


def _phrase(text: str, toks: list[Tok]) -> str:
    return text[toks[0].start : toks[-1].end]


def _is_int(tok: Tok) -> bool:
    return (
        tok.kind == "num" and tok.value is not None and tok.value == tok.value.to_integral_value()
    )


def _readings(items: list[tuple[str, str, dict[str, Any], float]]) -> tuple[Reading, ...]:
    return tuple(
        Reading(i, label, value, score) for i, label, value, score in items[:MAX_CANDIDATES]
    )


def format_duration(unit: str, amount: Decimal) -> str | None:
    seconds = amount * _SECONDS[unit]
    if seconds != seconds.to_integral_value() or seconds <= 0:
        return None
    total = int(seconds)
    if unit == "W" and amount == amount.to_integral_value():
        return f"P{int(amount)}W"
    if unit == "D" and amount == amount.to_integral_value():
        return f"P{int(amount)}D"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    out = "PT"
    if hours:
        out += f"{hours}H"
    if minutes:
        out += f"{minutes}M"
    if secs:
        out += f"{secs}S"
    return out


# ------------------------------------------------------------------------------- recognizers


class _Scanner:
    def __init__(self, text: str, toks: list[Tok], now: datetime) -> None:
        self.text = text
        self.toks = toks
        self.now = now
        self.today = now.date()

    def at(self, i: int) -> Tok | None:
        return self.toks[i] if 0 <= i < len(self.toks) else None

    def word(self, i: int) -> str:
        tok = self.at(i)
        return tok.lower if tok is not None and tok.kind == "word" else ""

    # ---- money

    def money(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        # $12.50
        if tok.kind == "sym" and tok.text in CURRENCY_SYMBOLS:
            nxt = self.at(i + 1)
            if nxt is not None and nxt.kind == "num" and nxt.value is not None:
                currency = CURRENCY_SYMBOLS[tok.text]
                end = i + 1
                amount = nxt.value
                if self.word(i + 2) in ("and",) and (c := self._cents(i + 3)):
                    amount += c[0]
                    end = c[1]
                return self._money_tv(self.toks[i : end + 1], amount, currency), end + 1
            return None
        if tok.kind != "num" or tok.value is None:
            return None
        # twelve dollars [and] fifty [cents]
        word_currency = CURRENCY_WORDS.get(self.word(i + 1))
        if word_currency is not None:
            currency = word_currency
            amount = tok.value
            end = i + 1
            j = i + 2
            if self.word(j) == "and":
                j += 1
            cents = self._cents(j)
            if cents is not None and tok.value == tok.value.to_integral_value():
                amount += cents[0]
                end = cents[1]
            return self._money_tv(self.toks[i : end + 1], amount, currency), end + 1
        # fifty cents
        if self.word(i + 1) in ("cent", "cents") and tok.value < 100:
            return self._money_tv(self.toks[i : i + 2], tok.value / 100, "USD"), i + 2
        # "a buck"
        return None

    def _cents(self, j: int) -> tuple[Decimal, int] | None:
        tok = self.at(j)
        if (
            tok is None
            or tok.kind != "num"
            or tok.value is None
            or not _is_int(tok)
            or not (0 < tok.value < 100)
        ):
            return None
        end = j
        if self.word(j + 1) in ("cent", "cents"):
            end = j + 1
        return tok.value / 100, end

    def _money_tv(self, toks: list[Tok], amount: Decimal, currency: str) -> TypedValue:
        return TypedValue(
            "money",
            _phrase(self.text, toks),
            _readings(
                [
                    (
                        f"{amount:.2f}-{currency}",
                        _money_label(amount, currency),
                        _money_value(amount, currency),
                        1.0,
                    )
                ]
            ),
        )

    def bare_pair(self, i: int) -> tuple[TypedValue, int] | None:
        """ "two fifty", "twelve fifty": dollars and cents, or a plain number twice the size."""
        first, second = self.at(i), self.at(i + 1)
        if first is None or second is None or first.kind != "num" or second.kind != "num":
            return None
        if not (_is_int(first) and _is_int(second)) or first.value is None or second.value is None:
            return None
        if not (1 <= first.value <= 99 and 10 <= second.value <= 99):
            return None
        if first.text.isdigit() and second.text.isdigit():
            return None  # digits next to digits ("3 25") is not a spoken price
        after = self.word(i + 2)
        if after in DURATION_UNITS or after in ("percent", "am", "pm") or self.word(i - 1) == "at":
            return None
        cued = (
            self.word(i - 1) in MONEY_CUES
            or self.word(i - 2) in MONEY_CUES
            or after in CURRENCY_WORDS
            or after in ("for", "on")
            or self.word(i - 1) in CURRENCY_WORDS
        )
        dollars_and_cents = first.value + second.value / 100
        as_hundreds = first.value * 100 + second.value
        currency = CURRENCY_WORDS.get(after, "USD")
        phrase = _phrase(self.text, self.toks[i : i + 2])
        end = i + 2
        if after in CURRENCY_WORDS:
            end = i + 3
            phrase = _phrase(self.text, self.toks[i : i + 3])
        if cued:
            readings = _readings(
                [
                    (
                        f"{dollars_and_cents:.2f}-{currency}",
                        _money_label(dollars_and_cents, currency),
                        _money_value(dollars_and_cents, currency),
                        0.6,
                    ),
                    (
                        f"{as_hundreds:.2f}-{currency}",
                        _money_label(as_hundreds, currency),
                        _money_value(as_hundreds, currency),
                        0.4,
                    ),
                ]
            )
            return TypedValue("money", phrase, readings), end
        readings = _readings(
            [
                (
                    _number_text(as_hundreds),
                    _number_text(as_hundreds),
                    {"number": _number_text(as_hundreds)},
                    0.5,
                ),
                (
                    _number_text(dollars_and_cents),
                    _number_text(dollars_and_cents),
                    {"number": _number_text(dollars_and_cents)},
                    0.5,
                ),
            ]
        )
        return TypedValue("number", phrase, readings), end

    # ---- percent

    def percent(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        if tok.kind != "num" or tok.value is None:
            return None
        nxt = self.at(i + 1)
        if nxt is not None and (nxt.text == "%" or nxt.lower == "percent"):
            value = {"percent": _number_text(tok.value)}
            return (
                TypedValue(
                    "percent",
                    _phrase(self.text, self.toks[i : i + 2]),
                    _readings([(value["percent"], value["percent"] + "%", value, 1.0)]),
                ),
                i + 2,
            )
        return None

    # ---- duration

    def duration(self, i: int) -> tuple[TypedValue, int] | None:
        word = self.word(i)
        # half an hour
        if (
            word == "half"
            and self.word(i + 1) in ("an", "a")
            and (unit := DURATION_UNITS.get(self.word(i + 2)))
        ):
            iso = format_duration(unit, Decimal("0.5"))
            if iso:
                return self._duration_tv(self.toks[i : i + 3], iso), i + 3
        amount: Decimal | None = None
        end = i
        if (
            word in ("a", "an")
            and DURATION_UNITS.get(self.word(i + 1))
            and self._reads_as_a_length(i)
        ):
            amount, end = Decimal(1), i + 1
        elif (
            (tok := self.toks[i]).kind == "num"
            and tok.value is not None
            and (unit := DURATION_UNITS.get(self.word(i + 1)))
            and (tok.text.lower() != "one" or self._reads_as_a_length(i))
        ):
            amount, end = tok.value, i + 1
        if amount is None:
            return None
        iso_unit = DURATION_UNITS[self.word(end)]
        # "an hour and a half" / "two hours and thirty minutes"
        if self.word(end + 1) == "and":
            if self.word(end + 2) in ("a", "an") and self.word(end + 3) == "half":
                amount += Decimal("0.5")
                end += 3
            elif (
                (tok2 := self.at(end + 2)) is not None
                and tok2.kind == "num"
                and tok2.value is not None
                and DURATION_UNITS.get(self.word(end + 3)) == "M"
                and iso_unit == "H"
            ):
                total_minutes = amount * 60 + tok2.value
                iso = format_duration("M", total_minutes)
                if iso:
                    return self._duration_tv(self.toks[i : end + 4], iso), end + 4
        iso = format_duration(iso_unit, amount)
        if iso is None:
            return None
        return self._duration_tv(self.toks[i : end + 1], iso), end + 1

    def _reads_as_a_length(self, i: int) -> bool:
        """ "a minute" is a length after for/in/about..., and an idiom in "wait a minute"."""
        if self.word(i - 1) in ("for", "in", "about", "every", "within", "after", "over", "than"):
            return True
        if i == 0 and len(self.toks) == 2 and DURATION_UNITS.get(self.word(1)) != "S":
            return True  # the whole answer: "an hour" ("one sec" is a figure of speech)
        unit_at = i + 1
        return self.word(unit_at + 1) == "and" and self.word(unit_at + 2) in ("a", "an")

    def _duration_tv(self, toks: list[Tok], iso: str) -> TypedValue:
        return TypedValue(
            "duration", _phrase(self.text, toks), _readings([(iso, iso, {"duration": iso}, 1.0)])
        )

    # ---- time

    def time_of_day(self, i: int) -> tuple[TypedValue, int] | None:
        word = self.word(i)
        if word in ("noon", "midnight"):
            hhmm = "12:00" if word == "noon" else "00:00"
            return self._time_tv(self.toks[i : i + 1], [(hhmm, 1.0)]), i + 1
        if word == "half" and self.word(i + 1) == "past" and self._hour(i + 2) is not None:
            hour, end = self._hour(i + 2)  # type: ignore[misc]
            return self._time_tv(self.toks[i:end], self._hour_readings(hour, 30)), end
        if (
            word == "quarter"
            and self.word(i + 1) in ("past", "to")
            and self._hour(i + 2) is not None
        ):
            hour, end = self._hour(i + 2)  # type: ignore[misc]
            if self.word(i + 1) == "past":
                return self._time_tv(self.toks[i:end], self._hour_readings(hour, 15)), end
            return self._time_tv(
                self.toks[i:end], self._hour_readings((hour - 1) % 12 or 12, 45)
            ), end
        tok = self.toks[i]
        # at 7 / at seven thirty
        if word == "at":
            parsed = self._clock_after(i + 1)
            if parsed is not None:
                readings, end = parsed
                return self._time_tv(self.toks[i:end], readings), end
            return None
        # 7:30 [am|pm]  /  7 pm  /  19:00
        parsed = self._clock_after(i)
        if parsed is not None and tok.kind == "num":
            readings, end = parsed
            explicit = self.word(end - 1) in ("am", "pm") or (
                self.at(i + 1) is not None and self.toks[i + 1].text == ":"
            )
            if explicit or self.word(end) in ("o'clock",):
                return self._time_tv(self.toks[i:end], readings), end
        return None

    def _hour(self, j: int) -> tuple[int, int] | None:
        tok = self.at(j)
        if (
            tok is not None
            and tok.kind == "num"
            and tok.value is not None
            and _is_int(tok)
            and 1 <= tok.value <= 12
        ):
            return int(tok.value), j + 1
        return None

    def _clock_after(self, j: int) -> tuple[list[tuple[str, float]], int] | None:
        tok = self.at(j)
        if tok is None or tok.kind != "num" or tok.value is None or not _is_int(tok):
            return None
        hour = int(tok.value)
        if not 0 <= hour <= 24:
            return None
        end = j + 1
        minute = 0
        colon = self.at(j + 1)
        if (
            colon is not None
            and colon.text == ":"
            and (m := self.at(j + 2)) is not None
            and m.kind == "num"
            and m.value is not None
            and _is_int(m)
            and 0 <= m.value < 60
            and len(m.text) == 2
        ):
            minute = int(m.value)
            end = j + 3
        elif (
            (m2 := self.at(j + 1)) is not None
            and m2.kind == "num"
            and m2.value is not None
            and _is_int(m2)
            and 10 <= m2.value < 60
            and self.word(j - 1) == "at"
        ):
            minute = int(m2.value)  # "at seven thirty"
            end = j + 2
        suffix = self.word(end)
        if suffix in ("am", "pm"):
            if hour > 12 or hour == 0:
                return None
            h24 = hour % 12 + (12 if suffix == "pm" else 0)
            return [(f"{h24:02d}:{minute:02d}", 1.0)], end + 1
        if self.word(end) == "o'clock":
            return self._hour_readings(hour, minute), end + 1
        if (
            hour > 12
            or (end > j + 1 and hour >= 13)
            or (colon is not None and colon.text == ":" and hour >= 13)
        ):
            return [(f"{hour % 24:02d}:{minute:02d}", 1.0)], end
        if hour == 0:
            return [(f"00:{minute:02d}", 1.0)], end
        return self._hour_readings(hour, minute), end

    @staticmethod
    def _hour_readings(hour: int, minute: int) -> list[tuple[str, float]]:
        if hour == 12:
            return [(f"12:{minute:02d}", 0.7), (f"00:{minute:02d}", 0.3)]
        return [(f"{hour:02d}:{minute:02d}", 0.55), (f"{hour + 12:02d}:{minute:02d}", 0.45)]

    def _time_tv(self, toks: list[Tok], readings: list[tuple[str, float]]) -> TypedValue:
        return TypedValue(
            "time",
            _phrase(self.text, toks),
            _readings([(hhmm, hhmm, {"time": hhmm}, score) for hhmm, score in readings]),
        )

    # ---- dates

    def date_value(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        word = tok.lower if tok.kind == "word" else ""
        if tok.kind == "iso":
            try:
                parsed = date.fromisoformat(tok.text)
            except ValueError:
                return None
            return self._date_tv(self.toks[i : i + 1], [(parsed, 1.0)]), i + 1
        if word == "today":
            return self._date_tv(self.toks[i : i + 1], [(self.today, 1.0)]), i + 1
        if word == "tomorrow":
            return self._date_tv(
                self.toks[i : i + 1], [(self.today + timedelta(days=1), 1.0)]
            ), i + 1
        if word == "yesterday":
            return self._date_tv(
                self.toks[i : i + 1], [(self.today - timedelta(days=1), 1.0)]
            ), i + 1
        if word == "day" and self.word(i + 1) == "after" and self.word(i + 2) == "tomorrow":
            return self._date_tv(
                self.toks[i : i + 3], [(self.today + timedelta(days=2), 1.0)]
            ), i + 3
        # next / this / last <weekday>
        if word in ("next", "this", "last") and self.word(i + 1) in WEEKDAYS:
            return self._weekday(i, word, WEEKDAYS[self.word(i + 1)], i + 2)
        if word in WEEKDAYS:
            return self._weekday(i, "", WEEKDAYS[word], i + 1)
        # in three days / in two weeks / in a month
        if word == "in":
            amount = self._count(i + 1)
            if amount is not None:
                value, j = amount
                unit = self.word(j)
                if unit in ("day", "days"):
                    return self._date_tv(
                        self.toks[i : j + 1], [(self.today + timedelta(days=int(value)), 1.0)]
                    ), j + 1
                if unit in ("week", "weeks"):
                    return self._date_tv(
                        self.toks[i : j + 1], [(self.today + timedelta(weeks=int(value)), 1.0)]
                    ), j + 1
        # october 20 / 20 october / the 20th of october
        month_day = self._month_day(i)
        if month_day is not None:
            return month_day
        # the 15th
        if word == "the" or tok.kind == "num":
            return self._day_of_month(i)
        return None

    def _count(self, j: int) -> tuple[Decimal, int] | None:
        tok = self.at(j)
        if tok is not None and tok.kind == "num" and tok.value is not None and _is_int(tok):
            return tok.value, j + 1
        if self.word(j) in ("a", "an"):
            return Decimal(1), j + 1
        return None

    def _weekday(
        self, i: int, qualifier: str, target: int, end: int
    ) -> tuple[TypedValue, int] | None:
        ahead = (target - self.today.weekday()) % 7
        toks = self.toks[i:end]
        if qualifier == "last":
            back = (self.today.weekday() - target) % 7 or 7
            return self._date_tv(toks, [(self.today - timedelta(days=back), 1.0)]), end
        if qualifier == "this":
            return self._date_tv(toks, [(self.today + timedelta(days=ahead), 1.0)]), end
        if qualifier == "next":
            if ahead == 0:
                return self._date_tv(toks, [(self.today + timedelta(days=7), 1.0)]), end
            return self._date_tv(
                toks,
                [
                    (self.today + timedelta(days=ahead), 0.55),
                    (self.today + timedelta(days=ahead + 7), 0.45),
                ],
            ), end
        if ahead == 0:  # "wednesday" said on a Wednesday: today, or a week from today
            return self._date_tv(
                toks, [(self.today, 0.6), (self.today + timedelta(days=7), 0.4)]
            ), end
        return self._date_tv(toks, [(self.today + timedelta(days=ahead), 1.0)]), end

    def _month_day(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        # october 20 (the 20th)
        if tok.kind == "word" and tok.lower in MONTHS:
            day = self._day_number(i + 1)
            if day is not None:
                d, end = day
                tv = self._month_day_tv(self.toks[i:end], MONTHS[tok.lower], d)
                return (tv, end) if tv is not None else None
            return None
        # 20 october / 20th of october / the 20th of october / the third of november
        start = i
        if tok.lower == "the":
            start = i + 1
        day = self._day_number(start)
        if day is not None:
            d, end = day
            if self.word(end) == "of":
                end += 1
            if self.word(end) in MONTHS:
                tv = self._month_day_tv(self.toks[i : end + 1], MONTHS[self.word(end)], d)
                return (tv, end + 1) if tv is not None else None
        return None

    def _day_number(self, j: int) -> tuple[int, int] | None:
        tok = self.at(j)
        if tok is None:
            return None
        if tok.kind == "num" and tok.value is not None and _is_int(tok) and 1 <= tok.value <= 31:
            end = j + 1
            if self.word(end) in ("st", "nd", "rd", "th"):
                end += 1
            return int(tok.value), end
        if tok.kind == "word" and tok.lower in ORDINALS:
            return ORDINALS[tok.lower], j + 1
        return None

    def _month_day_tv(self, toks: list[Tok], month: int, day: int) -> TypedValue | None:
        try:
            this_year = date(self.today.year, month, day)
        except ValueError:
            return None
        readings: list[tuple[date, float]]
        if this_year >= self.today:
            readings = [(this_year, 1.0)]
        else:
            readings = [(this_year, 0.6), (date(self.today.year + 1, month, day), 0.4)]
        return self._date_tv(toks, readings)

    def _day_of_month(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        start = i + 1 if tok.lower == "the" else i
        day = self._day_number(start)
        if day is None:
            return None
        d, end = day
        # only the digit forms ("the 15th"): "the first thing" and "the second" are not dates
        suffixed = self.word(end - 1) in ("st", "nd", "rd", "th")
        if not suffixed:
            return None
        this_month = self._safe_date(self.today.year, self.today.month, d)
        if this_month is None:
            return None
        if this_month >= self.today:
            readings = [(this_month, 1.0)]
        else:
            year, month = (
                (self.today.year + 1, 1)
                if self.today.month == 12
                else (self.today.year, self.today.month + 1)
            )
            following = self._safe_date(year, month, d)
            readings = [(this_month, 0.6)] + ([(following, 0.4)] if following else [])
        return self._date_tv(self.toks[i:end], readings), end

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> date | None:
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _date_tv(self, toks: list[Tok], readings: list[tuple[date, float]]) -> TypedValue:
        return TypedValue(
            "date",
            _phrase(self.text, toks),
            _readings(
                [
                    (d.isoformat(), d.isoformat(), {"date": d.isoformat()}, score)
                    for d, score in readings
                ]
            ),
        )

    # ---- plain number

    def number(self, i: int) -> tuple[TypedValue, int] | None:
        tok = self.toks[i]
        if tok.kind != "num" or tok.value is None:
            return None
        if tok.text.lower() == "one" and (
            self.word(i - 1) in _NOT_A_COUNT_BEFORE_ONE or self.word(i - 1) in ORDINALS
        ):
            return None  # "which one", "the second one": a pronoun, not the number 1
        if tok.text.lower() == "one" and self.word(i + 1) in DURATION_UNITS:
            return None  # "one sec" / "one minute": a figure of speech the duration rule declined
        text = _number_text(tok.value)
        return TypedValue(
            "number", _phrase(self.text, [tok]), _readings([(text, text, {"number": text}, 1.0)])
        ), i + 1


def _combine(date_tv: TypedValue, time_tv: TypedValue, now: datetime) -> TypedValue:
    combos: list[Reading] = []
    for d in date_tv.readings:
        for t in time_tv.readings:
            moment = datetime.combine(
                date.fromisoformat(d.value["date"]),
                time.fromisoformat(t.value["time"]),
                tzinfo=now.tzinfo,
            )
            iso = moment.isoformat()
            combos.append(Reading(iso, iso, {"datetime": iso}, round(d.score * t.score, 4)))
    combos.sort(key=lambda r: -r.score)
    return TypedValue(
        "datetime", f"{date_tv.phrase} {time_tv.phrase}", tuple(combos[:MAX_CANDIDATES])
    )


def normalize(transcript: str, *, now: datetime, language: str = "en") -> Normalized:
    """Typed values found in `transcript`, relative to the aware datetime `now`."""
    if now.tzinfo is None:
        raise ValueError("normalize needs a timezone-aware 'now' (the device clock and zone)")
    text = _prepare(transcript)
    cleaned, removed = clean_fillers(text)
    toks = tokenize(cleaned)
    scanner = _Scanner(cleaned, toks, now)
    found: list[TypedValue] = []
    i = 0
    recognizers = (
        scanner.money,
        scanner.bare_pair,
        scanner.percent,
        scanner.duration,
        scanner.time_of_day,
        scanner.date_value,
        scanner.number,
    )
    while i < len(toks):
        for recognize in recognizers:
            hit = recognize(i)
            if hit is not None:
                typed, after = hit
                found.append(typed)
                i = max(after, i + 1)
                break
        else:
            i += 1
    # "tomorrow at 7": a date directly followed by a time is one datetime
    merged: list[TypedValue] = []
    skip = False
    for index, value in enumerate(found):
        if skip:
            skip = False
            continue
        nxt = found[index + 1] if index + 1 < len(found) else None
        if (
            value.kind == "date"
            and nxt is not None
            and nxt.kind == "time"
            and _adjacent(cleaned, value, nxt)
        ):
            merged.append(_combine(value, nxt, now))
            skip = True
        else:
            merged.append(value)
    return Normalized(transcript, cleaned, removed, tuple(merged), language)


def _adjacent(text: str, first: TypedValue, second: TypedValue) -> bool:
    a = text.lower().find(first.phrase.lower())
    b = text.lower().find(second.phrase.lower(), a + len(first.phrase)) if a >= 0 else -1
    if a < 0 or b < 0:
        return False
    between = text[a + len(first.phrase) : b].strip().lower()
    return between in ("", "at", "around", "by", "@")


# ------------------------------------------------------------------------------ NluFrame


def to_frame(
    normalized: Normalized,
    *,
    turn_id: str,
    turn_epoch: int,
    intent: str = UNROUTED_INTENT,
    source: str = "rule",
    rule_id: str = "normalizer",
) -> dict[str, Any]:
    """An NluFrame (contracts/nlu-frame.schema.json) carrying the typed values as slots.

    The intent is a placeholder until a rule or the planner sets one (S09). Ambiguous values become
    `ambiguous` slots with their readings as candidates; the resolution stage asks about them.
    """
    slots: list[dict[str, Any]] = []
    for value in normalized.values:
        slot: dict[str, Any] = {
            "name": value.kind,
            "phrase": value.phrase,
            "resolution": "typed_value",
        }
        if value.ambiguous:
            slot["status"] = "ambiguous"
            slot["value"] = {"readings": [r.value for r in value.readings]}
            slot["candidates"] = [
                {"id": r.id, "label": r.label, "score": r.score}
                for r in value.readings[:MAX_CANDIDATES]
            ]
        else:
            slot["status"] = "resolved"
            slot["value"] = value.value
        slots.append(slot)
    return {
        "schema_version": "2.0",
        "turn_id": turn_id,
        "turn_epoch": turn_epoch,
        "transcript": normalized.transcript[:4000],
        "language": normalized.language,
        "source": source,
        "rule_id": rule_id,
        "intent": intent,
        "slots": slots,
        "unresolved_terms": [],
        "references": [],
    }


__all__ = ["Normalized", "Reading", "TypedValue", "normalize", "to_frame", "clean_fillers", "UNITS"]
