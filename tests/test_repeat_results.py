"""Repeat discover() and rescore must keep producing results."""

from unittest.mock import Mock

from ebff import FeedFinder, FeedInfo
from ebff.config import ConfigManager
from ebff.validator import FeedValidator


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
