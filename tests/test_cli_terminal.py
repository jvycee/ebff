"""CLI batch results use the same exit and export rules as one URL."""

import json
import sys
from unittest.mock import Mock, patch

import pytest

from ebff.cli import main
from ebff.models import FeedInfo


def _feed():
    return FeedInfo(
        url="https://one.example/feed",
        title="One",
        feed_type="rss",
        quality_score=80,
        entry_count=3,
        validation_status="valid",
    )


def _run(argv):
    with patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit) as caught:
            main()
    return caught.value.code


class TestBatchTerminal:
    def test_partial_batch_exits_zero_and_exports_found_feeds(self, tmp_path):
        urls = tmp_path / "urls.txt"
        urls.write_text(
            "https://one.example\n\n# comment\nhttps://two.example\n",
            encoding="utf-8",
        )
        out = tmp_path / "out.json"
        finder = Mock()
        finder.batch_discover.return_value = {
            "https://one.example": [_feed()],
            "https://two.example": [],
        }

        with patch("ebff.cli.FeedFinder", return_value=finder):
            code = _run(["ebff", "--batch", str(urls), "--output", str(out)])

        assert code == 0
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert [item["url"] for item in saved] == ["https://one.example/feed"]
        finder.batch_discover.assert_called_once()

    def test_batch_with_no_feeds_exits_one_and_does_not_export(self, tmp_path):
        urls = tmp_path / "urls.txt"
        urls.write_text("https://one.example\n", encoding="utf-8")
        out = tmp_path / "out.json"
        finder = Mock()
        finder.batch_discover.return_value = {"https://one.example": []}

        with patch("ebff.cli.FeedFinder", return_value=finder):
            code = _run(["ebff", "--batch", str(urls), "--output", str(out)])

        assert code == 1
        assert out.exists() is False
