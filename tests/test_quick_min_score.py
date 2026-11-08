"""v1 quick mode stops discovery and still applies --min-score."""

from ebff.feed_finder import FeedFinder
from ebff.models import FeedInfo


def _feed(url, score):
    return FeedInfo(url=url, quality_score=score, validation_status="valid")


def _finder_with(feeds):
    finder = FeedFinder(timeout=1)
    finder._check_common_patterns = lambda url: list(feeds)
    finder._parse_html_links = lambda url: []
    finder._analyze_meta_tags = lambda url: []
    finder._check_sitemap = lambda url: []
    finder._sniff_content = lambda url: []
    return finder


class TestQuickMinScore:
    def test_quick_and_nonquick_omit_scores_below_min_and_keep_the_rest(self):
        low = _feed("https://example.com/low", 10)
        high = _feed("https://example.com/high", 90)

        quick = _finder_with([low, high]).discover(
            "https://example.com",
            quick_mode=True,
            validate_quality=False,
            min_score=50,
            deep_scan=True,
        )
        plain = _finder_with([_feed("https://example.com/low", 10), _feed("https://example.com/high", 90)]).discover(
            "https://example.com",
            quick_mode=False,
            validate_quality=False,
            min_score=50,
            deep_scan=False,
        )

        assert [feed.url for feed in quick] == ["https://example.com/high"]
        assert [feed.url for feed in plain] == ["https://example.com/high"]

    def test_quick_with_only_low_scores_returns_nothing(self):
        found = _finder_with([_feed("https://example.com/low", 10)]).discover(
            "https://example.com",
            quick_mode=True,
            validate_quality=False,
            min_score=50,
        )

        assert found == []
