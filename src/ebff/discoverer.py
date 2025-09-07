"""
Core Feed Discovery Engine for EBFF
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set, Optional, Dict
from urllib.parse import urljoin, urlparse
import validators

from .models import FeedInfo
from .config import ConfigManager
from .http_client import HTTPClient
from .validator import FeedValidator
from .plugins import PluginManager


logger = logging.getLogger(__name__)


class FeedDiscoverer:
    """Core feed discovery engine with pluggable discovery methods"""
    
    def __init__(self, config_manager: ConfigManager = None):
        self.config = config_manager or ConfigManager()
        self.http_client = HTTPClient(self.config)
        self.validator = FeedValidator(self.config)
        self.plugin_manager = PluginManager(self.http_client, self.validator, self.config)
        self._discovered_feeds: Set[str] = set()
    
    def discover(self, url: str, deep_scan: bool = None, 
                 validate_quality: bool = None, min_score: int = None,
                 quick_mode: bool = False) -> List[FeedInfo]:
        """
        Main discovery method - finds all feeds for a given URL
        
        Args:
            url: The URL to search for feeds
            deep_scan: Whether to use all discovery methods
            validate_quality: Whether to validate and score feeds
            min_score: Minimum quality score to include feed
            quick_mode: Stop as soon as valid feeds are found
            
        Returns:
            List of FeedInfo objects for discovered feeds
        """
        # Use config defaults if not specified
        deep_scan = deep_scan if deep_scan is not None else self.config.get('deep_scan')
        validate_quality = validate_quality if validate_quality is not None else self.config.get('validate_quality')
        min_score = min_score if min_score is not None else self.config.get('min_score')
        
        # Normalize URL
        url = self._normalize_url(url)
        if not url:
            logger.error(f"Invalid URL provided: {url}")
            return []
        
        logger.debug(f"Starting feed discovery for: {url}")
        self._discovered_feeds.clear()
        feeds = []
        
        print(f"\n🔍 Discovering feeds for: {url}")
        
        # Method 1: Check common URL patterns
        print("Checking feed patterns: ", end="", flush=True)
        pattern_feeds = self.plugin_manager.get_plugin("common_pattern").discover(url)
        feeds.extend(pattern_feeds)
        print(" Done!")
        
        if quick_mode and feeds:
            print("✅ Found feeds! (quick mode)")
            return self._finalize_feeds(feeds, validate_quality, min_score)
        
        if not deep_scan:
            return self._finalize_feeds(feeds, validate_quality, min_score)
        
        # Method 2: Parse HTML for link tags
        print("Parsing HTML: ", end="", flush=True)
        html_feeds = self.plugin_manager.get_plugin("html_link").discover(url)
        feeds.extend(html_feeds)
        print("✓" if html_feeds else "✗")
        
        # Method 3: Check meta tags
        print("Analyzing meta tags: ", end="", flush=True)
        meta_feeds = self.plugin_manager.get_plugin("meta_tag").discover(url)
        feeds.extend(meta_feeds)
        print("✓" if meta_feeds else "✗")
        
        # Method 4: Check sitemap
        print("Checking sitemap: ", end="", flush=True)
        sitemap_feeds = self.plugin_manager.get_plugin("sitemap").discover(url)
        feeds.extend(sitemap_feeds)
        print("✓" if sitemap_feeds else "✗")
        
        # Method 5: Content sniffing
        print("Content sniffing: ", end="", flush=True)
        sniff_feeds = self.plugin_manager.get_plugin("content_sniff").discover(url)
        feeds.extend(sniff_feeds)
        print("✓" if sniff_feeds else "✗")
        
        return self._finalize_feeds(feeds, validate_quality, min_score)
    
    def _finalize_feeds(self, feeds: List[FeedInfo], validate_quality: bool, min_score: int) -> List[FeedInfo]:
        """Finalize feeds by deduplicating, validating, and scoring"""
        if not feeds:
            return feeds
        
        # Deduplicate feeds
        feeds = self.validator.deduplicate_feeds(feeds)
        
        # Validate and score feeds if requested
        if validate_quality:
            feeds = self.validator.validate_and_score_feeds(feeds)
            
            # Filter by minimum score
            if min_score > 0:
                feeds = [f for f in feeds if f.quality_score >= min_score]
        
        # Sort by quality score (highest first)
        feeds.sort(key=lambda f: f.quality_score, reverse=True)
        
        return feeds
    
    def _normalize_url(self, url: str) -> Optional[str]:
        """Normalize and validate URL"""
        if not url or not isinstance(url, str):
            return None
        
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Basic validation
        if not validators.url(url):
            return None
        
        # Parse and reconstruct to normalize
        parsed = urlparse(url)
        
        # Remove trailing slash from path
        path = parsed.path.rstrip('/') if parsed.path != '/' else ''
        
        # Reconstruct URL
        if path:
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        else:
            return f"{parsed.scheme}://{parsed.netloc}"
    
    def _check_single_pattern(self, base_url: str, pattern: str) -> Optional[FeedInfo]:
        """Check a single feed pattern - helper for parallel execution"""
        feed_url = urljoin(base_url, pattern)
        
        # Skip if already checked
        if feed_url in self._discovered_feeds:
            return None
        
        # Try to fetch
        response = self.http_client.get(feed_url)
        if response and response.status_code == 200:
            if self.validator.is_feed_content(response.text):
                self._discovered_feeds.add(feed_url)
                feed_info = self.validator.parse_feed(feed_url, response.text)
                if feed_info:
                    feed_info.discovery_method = "common_pattern"
                    logger.debug(f"Found feed via pattern: {feed_url}")
                    return feed_info
        
        return None
    
    def _check_common_patterns(self, base_url: str) -> List[FeedInfo]:
        """Check common feed URL patterns in parallel"""
        discovered = []
        print("Checking feed patterns: ", end="", flush=True)
        
        patterns_to_check = self.config.get('feed_patterns')[:self.config.get('max_patterns_to_check')]
        completed = 0
        
        # Use ThreadPoolExecutor for parallel pattern checking
        with ThreadPoolExecutor(max_workers=self.config.get('max_workers')) as executor:
            # Submit all pattern checks
            future_to_pattern = {
                executor.submit(self._check_single_pattern, base_url, pattern): pattern
                for pattern in patterns_to_check
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_pattern):
                completed += 1
                if completed % 5 == 0:
                    print("#", end="", flush=True)
                    
                try:
                    result = future.result()
                    if result:
                        discovered.append(result)
                except Exception as e:
                    pattern = future_to_pattern[future]
                    logger.warning(f"Pattern check failed for {pattern}: {e}")
        
        print(" Done!")
        return discovered
    
    def _parse_html_links(self, url: str) -> List[FeedInfo]:
        """Parse HTML page for feed links in <link> tags"""
        discovered = []
        
        response = self.http_client.get(url)
        if not response or response.status_code != 200:
            return discovered
        
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            return discovered
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find feed links
            link_tags = soup.find_all('link', rel='alternate')
            
            for link in link_tags:
                feed_type = link.get('type', '').lower()
                href = link.get('href')
                
                if not href:
                    continue
                
                # Check if it's a feed type
                if any(feed_type_indicator in feed_type for feed_type_indicator in [
                    'rss', 'atom', 'application/rss+xml', 'application/atom+xml',
                    'application/json', 'application/feed+json'
                ]):
                    feed_url = urljoin(url, href)
                    
                    if feed_url not in self._discovered_feeds:
                        self._discovered_feeds.add(feed_url)
                        
                        # Fetch and parse the feed
                        feed_response = self.http_client.get(feed_url)
                        if feed_response and feed_response.status_code == 200:
                            feed_info = self.validator.parse_feed(feed_url, feed_response.text)
                            if feed_info:
                                feed_info.discovery_method = "html_link"
                                discovered.append(feed_info)
                                logger.debug(f"Found feed via HTML link: {feed_url}")
        
        except Exception as e:
            logger.warning(f"Failed to parse HTML links for {url}: {e}")
        
        return discovered
    
    def _analyze_meta_tags(self, url: str) -> List[FeedInfo]:
        """Analyze meta tags for feed information"""
        # Implementation similar to original but using new architecture
        # Simplified for brevity - would include full meta tag analysis
        return []
    
    def _check_sitemap(self, url: str) -> List[FeedInfo]:
        """Check sitemap for feed links"""
        # Implementation similar to original but using new architecture
        # Simplified for brevity - would include full sitemap checking
        return []
    
    def _sniff_content(self, url: str) -> List[FeedInfo]:
        """Content sniffing for feeds"""
        # Implementation similar to original but using new architecture
        # Simplified for brevity - would include content sniffing
        return []
    
    def batch_discover(self, urls: List[str], max_workers: int = None) -> Dict[str, List[FeedInfo]]:
        """Discover feeds for multiple URLs concurrently"""
        max_workers = max_workers or self.config.get('max_workers')
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all discovery tasks
            future_to_url = {
                executor.submit(self.discover, url): url
                for url in urls
            }
            
            # Collect results
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    feeds = future.result()
                    results[url] = feeds
                except Exception as e:
                    logger.error(f"Discovery failed for {url}: {e}")
                    results[url] = []
        
        return results
    
    def close(self) -> None:
        """Close resources"""
        if self.http_client:
            self.http_client.close()
        if self.plugin_manager:
            self.plugin_manager.clear_all_caches()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()