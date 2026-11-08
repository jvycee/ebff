"""Sitemap robots expansion must finish and still follow a new sitemap URL."""

from ebff.config import ConfigManager
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
        if len(self.calls) > 12:
            raise AssertionError("sitemap worklist did not terminate: %s" % self.calls)
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
                "Sitemap: https://example.com/robots.txt\n"
                "Sitemap: https://example.com/alt-sitemap.xml\n"
            ),
            sibling: (
                "<?xml version='1.0'?>"
                "<urlset><url><loc>https://example.com/posts/1</loc></url></urlset>"
            ),
        })

        feeds = _plugin(http).discover("https://example.com")

        assert feeds == []
        assert http.calls.count(robots) == 1
        assert http.calls.count(sibling) == 1

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
        assert http.calls.count(sitemap) == 1
        assert http.calls.count(feed) == 1
