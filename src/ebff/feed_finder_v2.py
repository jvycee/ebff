"""
Backward-compatible FeedFinder implementation using new architecture
"""

from typing import List, Dict

from .models import FeedInfo
from .config import ConfigManager
from .discoverer import FeedDiscoverer


class FeedFinder:
    """
    Backward-compatible interface to EBFF feed discovery
    
    This class maintains the original API while using the new modular architecture internally.
    For new projects, consider using FeedDiscoverer directly for more flexibility.
    """
    
    def __init__(self, timeout: int = 10, max_retries: int = 3):
        """Initialize FeedFinder with backward compatibility"""
        # Create config from parameters
        config_data = {
            'timeout': timeout,
            'max_retries': max_retries,
        }
        
        self.config_manager = ConfigManager.from_dict(config_data)
        self.discoverer = FeedDiscoverer(self.config_manager)
        
        # Expose some properties for backward compatibility
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = self.discoverer.http_client._session  # Expose session for compatibility
    
    def discover(self, url: str, deep_scan: bool = True, 
                 validate_quality: bool = True,
                 min_score: int = 0,
                 quick_mode: bool = False) -> List[FeedInfo]:
        """
        Main discovery method - backward compatible interface
        
        Args:
            url: The URL to search for feeds
            deep_scan: Whether to use all discovery methods
            validate_quality: Whether to validate and score feeds
            min_score: Minimum quality score to include feed
            quick_mode: Stop as soon as valid feeds are found
            
        Returns:
            List of FeedInfo objects for discovered feeds
        """
        return self.discoverer.discover(
            url=url,
            deep_scan=deep_scan,
            validate_quality=validate_quality,
            min_score=min_score,
            quick_mode=quick_mode
        )
    
    def batch_discover(self, urls: List[str], max_workers: int = 10) -> Dict[str, List[FeedInfo]]:
        """Discover feeds for multiple URLs concurrently"""
        return self.discoverer.batch_discover(urls, max_workers)
    
    # Expose internal methods for backward compatibility
    def _normalize_url(self, url: str):
        """Backward compatibility method"""
        return self.discoverer._normalize_url(url)
    
    def _make_request(self, url: str, timeout=None):
        """Backward compatibility method"""
        return self.discoverer.http_client.get(url, timeout)
    
    def _is_feed_content(self, content: str) -> bool:
        """Backward compatibility method"""
        return self.discoverer.validator.is_feed_content(content)
    
    def _parse_feed(self, url: str, content: str):
        """Backward compatibility method"""
        return self.discoverer.validator.parse_feed(url, content)
    
    def _validate_and_score_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Backward compatibility method"""
        return self.discoverer.validator.validate_and_score_feeds(feeds)
    
    def _deduplicate_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Backward compatibility method"""
        return self.discoverer.validator.deduplicate_feeds(feeds)
    
    def close(self):
        """Close resources"""
        self.discoverer.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()