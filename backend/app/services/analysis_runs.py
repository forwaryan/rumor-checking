from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Event, Thread
from typing import Any, BinaryIO
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalysisRun, AnalyzeRequest, Report
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.checking_playbooks import record_checking_experience
from backend.app.services.progress import reset_progress_callback, set_progress_callback

logger = logging.getLogger(__name__)
_ACTIVE = {"queued", "running"}


class AnalysisRunManager:
    """Durable runs for workers sharing one local SQLite database and checkpoint directory."""

    def __init__(
        self,
        directory: Path,
        *,
        retention_seconds: float = 86400,
        max_active: int = 4,
        lease_seconds: float = 30,
        clock: Callable[[], float] = time.time,
        pipeline_factory: Callable[[], AnalyzePipeline] = AnalyzePipeline,
    ) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.database = directory / "analysis-runs.sqlite3"
        self.database.touch(mode=0o600, exist_ok=True)
        self.database.chmod(0o600)
        self.lock_directory = directory / "execution-locks"
        self.lock_directory.mkdir(mode=0o700, exist_ok=True)
        self.retention_seconds = max(0, retention_seconds)
        self.max_active = max(1, max_active)
        self.lease_seconds = max(0.1, lease_seconds)
        self.clock = clock
        self.pipeline_factory = pipeline_factory
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    request_json TEXT NOT NULL, mode TEXT NOT NULL, input_preview TEXT NOT NULL,
                    report_json TEXT, error TEXT, last_event_id INTEGER NOT NULL DEFAULT 0,
                    owner TEXT, lease_until REAL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL, event_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, event_id)
                );
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except AppError:
                connection.commit()
                raise
            except BaseException:
                connection.rollback()
                raise

    def _cleanup(self, connection: sqlite3.Connection) -> None:
        now = self.clock()
        connection.execute(
            "UPDATE runs SET status='interrupted', error='run_interrupted', owner=NULL, lease_until=NULL "
            "WHERE status IN ('queued', 'running') AND lease_until <= ?",
            (now,),
        )
        expired = connection.execute(
            "SELECT run_id FROM runs WHERE status NOT IN ('queued', 'running') AND updated_at < ?",
            (now - self.retention_seconds,),
        ).fetchall()
        for row in expired:
            execution_lock = self._try_execution_lock(row["run_id"])
            if execution_lock is None:
                continue
            try:
                connection.execute("DELETE FROM runs WHERE run_id=?", (row["run_id"],))
            finally:
                execution_lock.close()
            (self.lock_directory / f"{row['run_id']}.lock").unlink(missing_ok=True)

    def _try_execution_lock(self, run_id: str) -> BinaryIO | None:
        """Acquire only inside a database transaction, including during lock-file cleanup."""
        descriptor = os.open(self.lock_directory / f"{run_id}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        handle = os.fdopen(descriptor, "r+b")
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return None
            raise
        return handle

    @staticmethod
    def _row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise AppError(status_code=404, code="run_not_found", message="Analysis run was not found or expired.")
        return row

    @staticmethod
    def _view(row: sqlite3.Row) -> AnalysisRun:
        return AnalysisRun(
            run_id=row["run_id"],
            status=row["status"],
            created_at=datetime.fromtimestamp(row["created_at"], UTC).isoformat(),
            updated_at=datetime.fromtimestamp(row["updated_at"], UTC).isoformat(),
            last_event_id=row["last_event_id"],
            mode=row["mode"],
            input_preview=row["input_preview"],
            raw_input=json.loads(row["request_json"])["raw_input"],
            report=Report.model_validate_json(row["report_json"]) if row["report_json"] else None,
            error=row["error"],
            resumable=row["status"] == "interrupted",
        )

    def _check_capacity(self, connection: sqlite3.Connection, *, exclude_run_id: str = "") -> None:
        count = connection.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued', 'running')").fetchone()[0]
        interrupted = connection.execute(
            "SELECT run_id FROM runs WHERE status='interrupted' AND run_id != ?", (exclude_run_id,)
        ).fetchall()
        for row in interrupted:
            execution_lock = self._try_execution_lock(row["run_id"])
            if execution_lock is None:
                count += 1
            else:
                execution_lock.close()
        if count >= self.max_active:
            raise AppError(status_code=429, code="run_capacity_exceeded", message="Too many analyses are running.")

    def create(self, request: AnalyzeRequest) -> AnalysisRun:
        run_id, owner = uuid4().hex, uuid4().hex
        payload = request.model_copy(deep=True)
        payload.request_context["run_id"] = run_id
        requested_mode = payload.request_context.get("mode")
        mode = "deep" if isinstance(requested_mode, str) and requested_mode.strip().lower() == "deep" else "fast"
        payload.request_context["mode"] = mode
        preview = " ".join(payload.raw_input.split())[:140]
        now = self.clock()
        execution_lock = None
        try:
            with self._transaction() as connection:
                self._cleanup(connection)
                self._check_capacity(connection)
                execution_lock = self._try_execution_lock(run_id)
                if execution_lock is None:
                    raise AppError(status_code=409, code="run_still_executing", message="Analysis is still stopping. Retry later.")
                connection.execute(
                    "INSERT INTO runs (run_id,status,created_at,updated_at,request_json,mode,input_preview,owner,lease_until) "
                    "VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, now, now, payload.model_dump_json(), mode, preview, owner, now + self.lease_seconds),
                )
                run = self._view(self._row(connection, run_id))
        except BaseException:
            if execution_lock is not None:
                execution_lock.close()
            raise
        self._launch(run_id, owner, execution_lock)
        return run

    def get(self, run_id: str) -> AnalysisRun:
        with self._transaction() as connection:
            self._cleanup(connection)
            return self._view(self._row(connection, run_id))

    def resume(self, run_id: str) -> AnalysisRun:
        owner = uuid4().hex
        execution_lock = None
        try:
            with self._transaction() as connection:
                self._cleanup(connection)
                row = self._row(connection, run_id)
                if row["status"] in _ACTIVE or row["status"] == "completed":
                    return self._view(row)
                if row["status"] == "failed":
                    raise AppError(status_code=409, code="run_failed", message="A failed analysis requires a new run.")
                execution_lock = self._try_execution_lock(run_id)
                if execution_lock is None:
                    raise AppError(status_code=409, code="run_still_executing", message="Analysis is still stopping. Retry later.")
                self._check_capacity(connection, exclude_run_id=run_id)
                now = self.clock()
                connection.execute(
                    "UPDATE runs SET status='queued', owner=?, lease_until=?, updated_at=?, error=NULL WHERE run_id=?",
                    (owner, now + self.lease_seconds, now, run_id),
                )
                run = self._view(self._row(connection, run_id))
        except BaseException:
            if execution_lock is not None:
                execution_lock.close()
            raise
        self._launch(run_id, owner, execution_lock)
        return run

    def _launch(self, run_id: str, owner: str, execution_lock: BinaryIO) -> None:
        try:
            Thread(target=self._worker, args=(run_id, owner, execution_lock), name=f"analysis-{run_id}", daemon=True).start()
        except Exception:
            try:
                self._finish(run_id, owner, error="analysis_unavailable")
            finally:
                execution_lock.close()

    def _owns(self, connection: sqlite3.Connection, run_id: str, owner: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM runs WHERE run_id=? AND owner=? AND status IN ('queued', 'running') AND lease_until > ?",
            (run_id, owner, self.clock()),
        ).fetchone() is not None

    def _append(self, connection: sqlite3.Connection, run_id: str, event: dict[str, Any]) -> None:
        event = {"emitted_at": datetime.fromtimestamp(self.clock(), UTC).isoformat(), **event}
        connection.execute(
            "UPDATE runs SET last_event_id=last_event_id+1, updated_at=? WHERE run_id=?", (self.clock(), run_id)
        )
        connection.execute(
            "INSERT INTO events (run_id,event_id,event_json) "
            "SELECT run_id,last_event_id,? FROM runs WHERE run_id=?",
            (json.dumps(event, ensure_ascii=False), run_id),
        )

    def _push(self, run_id: str, owner: str, event: dict[str, Any]) -> None:
        with self._transaction() as connection:
            if not self._owns(connection, run_id, owner):
                raise RuntimeError("analysis lease lost")
            self._append(connection, run_id, event)

    def _renew(self, run_id: str, owner: str) -> bool:
        with self._transaction() as connection:
            if not self._owns(connection, run_id, owner):
                return False
            connection.execute(
                "UPDATE runs SET lease_until=?, updated_at=? WHERE run_id=?",
                (self.clock() + self.lease_seconds, self.clock(), run_id),
            )
        return True

    def _heartbeat(self, run_id: str, owner: str, stop: Event) -> None:
        while not stop.wait(self.lease_seconds / 3):
            try:
                if not self._renew(run_id, owner):
                    return
            except sqlite3.Error:
                logger.warning("analysis_run_lease_renewal_failed run_id=%s", run_id)
                return

    def _finish(self, run_id: str, owner: str, *, report: Report | None = None, error: str | None = None) -> None:
        with self._transaction() as connection:
            if not self._owns(connection, run_id, owner):
                return
            if report is not None:
                self._append(connection, run_id, {"type": "report", "run_id": run_id, "report": report.model_dump(mode="json")})
            else:
                self._append(connection, run_id, {
                    "type": "error", "run_id": run_id, "code": error,
                    "message": "Analysis could not be completed. Please start a new run.", "status_code": 500,
                })
            self._append(connection, run_id, {"type": "complete", "run_id": run_id, "success": report is not None})
            connection.execute(
                "UPDATE runs SET status=?, report_json=?, error=?, owner=NULL, lease_until=NULL WHERE run_id=?",
                ("completed" if report is not None else "failed", report.model_dump_json() if report else None, error, run_id),
            )

    def _worker(self, run_id: str, owner: str, execution_lock: BinaryIO) -> None:
        stop = Event()
        token = set_progress_callback(lambda event: self._push(run_id, owner, event))
        try:
            with self._transaction() as connection:
                if not self._owns(connection, run_id, owner):
                    return
                payload = AnalyzeRequest.model_validate_json(self._row(connection, run_id)["request_json"])
                connection.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
            Thread(target=self._heartbeat, args=(run_id, owner, stop), daemon=True).start()
            self._push(run_id, owner, {"type": "session", "run_id": run_id, "summary": "分析任务已开始或恢复。"})
            report = self.pipeline_factory().analyze(payload)
            if not self._renew(run_id, owner):
                return
            self._record_experience(run_id, payload, report)
            self._finish(run_id, owner, report=report)
        except Exception as exc:
            logger.warning("analysis_run_failed run_id=%s error_type=%s", run_id, type(exc).__name__)
            try:
                self._finish(run_id, owner, error="analysis_failed" if isinstance(exc, AppError) else "internal_server_error")
            except sqlite3.Error:
                logger.warning("analysis_run_finalization_failed run_id=%s", run_id)
        finally:
            stop.set()
            reset_progress_callback(token)
            execution_lock.close()

    @staticmethod
    def _record_experience(run_id: str, payload: AnalyzeRequest, report: Report) -> None:
        try:
            settings = get_settings()
            if settings.agent_playbooks_enabled:
                record_checking_experience(
                    run_id=run_id,
                    raw_input=payload.raw_input,
                    report=report,
                    output_dir=settings.analysis_run_dir / "experience",
                    playbook_dir=settings.agent_playbook_dir,
                )
        except Exception as exc:
            logger.warning("analysis_run_experience_failed run_id=%s error_type=%s", run_id, type(exc).__name__)

    def event_page(self, run_id: str, after: int) -> tuple[list[dict[str, Any]], AnalysisRun]:
        with self._transaction() as connection:
            self._cleanup(connection)
            run = self._view(self._row(connection, run_id))
            rows = connection.execute(
                "SELECT event_id,event_json FROM events WHERE run_id=? AND event_id>? ORDER BY event_id LIMIT 200",
                (run_id, after),
            ).fetchall()
        return [{"event_id": row["event_id"], "event": json.loads(row["event_json"])} for row in rows], run

    async def events(self, run_id: str, after: int = 0) -> AsyncIterator[str]:
        cursor = after
        heartbeat_at = time.monotonic()
        while True:
            try:
                page, run = await asyncio.to_thread(self.event_page, run_id, cursor)
            except AppError:
                return
            for envelope in page:
                cursor = envelope["event_id"]
                yield json.dumps(envelope, ensure_ascii=False) + "\n"
            if run.status not in _ACTIVE and cursor >= run.last_event_id:
                return
            if time.monotonic() - heartbeat_at >= 10:
                yield json.dumps({"type": "heartbeat", "run_id": run_id}) + "\n"
                heartbeat_at = time.monotonic()
            if cursor >= run.last_event_id:
                await asyncio.sleep(0.1)


@lru_cache(maxsize=8)
def _manager(directory: Path, retention_seconds: float, max_active: int) -> AnalysisRunManager:
    return AnalysisRunManager(directory, retention_seconds=retention_seconds, max_active=max_active)


def get_analysis_run_manager() -> AnalysisRunManager:
    settings = get_settings()
    return _manager(settings.analysis_run_dir, settings.analysis_run_retention_seconds, settings.analysis_run_max_active)
