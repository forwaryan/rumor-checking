from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.app.models.schemas import Report

logger = logging.getLogger(__name__)
_DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "agent" / "playbooks"
_MAX_FILE_BYTES = 24_000
_MAX_PLAYBOOKS = 32
_MAX_EXPERIENCES = 200


class CheckingPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    kind: Literal["procedure"]
    status: Literal["draft", "approved"] = "draft"
    title: str = Field(min_length=1, max_length=100)
    match_terms: list[Annotated[str, Field(min_length=2, max_length=40)]] = Field(min_length=1, max_length=20)
    instructions: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(min_length=1, max_length=8)
    source_url: str = Field(min_length=1, max_length=300)
    reviewed_at: date
    expires_at: date | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http", "repo"} or not parsed.netloc:
            raise ValueError("A public source URL or repo:// reference is required")
        if parsed.username or parsed.password or ".." in parsed.path.split("/"):
            raise ValueError("Invalid playbook source reference")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> CheckingPlaybook:
        if self.expires_at is not None and self.expires_at < self.reviewed_at:
            raise ValueError("Expiry must not precede review")
        return self


def _matches(text: str, term: str) -> bool:
    normalized = term.casefold()
    if normalized.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text


def select_checking_playbooks(
    text: str,
    *,
    playbook_dir: Path | None = None,
    limit: int = 3,
) -> list[dict]:
    directory = playbook_dir if playbook_dir is not None else _DEFAULT_DIRECTORY
    if limit <= 0:
        return []
    ranked: list[tuple[int, CheckingPlaybook]] = []
    today = date.today()
    normalized = text.casefold()
    seen: set[str] = set()
    try:
        paths = sorted(directory.glob("*.json"))[:_MAX_PLAYBOOKS]
    except OSError:
        return []
    for path in paths:
        try:
            if path.is_symlink() or path.stat().st_size > _MAX_FILE_BYTES:
                continue
            with path.open("rb") as source:
                payload = source.read(_MAX_FILE_BYTES + 1)
            if len(payload) > _MAX_FILE_BYTES:
                continue
            playbook = CheckingPlaybook.model_validate_json(payload)
        except (OSError, ValueError, ValidationError):
            continue
        if playbook.status != "approved" or playbook.reviewed_at > today:
            continue
        if playbook.expires_at is not None and playbook.expires_at < today:
            continue
        if playbook.id in seen:
            continue
        seen.add(playbook.id)
        score = sum(_matches(normalized, term) for term in set(playbook.match_terms))
        if score:
            ranked.append((score, playbook))
    ranked.sort(key=lambda entry: (-entry[0], entry[1].id))
    return [
        playbook.model_dump(mode="json", include={"id", "title", "instructions", "source_url", "reviewed_at"})
        for _, playbook in ranked[:min(limit, 3)]
    ]


def record_checking_experience(
    *,
    run_id: str,
    raw_input: str,
    report: Report,
    output_dir: Path,
    playbook_dir: Path | None = None,
) -> None:
    """Save bounded outcome counters for review; never promote them into evidence or instructions."""
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        return
    temporary_path: Path | None = None
    try:
        selected = select_checking_playbooks(raw_input, playbook_dir=playbook_dir)
        counts = {
            verdict: sum(claim.verdict == verdict for claim in report.claim_results)
            for verdict in ("supported", "refuted", "insufficient", "conflicting")
        }
        payload = {
            "kind": "experience",
            "status": "draft",
            "source_run_id": run_id,
            "observed_at": datetime.now(UTC).isoformat(),
            "playbook_ids": [playbook["id"] for playbook in selected],
            "claim_counts": counts,
            "source_count": len(report.sources),
        }
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir, delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
        temporary_path.replace(output_dir / f"experience-{run_id}.json")
        paths = sorted(output_dir.glob("experience-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for expired in paths[_MAX_EXPERIENCES:]:
            expired.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError) as exc:
        logger.debug("checking_experience_record_failed error_type=%s", type(exc).__name__)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
