"""Repeat discover(), concurrent batch dedupe, and rescore contracts."""

import threading
from unittest.mock import Mock

from ebff import FeedFinder, FeedInfo
from ebff.config import ConfigManager
from ebff.validator import FeedValidator

SHARED = "https://shared.example/feed"
PAGE_A = "https://a.example/news"
PAGE_B = "https://b.example/news"
WAIT = 2.0


def _rich_feed(url: str) -> FeedInfo:
    return FeedInfo(
        url=url,
        title="Example Site Feed",
        feed_type="rss",
        discovery_method="html_link",
        entry_count=12,
        description="A long enough description for the scorer",
        language="en",
        validation_status="valid",
    )


def _install_pattern_feeds(finder: FeedFinder) -> None:
    def get(url, timeout=None, use_cache=True):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.text = "<rss></rss>" if url.rstrip("/").endswith("/feed") else "no"
        return response

    finder.discoverer.http_client.get = get
    finder.discoverer.validator.is_feed_content = lambda content: "<rss>" in (content or "")
    finder.discoverer.validator.parse_feed = lambda url, content: FeedInfo(
        url=url,
        title="Example",
        validation_status="valid",
        entry_count=3,
    )


class TestRepeatDiscover:
    def test_second_discover_returns_pattern_feed_again(self):
        finder = FeedFinder(timeout=1)
        _install_pattern_feeds(finder)

        first = finder.discover(
            "https://example.com",
            deep_scan=False,
            validate_quality=False,
        )
        second = finder.discover(
            "https://example.com",
            deep_scan=False,
            validate_quality=False,
        )

        assert any(feed.url == "https://example.com/feed" for feed in first)
        assert any(feed.url == "https://example.com/feed" for feed in second)

    def test_pattern_plugin_still_dedupes_inside_one_run(self):
        finder = FeedFinder(timeout=1)
        _install_pattern_feeds(finder)
        plugin = finder.discoverer.plugin_manager.get_plugin("common_pattern")
        plugin.clear_cache()

        first = plugin._check_single_pattern("https://example.com", "/feed")
        second = plugin._check_single_pattern("https://example.com", "/feed")

        assert first is not None
        assert first.url == "https://example.com/feed"
        assert second is None


class TestRepeatScore:
    def test_fresh_object_for_scored_url_is_scored(self):
        validator = FeedValidator(ConfigManager())
        first = _rich_feed("https://example.com/feed")
        validator.validate_and_score_feeds([first])

        second = _rich_feed("https://example.com/feed")
        validator.validate_and_score_feeds([second])

        assert first.quality_score > 0
        assert second.quality_score == first.quality_score

    def test_unseen_url_is_scored(self):
        validator = FeedValidator(ConfigManager())
        feed = _rich_feed("https://example.com/atom.xml")

        validator.validate_and_score_feeds([feed])

        assert feed.quality_score > 0


def _html(*hrefs: str) -> str:
    links = "\n".join(
        '<link rel="alternate" type="application/rss+xml" href="%s">' % href
        for href in hrefs
    )
    return "<html><head>%s</head></html>" % links


class _PageResponse:
    def __init__(self, text, content_type="text/html", status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}


class _BarrierHttp:
    """Fake HTTP. Timeouts are recorded; get() does not raise into discover()."""

    def __init__(self):
        self.calls = []
        self.timed_out = False
        self._lock = threading.Lock()

    def get(self, url, timeout=None, use_cache=True):
        with self._lock:
            self.calls.append((threading.get_ident(), url))
        return self._response(url)

    def _response(self, url):
        if url in (PAGE_A, PAGE_B):
            return _PageResponse(_html(SHARED))
        if url == SHARED:
            return _PageResponse("<rss></rss>", content_type="application/rss+xml")
        return _PageResponse("", content_type="text/plain", status_code=404)

    def wait(self, event):
        if not event.wait(WAIT):
            self.timed_out = True
            return False
        return True

    def count(self, url, thread_id=None):
        return sum(
            1
            for tid, called in self.calls
            if called == url and (thread_id is None or tid == thread_id)
        )


def _install_shared_feed(finder, http):
    finder.discoverer.http_client.get = http.get
    finder.discoverer.validator.parse_feed = lambda url, content: (
        FeedInfo(url=url, title="Shared", validation_status="valid", entry_count=1)
        if url == SHARED
        else None
    )


def _urls(feeds):
    return [feed.url for feed in feeds]


class TestConcurrentDiscover:
    def _both_return_shared_feed(self, waiting_page):
        finder = FeedFinder(timeout=1)
        http = _BarrierHttp()
        entered_feed_get = threading.Event()
        other_passed_html = threading.Event()
        holder = {}

        def get(url, timeout=None, use_cache=True):
            tid = threading.get_ident()
            with http._lock:
                http.calls.append((tid, url))
                feed_gets = http.count(SHARED, tid)
            if url == SHARED and holder.get("id") is None:
                holder["id"] = tid
            if url == SHARED and tid == holder.get("id") and feed_gets == 1:
                entered_feed_get.set()
                http.wait(other_passed_html)
            if url == waiting_page:
                http.wait(entered_feed_get)
                with http._lock:
                    page_gets = http.count(waiting_page, tid)
                if page_gets > 1:
                    other_passed_html.set()
            return http._response(url)

        _install_shared_feed(finder, http)
        finder.discoverer.http_client.get = get

        results = finder.batch_discover([PAGE_A, PAGE_B], max_workers=2)

        assert http.timed_out is False
        assert SHARED in _urls(results[PAGE_A])
        assert SHARED in _urls(results[PAGE_B])
        assert http.count(SHARED) == 2

    def test_batch_each_call_returns_shared_feed_while_the_other_get_is_held(self):
        self._both_return_shared_feed(PAGE_B)
        self._both_return_shared_feed(PAGE_A)

    def test_second_call_cannot_make_the_first_refetch_a_duplicate_link(self):
        finder = FeedFinder(timeout=1)
        http = _BarrierHttp()
        in_first_get = threading.Event()
        second_call_entered = threading.Event()
        release_first = threading.Event()
        ids = {}

        def get(url, timeout=None, use_cache=True):
            tid = threading.get_ident()
            with http._lock:
                http.calls.append((tid, url))
            if tid == ids.get("b") and not second_call_entered.is_set():
                second_call_entered.set()
            if url == SHARED and tid == ids.get("a"):
                with http._lock:
                    owned = http.count(SHARED, tid)
                if owned == 1:
                    in_first_get.set()
                    http.wait(release_first)
            if url == PAGE_A:
                return _PageResponse(_html(SHARED, SHARED))
            return http._response(url)

        _install_shared_feed(finder, http)
        finder.discoverer.http_client.get = get
        results = {}

        def run(slot, page):
            ids[slot] = threading.get_ident()
            results[slot] = finder.discover(
                page, deep_scan=True, validate_quality=False
            )

        first = threading.Thread(target=run, args=("a", PAGE_A))
        second = threading.Thread(target=run, args=("b", PAGE_B))
        first.start()
        try:
            http.wait(in_first_get)
            second.start()
            http.wait(second_call_entered)
        finally:
            release_first.set()
        first.join(WAIT)
        second.join(WAIT)

        assert http.timed_out is False
        assert first.is_alive() is False
        assert second.is_alive() is False
        assert http.count(SHARED, ids["a"]) == 1
        assert SHARED in _urls(results["a"])
        assert SHARED in _urls(results["b"])


class TestScoreBeforeDedupe:
    def _candidate(self, method, url="https://example.com/feed"):
        feed = _rich_feed(url)
        feed.discovery_method = method
        feed.quality_score = 0
        return feed

    def test_html_alias_survives_threshold_when_pattern_alias_is_listed_first(self):
        finder = FeedFinder(timeout=1)
        validator = finder.discoverer.validator
        pattern_score = validator.score_feed(self._candidate("common_pattern"))
        html_score = validator.score_feed(self._candidate("html_link"))
        assert html_score > pattern_score

        result = finder.discoverer._finalize_feeds(
            [self._candidate("common_pattern"), self._candidate("html_link")],
            validate_quality=True,
            min_score=pattern_score + 1,
        )

        assert [feed.discovery_method for feed in result] == ["html_link"]
        assert result[0].quality_score == html_score

    def test_without_validation_min_score_does_not_drop_unscored_duplicates(self):
        finder = FeedFinder(timeout=1)
        result = finder.discoverer._finalize_feeds(
            [self._candidate("common_pattern"), self._candidate("html_link")],
            validate_quality=False,
            min_score=100,
        )

        assert len(result) == 1
        assert result[0].quality_score == 0
