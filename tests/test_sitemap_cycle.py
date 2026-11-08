"""Sitemap robots expansion must finish, preserve feeds, and run again."""

from ebff.config import ConfigManager
from ebff.models import FeedInfo
from ebff.plugins import SitemapDiscovery
from ebff.validator import FeedValidator


class _Response:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.headers = {}


class _Http:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, timeout=None, use_cache=True):
        self.calls.append(url)
        # A non-200 stops expansion without raising. The production loop
        # catches exceptions, so a raised cap would be swallowed and hang.
        # Above every exact list below. A repeated robots target still
        # exceeds those lists before this bound, so the bound cannot make
        # the old loop pass.
        if len(self.calls) > 40:
            return _Response(404, "")
        page = self.pages.get(url)
        if page is None:
            return _Response(404, "")
        return _Response(200, page)


def _plugin(http):
    return SitemapDiscovery(http, FeedValidator(ConfigManager()), ConfigManager())


class TestSitemapWorklist:
    def test_robots_self_reference_is_fetched_once_and_sibling_is_followed(self):
        robots = "https://example.com/robots.txt"
        sibling = "https://example.com/alt-sitemap.xml"
        http = _Http({
            robots: (
                "Sitemap:\n"
                "Sitemap:    \n"
                "Sitemap: https://example.com/robots.txt  \n"
                "Sitemap: https://example.com/alt-sitemap.xml\n"
            ),
            sibling: (
                "<?xml version='1.0'?>"
                "<urlset><url><loc>https://example.com/posts/1</loc></url></urlset>"
            ),
        })

        feeds = _plugin(http).discover("https://example.com")

        assert feeds == []
        assert "" not in http.calls
        assert http.calls == [
            "https://example.com/sitemap.xml",
            "https://example.com/sitemap_index.xml",
            robots,
            sibling,
        ]

    def test_feed_loc_is_still_requested_once(self):
        sitemap = "https://example.com/sitemap.xml"
        feed = "https://example.com/feed"
        http = _Http({
            sitemap: (
                "<?xml version='1.0'?>"
                "<urlset><url><loc>https://example.com/feed</loc></url></urlset>"
            ),
        })
        plugin = _plugin(http)
        plugin.validator.is_feed_content = lambda content: False

        feeds = plugin.discover("https://example.com")

        assert feeds == []
        assert http.calls == [
            sitemap,
            feed,
            "https://example.com/sitemap_index.xml",
            "https://example.com/robots.txt",
        ]


class TestSitemapCyclesAndFeeds:
    def test_two_document_cycle_and_second_call_revisit_each_url_once(self):
        origin = "https://a.example/robots.txt"
        other = "https://b.example/robots.txt"
        http = _Http({
            origin: "Sitemap: https://b.example/robots.txt\n",
            other: "Sitemap: https://a.example/robots.txt\n",
        })
        plugin = _plugin(http)

        plugin.discover("https://a.example")
        plugin.discover("https://a.example")

        once = [
            "https://a.example/sitemap.xml",
            "https://a.example/sitemap_index.xml",
            origin,
            other,
        ]
        assert http.calls == once + once
        assert "" not in http.calls

    def test_diamond_and_pending_duplicate_fetch_each_robots_url_once(self):
        start = "https://a.example/robots.txt"
        left = "https://a.example/left-robots.txt"
        right = "https://a.example/right-robots.txt"
        shared = "https://a.example/shared-robots.txt"
        http = _Http({
            start: (
                "Sitemap: https://a.example/left-robots.txt\n"
                "Sitemap: https://a.example/right-robots.txt\n"
                "Sitemap: https://a.example/shared-robots.txt\n"
            ),
            left: "Sitemap: https://a.example/shared-robots.txt\n",
            right: "Sitemap: https://a.example/shared-robots.txt\n",
            shared: "User-agent: *\n",
        })

        feeds = _plugin(http).discover("https://a.example")

        assert feeds == []
        assert http.calls == [
            "https://a.example/sitemap.xml",
            "https://a.example/sitemap_index.xml",
            start,
            left,
            right,
            shared,
        ]

    def test_repeated_feed_loc_is_returned_once(self):
        sitemap = "https://example.com/sitemap.xml"
        feed = "https://example.com/feed"
        http = _Http({
            sitemap: (
                "<?xml version='1.0'?>"
                "<urlset>"
                "<url><loc>https://example.com/feed</loc></url>"
                "<url><loc>https://example.com/feed</loc></url>"
                "</urlset>"
            ),
            feed: "<?xml version='1.0'?><rss><channel><title>T</title></channel></rss>",
        })
        plugin = _plugin(http)
        plugin.validator.is_feed_content = lambda content: True
        plugin.validator.parse_feed = lambda url, content: FeedInfo(
            url=url,
            title="T",
            validation_status="valid",
            entry_count=1,
        )

        feeds = plugin.discover("https://example.com")

        assert [item.url for item in feeds] == [feed]
        assert http.calls.count(sitemap) == 1
        assert http.calls.count(feed) == 1
