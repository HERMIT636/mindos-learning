"""Small, bounded Brave Web Search adapter for course-direction review."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class SearchUnavailable(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class WebSearch:
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise SearchUnavailable("请先在“管理模型与 API”中配置 Brave 网页搜索密钥")
        self.api_key = api_key

    def search(self, queries: list[str]) -> list[dict]:
        if not 1 <= len(queries) <= 3 or any(not isinstance(query, str) or
                                               not 3 <= len(query.strip()) <= 250 for query in queries):
            raise ValueError("搜索词格式无效")
        results: list[dict] = []
        seen: set[str] = set()
        for query in queries:
            url = self.ENDPOINT + "?" + urllib.parse.urlencode({"q": query.strip(), "count": 4})
            request = urllib.request.Request(url, headers={
                "Accept": "application/json", "X-Subscription-Token": self.api_key,
            })
            try:
                with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
                    raw = response.read(1_500_001)
                if len(raw) > 1_500_000:
                    raise SearchUnavailable("网页搜索结果过大，请缩小课程范围")
                body = json.loads(raw)
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                if code in (401, 403):
                    raise SearchUnavailable("网页搜索密钥无效或无权限，请检查 Brave Search API 配置") from exc
                if code in (402, 429):
                    raise SearchUnavailable("网页搜索额度不足或请求过于频繁，请检查 Brave Search API 账户") from exc
                raise SearchUnavailable(f"网页搜索失败（HTTP {code}）") from exc
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                raise SearchUnavailable("网页搜索连接失败，请检查网络后重试") from exc
            web = body.get("web") if isinstance(body, dict) else None
            entries = web.get("results", []) if isinstance(web, dict) else []
            if not isinstance(entries, list):
                raise SearchUnavailable("网页搜索返回了无效结果")
            for item in entries:
                if not isinstance(item, dict):
                    continue
                link = item.get("url")
                if not isinstance(link, str) or len(link) > 1000:
                    continue
                try:
                    parsed = urllib.parse.urlsplit(link)
                except ValueError:
                    continue
                if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                    continue
                clean_link = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
                if clean_link in seen:
                    continue
                seen.add(clean_link)
                title = item.get("title", "")
                description = item.get("description", "")
                results.append({"title": str(title)[:180], "url": clean_link,
                                "description": str(description)[:240]})
                if len(results) >= 8:
                    return results
        if not results:
            raise SearchUnavailable("网页搜索没有找到可用结果，请换一个更明确的课程名称")
        return results
