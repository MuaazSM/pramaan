"""Narrative draft validator tests (docs/03-AI-TIMELINE.md §8.3.2/§9,
CLAUDE.md rule 6). Table-driven: every sentence shape the validator must
reject, and the sentences that must be accepted unchanged.
"""

from __future__ import annotations

import pytest
from pramaan_llm.validator import DraftSentence, ReportFact, validate_sentence, validate_sentences

FACTS = [
    ReportFact(id="fact_1", text="Recording gap on CH2 from 20:00 to 09:00."),
    ReportFact(id="fact_2", text="37 seconds of OSD drift measured on CH2."),
]
FACTS_BY_ID = {f.id: f for f in FACTS}


@pytest.mark.parametrize(
    "sentence,expect_reason_substring",
    [
        (DraftSentence(text="Something happened.", evidence_ids=[]), "no evidence ids"),
        (
            DraftSentence(text="Something happened.", evidence_ids=["fact_999"]),
            "unknown evidence id",
        ),
        (
            DraftSentence(
                text="There was a 45 second gap on CH2.", evidence_ids=["fact_1"]
            ),
            "not present in the cited fact",
        ),
        (
            DraftSentence(
                text="There is a gap on CH2 and 12 people were seen.",
                evidence_ids=["fact_1"],
            ),
            "not present in the cited fact",
        ),
    ],
)
def test_rejects_bad_sentences(sentence: DraftSentence, expect_reason_substring: str) -> None:
    reasons = validate_sentence(sentence, FACTS_BY_ID)
    assert reasons, "expected at least one rejection reason"
    assert any(expect_reason_substring in r for r in reasons)


@pytest.mark.parametrize(
    "sentence",
    [
        DraftSentence(
            text="There is a recording gap on CH2 from 20:00 to 09:00.",
            evidence_ids=["fact_1"],
        ),
        DraftSentence(
            text="CH2 shows 37 seconds of OSD drift.", evidence_ids=["fact_2"]
        ),
        # Cites two facts; every number must come from *some* cited fact.
        DraftSentence(
            text="CH2 has a gap from 20:00 to 09:00 and 37 seconds of OSD drift.",
            evidence_ids=["fact_1", "fact_2"],
        ),
    ],
)
def test_accepts_well_formed_sentences(sentence: DraftSentence) -> None:
    assert validate_sentence(sentence, FACTS_BY_ID) == []


def test_partial_unknown_ids_are_still_rejected_even_with_one_known_id() -> None:
    sentence = DraftSentence(
        text="Recording gap on CH2 from 20:00 to 09:00.",
        evidence_ids=["fact_1", "fact_unknown"],
    )
    reasons = validate_sentence(sentence, FACTS_BY_ID)
    assert any("unknown evidence id" in r for r in reasons)


def test_validate_sentences_splits_accepted_and_rejected() -> None:
    sentences = [
        DraftSentence(
            text="There is a recording gap on CH2 from 20:00 to 09:00.",
            evidence_ids=["fact_1"],
        ),
        DraftSentence(text="Someone deleted the footage on purpose.", evidence_ids=[]),
    ]
    result = validate_sentences(sentences, FACTS)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].sentence.text == "Someone deleted the footage on purpose."


def test_numbers_with_comma_grouping_are_recognised() -> None:
    fact = ReportFact(id="fact_3", text="1,234 frames were recovered on CH2.")
    sentence = DraftSentence(text="1234 frames were recovered.", evidence_ids=["fact_3"])
    assert validate_sentence(sentence, {"fact_3": fact}) == []


def test_no_numbers_in_either_sentence_or_fact_is_fine() -> None:
    fact = ReportFact(id="fact_4", text="The device log records a format event.")
    sentence = DraftSentence(text="A format event appears in the device log.", evidence_ids=["fact_4"])
    assert validate_sentence(sentence, {"fact_4": fact}) == []
