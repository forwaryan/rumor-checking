from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import ClaimItem, NormalizedEvent, ProviderAnalysis, ProviderEventDraft
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.progress import emit_api_call, emit_log
from backend.app.services.question_intent import is_broad_trend_question

logger = logging.getLogger(__name__)

ALLOWED_CLAIM_TYPES = {"fact", "opinion", "prediction", "unverifiable"}
CLAIM_TYPE_ALIASES = {
    "fact": "fact",
    "事实": "fact",
    "factual": "fact",
    "news_fact": "fact",
    "opinion": "opinion",
    "观点": "opinion",
    "评价": "opinion",
    "commentary": "opinion",
    "prediction": "prediction",
    "预测": "prediction",
    "forecast": "prediction",
    "研判": "prediction",
    "unverifiable": "unverifiable",
    "无法核实": "unverifiable",
    "不可核实": "unverifiable",
    "未经证实": "unverifiable",
    "hearsay": "unverifiable",
}
GENERIC_TITLES = {
    "待核实事件",
    "相关情况",
    "新闻事件",
    "网传消息",
    "热搜截图",
    "截图内容",
    "消息截图",
}
GENERIC_TITLE_MARKERS = ("待核实", "相关情况", "截图", "热搜", "网友热议")
GENERIC_SUMMARY_PHRASES = (
    "引发关注",
    "有待核实",
    "仍待核实",
    "详情以官方通报为准",
    "请以官方通报为准",
    "相关消息正在传播",
)
GENERIC_SOURCE_NAMES = {"社交平台", "网友爆料", "网传消息", "网络消息"}
GENERIC_CLAIM_PATTERNS = (
    re.compile(r"^(此事|该消息|相关情况)(仍)?(有待|待)核实[。]?$"),
    re.compile(r"^(请|详情请)?以官方(通报|消息|说明)为准[。]?$"),
    re.compile(r"^(网上|网络上|社交平台).{0,10}(有|出现).{0,6}(传闻|消息)[。]?$"),
    re.compile(r"^(相关(消息|情况)|该事件).{0,8}(引发关注|持续传播)[。]?$"),
)
EVENT_ACTION_PATTERN = re.compile(r"通报|回应|辟谣|核查|暂停|恢复|抽检|停课|停运|裁员|召回|否认|证实|救治|溯源")
ENTITY_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}(局|公司|医院|学校|平台|部门|政府|警方|管理局|运营公司)")
SYSTEM_PROMPT = """
你是谣言研判后端的结构化抽取器。你的任务不是下最终 verdict，而是把输入文本整理成稳定的事件信息和待核查 claims。
你必须返回一个 JSON 对象，不能输出额外解释。
JSON 结构如下：
{
  "event": {
    "title": "string 或 null",
    "summary": "string 或 null",
    "keywords": ["string"],
    "source_name": "string 或 null",
    "published_at": "ISO-8601 datetime 或 YYYY-MM-DD 或 null"
  },
  "claims": [
    {
      "claim": "string",
      "claim_type": "fact|opinion|prediction|unverifiable"
    }
  ]
}
抽取要求：
- 只基于用户输入做结构化抽取，不要假装已经检索互联网。
- `title` 尽量写成具体新闻标题，优先包含主体 + 动作或结论，不要写“待核实事件”“热搜截图”“网传消息”等空标题。
- `summary` 用 1 到 2 句概括核心事实；如果原文同时包含传闻与回应，要把两边都写清楚，不要只写“引发关注”“仍待核实”。
- `claims` 优先抽取 2 到 4 条、最多 5 条可单独核查的陈述句；优先保留核心传闻、官方/当事方回应、核查动作、处置结果。
- 如果输入像疑问句、标题党或聊天记录，请改写成陈述句，不要保留问号，也不要只复述“网上有传言”。
- 如果输入真假混杂，请拆成多条 claim，而不是混成一句笼统表述。
- 如果一句话里混了“事件本体 + 追加细节 + 阴谋式推断/归因”，必须拆开；例如“住院”“已经死亡”“平台封锁消息”要拆成不同 claim。
- 不确定时可以使用 null 或空数组，但不要用空泛句子凑字段。
""".strip()


class LlmStructuredProvider:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.analysis_provider == "kimi" and bool(self.settings.llm_api_key)

    def analyze(self, event: NormalizedEvent) -> Optional[ProviderAnalysis]:
        if not self.enabled:
            raise RuntimeError("LLM structured analysis is not configured.")
        if event.input_type == "question_only" and is_broad_trend_question(event.raw_input):
            emit_log(
                stage_key="provider_enrichment",
                title="跳过 provider enrichment",
                summary="这是宽泛趋势型问题，provider enrichment 不参与。",
                details=[],
            )
            return None

        content = self._request_completion(event)
        analysis = self._parse_content(content)
        if analysis is None:
            logger.warning("llm_provider_empty_result input_type=%s", event.input_type)
            raise RuntimeError("LLM returned no structured claims.")
        return analysis

    def _request_completion(self, event: NormalizedEvent) -> str:
        emit_api_call(
            stage_key="provider_enrichment",
            call_type="llm",
            status="running",
            title="调用 LLM structured analysis",
            summary="正在请求 LLM 结构化抽取事件和 claims。",
            details=[
                f"endpoint={self.settings.llm_base_url}/chat/completions",
                f"model={self.settings.llm_model}",
            ],
        )
        response = httpx.post(
            f"{self.settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
                "temperature": self._request_temperature(),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(event)},
                ],
            },
            timeout=self.settings.provider_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        emit_api_call(
            stage_key="provider_enrichment",
            call_type="llm",
            status="completed",
            title="LLM structured analysis 返回",
            summary="LLM 已返回结构化抽取结果。",
            details=[
                f"status_code={response.status_code}",
                f"model={self.settings.llm_model}",
            ],
        )
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {})
        return self._coerce_content(message.get("content"))

    def _request_temperature(self) -> float:
        return self.settings.llm_temperature

    def _build_user_prompt(self, event: NormalizedEvent) -> str:
        title_hint = event.title or "null"
        summary_hint = event.summary or "null"
        source_hint = event.source_name or "null"
        published_hint = event.published_at or "null"
        return (
            "请只做结构化抽取，不要输出 verdict 或解释。\n"
            "请优先保留‘谁在什么时候对什么做了什么/回应了什么’。\n"
            "如果文本里同时出现传闻和辟谣/回应，请分别体现在 summary 与 claims 里。\n"
            "如果一句话里有一部分像事实、一部分像追加脑补，请拆成多条 claim，不要混成一句。\n"
            "不要把‘有待核实’‘引发关注’‘请以官方通报为准’当成主要标题、摘要或 claim。\n"
            "已有提示字段如下，这些字段可能不完整，只能作为参考：\n"
            f"- input_type: {event.input_type}\n"
            f"- title_hint: {title_hint}\n"
            f"- summary_hint: {summary_hint}\n"
            f"- source_name_hint: {source_hint}\n"
            f"- published_at_hint: {published_hint}\n"
            "原始输入开始\n"
            "<<<RAW_INPUT>>>\n"
            f"{event.raw_input}\n"
            "<<<END_RAW_INPUT>>>\n"
        )

    def _coerce_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts)
        raise ValueError("Unsupported LLM content format")

    def _parse_content(self, content: str) -> Optional[ProviderAnalysis]:
        payload = self._extract_json_payload(content)
        if payload is None:
            return None

        raw_event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        provider_event = ProviderEventDraft(
            title=self._normalize_event_title(raw_event.get("title")),
            summary=self._normalize_event_summary(raw_event.get("summary")),
            keywords=self._clean_string_list(raw_event.get("keywords")),
            source_name=self._normalize_source_name(raw_event.get("source_name")),
            published_at=self._clean_optional_datetime(raw_event.get("published_at")),
        )

        claims = self._extract_claims(payload.get("claims"))
        if not provider_event.title and provider_event.summary:
            provider_event = provider_event.model_copy(update={"title": self._derive_title_from_text(provider_event.summary)})

        if not provider_event.title and not provider_event.summary and not claims:
            return None
        return ProviderAnalysis(event=provider_event, claims=claims)

    def _extract_json_payload(self, content: str) -> Optional[Dict[str, Any]]:
        stripped = content.strip()
        candidates = [stripped]

        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        brace_start = stripped.find("{")
        brace_end = stripped.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidates.append(stripped[brace_start : brace_end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _extract_claims(self, value: Any) -> List[ClaimItem]:
        if not isinstance(value, list):
            return []

        claims: List[ClaimItem] = []
        seen = set()
        for item in value:
            claim_text = self._extract_claim_text(item)
            if not claim_text:
                continue
            normalized_text = self._normalize_claim_text(claim_text)
            if not normalized_text or self._is_generic_claim(normalized_text):
                continue

            claim_type = self._normalize_claim_type(item, normalized_text)
            if claim_type not in ALLOWED_CLAIM_TYPES:
                continue

            claim_key = self._claim_key(normalized_text)
            if claim_key in seen:
                continue
            seen.add(claim_key)
            claims.append(ClaimItem(claim=normalized_text, claim_type=claim_type))
            if len(claims) >= 5:
                break
        return claims

    def _extract_claim_text(self, item: Any) -> Optional[str]:
        if isinstance(item, str):
            return self._clean_optional_string(item)
        if not isinstance(item, dict):
            return None
        for key in ("claim", "text", "content", "statement"):
            cleaned = self._clean_optional_string(item.get(key))
            if cleaned:
                return cleaned
        return None

    def _normalize_claim_type(self, item: Any, claim_text: str) -> str:
        raw_type = None
        if isinstance(item, dict):
            raw_type = self._clean_optional_string(item.get("claim_type") or item.get("type"))
        if raw_type:
            compact = raw_type.strip().lower().replace("-", "_")
            if compact in ALLOWED_CLAIM_TYPES:
                return compact
            if compact in {"rumor", "传闻", "待核实"}:
                return self._guess_claim_type(claim_text)
            alias = CLAIM_TYPE_ALIASES.get(compact) or CLAIM_TYPE_ALIASES.get(raw_type)
            if alias:
                return alias
        return self._guess_claim_type(claim_text)

    def _guess_claim_type(self, claim_text: str) -> str:
        if any(token in claim_text for token in ["觉得", "认为", "明显", "不值得相信", "隐瞒", "混乱"]):
            return "opinion"
        if any(token in claim_text for token in ["将", "下周", "会继续", "肯定会", "预计", "或将"]):
            return "prediction"
        if any(token in claim_text for token in ["匿名", "群聊", "爆料", "内部人员"]) and not any(
            token in claim_text for token in ["通报", "回应", "辟谣", "说明", "证实", "否认"]
        ):
            return "unverifiable"
        return "fact"

    def _normalize_claim_text(self, value: str) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"^(网传|传闻|消息称|报道称|有消息称|聊天记录称)[：:，,\s]*", "", cleaned)
        cleaned = re.sub(r"^(是否|是不是)", "", cleaned)
        cleaned = re.sub(r"(是真的吗|是否属实|是真是假)[？?]?$", "", cleaned)
        cleaned = cleaned.rstrip("。！？?!；; ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None
        return f"{cleaned}。"

    def _claim_key(self, claim_text: str) -> str:
        return re.sub(r"[\s，。！？?!；;:：]", "", claim_text).lower()

    def _is_generic_claim(self, claim_text: str) -> bool:
        compact = claim_text.strip()
        if len(compact) < 8:
            return True
        return any(pattern.match(compact) for pattern in GENERIC_CLAIM_PATTERNS)

    def _normalize_event_title(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        if cleaned in GENERIC_TITLES:
            return None
        if any(marker in cleaned for marker in GENERIC_TITLE_MARKERS) and not self._has_specific_signal(cleaned):
            return None
        return cleaned[:40]

    def _normalize_event_summary(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        if any(phrase in cleaned for phrase in GENERIC_SUMMARY_PHRASES) and not self._has_specific_signal(cleaned):
            return None
        if len(cleaned) > 160:
            return cleaned[:157] + "..."
        return cleaned

    def _normalize_source_name(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned or cleaned in GENERIC_SOURCE_NAMES:
            return None
        return cleaned

    def _derive_title_from_text(self, text: str) -> Optional[str]:
        sentence = re.split(r"[。！？?!]", text, maxsplit=1)[0].strip("，,：:；; ")
        if not sentence:
            return None
        if len(sentence) > 28:
            first_chunk = re.split(r"[，,；;]", sentence, maxsplit=1)[0].strip()
            if 8 <= len(first_chunk) <= 28:
                sentence = first_chunk
            else:
                sentence = sentence[:28]
        if sentence in GENERIC_TITLES:
            return None
        return sentence

    def _has_specific_signal(self, text: str) -> bool:
        return bool(ENTITY_PATTERN.search(text) or EVENT_ACTION_PATTERN.search(text) or re.search(r"\d", text))

    def _clean_optional_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip(" \n\t\r\"'")
        return compact or None

    def _clean_string_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            value = re.split(r"[,，、/]+", value)
        if not isinstance(value, list):
            return []
        ordered: List[str] = []
        seen = set()
        for item in value:
            cleaned = self._clean_optional_string(item)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
            if len(ordered) >= 6:
                break
        return ordered

    def _clean_optional_datetime(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        return ensure_datetime_string(cleaned)
