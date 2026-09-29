"""Budget meter: caps, ``llm_calls`` rows and audit entries
(docs/03-AI-TIMELINE.md §8.2, CLAUDE.md rules 4/5/6).

Every call to a provider is metered through :class:`BudgetMeter`:

1. **Pre-flight** (:meth:`BudgetMeter.check`): a conservative cost estimate
   is checked against the per-case and total USD caps *before* the (costly)
   provider call is made. A call that would exceed either cap never runs —
   it raises :class:`BudgetExceededError`, which the API layer turns into a
   typed error response the UI can show.
2. **Recording** (:meth:`BudgetMeter.record`): after the call, the *actual*
   token usage is priced and written as one row in the ``llm_calls`` table
   (schema: ``packages/core/pramaan_core/schema.sql``) plus one hash-chained
   ``audit_log`` entry (same chaining scheme as
   ``apps/api/pramaan_api/fixtures/store.verify_chain`` — content hash of an
   ``entry_hash``/``prev_hash`` pair). No wall-clock value is hashed; the
   caller supplies ``now_utc`` so tests stay deterministic (CLAUDE.md rule 5).

The signature field on the audit entry is a placeholder (``"unsigned:..."``,
clearly labelled), exactly like the fixture dataset's audit entries
(docs/progress/W0.3.md) — real Ed25519 signing belongs to ``packages/custody``
and is out of this task's scope.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Literal

from pramaan_core.ids import content_hash, content_id

from pramaan_llm.config import DEFAULT_BUDGET_USD_PER_CASE, DEFAULT_BUDGET_USD_TOTAL, ModelPrice
from pramaan_llm.config import DEFAULT_PRICES as _DEFAULT_PRICES


@dataclass
class BudgetExceededError(Exception):
    """Raised by :meth:`BudgetMeter.check` when a call would exceed a cap."""

    scope: Literal["case", "total"]
    case_id: str
    spent_usd: float
    estimated_usd: float
    cap_usd: float

    def __str__(self) -> str:
        return (
            f"LLM budget exceeded ({self.scope}): spent ${self.spent_usd:.4f} + "
            f"estimated ${self.estimated_usd:.4f} > cap ${self.cap_usd:.4f} "
            f"(case={self.case_id})"
        )


def estimate_tokens(text: str) -> int:
    """A crude, deterministic, offline token estimate (~4 chars/token).

    Used only for the *pre-flight* cap check, never for pricing an actual
    call (that always uses the provider's real ``usage`` counts) — see
    ``docs/progress/A3.md`` "Decisions" for why this doesn't call the live
    ``count_tokens`` endpoint (it would require network access, which the
    guard/budget path must work without).
    """
    return max(1, len(text) // 4)


def estimate_cost_usd(
    *,
    model: str,
    system: str,
    messages: list[dict[str, object]],
    max_tokens: int,
    prices: dict[str, ModelPrice] | None = None,
) -> float:
    """Conservative pre-flight cost estimate: real input size, worst-case
    (``max_tokens``) output size, no cache-read discount assumed."""
    price = (prices or _DEFAULT_PRICES).get(model)
    if price is None:
        # Unknown model: assume the most expensive known price so an
        # unrecognised model id can never silently bypass the cap.
        price = max((prices or _DEFAULT_PRICES).values(), key=lambda p: p.input_per_mtok)
    text = system + "".join(str(m.get("content", "")) for m in messages)
    input_tokens = estimate_tokens(text)
    return (input_tokens * price.input_per_mtok + max_tokens * price.output_per_mtok) / 1_000_000


def actual_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    prices: dict[str, ModelPrice] | None = None,
) -> float:
    price = (prices or _DEFAULT_PRICES).get(model)
    if price is None:
        price = max((prices or _DEFAULT_PRICES).values(), key=lambda p: p.input_per_mtok)
    billed_input = max(0, input_tokens - cache_read_input_tokens)
    cost = billed_input * price.input_per_mtok
    cost += cache_read_input_tokens * price.cache_read_per_mtok
    cost += output_tokens * price.output_per_mtok
    return cost / 1_000_000


@dataclass(frozen=True)
class LlmCallRecord:
    id: str
    case_id: str
    feature: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    request_sha256: str
    response_sha256: str
    accepted: bool | None
    created_utc: str


class BudgetMeter:
    """Wraps one ``sqlite3.Connection`` open on a case DB (schema.sql
    applied — see ``pramaan_core.db.open_case``)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        cap_total_usd: float = DEFAULT_BUDGET_USD_TOTAL,
        cap_case_usd: float = DEFAULT_BUDGET_USD_PER_CASE,
        prices: dict[str, ModelPrice] | None = None,
    ) -> None:
        self._conn = conn
        self.cap_total_usd = cap_total_usd
        self.cap_case_usd = cap_case_usd
        self.prices = prices or _DEFAULT_PRICES

    def spent_total_usd(self) -> float:
        row = self._conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls").fetchone()
        return float(row[0])

    def spent_case_usd(self, case_id: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE case_id = ?", (case_id,)
        ).fetchone()
        return float(row[0])

    def check(self, case_id: str, estimated_usd: float) -> None:
        """Raise :class:`BudgetExceededError` if spending ``estimated_usd``
        more would exceed either cap. Checked *before* any provider call."""
        spent_total = self.spent_total_usd()
        if spent_total + estimated_usd > self.cap_total_usd:
            raise BudgetExceededError(
                "total", case_id, spent_total, estimated_usd, self.cap_total_usd
            )
        spent_case = self.spent_case_usd(case_id)
        if spent_case + estimated_usd > self.cap_case_usd:
            raise BudgetExceededError(
                "case", case_id, spent_case, estimated_usd, self.cap_case_usd
            )

    def record(
        self,
        *,
        case_id: str,
        feature: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int,
        request_sha256: str,
        response_sha256: str,
        actor: str,
        now_utc: str,
        accepted: bool | None = None,
    ) -> LlmCallRecord:
        """Insert one ``llm_calls`` row and one chained ``audit_log`` entry,
        in the same transaction."""
        cost_usd = actual_cost_usd(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            prices=self.prices,
        )
        call_id = content_id(
            "llmcall",
            {
                "case_id": case_id,
                "feature": feature,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
                "now_utc": now_utc,
            },
        )
        record = LlmCallRecord(
            id=call_id,
            case_id=case_id,
            feature=feature,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
            accepted=accepted,
            created_utc=now_utc,
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO llm_calls (
                    id, case_id, feature, provider, model, input_tokens,
                    output_tokens, cost_usd, request_sha256, response_sha256,
                    accepted, created_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.case_id,
                    record.feature,
                    record.provider,
                    record.model,
                    record.input_tokens,
                    record.output_tokens,
                    record.cost_usd,
                    record.request_sha256,
                    record.response_sha256,
                    None if record.accepted is None else int(record.accepted),
                    record.created_utc,
                ),
            )
            self._append_audit_entry(record, actor=actor)
        return record

    def _append_audit_entry(self, record: LlmCallRecord, *, actor: str) -> None:
        row = self._conn.execute(
            "SELECT entry_hash, seq FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash: str | None
        next_seq: int
        if row is None:
            prev_hash, next_seq = None, 1
        else:
            prev_hash, next_seq = row[0], row[1] + 1
        details = {
            "model": record.model,
            "provider": record.provider,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cost_usd": record.cost_usd,
        }
        unsigned = {
            "seq": next_seq,
            "prev_hash": prev_hash,
            "ts_utc": record.created_utc,
            "actor": actor,
            "role": "assistant",
            "action": "llm_call",
            "object_type": "llm_call",
            "object_id": record.id,
            "payload_sha256": record.request_sha256,
            "details": details,
        }
        entry_hash = content_hash(unsigned)

        self._conn.execute(
            """
            INSERT INTO audit_log (
                id, seq, prev_hash, entry_hash, ts_utc, actor, role, action,
                object_type, object_id, payload_sha256, details, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_hash,
                next_seq,
                prev_hash,
                entry_hash,
                record.created_utc,
                actor,
                "assistant",
                "llm_call",
                "llm_call",
                record.id,
                record.request_sha256,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
                # placeholder — real Ed25519 signing is packages/custody's job
                f"unsigned:{entry_hash[:16]}",
            ),
        )
