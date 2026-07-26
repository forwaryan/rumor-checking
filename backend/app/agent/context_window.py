"""Context window management — token estimation and dynamic truncation.

Provides utilities to estimate token counts for Chinese/English mixed text and
dynamically truncate prompts to stay within model context limits. This prevents
prompt overflow when evidence pools are large.

Token estimation uses a hybrid heuristic: Chinese characters ≈ 1.5 tokens each,
ASCII words ≈ 1.3 tokens each (accounts for subword tokenization). This is a
conservative estimate that works for the OpenAI-compatible tokenizer family.
"""
from __future__ import annotations

import re
from typing import Any

# Heuristic ratios for token estimation without loading a tokenizer.
# Conservative: slightly overestimates to avoid overflow.
_CHINESE_CHAR_TOKENS = 1.5
_ASCII_WORD_TOKENS = 1.3
_JSON_OVERHEAD_TOKENS = 1.2  # JSON structure (braces, quotes, colons) adds ~20%

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
_ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def estimate_tokens(text: str) -> int:
    """Estimate token count for mixed Chinese/English text.

    Returns a conservative upper bound (never underestimates).
    """
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    ascii_words = len(_ASCII_WORD_RE.findall(text))
    # Remaining characters (punctuation, whitespace, symbols)
    other_chars = len(text) - cjk_chars - sum(len(m.group()) for m in _ASCII_WORD_RE.finditer(text))
    return int(
        cjk_chars * _CHINESE_CHAR_TOKENS
        + ascii_words * _ASCII_WORD_TOKENS
        + other_chars * 0.5
    )


def estimate_json_tokens(obj: Any) -> int:
    """Estimate tokens for a JSON-serializable object (dict/list/str)."""
    import json
    text = json.dumps(obj, ensure_ascii=False)
    return int(estimate_tokens(text) * _JSON_OVERHEAD_TOKENS)


def truncate_to_budget(
    items: list[dict],
    *,
    budget_tokens: int,
    key: str = "snippet",
    min_items: int = 2,
    max_chars_per_item: int = 200,
) -> list[dict]:
    """Truncate a list of evidence items to fit within a token budget.

    Strategy:
    1. Include at least min_items (even if over budget).
    2. For each additional item, check if adding it exceeds the budget.
    3. Within included items, truncate the `key` field if needed.

    Returns a new list (does not mutate the input).
    """
    if not items:
        return []
    if budget_tokens <= 0:
        return items[:min_items]

    result: list[dict] = []
    running_tokens = 0

    for i, item in enumerate(items):
        item_copy = dict(item)
        # Truncate the text field within each item
        text = item_copy.get(key, "")
        if isinstance(text, str) and len(text) > max_chars_per_item:
            item_copy[key] = text[:max_chars_per_item].rstrip() + "…"

        item_tokens = estimate_json_tokens(item_copy)

        if i < min_items:
            result.append(item_copy)
            running_tokens += item_tokens
        elif running_tokens + item_tokens <= budget_tokens:
            result.append(item_copy)
            running_tokens += item_tokens
        else:
            break

    return result


class ContextBudget:
    """Manages token allocation across prompt sections.

    Allocates a fixed model context into sections (system, evidence, user prompt)
    and provides guardrails to prevent any section from overflowing.
    """

    def __init__(self, max_context_tokens: int, *, reserved_output_tokens: int = 4096):
        self.max_context_tokens = max_context_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self._sections: dict[str, int] = {}

    @property
    def available_input_tokens(self) -> int:
        return self.max_context_tokens - self.reserved_output_tokens

    @property
    def used_tokens(self) -> int:
        return sum(self._sections.values())

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.available_input_tokens - self.used_tokens)

    def allocate(self, section: str, tokens: int) -> None:
        self._sections[section] = tokens

    def can_fit(self, tokens: int) -> bool:
        return self.remaining_tokens >= tokens

    def section_budget(self, section: str, default_fraction: float = 0.5) -> int:
        """How many tokens a section can use, given what's already allocated."""
        already = self._sections.get(section, 0)
        if already > 0:
            return already
        return int(self.remaining_tokens * default_fraction)


# Default context sizes for common model families.
# The runner picks based on settings.is_reasoning_model().
MODEL_CONTEXT_SIZES = {
    "fast": 32_000,
    "reasoning": 64_000,
}


def build_evidence_budget(
    *,
    system_prompt_tokens: int,
    max_context: int = 32_000,
    output_tokens: int = 4096,
    user_prompt_overhead: int = 500,
) -> int:
    """Calculate how many tokens are available for evidence in a synthesis prompt.

    evidence_budget = max_context - output - system - overhead
    """
    return max(
        2000,
        max_context - output_tokens - system_prompt_tokens - user_prompt_overhead,
    )
