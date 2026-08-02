from __future__ import annotations

import json
import logging
from dataclasses import replace
from io import StringIO
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging


def _make_settings(**overrides):
    return replace(get_settings(), **overrides)


def _capture_log(settings, msg, *args, extra=None):
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    configure_logging(settings)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(root.handlers[0].formatter)
    logger = logging.getLogger("test.structured")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.info(msg, *args, extra=extra)
    return stream.getvalue()


def test_text_format_default():
    settings = _make_settings(log_format="text")
    line = _capture_log(settings, "stage=%s model=%s", "retrieve", "gpt")
    assert " | INFO | test.structured | stage=retrieve model=gpt" in line


def test_json_format_emits_valid_json_with_fields():
    settings = _make_settings(log_format="json")
    line = _capture_log(
        settings, "hello %s", "world", extra={"run_id": "abc"},
    )
    obj = json.loads(line)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "test.structured"
    assert obj["message"] == "hello world"
    assert "timestamp" in obj
    assert obj["run_id"] == "abc"


def test_json_extras_cannot_overwrite_envelope_keys():
    settings = _make_settings(log_format="json")
    line = _capture_log(
        settings, "check", extra={"level": "spoofed", "run_id": "abc"},
    )
    obj = json.loads(line)
    assert obj["level"] == "INFO"
    assert obj["extra_level"] == "spoofed"
    assert obj["run_id"] == "abc"


def test_json_handles_exc_info():
    settings = _make_settings(log_format="json")
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    configure_logging(settings)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(root.handlers[0].formatter)
    logger = logging.getLogger("test.exc")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("caught")
    obj = json.loads(stream.getvalue())
    assert obj["level"] == "ERROR"
    assert "traceback" in obj
    assert "ValueError: boom" in obj["traceback"]


def test_json_handles_non_serializable_extras():
    settings = _make_settings(log_format="json")
    line = _capture_log(settings, "x", extra={"path": Path("/tmp")})
    obj = json.loads(line)
    assert obj["path"] == "/tmp"
