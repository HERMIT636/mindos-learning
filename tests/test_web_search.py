"""Search transport boundaries without external services or real credentials."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from mindos.web_search import WebSearch, SearchUnavailable


class SearchTests(unittest.TestCase):
    def search_with(self, body):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(body).encode()
        opener = MagicMock()
        opener.open.return_value = response
        return opener

    def test_tavily_request_and_bounded_results(self):
        entries = [{"title": "Title", "url": f"https://example.org/{i}", "content": "a" * 500}
                   for i in range(12)]
        entries.insert(0, {"url": "javascript:alert(1)"})
        entries.insert(1, {"url": "https://user:password@example.org/"})
        opener = self.search_with({"results": entries})
        with patch('mindos.web_search.urllib.request.build_opener', return_value=opener):
            results = WebSearch("test-secret", "tavily", "https://proxy.example/search").search(["learn python"])
        self.assertEqual(len(results), 8)
        self.assertEqual(len(results[0]["description"]), 240)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://proxy.example/search")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertNotIn("test-secret", request.data.decode())
        payload = json.loads(request.data)
        self.assertEqual(payload["max_results"], 4)
        self.assertFalse(payload["include_raw_content"])
        self.assertFalse(payload["include_answer"])

    def test_empty_malformed_and_error_responses_fail_closed(self):
        for body in ({"results": []}, {"results": {}}, {"unexpected": True}, []):
            with self.subTest(body=body), patch('mindos.web_search.urllib.request.build_opener',
                                               return_value=self.search_with(body)):
                with self.assertRaises(SearchUnavailable):
                    WebSearch("secret", "tavily").search(["learn python"])
        for code in (301, 401, 403, 429, 432, 500):
            opener = MagicMock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://api.tavily.com/search", code, "secret-provider-message", {}, io.BytesIO(b"secret"))
            with patch('mindos.web_search.urllib.request.build_opener', return_value=opener):
                with self.assertRaises(SearchUnavailable) as raised:
                    WebSearch("secret", "tavily").search(["learn python"])
                self.assertNotIn("secret", str(raised.exception))


class PublicSearchTests(unittest.TestCase):
    def test_language_routing_fallback_and_source_balance(self):
        from mindos.web_search import PublicSourceSearch
        from urllib.parse import parse_qs, urlsplit
        import threading
        barrier = threading.Barrier(3)
        calls = []
        def fetch(url):
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            calls.append((parsed.hostname, query))
            if 'srsearch' in query:
                if query['srsearch'][0] != '摄影':
                    barrier.wait(timeout=2)
                    return {'query': {'search': []}}
                return {'query': {'search': [{'title': f'摄影{i}', 'snippet': '<b>入门</b> &amp; 实例'}
                                              for i in range(4)]}}
            barrier.wait(timeout=2)
            return {'items': [{'full_name': f'example/photo{i}', 'html_url': f'https://github.com/example/photo{i}',
                                'description': 'photography 入门资料'} for i in range(4)]}
        search = PublicSourceSearch()
        with patch.object(PublicSourceSearch, '_get_json', side_effect=fetch):
            results = search.search(['摄影构图基础', 'photography composition'], topic='摄影')
        self.assertEqual(len(results), 8)
        self.assertEqual([r['provider'] for r in results[:3]], ['Wikipedia zh', 'Wikipedia en', 'GitHub'])
        self.assertEqual(results[0]['description'], '入门 & 实例')
        self.assertEqual(search.report['sources'][0]['queries'], ['摄影构图基础', '摄影'])
        self.assertEqual(search.report['sources'][1]['queries'][0], 'photography composition')
        github = next(params for host, params in calls if host == 'api.github.com')
        self.assertEqual(github['q'], ['photography composition in:name,description,readme'])
        self.assertEqual(len(calls), 5)

    def test_partial_failure_and_malformed_response_do_not_hide_good_sources(self):
        from mindos.web_search import PublicSourceSearch
        def fetch(url):
            if 'zh.wikipedia' in url:
                raise urllib.error.HTTPError(url, 429, 'limited', {}, io.BytesIO())
            if 'en.wikipedia' in url:
                return {'query': None}
            return {'items': [{'full_name': 'example/python', 'html_url': 'https://github.com/example/python',
                               'description': '教材'}]}
        search = PublicSourceSearch()
        with patch.object(PublicSourceSearch, '_get_json', side_effect=fetch) as mock:
            results = search.search(['Python programming', 'Python tutorial'], topic='Python')
        self.assertEqual(len(results), 1)
        self.assertEqual(mock.call_count, 3)
        self.assertEqual([r['status'] for r in search.report['sources']], ['unavailable', 'unavailable', 'ok'])

    def test_readme_only_noise_is_discarded_and_topic_is_retried(self):
        from mindos.web_search import PublicSourceSearch
        responses = [
            {'items': [{'full_name': 'example/prompts', 'html_url': 'https://github.com/example/prompts',
                        'description': 'unrelated image prompts'}]},
            {'items': [{'full_name': 'example/photo', 'html_url': 'https://github.com/example/photo',
                        'description': '摄影入门'}]},
        ]
        with patch.object(PublicSourceSearch, '_get_json', side_effect=responses):
            results, report = PublicSourceSearch()._source('GitHub', PublicSourceSearch.GITHUB_ENDPOINT,
                                                          ['photography composition', '摄影'])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'example/photo')
        self.assertEqual(len(report['queries']), 2)

    def test_no_results_fail_without_fabricated_sources(self):
        from mindos.web_search import PublicSourceSearch
        search = PublicSourceSearch()
        with patch.object(PublicSourceSearch, '_get_json', return_value={'query': {'search': []}, 'items': []}):
            with self.assertRaises(SearchUnavailable):
                search.search(['no such course'], topic='unknown')
        self.assertEqual(search.report['result_count'], 0)
        self.assertTrue(all(item['status'] == 'empty' for item in search.report['sources']))
