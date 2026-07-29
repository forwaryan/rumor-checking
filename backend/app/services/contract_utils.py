from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from backend.app.models.schemas import InternalInputType

SHANGHAI_TZ = timezone(timedelta(hours=8))


def repair_unescaped_inner_quotes(json_text: str) -> str:
    """Escape stray ASCII double-quotes that appear *inside* a JSON string value.

    Some models (e.g. GLM) quote Chinese phrases with raw `"..."` inside a string
    value without escaping them (`"他叫"张三",今年30岁。"`), which closes the string
    early and breaks json.loads. We walk the text tracking string state and decide,
    for each `"` inside a string, whether it is the real closing quote or a stray
    inner one.

    The hard case is a quote followed by a comma: `"张三",今年` (inner) vs
    `"foo","bar"` (real close). We disambiguate by what follows the comma — a real
    value/key-separator comma is followed by another JSON token (`"`, `{`, `[`, a
    number, or true/false/null), whereas a comma that is part of the prose is
    followed by ordinary text (e.g. a CJK char). Only `:`, `}`, `]`, and a
    "structural" comma close the string; anything else is escaped. Well-formed JSON
    (all inner quotes already escaped) passes through unchanged."""
    out: list[str] = []
    in_string = False
    i = 0
    n = len(json_text)

    def _next_nonspace(idx: int) -> tuple[str, int]:
        while idx < n and json_text[idx] in " \t\r\n":
            idx += 1
        return (json_text[idx] if idx < n else ""), idx

    def _closes_string(quote_idx: int) -> bool:
        following, pos = _next_nonspace(quote_idx + 1)
        if following in (":", "}", "]", ""):
            return True
        if following == ",":
            # A structural comma is followed by the next key/element; a comma that
            # is part of the string's prose is followed by ordinary text. A comma
            # then a closer (`}`/`]`) is a trailing comma after a real closing
            # quote, so that still closes the string.
            after_comma, _ = _next_nonspace(pos + 1)
            return (
                after_comma in ('"', "{", "[", "-", "}", "]", "")
                or after_comma.isdigit()
                or after_comma in ("t", "f", "n")
            )
        return False

    while i < n:
        char = json_text[i]
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue
        if char == "\\":
            # Preserve existing escape sequences verbatim.
            out.append(char)
            if i + 1 < n:
                out.append(json_text[i + 1])
                i += 2
                continue
            i += 1
            continue
        if char == '"':
            if _closes_string(i):
                out.append('"')
                in_string = False
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _recover_truncated_json(text: str) -> Optional[str]:
    """Rebuild a parseable object from JSON that was cut off mid-stream.

    LLM completions on this gateway are frequently truncated part-way through a
    value (e.g. synthesis stops at `..."claims":[{obj},{obj},{obj3_incomplete`).
    We walk the text tracking string state and a stack of open `{`/`[`, and each
    time a nested container closes we record a checkpoint: the prefix up to there,
    plus closers for whatever is still open, is a valid object. Returning the last
    such checkpoint recovers every COMPLETE element before the cut (e.g. the two
    finished claims) and discards the partial tail. Returns None when no nested
    element ever completed."""
    stack: list[str] = []
    in_string = False
    escape = False
    best_cut: Optional[int] = None
    best_stack: list[str] = []
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            # A container just closed. If we're still inside an outer container,
            # this prefix + closers is a candidate recovery (a complete element,
            # like one finished claim object, sits just before here).
            if stack:
                best_cut = i + 1
                best_stack = list(stack)
    if best_cut is None:
        return None
    closers = "".join("}" if opener == "{" else "]" for opener in reversed(best_stack))
    return text[:best_cut] + closers


def repair_structural_defects(json_text: str) -> str:
    """Fix common non-quote JSON defects that models (e.g. GLM) emit.

    Walks the text tracking string state so prose is never touched, and repairs
    only structural (outside-string) defects plus illegal control chars inside
    strings:

    - trailing commas before `}` / `]`  ->  dropped
    - a fullwidth comma `，` used as an element/pair separator (outside a string)
      ->  ASCII `,`  (a `，` *inside* a string is normal Chinese text, kept)
    - a literal newline / tab / carriage return *inside* a string  ->  escaped
      (strict JSON forbids raw control chars in strings)

    Unescaped inner double-quotes are handled separately by
    ``repair_unescaped_inner_quotes``; this function leaves quotes alone."""
    out: list[str] = []
    in_string = False
    i = 0
    n = len(json_text)

    def _next_nonspace_outside(idx: int) -> str:
        while idx < n and json_text[idx] in " \t\r\n":
            idx += 1
        return json_text[idx] if idx < n else ""

    while i < n:
        char = json_text[i]
        if in_string:
            if char == "\\":
                out.append(char)
                if i + 1 < n:
                    out.append(json_text[i + 1])
                    i += 2
                    continue
                i += 1
                continue
            if char == '"':
                out.append(char)
                in_string = False
                i += 1
                continue
            if char == "\n":
                out.append("\\n")
            elif char == "\t":
                out.append("\\t")
            elif char == "\r":
                out.append("\\r")
            else:
                out.append(char)
            i += 1
            continue
        # outside a string
        if char == '"':
            out.append(char)
            in_string = True
            i += 1
            continue
        if char == "，":
            # A fullwidth comma outside any string is a mis-typed separator.
            out.append(",")
            i += 1
            continue
        if char == ",":
            # Drop a trailing comma that is immediately followed by a closer.
            if _next_nonspace_outside(i + 1) in ("}", "]"):
                i += 1
                continue
            out.append(char)
            i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def loads_lenient_json(text: str) -> Optional[dict[str, Any]]:
    """Parse a JSON object from an LLM response, tolerating common defects.

    Tries, in order: the text as-is, a ```json fenced block, the outermost
    {...} slice, and finally each of those with unescaped inner quotes repaired.
    If none parse, a last resort rebuilds a valid object from a mid-stream
    truncation, keeping every complete element before the cut.
    Returns the first dict that parses, or None."""
    stripped = text.strip()
    candidates: list[str] = [stripped]

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fenced_match:
        candidates.insert(0, fenced_match.group(1).strip())

    brace_start = stripped.find("{")
    brace_end = stripped.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        candidates.append(stripped[brace_start : brace_end + 1])

    # Last resort: the completion was cut mid-JSON (no matching close brace), so
    # rebuild a valid object from the complete elements that precede the cut.
    if brace_start != -1:
        recovered = _recover_truncated_json(stripped[brace_start:])
        if recovered is not None:
            candidates.append(recovered)

    for candidate in candidates:
        # Try the candidate as-is, then with each repair, then with both stacked —
        # a single response can carry inner-quote AND structural defects at once.
        attempts = (
            candidate,
            repair_unescaped_inner_quotes(candidate),
            repair_structural_defects(candidate),
            repair_structural_defects(repair_unescaped_inner_quotes(candidate)),
        )
        for attempt in attempts:
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def looks_like_url(value: str) -> bool:
    compact = value.strip()
    return compact.startswith(("http://", "https://"))


def ensure_datetime_string(value: Optional[str]) -> str:
    if value:
        compact = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", compact):
            return f"{compact}T00:00:00+08:00"

        try:
            normalized = compact.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
            return parsed.isoformat()
        except ValueError:
            pass

    return datetime.now(SHANGHAI_TZ).isoformat()


def ensure_datetime_string_or_empty(value: Optional[str]) -> str:
    """Normalize a datetime string, or return "" when the source has none.

    Use this for user-visible SOURCE dates (evidence.published_at,
    TimelineNode.published_at) where fabricating datetime.now() as a
    fallback misleads the reader into thinking every hit was published
    at report-generation time. Contrast with ensure_datetime_string,
    which is fine for retrieval/generation-side timestamps."""
    if not value:
        return ""
    compact = value.strip()
    if not compact:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", compact):
        return f"{compact}T00:00:00+08:00"
    try:
        normalized = compact.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
        return parsed.isoformat()
    except ValueError:
        return ""


def source_name_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().strip()
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


# Placeholder source names produced by default_source_name when the input has no
# real publisher. These are UI labels for provenance, never real-world subjects —
# downstream subject extraction must not treat them as claim subjects.
INPUT_PLACEHOLDER_SOURCE_NAMES = frozenset(
    {"用户提供文本", "用户提供链接", "用户问题输入"}
)


def default_source_name(input_type: InternalInputType) -> str:
    if input_type in {"url_news", "url_unknown"}:
        return "用户提供链接"
    if input_type == "question_only":
        return "用户问题输入"
    return "用户提供文本"


def default_source_url(input_type: InternalInputType, raw_input: str) -> str:
    if input_type in {"url_news", "url_unknown"} and looks_like_url(raw_input):
        return raw_input.strip()
    if input_type == "question_only":
        return "https://example.org/input/question-only"
    return "https://example.org/input/text-news"
