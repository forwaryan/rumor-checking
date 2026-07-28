"""Xiaohongshu (小红书) search provider via xhs-cli.

Calls `xhs search <keyword> --json --sort latest` as a subprocess and
converts the results into SearchResult objects compatible with the retrieval
pipeline. Runs as a supplementary source alongside the primary Baidu/Bing
provider — XHS captures social-media rumor discussion that rarely appears
in traditional search engines.

Requires: xhs-cli installed and authenticated (`xhs login`).
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from shutil import which
from typing import List, Optional

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)

_XHS_NOTE_URL = "https://www.xiaohongshu.com/explore/{note_id}"


class XhsSearchProvider:
    name = "xhs"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._xhs_path: Optional[str] = which("xhs")

    @property
    def enabled(self) -> bool:
        return (
            getattr(self.settings, "xhs_search_enabled", True)
            and self._xhs_path is not None
        )

    def search(self, query_text: str, *, max_results: int = 5) -> List[SearchResult]:
        if not self.enabled:
            return []

        stage_key = get_retrieval_stage_key() or "retrieval_initial"
        emit_api_call(
            stage_key=stage_key,
            call_type="cli",
            status="running",
            title="小红书检索",
            summary=f"正在通过 xhs-cli 搜索「{query_text[:20]}」。",
            details=[f"query={query_text}"],
        )

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [self._xhs_path, "search", query_text, "--json", "--sort", "latest", "--page", "1"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)

            if proc.returncode != 0:
                logger.warning("xhs_search_failed returncode=%s stderr=%s", proc.returncode, proc.stderr[:200])
                emit_api_call(
                    stage_key=stage_key,
                    call_type="cli",
                    status="error",
                    title="小红书搜索失败",
                    summary=f"xhs-cli 返回错误码 {proc.returncode}。",
                    details=[f"query={query_text}", f"stderr={proc.stderr[:100]}"],
                )
                return []

            data = json.loads(proc.stdout)
            if not data.get("ok"):
                logger.warning("xhs_search_not_ok response=%s", proc.stdout[:200])
                return []

            items = data.get("data", {}).get("items", [])
            results = self._parse_items(items, query_text=query_text, max_results=max_results)

            emit_api_call(
                stage_key=stage_key,
                call_type="cli",
                status="completed",
                title="小红书搜索完成",
                summary=f"小红书返回 {len(results)} 条结果。",
                details=[
                    f"query={query_text}",
                    f"count={len(results)}",
                    f"latency={latency_ms}ms",
                    f"raw_items={len(items)}",
                ],
            )
            return results

        except subprocess.TimeoutExpired:
            logger.warning("xhs_search_timeout query=%s", query_text)
            emit_api_call(
                stage_key=stage_key,
                call_type="cli",
                status="error",
                title="小红书搜索超时",
                summary="xhs-cli 执行超过 15 秒。",
                details=[f"query={query_text}"],
            )
            return []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("xhs_search_error query=%s error=%s", query_text, exc)
            emit_api_call(
                stage_key=stage_key,
                call_type="cli",
                status="error",
                title="小红书搜索异常",
                summary=f"xhs-cli 执行出错: {exc.__class__.__name__}",
                details=[f"query={query_text}", f"error={str(exc)[:100]}"],
            )
            return []

    def _parse_items(self, items: list, *, query_text: str, max_results: int) -> List[SearchResult]:
        results: List[SearchResult] = []
        for item in items[:max_results]:
            card = item.get("note_card", {})
            note_id = item.get("id", "")
            if not note_id:
                continue

            title = card.get("display_title", "").strip()
            if not title:
                continue

            user = card.get("user", {})
            nickname = user.get("nickname") or user.get("nick_name") or "小红书用户"

            # Build snippet from interaction data
            interact = card.get("interact_info", {})
            likes = interact.get("liked_count", "0")
            comments = interact.get("comment_count", "0")
            shares = interact.get("shared_count", "0")
            snippet = f"{likes}赞 {comments}评论 {shares}转发 · 作者: {nickname}"

            # Extract publish time from corner tags
            published_at = None
            for tag in card.get("corner_tag_info", []):
                if tag.get("type") == "publish_time":
                    published_at = tag.get("text")
                    break

            url = _XHS_NOTE_URL.format(note_id=note_id)

            results.append(SearchResult(
                case_id="xhs_search",
                query=query_text,
                result_id=f"xhs_{note_id}",
                title=title,
                url=url,
                source_name="xiaohongshu.com",
                published_at=published_at,
                snippet=snippet,
                source_tier="C",
            ))

        return results
