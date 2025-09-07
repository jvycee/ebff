"""
Tests for CLI functionality
"""

import pytest
from unittest.mock import patch, Mock
from io import StringIO
import sys

from ebff.cli import main
from ebff import FeedInfo


class TestCLI:
    """Test CLI argument parsing and functionality"""
    
    # Note: parse_args is internal to main(), so we test through main() integration

    @patch('ebff.cli.FeedFinder')
    @patch('sys.stdout', new_callable=StringIO)
    def test_main_basic_usage(self, mock_stdout, mock_finder_class):
        """Test basic CLI usage"""
        mock_finder = Mock()
        mock_finder_class.return_value = mock_finder
        
        # Mock successful feed discovery
        mock_feeds = [
            FeedInfo(
                url="https://techcrunch.com/feed/",
                title="TechCrunch",
                feed_type="rss",
                quality_score=85,
                entry_count=10
            )
        ]
        mock_finder.discover.return_value = mock_feeds
        
        # Mock sys.argv
        with patch.object(sys, 'argv', ['cli.py', 'techcrunch.com', '--quick']):
            try:
                main()
            except SystemExit:
                pass  # CLI calls sys.exit normally
        
        # Verify finder was called with correct parameters
        mock_finder.discover.assert_called_once()
        
        # Verify output contains feed information
        output = mock_stdout.getvalue()
        assert "techcrunch.com" in output.lower() or "TechCrunch" in output

    @patch('ebff.cli.FeedFinder')
    def test_main_no_feeds_found(self, mock_finder_class):
        """Test CLI behavior when no feeds are found"""
        mock_finder = Mock()
        mock_finder_class.return_value = mock_finder
        mock_finder.discover.return_value = []
        
        with patch.object(sys, 'argv', ['cli.py', 'example.com']):
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                try:
                    main()
                except SystemExit:
                    pass
                
                output = mock_stdout.getvalue()
                assert "No feeds found" in output or "no feeds" in output.lower()

    @patch('ebff.cli.FeedFinder')
    def test_main_with_error(self, mock_finder_class):
        """Test CLI behavior when discovery fails"""
        mock_finder = Mock()
        mock_finder_class.return_value = mock_finder
        mock_finder.discover.side_effect = Exception("Network error")
        
        with patch.object(sys, 'argv', ['cli.py', 'example.com']):
            with patch('sys.stdout', new_callable=StringIO):
                with pytest.raises(SystemExit):
                    main()