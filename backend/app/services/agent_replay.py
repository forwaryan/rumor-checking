from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

from backend.app.agent_tools.base import HookRegistry
from backend.app.core import config
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services import agent_reasoner, llm_verdict, model_health, page_fetcher, verdict_engine
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.progress import get_retrieval_stage_key, reset_progress_callback, set_progress_callback
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.retrieval_service import RetrievalService


class ReplayViolation(RuntimeError):
    pass


def fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_fixture(path: Path) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict) or fixture.get("synthetic") is not True:
        raise ValueError("Agent replay accepts explicitly synthetic fixtures only")
    for field in ("id", "input", "sources", "retrieval", "completions", "expected"):
        if field not in fixture:
            raise ValueError(f"Missing fixture field: {field}")
    if not isinstance(fixture["input"], str) or not fixture["input"].strip():
        raise ValueError("Fixture input must be nonempty text")
    if not fixture["completions"] or not fixture["retrieval"]:
        raise ValueError("Replay requires recorded model and retrieval responses")
    ids = [source["result_id"] for source in fixture["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate evidence IDs")
    return fixture


def _settings(workspace: Path) -> config.Settings:
    with patch.dict(os.environ, {}, clear=True), patch.object(config, "_load_env_defaults"):
        defaults = config.get_settings.__wrapped__()
    return replace(
        defaults, project_root=workspace, retrieval_cache_dir=workspace / "retrieval",
        url_fetch_cache_dir=workspace / "pages", agent_checkpoint_dir=workspace / "checkpoints",
        agent_trace_dir=workspace / "traces", model_ledger_dir=workspace / "ledger",
        analysis_run_dir=workspace / "runs", agent_playbooks_enabled=False,
        retrieval_provider="gdelt", retrieval_cache_enabled=False, retrieval_fallback_to_mock=False,
        url_fetch_cache_enabled=True, rendered_fetch_enabled=False, agent_trace_enabled=False,
        agent_max_url_fetches=0, agent_tool_max_retries=0, agent_max_extra_rounds=1,
        agent_verdict_cache_enabled=False, model_ledger_enabled=False, eval_record_enabled=False,
        llm_base_url="https://replay.invalid/v1", llm_model="replay-model", llm_models=("replay-model",),
        llm_model_base_urls={}, llm_reasoning_models=(), llm_reasoning_retries=0,
        llm_query_extraction_enabled=False, llm_synthesis_model="", llm_fast_model="",
        agent_synthesis_critic_enabled=True, agent_orchestrator_enabled=True, lightweight_agent_enabled=True, multi_agent_enabled=False,
        xhs_search_enabled=False, toutiao_search_enabled=False, sogou_weixin_search_enabled=False,
        piyao_search_enabled=False, searxng_search_enabled=False, evidence_rerank_enabled=False,
        phoenix_enabled=False, agent_rate_limit_enabled=False,
    )


class RecordedBoundaries:
    name = "recorded"
    enabled = True

    def __init__(self, fixture: dict, settings: config.Settings):
        self.fixture = fixture
        self.settings = settings
        self.model_calls: list[dict] = []
        self.retrieval_calls: list[dict] = []
        self.page_calls: list[dict] = []
        self.violations: list[str] = []
        self._retrieval_used = [0] * len(fixture["retrieval"])
        self._lock = Lock()
        self.templates = {
            value: name for name, value in vars(agent_reasoner).items()
            if name.endswith("SYSTEM_PROMPT") and isinstance(value, str) and name != "SYNTHESIS_SYSTEM_PROMPT"
        }
        self.templates[llm_verdict._SYSTEM_PROMPT] = "LLM_VERDICT"

    def reject(self, message: str):
        self.violations.append(message)
        raise ReplayViolation(message)

    def block_network(self, *args, **kwargs):
        self.reject("unrecorded_external_call")

    def resolve_host(self, host, port, *args, **kwargs):
        if host not in {urlsplit(url).hostname for url in self.fixture.get("pages", {})}:
            self.reject("unrecorded_dns_lookup")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))]

    def send_page(self, request, *args, **kwargs):
        logical_url = request.url
        if request.url.host == "93.184.216.34":
            hostname = request.extensions.get("sni_hostname")
            if not isinstance(hostname, str):
                self.reject("missing_public_host_identity")
            logical_url = request.url.copy_with(host=hostname)
            if request.headers.get("host") != logical_url.netloc.decode("ascii"):
                self.reject("mismatched_public_host_identity")
        url = str(logical_url)
        page = self.fixture.get("pages", {}).get(url)
        if request.method != "GET" or page is None:
            self.reject("unrecorded_http_request")
        if sum(call["url_sha256"] == fingerprint(url) for call in self.page_calls) >= page.get("calls", 1):
            self.reject("unrecorded_http_repeat")
        self.page_calls.append({"url_sha256": fingerprint(url), "status": page.get("status", 200), "body_sha256": fingerprint(page["html"])})
        return httpx.Response(page.get("status", 200), text=page["html"], headers={"content-type": "text/html; charset=utf-8"}, request=request)

    def evidence_ids(self, text: str) -> list[str]:
        ids = {source["result_id"] for source in self.fixture["sources"]}
        quoted = re.findall(r'"([^"\n]+)"', text)
        return sorted({value for value in quoted if any(value == source_id or value.endswith(f"-{source_id}") for source_id in ids)})

    def search(self, query_text: str) -> list[SearchResult]:
        stage = get_retrieval_stage_key()
        with self._lock:
            matching = [index for index, record in enumerate(self.fixture["retrieval"])
                        if record["query"] == query_text and record["stage"] == stage
                        and self._retrieval_used[index] < record.get("calls", 1)]
            if not matching:
                self.retrieval_calls.append({"stage": stage, "query_sha256": fingerprint(query_text), "result_ids": [], "recorded": False})
                self.reject(f"unrecorded_retrieval:{stage}:{fingerprint(query_text)}")
            index = matching[0]
            self._retrieval_used[index] += 1
            record = self.fixture["retrieval"][index]
            source_ids = record["source_ids"]
            self.retrieval_calls.append({"stage": stage, "query_sha256": fingerprint(query_text), "result_ids": sorted(source_ids), "recorded": True})
        source_map = {source["result_id"]: source for source in self.fixture["sources"]}
        return [SearchResult(case_id="real_search", query=query_text, provider_name=self.name,
                             retrieved_at="2026-09-01T00:00:00+00:00", **source_map[source_id]) for source_id in source_ids]

    def complete(self, *, endpoint: str, model: str, system_prompt: str, user_prompt: str, timeout_multiplier: float = 1.0) -> str:
        index = len(self.model_calls)
        template = self.templates.get(system_prompt, "unknown")
        prefix, separator, body = system_prompt.partition("\n\n")
        if (separator and body == llm_verdict._SYSTEM_PROMPT and re.fullmatch(
            r"本次核查日期：\d{4}-\d{2}-\d{2}" + re.escape(
                "。claim未明确其他基准时，'目前/今年'以此日期为准；"
                "这不是证据的发布日期，也不能补足证据缺失的时间信息。"), prefix)):
            template = "LLM_VERDICT"
        if system_prompt.startswith("你是事实核查助手。对每条claim，对比它的evidence"):
            template = "CLAIM_CORRECTION"
        call = {
            "sequence": index + 1, "template": template, "template_sha256": fingerprint(system_prompt),
            "prompt_sha256": fingerprint({"system": system_prompt, "user": user_prompt}), "model": model,
            "max_output_tokens": self.settings.llm_max_tokens, "timeout_multiplier": timeout_multiplier,
            "input_evidence_ids": self.evidence_ids(user_prompt),
            "output_evidence_ids": [],
        }
        self.model_calls.append(call)
        if index >= len(self.fixture["completions"]):
            self.reject(f"unrecorded_model_call:{template}")
        record = self.fixture["completions"][index]
        if template != record["template"]:
            self.reject(f"model_call_order:{index + 1}:{template}")
        if record.get("error"):
            if record["error"] != "timeout":
                self.reject("unsupported_recorded_error")
            call["outcome"] = "timeout"
            raise httpx.ReadTimeout("recorded timeout")
        response = record["response"]
        content = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        call["outcome"] = "response"
        call["response_sha256"] = fingerprint(content)
        call["output_evidence_ids"] = self.evidence_ids(content)
        return content

    def unused_records(self) -> list[str]:
        errors = []
        if len(self.model_calls) != len(self.fixture["completions"]):
            errors.append("unconsumed_model_responses")
        if any(used != record.get("calls", 1) for used, record in zip(self._retrieval_used, self.fixture["retrieval"], strict=True)):
            errors.append("unconsumed_retrieval_responses")
        for url, page in self.fixture.get("pages", {}).items():
            if sum(call["url_sha256"] == fingerprint(url) for call in self.page_calls) != page.get("calls", 1):
                errors.append("unconsumed_page_response")
        return errors


def _restore_settings_aliases(isolated, original):
    for module in list(sys.modules.values()):
        if module and getattr(module, "__name__", "").startswith("backend.app") and getattr(module, "get_settings", None) is isolated:
            module.get_settings = original


def replay_case(fixture: dict) -> dict:
    actions: list[dict] = []
    failures: list[str] = []
    report = None
    with TemporaryDirectory(prefix="agent-replay-") as temporary, ExitStack() as stack:
        settings = _settings(Path(temporary))
        boundaries = RecordedBoundaries(fixture, settings)
        original_settings = config.get_settings
        def isolated_settings():
            return settings
        for module in list(sys.modules.values()):
            if module and getattr(module, "__name__", "").startswith("backend.app") and getattr(module, "get_settings", None) is original_settings:
                stack.enter_context(patch.object(module, "get_settings", isolated_settings))
        stack.callback(_restore_settings_aliases, isolated_settings, original_settings)
        stack.enter_context(patch.object(model_health, "_registry", None))
        stack.enter_context(patch.object(page_fetcher, "_cache", None))
        for target in ((socket.socket, "connect"), (socket.socket, "connect_ex"), (socket, "create_connection"),
                       (httpx.AsyncClient, "send"), (subprocess, "Popen")):
            stack.enter_context(patch.object(*target, side_effect=boundaries.block_network))
        stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=boundaries.resolve_host))
        stack.enter_context(patch.object(httpx.Client, "send", side_effect=boundaries.send_page))
        stack.enter_context(patch.object(agent_reasoner.LlmAgentReasoner, "_stream_completion", side_effect=boundaries.complete))
        # Pin relative-date context for deterministic offline fingerprints. The
        # fixtures use September 2026 evidence; this is not a source timestamp.
        original_judge = llm_verdict.llm_judge_claims

        def dated_judge(*args, **kwargs):
            return original_judge(*args, **(kwargs | {"reference_date": date(2026, 9, 1)}))

        stack.enter_context(patch.object(verdict_engine, "llm_judge_claims", side_effect=dated_judge))
        hooks = HookRegistry()

        def observe(hook):
            bundle = hook.state.retrieval_bundle
            actions.append({"action": hook.action, "success": hook.error is None,
                            "evidence_ids": sorted(item.result_id for item in bundle.canonical_results) if bundle else []})

        hooks.add_post(observe)
        stack.enter_context(patch.object(AnalyzePipeline, "_build_trace_hooks", return_value=(hooks, None)))
        callback_token = set_progress_callback(None)
        try:
            pipeline = AnalyzePipeline()
            active_settings = replace(settings, analysis_provider="kimi", llm_api_key="synthetic-replay-key")
            pipeline.settings = active_settings
            pipeline.agent_reasoner.settings = active_settings
            pipeline.retriever = RetrievalService(settings=active_settings, provider=boundaries, agent_reasoner=pipeline.agent_reasoner)
            report = pipeline.analyze(AnalyzeRequest(raw_input=fixture["input"], input_type="text", request_context={
                "mode": "deep", "run_id": "0" * 32, "search_sources": ["baidu"], "disable_official_boost": True,
            }))
        except Exception as exc:
            failures.append(f"pipeline_exception:{type(exc).__name__}")
        finally:
            reset_progress_callback(callback_token)
        failures.extend(boundaries.violations)
        failures.extend(boundaries.unused_records())
    expected = fixture["expected"]
    actual_claims = {item.claim: item.verdict for item in report.claim_results} if report else {}
    for claim, verdict in expected["claims"].items():
        if actual_claims.get(claim) != verdict:
            failures.append(f"verdict_mismatch:{fingerprint(claim)}")
    if set(actual_claims) != set(expected["claims"]):
        failures.append("claim_set_mismatch")
    actual_actions = [item["action"] for item in actions]
    for action in expected["required_actions"]:
        if action not in actual_actions:
            failures.append(f"missing_action:{action}")
    if expected.get("no_decisive_verdicts") and any(verdict != "insufficient" for verdict in actual_claims.values()):
        failures.append("unexpected_decisive_verdict")
    actual_gaps = {claim.claim: sorted(gap.dimension for gap in claim.evidence_gaps) for claim in report.claim_results} if report else {}
    for claim, dimensions in expected.get("evidence_gaps", {}).items():
        if actual_gaps.get(claim) != sorted(dimensions):
            failures.append(f"gap_mismatch:{fingerprint(claim)}")
    source_map = {source["url"]: source["result_id"] for source in fixture["sources"]}
    output_ids = sorted({source_map[evidence.url] for claim in report.claim_results for evidence in claim.evidence if evidence.url in source_map}) if report else []
    if report and any(evidence.url not in source_map for claim in report.claim_results for evidence in claim.evidence):
        failures.append("unrecorded_cited_source")
    return {
        "case_id": fixture["id"], "fixture_sha256": fingerprint(fixture), "passed": not failures,
        "failures": failures, "actions": actions, "model_call_count": len(boundaries.model_calls),
        "model_calls": boundaries.model_calls,
        "retrieval_calls": sorted(boundaries.retrieval_calls, key=lambda call: (call["stage"] or "", call["query_sha256"])),
        "page_calls": sorted(boundaries.page_calls, key=lambda call: call["url_sha256"]),
        "input_evidence_ids": sorted(source["result_id"] for source in fixture["sources"]),
        "output_evidence_ids": output_ids,
        "claims": [{"claim_sha256": fingerprint(claim), "verdict": verdict, "evidence_gaps": actual_gaps[claim]} for claim, verdict in actual_claims.items()],
        "report_mode": report.mode if report else None,
    }


def replay_directory(directory: Path) -> dict:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("No agent replay fixtures found")
    cases = [replay_case(load_fixture(path)) for path in paths]
    return {"schema_version": 1, "offline": True, "runtime": "single_agent_deep", "passed": all(case["passed"] for case in cases),
            "case_count": len(cases), "passed_count": sum(case["passed"] for case in cases), "cases": cases}
