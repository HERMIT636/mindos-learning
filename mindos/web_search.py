"""Bounded source discovery for course-direction review."""

from __future__ import annotations

import json
from .search_planning import normalize_queries
from concurrent.futures import ThreadPoolExecutor
import re
from html import unescape
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

    PROVIDERS = {"brave": "Brave", "tavily": "Tavily"}

    @classmethod
    def endpoint(cls, provider: str, value: str = "") -> str:
        if not isinstance(provider, str) or provider not in cls.PROVIDERS:
            raise ValueError("请选择 Brave 或 Tavily 接口格式")
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError("搜索 API 地址格式无效")
        value = value.strip() or (cls.ENDPOINT if provider == "brave" else "https://api.tavily.com/search")
        try:
            parsed = urllib.parse.urlsplit(value)
            port = parsed.port
            valid = (parsed.hostname and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and not any(c.isspace() or ord(c) < 32 for c in value)
                     and "\\" not in value
                     and (parsed.scheme == "https" or (parsed.scheme == "http" and
                          parsed.hostname in ("localhost", "127.0.0.1", "::1"))))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("搜索 API 地址须为 HTTPS（本机可用 HTTP），不能包含账号、查询参数或片段")
        if parsed.path in ("", "/"):
            value = value.rstrip("/") + ("/search" if provider == "tavily" else "/res/v1/web/search")
        return value

    def __init__(self, api_key: str, provider: str = "brave", api_url: str = "") -> None:
        self.provider = provider
        self.api_url = self.endpoint(provider, api_url)
        if not api_key:
            raise SearchUnavailable("请先在“管理模型与 API”中配置网页搜索密钥")
        self.api_key = api_key

    def search(self, queries: list[str]) -> list[dict]:
        queries = normalize_queries(queries)
        if not 1 <= len(queries) <= 3:
            raise ValueError("搜索词格式无效")
        results: list[dict] = []
        seen: set[str] = set()
        for query in queries:
            if self.provider == "brave":
                url = self.api_url + "?" + urllib.parse.urlencode({"q": query.strip(), "count": 4})
                request = urllib.request.Request(url, headers={
                    "Accept": "application/json", "X-Subscription-Token": self.api_key,
                })
            else:
                payload = {"query": query.strip(), "max_results": 4, "search_depth": "basic",
                           "include_answer": False, "include_raw_content": False}
                request = urllib.request.Request(self.api_url, data=json.dumps(payload).encode(), headers={
                    "Accept": "application/json", "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.api_key,
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
                    raise SearchUnavailable("网页搜索密钥无效或无权限，请检查所选搜索 API 配置") from exc
                if code in (402, 429, 432, 433):
                    raise SearchUnavailable("网页搜索额度不足或请求过于频繁，请检查所选搜索 API 账户") from exc
                raise SearchUnavailable(f"网页搜索失败（HTTP {code}）") from exc
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                raise SearchUnavailable("网页搜索连接失败，请检查网络后重试") from exc
            web = body.get("web") if isinstance(body, dict) and self.provider == "brave" else body
            entries = web.get("results") if isinstance(web, dict) else None
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
                description = item.get("content" if self.provider == "tavily" else "description", "")
                results.append({"title": str(title)[:180], "url": clean_link,
                                "description": str(description)[:240], "provider": self.PROVIDERS[self.provider]})
                if len(results) >= 8:
                    return results
        if not results:
            raise SearchUnavailable("网页搜索没有找到可用结果，请换一个更明确的课程名称")
        return results


class PublicSourceSearch:
    """Keyless discovery from public encyclopedia and code repository indexes.

    This is deliberately not described as a whole-web search engine.
    """

    WIKIPEDIA_ENDPOINTS = {
        "zh": "https://zh.wikipedia.org/w/api.php",
        "en": "https://en.wikipedia.org/w/api.php",
    }
    GITHUB_ENDPOINT = "https://api.github.com/search/repositories"
    USER_AGENT = "MindOS-Learning/1.0 (https://github.com/HERMIT636/mindos-learning)"

    @staticmethod
    def _get_json(url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "Accept": "application/json", "User-Agent": PublicSourceSearch.USER_AGENT,
        })
        with urllib.request.build_opener(NoRedirect).open(request, timeout=6) as response:
            raw = response.read(1_500_001)
        if len(raw) > 1_500_000:
            raise ValueError("搜索响应过大")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("搜索响应格式无效")
        return body

    @staticmethod
    def _plain(value: object, limit: int) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", value))).strip()[:limit]

    def __init__(self) -> None:
        self.report: dict = {}

    def _source(self, provider: str, endpoint: str, queries: list[str]) -> tuple[list[dict], dict]:
        results: list[dict] = []
        attempts: list[str] = []
        issues: list[str] = []
        seen: set[str] = set()
        for query in queries[:2]:
            attempts.append(query)
            wiki = provider.startswith("Wikipedia ")
            params = ({"action": "query", "list": "search", "srsearch": query,
                       "srlimit": 4, "srnamespace": 0, "format": "json", "formatversion": 2}
                      if wiki else {"q": query + " in:name,description,readme", "per_page": 4})
            try:
                body = self._get_json(endpoint + "?" + urllib.parse.urlencode(params))
                group = body.get("query") if wiki else body
                entries = group.get("search" if wiki else "items") if isinstance(group, dict) else None
                if not isinstance(entries, list):
                    raise ValueError("搜索响应格式无效")
                if body.get("incomplete_results"):
                    issues.append("索引仅返回部分结果")
                for item in entries[:4]:
                    if not isinstance(item, dict):
                        continue
                    title = self._plain(item.get("title" if wiki else "full_name"), 180)
                    if not title:
                        continue
                    description = self._plain(item.get("snippet" if wiki else "description"), 240)
                    if not wiki:
                        # README matches alone can surface unrelated popular repositories.
                        terms = re.findall(r"[a-z0-9+#]{3,}|[\u3400-\u9fff]+", query.casefold())
                        visible = (title + " " + description).casefold()
                        if terms and not any(term in visible for term in terms):
                            continue
                    link = (f"https://{provider.split()[-1]}.wikipedia.org/wiki/" +
                            urllib.parse.quote(item["title"].replace(" ", "_"), safe="")
                            if wiki else item.get("html_url"))
                    if not isinstance(link, str) or len(link) > 1000:
                        continue
                    try:
                        parsed = urllib.parse.urlsplit(link)
                    except ValueError:
                        continue
                    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                        continue
                    clean = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
                    if clean in seen:
                        continue
                    seen.add(clean)
                    results.append({"title": title, "url": clean,
                                    "description": description,
                                    "provider": provider})
                if results:
                    break
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                issues.append("服务拒绝访问或请求受限" if code in (403, 429) else f"服务返回 HTTP {code}")
                # Do not retry rejected or unavailable services with another query.
                break
            except (urllib.error.URLError, OSError, ValueError):
                issues.append("连接失败、超时或返回格式异常")
                break
        return results, {"provider": provider, "queries": attempts, "count": len(results),
                         "status": "partial" if results and issues else "ok" if results else
                                   "unavailable" if issues else "empty", "issues": issues}

    def search(self, queries: list[str], topic: str = "") -> list[dict]:
        queries = normalize_queries(queries)
        if not 1 <= len(queries) <= 3:
            raise ValueError("搜索词格式无效")
        if not isinstance(topic, str) or len(topic) > 100:
            raise ValueError("课程主题格式无效")
        queries = list(dict.fromkeys(re.sub(r"\s+", " ", q).strip() for q in queries))
        chinese = [q for q in queries if re.search(r"[\u3400-\u9fff]", q)]
        english = [q for q in queries if not re.search(r"[\u3400-\u9fff]", q)]
        topic = topic.strip()

        def candidates(preferred: list[str]) -> list[str]:
            primary = (preferred or queries)[0]
            # Use the user's actual topic as fallback, never invent a translation.
            rest = ([topic] if len(topic) >= 2 else []) + preferred[1:] + queries
            return list(dict.fromkeys([primary] + rest))[:2]

        jobs = [(f"Wikipedia {language}", endpoint,
                 candidates(chinese if language == "zh" else english))
                for language, endpoint in self.WIKIPEDIA_ENDPOINTS.items()]
        jobs.append(("GitHub", self.GITHUB_ENDPOINT, candidates(english)))
        # Each source performs at most two bounded requests, sequentially within that source.
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self._source, *job) for job in jobs]
            batches = [future.result() for future in futures]
        results: list[dict] = []
        seen: set[str] = set()
        # Round-robin keeps late sources represented; completion timing never changes order.
        for rank in range(4):
            for entries, _ in batches:
                if rank < len(entries) and entries[rank]["url"] not in seen:
                    item = entries[rank]
                    results.append(item)
                    seen.add(item["url"])
                    if len(results) == 8:
                        break
            if len(results) == 8:
                break
        self.report = {"mode": "public", "sources": [report for _, report in batches],
                       "result_count": len(results)}
        if not results:
            if any(report["issues"] for _, report in batches):
                raise SearchUnavailable("免密钥资料检索暂时不可用或没有结果；请稍后重试、缩短课程名称，或配置网页搜索 API")
            raise SearchUnavailable("公开资料索引没有找到可用结果；已尝试补搜课程主题，请使用更明确的学科名称")
        return results
