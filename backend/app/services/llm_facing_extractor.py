"""LLM-facing body extractor PoC (borrows Crawl4AI's "fit markdown" idea).

Default-off, pluggable, and NON-destructive: it does not replace page_fetcher's
`_extract_key_paragraphs`. It exists so we can measure — on the same fetched HTML
— whether a structure- and link-density-aware extractor produces cleaner,
more citable body text than the current newline-split + digit/length scorer.

The one idea worth borrowing from Crawl4AI without any heavy dependency (no
torch, no headless browser, stdlib `html.parser` only): rank candidate blocks by
*link density*. A block whose text is mostly anchor text is navigation / related-
links boilerplate; a block that is mostly prose is article body. The current
extractor has no such notion, so a long nav column full of digits can outscore
the real lede. Everything here is pure Python and offline.

`extract_main_text(html)` returns cleaned body text. `compare_extractors(...)`
scores this against the baseline on three metrics for the PoC report:
  * effective_body_rate — did we get non-trivial prose out at all
  * citation_locatability — can a claim's key terms be located in the output
  * latency_ms — extraction wall-clock (extraction only, not network)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from html.parser import HTMLParser

# Structural tags that never hold article body — dropped whole.
_BOILERPLATE_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}
# Tags that open a fresh text block (article paragraphs, list items, headings).
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "h1", "h2", "h3", "h4", "blockquote", "td"}


@dataclass
class _Block:
    text_chars: int
    link_chars: int
    parts: list[str]

    @property
    def link_density(self) -> float:
        if self.text_chars <= 0:
            return 1.0
        return self.link_chars / self.text_chars


class _StructuralExtractor(HTMLParser):
    """Walk the DOM, accumulating text per block and tracking how much of each
    block's text sits inside <a> tags (link density). Boilerplate subtrees are
    skipped wholesale."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._current = _Block(0, 0, [])
        self._skip_depth = 0
        self._anchor_depth = 0

    def _flush(self) -> None:
        if self._current.parts:
            joined = " ".join(self._current.parts).strip()
            if joined:
                self._current.parts = [joined]
                self.blocks.append(self._current)
        self._current = _Block(0, 0, [])

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BOILERPLATE_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            self._anchor_depth += 1
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _BOILERPLATE_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        self._current.parts.append(stripped)
        self._current.text_chars += len(stripped)
        if self._anchor_depth:
            self._current.link_chars += len(stripped)

    def finish(self) -> list[_Block]:
        self._flush()
        return self.blocks


def extract_main_text(html: str, *, max_chars: int = 800, max_link_density: float = 0.5) -> str:
    """Structure- and link-density-aware body extraction.

    Keeps only blocks that are (a) substantial prose and (b) not link-heavy
    navigation, ordered by their original document position (article body reads
    top-to-bottom), truncated to max_chars."""
    parser = _StructuralExtractor()
    try:
        parser.feed(html)
        blocks = parser.finish()
    except Exception:
        return ""

    kept = [
        block.parts[0]
        for block in blocks
        if block.text_chars >= 40 and block.link_density <= max_link_density
    ]
    if not kept:
        return ""

    out: list[str] = []
    total = 0
    for para in kept:
        if total + len(para) > max_chars:
            remaining = max_chars - total
            if remaining > 40:
                out.append(para[:remaining])
            break
        out.append(para)
        total += len(para)
    return "\n\n".join(out)


@dataclass
class ExtractionScore:
    extractor: str
    effective_body_rate: float
    citation_locatability: float
    boilerplate_free_rate: float
    latency_ms: float
    body_samples: int


def _effective(body: str) -> bool:
    """Non-trivial prose: enough characters and not just a title fragment."""
    return len(body.strip()) >= 60


def _locatable(body: str, key_terms: list[str]) -> bool:
    """A claim's key terms are locatable in the extracted body — the property
    that makes a body citable rather than merely present."""
    if not key_terms:
        return _effective(body)
    hay = body.lower()
    hits = sum(1 for term in key_terms if term and term.lower() in hay)
    return hits >= max(1, len(key_terms) // 2)


def _boilerplate_free(body: str, boilerplate_markers: list[str]) -> bool:
    """No known navigation/footer boilerplate leaked into the body. This is the
    dimension a structure-aware extractor is meant to win: the baseline keeps
    link-heavy nav that happens to score well on digits+length."""
    if not boilerplate_markers:
        return True
    hay = body.lower()
    return not any(marker.lower() in hay for marker in boilerplate_markers)


def compare_extractors(
    samples: list[tuple[str, list[str], list[str]]],
    *,
    baseline_fn,
    candidate_fn=extract_main_text,
    max_chars: int = 800,
) -> dict[str, ExtractionScore]:
    """Score baseline vs candidate on the same samples.

    Each sample is (html, key_terms, boilerplate_markers). baseline_fn /
    candidate_fn each take raw html and return extracted text. Returns one
    ExtractionScore per extractor for the PoC report."""
    results: dict[str, ExtractionScore] = {}
    for name, fn in (("baseline", baseline_fn), ("candidate", candidate_fn)):
        effective = 0
        locatable = 0
        clean = 0
        start = time.monotonic()
        for html, key_terms, boilerplate in samples:
            body = fn(html)
            if _effective(body):
                effective += 1
            if _locatable(body, key_terms):
                locatable += 1
            if _boilerplate_free(body, boilerplate):
                clean += 1
        latency_ms = (time.monotonic() - start) * 1000
        n = len(samples) or 1
        results[name] = ExtractionScore(
            extractor=name,
            effective_body_rate=round(effective / n, 4),
            citation_locatability=round(locatable / n, 4),
            boilerplate_free_rate=round(clean / n, 4),
            latency_ms=round(latency_ms, 2),
            body_samples=len(samples),
        )
    return results
