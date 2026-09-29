"""Versioned system prompts (docs/03-AI-TIMELINE.md §8.4).

Each ``*.md`` file in this directory is one system prompt, with a leading
HTML-comment header (``<!-- purpose: ... model: ... -->``) that is stripped
before the text is sent to the model — the header is documentation for
humans reading the file, not an instruction for Claude.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

_HEADER_COMMENT_RE = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


@cache
def load_prompt(name: str) -> str:
    """Load and cache a prompt by filename (e.g. ``"system_query.md"``),
    stripping its leading documentation comment."""
    text = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    return _HEADER_COMMENT_RE.sub("", text, count=1).strip()
