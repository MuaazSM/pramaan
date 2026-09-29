"""Model IDs, pricing table and budget caps (docs/03-AI-TIMELINE.md §8.1/§8.2,
docs/PRD.md §7).

Model choice (recorded per task A3's instructions — docs/03-AI-TIMELINE.md
§8.1 and docs/PRD.md §7 name ``claude-haiku-4-5-20251001`` /
``claude-sonnet-5-5``; the task brief says to prefer current model IDs when
the doc names an older one, so this module pins ``claude-sonnet-5`` for
drafting instead of the ``-5-5`` id, and keeps the dated Haiku snapshot for
the cheap path — a dated snapshot id is also the more deterministic choice,
CLAUDE.md rule 5). All prices are USD per 1M tokens, from the Anthropic
pricing page at the time of writing; update here if prices change — nothing
else in this package hard-codes a price.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Cheap path — natural-language case query (tool-use only, no long output).
MODEL_CHEAP = "claude-haiku-4-5-20251001"

#: Drafting path — report narrative drafting and the inference explainer.
MODEL_DRAFT = "claude-sonnet-5"


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


#: USD per 1,000,000 tokens. Keyed by exact model id string.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    MODEL_CHEAP: ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00, cache_read_per_mtok=0.10),
    MODEL_DRAFT: ModelPrice(input_per_mtok=2.00, output_per_mtok=10.00, cache_read_per_mtok=0.20),
}

#: docs/03-AI-TIMELINE.md §8.2 hard caps — ``llm.budget_usd_total`` / ``llm.budget_usd_per_case``.
DEFAULT_BUDGET_USD_TOTAL = 60.0
DEFAULT_BUDGET_USD_PER_CASE = 5.0

#: Payload guard defaults (docs/03-AI-TIMELINE.md §8.2).
GUARD_MAX_STRING_LEN = 256
GUARD_MAX_PAYLOAD_BYTES = 32_768
