"""Static, secret-safe capability registry for retrieval sources.

The registry describes configuration and cheap local prerequisites only. It
must not make network requests: health endpoints need to remain deterministic
and safe to call from operator dashboards.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from shutil import which
from typing import Literal

from backend.app.core.config import Settings, get_settings

SourceKind = Literal["primary", "supplementary", "derived"]


@dataclass(frozen=True)
class SourceCapability:
    id: str
    label: str
    description: str
    kind: SourceKind
    configured: bool
    available: bool
    enabled: bool
    default_on: bool
    selectable: bool
    requires_auth: bool
    capabilities: tuple[str, ...]
    fallback_to: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        payload["fallback_to"] = list(self.fallback_to)
        return payload


def _reason(*, configured: bool, available: bool, not_configured: str, unavailable: str) -> str | None:
    if not configured:
        return not_configured
    if not available:
        return unavailable
    return None


def list_source_capabilities(settings: Settings | None = None) -> list[SourceCapability]:
    """Return all known retrieval capabilities without probing remote systems."""
    settings = settings or get_settings()
    provider = settings.retrieval_provider
    has_llm_credential = bool(settings.llm_api_key)
    has_xhs_cli = which("xhs") is not None

    primary_available = {
        "mock": True,
        "playwright": True,
        "gdelt": True,
        "kimi": has_llm_credential,
    }
    official_boost_configured = provider in primary_available and provider != "mock"
    official_boost_available = primary_available.get(provider, False)

    definitions = [
        SourceCapability(
            id="mock",
            label="离线样例",
            description="确定性离线检索样例",
            kind="primary",
            configured=provider == "mock",
            available=True,
            enabled=provider == "mock",
            default_on=False,
            selectable=False,
            requires_auth=False,
            capabilities=("offline_fixture",),
            unavailable_reason=_reason(
                configured=provider == "mock",
                available=True,
                not_configured="未选择为当前主检索源",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="baidu",
            label="百度",
            description="百度搜索引擎（主力源）",
            kind="primary",
            configured=provider == "playwright",
            available=True,
            enabled=provider == "playwright",
            default_on=True,
            selectable=True,
            requires_auth=False,
            capabilities=("web_search", "chinese_search"),
            unavailable_reason=_reason(
                configured=provider == "playwright",
                available=True,
                not_configured="未选择 playwright 主检索源",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="gdelt",
            label="GDELT",
            description="GDELT 全球新闻检索",
            kind="primary",
            configured=provider == "gdelt",
            available=True,
            enabled=provider == "gdelt",
            default_on=False,
            selectable=False,
            requires_auth=False,
            capabilities=("news_search", "global_search"),
            unavailable_reason=_reason(
                configured=provider == "gdelt",
                available=True,
                not_configured="未选择为当前主检索源",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="kimi",
            label="LLM 联网检索",
            description="模型内建联网搜索工具",
            kind="primary",
            configured=provider == "kimi",
            available=has_llm_credential,
            enabled=provider == "kimi" and has_llm_credential,
            default_on=False,
            selectable=False,
            requires_auth=True,
            capabilities=("web_search", "tool_calling"),
            unavailable_reason=_reason(
                configured=provider == "kimi",
                available=has_llm_credential,
                not_configured="未选择为当前主检索源",
                unavailable="未配置 LLM 凭据",
            ),
        ),
        SourceCapability(
            id="xiaohongshu",
            label="小红书",
            description="小红书社交笔记",
            kind="supplementary",
            configured=settings.xhs_search_enabled,
            available=has_xhs_cli,
            enabled=settings.xhs_search_enabled and has_xhs_cli,
            default_on=True,
            selectable=True,
            requires_auth=True,
            capabilities=("social_search", "user_generated_content"),
            unavailable_reason=_reason(
                configured=settings.xhs_search_enabled,
                available=has_xhs_cli,
                not_configured="配置已关闭",
                unavailable="未检测到 xhs-cli",
            ),
        ),
        SourceCapability(
            id="toutiao",
            label="今日头条",
            description="头条搜索（聚合辟谣/媒体）",
            kind="supplementary",
            configured=settings.toutiao_search_enabled,
            available=True,
            enabled=settings.toutiao_search_enabled,
            default_on=True,
            selectable=True,
            requires_auth=False,
            capabilities=("news_search", "debunk_search"),
            unavailable_reason=_reason(
                configured=settings.toutiao_search_enabled,
                available=True,
                not_configured="配置已关闭",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="sogou_weixin",
            label="微信公众号",
            description="搜狗微信（辟谣公众号：腾讯较真、科普中国等）",
            kind="supplementary",
            configured=settings.sogou_weixin_search_enabled,
            available=True,
            enabled=settings.sogou_weixin_search_enabled,
            default_on=True,
            selectable=True,
            requires_auth=False,
            capabilities=("social_search", "publisher_search"),
            unavailable_reason=_reason(
                configured=settings.sogou_weixin_search_enabled,
                available=True,
                not_configured="配置已关闭",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="piyao",
            label="联合辟谣平台",
            description="中国互联网联合辟谣平台",
            kind="supplementary",
            configured=settings.piyao_search_enabled,
            available=True,
            enabled=settings.piyao_search_enabled,
            default_on=True,
            selectable=True,
            requires_auth=False,
            capabilities=("official_debunk", "web_search"),
            unavailable_reason=_reason(
                configured=settings.piyao_search_enabled,
                available=True,
                not_configured="配置已关闭",
                unavailable="运行时不可用",
            ),
        ),
        SourceCapability(
            id="searxng",
            label="SearXNG 元搜索",
            description="自建 SearXNG 元搜索（英文/海外官方来源补充，AGPL 独立服务）",
            kind="supplementary",
            configured=settings.searxng_search_enabled,
            available=bool(settings.searxng_base_url),
            enabled=settings.searxng_search_enabled and bool(settings.searxng_base_url),
            default_on=False,
            selectable=True,
            requires_auth=False,
            capabilities=("web_search", "overseas_search", "metasearch"),
            unavailable_reason=_reason(
                configured=settings.searxng_search_enabled,
                available=bool(settings.searxng_base_url),
                not_configured="配置已关闭",
                unavailable="未配置 SEARXNG_BASE_URL 实例地址",
            ),
        ),
        SourceCapability(
            id="official_boost",
            label="权威信源补强",
            description="证据不足时定向补充官方与主流媒体来源",
            kind="derived",
            configured=official_boost_configured,
            available=official_boost_available,
            enabled=official_boost_configured and official_boost_available,
            default_on=True,
            selectable=True,
            requires_auth=provider == "kimi",
            capabilities=("official_boost", "targeted_search"),
            unavailable_reason=_reason(
                configured=official_boost_configured,
                available=official_boost_available,
                not_configured="当前主检索源不支持权威信源补强",
                unavailable="主检索源运行时不可用",
            ),
        ),
    ]
    return definitions


def source_capability_snapshot(settings: Settings | None = None) -> dict:
    sources = list_source_capabilities(settings)
    enabled_primary = next(
        (source for source in sources if source.kind == "primary" and source.enabled),
        None,
    )
    unavailable = [source for source in sources if source.configured and not source.available]
    status = "ok" if enabled_primary is not None and not unavailable else "degraded"
    return {
        "sources": [source.to_dict() for source in sources],
        "summary": {
            "status": status,
            "active_primary": enabled_primary.id if enabled_primary is not None else None,
            "total": len(sources),
            "configured": sum(source.configured for source in sources),
            "available": sum(source.available for source in sources),
            "enabled": sum(source.enabled for source in sources),
            "unavailable": len(unavailable),
            "enabled_by_kind": {
                kind: sum(source.enabled and source.kind == kind for source in sources)
                for kind in ("primary", "supplementary", "derived")
            },
        },
    }
