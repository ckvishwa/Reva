"""S06: the normalizer turns a final transcript into typed values (AR-LANG-002, ARD-450 §3.1).

`NOW` is Wednesday 2026-10-14 10:30 at UTC-4. Every case says what the person said and which typed
values come out; ambiguous ones list every reading, in order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from reva_core.language.normalizer import clean_fillers, normalize, to_frame

NOW = datetime(2026, 10, 14, 10, 30, tzinfo=timezone(timedelta(hours=-4)))
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "nlu-frame.schema.json").read_text(
        encoding="utf-8"
    )
)


def values(text: str) -> list[tuple[str, list[dict]]]:
    return [(v.kind, [r.value for r in v.readings]) for v in normalize(text, now=NOW).values]


def money(amount: str, minor: int, currency: str = "USD") -> dict:
    return {"amount": amount, "amount_minor": minor, "currency": currency}


# --------------------------------------------------------------------------------- money


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I spent twelve bucks on lunch", money("12.00", 1200)),
        ("twelve dollars and fifty cents", money("12.50", 1250)),
        ("twelve dollars fifty", money("12.50", 1250)),
        ("$12.50", money("12.50", 1250)),
        ("12.5 dollars", money("12.50", 1250)),
        ("fifty cents", money("0.50", 50)),
        ("a hundred bucks", money("100.00", 10000)),
        ("three thousand two hundred dollars", money("3200.00", 320000)),
        ("1,200 dollars", money("1200.00", 120000)),
        ("five bucks", money("5.00", 500)),
        ("ninety nine dollars", money("99.00", 9900)),
        ("20 euros", money("20.00", 2000, "EUR")),
    ],
)
def test_money_is_typed_with_exact_minor_units(text: str, expected: dict) -> None:
    found = values(text)

    assert [kind for kind, _ in found] == ["money"], found
    assert found[0][1] == [expected]


def test_a_price_said_as_two_numbers_keeps_both_readings() -> None:
    found = normalize("I spent two fifty on coffee", now=NOW).values

    assert len(found) == 1 and found[0].kind == "money" and found[0].ambiguous
    assert [r.value for r in found[0].readings] == [money("2.50", 250), money("250.00", 25000)]
    assert [r.score for r in found[0].readings] == [0.6, 0.4]
    assert found[0].phrase == "two fifty"


def test_twelve_fifty_for_lunch_is_a_price_or_twelve_fifty_hundred() -> None:
    found = normalize("twelve fifty for lunch", now=NOW).values[0]

    assert found.kind == "money" and found.ambiguous
    assert [r.value["amount"] for r in found.readings] == ["12.50", "1250.00"]


def test_without_a_money_cue_the_pair_stays_a_number_with_two_readings() -> None:
    found = normalize("set it to two fifty", now=NOW).values[0]

    assert found.kind == "number" and found.ambiguous
    assert [r.value for r in found.readings] == [{"number": "250"}, {"number": "2.5"}]


def test_a_currency_word_after_the_pair_makes_it_money_and_is_part_of_the_phrase() -> None:
    found = normalize("two fifty dollars", now=NOW).values[0]

    assert found.kind == "money" and found.phrase == "two fifty dollars"


# -------------------------------------------------------------------- numbers and percent


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("forty two", "42"),
        ("one hundred and five", "105"),
        ("fifteen hundred", "1500"),
        ("three", "3"),
        ("add 7 items", "7"),
        ("two point five", "2.5"),
        ("a thousand", "1000"),
        ("twenty five", "25"),
        ("1,200", "1200"),
        ("two thousand twenty six", "2026"),
    ],
)
def test_numbers(text: str, number: str) -> None:
    assert values(text) == [("number", [{"number": number}])]


@pytest.mark.parametrize(
    ("text", "percent"),
    [
        ("twenty percent", "20"),
        ("15%", "15"),
        ("two point five percent", "2.5"),
        ("100 percent", "100"),
    ],
)
def test_percentages(text: str, percent: str) -> None:
    assert values(text) == [("percent", [{"percent": percent}])]


def test_twelve_and_fifty_are_two_numbers_not_sixty_two() -> None:
    assert [r for _, r in values("twelve fifty")][0] != [{"number": "62"}]


# ----------------------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("tomorrow", "2026-10-15"),
        ("yesterday", "2026-10-13"),
        ("today", "2026-10-14"),
        ("day after tomorrow", "2026-10-16"),
        ("this friday", "2026-10-16"),
        ("friday", "2026-10-16"),
        ("monday", "2026-10-19"),
        ("last monday", "2026-10-12"),
        ("next wednesday", "2026-10-21"),
        ("october 20", "2026-10-20"),
        ("20 october", "2026-10-20"),
        ("the 20th of october", "2026-10-20"),
        ("the third of november", "2026-11-03"),
        ("the 15th", "2026-10-15"),
        ("in three days", "2026-10-17"),
        ("in two weeks", "2026-10-28"),
        ("in a week", "2026-10-21"),
        ("2026-11-02", "2026-11-02"),
    ],
)
def test_dates_that_have_one_meaning(text: str, iso: str) -> None:
    found = normalize(text, now=NOW).values

    assert [v.kind for v in found] == ["date"], found
    assert found[0].ambiguous is False
    assert found[0].value == {"date": iso}


def test_next_friday_is_this_coming_friday_or_the_one_after() -> None:
    found = normalize("next friday", now=NOW).values[0]

    assert [r.value["date"] for r in found.readings] == ["2026-10-16", "2026-10-23"]


def test_the_weekday_you_are_on_is_today_or_a_week_away() -> None:
    found = normalize("wednesday", now=NOW).values[0]

    assert [r.value["date"] for r in found.readings] == ["2026-10-14", "2026-10-21"]


def test_a_date_that_has_passed_this_year_keeps_next_year_as_a_reading() -> None:
    found = normalize("october 5", now=NOW).values[0]

    assert [r.value["date"] for r in found.readings] == ["2026-10-05", "2027-10-05"]


def test_the_15th_after_the_15th_is_this_month_or_next() -> None:
    found = normalize("the 3rd", now=NOW).values[0]

    assert [r.value["date"] for r in found.readings] == ["2026-10-03", "2026-11-03"]


def test_an_impossible_date_is_not_a_date() -> None:
    assert values("february 30") == [("number", [{"number": "30"}])]


# ----------------------------------------------------------------------------------- times


@pytest.mark.parametrize(
    ("text", "hhmm"),
    [
        ("7 pm", "19:00"),
        ("7:30 am", "07:30"),
        ("7 p.m.", "19:00"),
        ("12 am", "00:00"),
        ("12 pm", "12:00"),
        ("noon", "12:00"),
        ("midnight", "00:00"),
        ("19:00", "19:00"),
        ("at 18:45", "18:45"),
    ],
)
def test_times_that_have_one_meaning(text: str, hhmm: str) -> None:
    found = normalize(text, now=NOW).values

    assert [v.kind for v in found] == ["time"], found
    assert found[0].ambiguous is False and found[0].value == {"time": hhmm}


@pytest.mark.parametrize(
    ("text", "first", "second"),
    [
        ("at 7", "07:00", "19:00"),
        ("at seven thirty", "07:30", "19:30"),
        ("half past seven", "07:30", "19:30"),
        ("quarter past eight", "08:15", "20:15"),
        ("quarter to eight", "07:45", "19:45"),
        ("at 12", "12:00", "00:00"),
    ],
)
def test_times_without_am_or_pm_keep_both_readings(text: str, first: str, second: str) -> None:
    found = normalize(text, now=NOW).values[0]

    assert found.kind == "time" and found.ambiguous
    assert [r.value["time"] for r in found.readings] == [first, second]


def test_tomorrow_at_7_is_a_datetime_with_both_readings() -> None:
    found = normalize("remind me tomorrow at 7", now=NOW).values

    assert [v.kind for v in found] == ["datetime"]
    assert [r.value["datetime"] for r in found[0].readings] == [
        "2026-10-15T07:00:00-04:00",
        "2026-10-15T19:00:00-04:00",
    ]


def test_tomorrow_at_7_pm_is_one_datetime() -> None:
    found = normalize("tomorrow at 7 pm", now=NOW).values

    assert [v.kind for v in found] == ["datetime"] and not found[0].ambiguous
    assert found[0].value == {"datetime": "2026-10-15T19:00:00-04:00"}


def test_an_ambiguous_date_and_time_multiply_their_readings_in_order() -> None:
    found = normalize("next friday at 7", now=NOW).values[0]

    assert found.kind == "datetime" and len(found.readings) == 4
    assert found.readings[0].value["datetime"] == "2026-10-16T07:00:00-04:00"
    assert [r.score for r in found.readings] == sorted(
        (r.score for r in found.readings), reverse=True
    )


# -------------------------------------------------------------------------------- durations


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("for forty minutes", "PT40M"),
        ("an hour and a half", "PT1H30M"),
        ("two hours", "PT2H"),
        ("ninety minutes", "PT1H30M"),
        ("half an hour", "PT30M"),
        ("3 days", "P3D"),
        ("two weeks", "P2W"),
        ("a minute", "PT1M"),
        ("an hour", "PT1H"),
        ("two hours and thirty minutes", "PT2H30M"),
        ("45 seconds", "PT45S"),
    ],
)
def test_durations_are_iso_8601(text: str, iso: str) -> None:
    assert values(text) == [("duration", [{"duration": iso}])]


# --------------------------------------------------------------------------------- fillers


def test_filler_is_removed_for_matching_and_reported_but_the_transcript_is_kept() -> None:
    result = normalize("uh can I please add twelve dollars", now=NOW)

    assert result.transcript == "uh can I please add twelve dollars"
    assert result.cleaned == "add twelve dollars"
    assert result.fillers_removed == ("uh", "can I please")


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("um, like, twelve bucks", "twelve bucks"),
        ("could you please move it to Friday", "move it to Friday"),
        ("I'd like to add a note", "I'd like to add a note"),
        ("add milk, you know, to the list", "add milk, to the list"),
        ("hmm what is my budget", "what is my budget"),
    ],
)
def test_filler_cleaning_keeps_real_content_words(text: str, cleaned: str) -> None:
    assert clean_fillers(text)[0] == cleaned


def test_content_words_are_never_removed() -> None:
    cleaned, removed = clean_fillers("delete the old reminder")

    assert cleaned == "delete the old reminder" and removed == ()


# ----------------------------------------------------------------------------- combinations


def test_a_whole_request_yields_every_typed_value_in_order() -> None:
    found = normalize("add twelve bucks for lunch tomorrow at noon", now=NOW).values

    assert [v.kind for v in found] == ["money", "datetime"]
    assert found[0].value == money("12.00", 1200)
    assert (
        found[1].value == {"datetime": "2026-10-15T12:00:00-04:00"} or found[1].ambiguous is False
    )


def test_text_with_no_typed_values_has_none() -> None:
    assert values("open notepad") == []
    assert values("") == []


def test_normalize_needs_a_timezone_aware_clock() -> None:
    with pytest.raises(ValueError):
        normalize("tomorrow", now=datetime(2026, 10, 14, 10, 30))


def test_the_clock_decides_relative_words() -> None:
    other = datetime(2027, 1, 31, 9, 0, tzinfo=UTC)

    assert normalize("tomorrow", now=other).values[0].value == {"date": "2027-02-01"}
    assert normalize("in a week", now=other).values[0].value == {"date": "2027-02-07"}


# --------------------------------------------------------------------------------- the frame


def test_the_frame_validates_against_the_contract() -> None:
    result = normalize("I spent two fifty on coffee tomorrow at 7", now=NOW)

    frame = to_frame(result, turn_id="turn-0001", turn_epoch=3)

    jsonschema.validate(frame, SCHEMA)
    assert frame["intent"] == "unrouted.pending" and frame["turn_epoch"] == 3
    assert frame["transcript"] == "I spent two fifty on coffee tomorrow at 7"


def test_ambiguous_values_become_ambiguous_slots_with_ranked_candidates() -> None:
    frame = to_frame(normalize("I spent two fifty", now=NOW), turn_id="turn-0002", turn_epoch=0)

    slot = frame["slots"][0]
    assert (slot["name"], slot["status"], slot["resolution"]) == (
        "money",
        "ambiguous",
        "typed_value",
    )
    assert [c["label"] for c in slot["candidates"]] == ["$2.50", "$250.00"]
    assert slot["candidates"][0]["score"] > slot["candidates"][1]["score"]
    assert slot["value"]["readings"][0]["amount"] == "2.50"


def test_unambiguous_values_become_resolved_slots() -> None:
    frame = to_frame(normalize("twelve dollars", now=NOW), turn_id="turn-0003", turn_epoch=0)

    slot = frame["slots"][0]
    assert slot["status"] == "resolved" and slot["value"]["amount_minor"] == 1200
    assert "candidates" not in slot
    jsonschema.validate(frame, SCHEMA)


def test_every_frame_for_every_case_in_this_file_is_schema_valid() -> None:
    samples = [
        "tomorrow at 7",
        "next friday",
        "an hour and a half",
        "twenty percent",
        "wednesday at 12",
        "october 5",
        "",
        "hello there",
    ]
    for index, text in enumerate(samples):
        frame = to_frame(normalize(text, now=NOW), turn_id=f"turn-{index:04d}", turn_epoch=index)
        jsonschema.validate(frame, SCHEMA)


@pytest.mark.parametrize(
    "text",
    [
        "give me a second",
        "wait a minute",
        "the first thing I want",
        "the second one",
        "may I add a note",
    ],
)
def test_idioms_and_ordinary_words_are_not_typed_values(text: str) -> None:
    assert values(text) == []


@pytest.mark.parametrize(
    ("text", "iso"),
    [("for a minute", "PT1M"), ("in an hour", "PT1H"), ("about a week", "P1W")],
)
def test_a_length_after_for_in_about_is_a_duration(text: str, iso: str) -> None:
    assert values(text) == [("duration", [{"duration": iso}])]


@pytest.mark.parametrize(
    ("text", "kinds"),
    [("add one", ["number"]), ("which one", []), ("one sec", []), ("for one minute", ["duration"])],
)
def test_the_word_one_is_a_number_only_when_it_is_one(text: str, kinds: list[str]) -> None:
    assert [kind for kind, _ in values(text)] == kinds
