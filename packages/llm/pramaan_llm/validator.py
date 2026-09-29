"""Narrative draft validator (docs/03-AI-TIMELINE.md §8.3.2, CLAUDE.md rule 6:
"the LLM never produces a finding").

The model's job is to phrase facts the deterministic pipeline already
established, each already carrying an evidence id — never to introduce a new
claim. This validator is the enforcement point: every sentence must cite at
least one evidence id that actually exists in the facts the caller supplied,
and every number appearing in a sentence must already appear in the text of
the fact(s) it cites. A sentence that fails either check is rejected, not
"fixed" — silently editing a model's claim would hide exactly the kind of
fabrication this rule exists to catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

#: Matches integers/decimals, optionally comma-grouped (e.g. "1,234", "37.5").
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ReportFact(BaseModel):
    """One fact from the report manifest (docs/03-AI-TIMELINE.md §8.3.2)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class DraftSentence(BaseModel):
    """One sentence the model proposed, as raw model output (unvalidated)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    evidence_ids: list[str]


@dataclass(frozen=True)
class RejectedSentence:
    sentence: DraftSentence
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    accepted: list[DraftSentence]
    rejected: list[RejectedSentence]


def _numbers_in(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER_RE.findall(text)}


def validate_sentence(sentence: DraftSentence, facts_by_id: dict[str, ReportFact]) -> list[str]:
    """Return a list of rejection reasons for ``sentence`` (empty = valid)."""
    reasons: list[str] = []

    if not sentence.evidence_ids:
        reasons.append("cites no evidence ids")
        return reasons  # nothing further to check without a citation

    unknown = [eid for eid in sentence.evidence_ids if eid not in facts_by_id]
    if unknown:
        reasons.append(f"cites unknown evidence id(s): {', '.join(sorted(unknown))}")

    known_ids = [eid for eid in sentence.evidence_ids if eid in facts_by_id]
    cited_text = " ".join(facts_by_id[eid].text for eid in known_ids)
    cited_numbers = _numbers_in(cited_text)
    sentence_numbers = _numbers_in(sentence.text)
    unsupported = sorted(sentence_numbers - cited_numbers)
    if unsupported:
        reasons.append(
            "contains number(s) not present in the cited fact(s): " + ", ".join(unsupported)
        )

    return reasons


def validate_sentences(
    sentences: list[DraftSentence], facts: list[ReportFact]
) -> ValidationResult:
    """Validate every sentence in a draft against the supplied facts.

    Table-driven per docs/03-AI-TIMELINE.md §9: rejects sentences without
    evidence ids, with unknown evidence ids, or with unsupported numbers;
    everything else is accepted.
    """
    facts_by_id = {f.id: f for f in facts}
    accepted: list[DraftSentence] = []
    rejected: list[RejectedSentence] = []
    for sentence in sentences:
        reasons = validate_sentence(sentence, facts_by_id)
        if reasons:
            rejected.append(RejectedSentence(sentence=sentence, reasons=tuple(reasons)))
        else:
            accepted.append(sentence)
    return ValidationResult(accepted=accepted, rejected=rejected)
