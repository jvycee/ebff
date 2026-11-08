"""
EBFF - Even Better Feed Finder
Core Discovery Engine for RSS/Atom/JSON feeds
"""

import re
import time
import logging
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import feedparser
from bs4 import BeautifulSoup
import validators
import tldextract

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Import FeedInfo from models for backward compatibility
from .models import FeedInfo


class FeedFinder:
    """Main class for discovering RSS/Atom/JSON feeds"""
    
    # Common feed URL patterns (top patterns first for speed)
    COMMON_FEED_PATTERNS = [
        '/feed', '/rss', '/feed/', '/rss/', '/rss.xml', '/feed.xml',
        '/atom.xml', '/feed.atom', '/feed.rss', '/index.xml', '/index.rss',
        '/blog/feed', '/blog/rss', '/news/feed', '/news/rss',
        '/feed/rss2', '/feed/atom', '/rss2.xml', '/atom', '/atom/',
        '/?feed=rss', '/?feed=rss2', '/?feed=atom',
        '/feed.php', '/rss.php', '/feeds/posts/default',
        '/podcast.xml', '/podcast/feed', '/episodes/feed',
    ]
    
    # User agent for requests
    USER_AGENTS = [
        'Mozilla/5.0 (compatible; EBFF/1.0; +https://github.com/yourusername/ebff)',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    ]
    
    def __init__(self, timeout: int = 10, max_retries: int = 3):
        """Initialize FeedFinder with optimized connection pooling"""
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Create session with optimized connection pooling
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],  # Updated parameter name
            backoff_factor=1
        )
        
        # Configure HTTP adapter with connection pooling
        adapter = HTTPAdapter(
            pool_connections=20,  # Number of connection pools to cache
            pool_maxsize=20,      # Maximum number of connections in pool
            max_retries=retry_strategy
        )
        
        # Mount adapter for both HTTP and HTTPS
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers
        self.session.headers.update({
            'User-Agent': self.USER_AGENTS[0],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        self._discovered_feeds: Set[str] = set()
        self._request_cache: Dict[str, requests.Response] = {}
    
    def discover(self, url: str, deep_scan: bool = True, 
                 validate_quality: bool = True,
                 min_score: int = 0,
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
        feeds.extend(self._check_common_patterns(url))
        
        # Method 2: Parse HTML for link tags
        print("Parsing HTML: ", end="", flush=True)
        feeds.extend(self._parse_html_links(url))
        print("✓")
        
        # Quick mode: stop if we found valid feeds
        if quick_mode and feeds:
            print("\n✅ Found feeds! (quick mode)\n")
            unique_feeds = self._deduplicate_feeds(feeds)
            if validate_quality:
                unique_feeds = self._validate_and_score_feeds(unique_feeds)
            if min_score > 0:
                unique_feeds = [f for f in unique_feeds if f.quality_score >= min_score]
            return sorted(unique_feeds, key=lambda x: x.quality_score, reverse=True)
        
        if deep_scan:
            # Method 3: Check meta tags
            print("Checking meta tags: ", end="", flush=True)
            feeds.extend(self._analyze_meta_tags(url))
            print("✓")
            
            # Only check sitemap if we haven't found good feeds yet
            if not feeds or not any(f.validation_status == "valid" for f in feeds):
                # Method 4: Check sitemap (with limits)
                print("Checking sitemap: ", end="", flush=True)
                feeds.extend(self._check_sitemap(url))
                print("✓")
            
            # Method 5: Content sniffing
            print("Content sniffing: ", end="", flush=True)
            feeds.extend(self._sniff_content(url))
            print("✓")
        
        # Deduplicate feeds
        unique_feeds = self._deduplicate_feeds(feeds)
        
        # Validate and score feeds if requested
        if validate_quality:
            unique_feeds = self._validate_and_score_feeds(unique_feeds)
        
        # Filter by minimum score
        if min_score > 0:
            unique_feeds = [f for f in unique_feeds if f.quality_score >= min_score]
        
        return sorted(unique_feeds, key=lambda x: x.quality_score, reverse=True)
    
    def _normalize_url(self, url: str) -> Optional[str]:
        """Normalize and validate URL"""
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Validate URL
        if not validators.url(url):
            return None
        
        # Parse and reconstruct
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        
        # Return base URL if path is just '/'
        if parsed.path in ('', '/'):
            return f"{parsed.scheme}://{parsed.netloc}"
        
        return url
    
    def _make_request(self, url: str, timeout: Optional[int] = None) -> Optional[requests.Response]:
        """Make HTTP request with connection pooling and caching"""
        timeout = timeout or self.timeout
        
        # Check cache first
        if url in self._request_cache:
            cached_response = self._request_cache[url]
            # Simple cache validation - could be enhanced with timestamps
            if cached_response.status_code == 200:
                return cached_response
        
        try:
            response = self.session.get(
                url, 
                timeout=timeout,
                allow_redirects=True,
                verify=True
            )
            
            # Cache successful responses
            if response.status_code == 200:
                # Simple cache with size limit
                if len(self._request_cache) < 100:
                    self._request_cache[url] = response
                return response
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed for {url}: {e}")
        
        return None
    
    def _check_single_pattern(self, base_url: str, pattern: str) -> Optional[FeedInfo]:
        """Check a single feed pattern - helper for parallel execution"""
        feed_url = urljoin(base_url, pattern)
        
        # Skip if already checked
        if feed_url in self._discovered_feeds:
            return None
        
        # Try to fetch
        response = self._make_request(feed_url)
        if response and self._is_feed_content(response.text):
            self._discovered_feeds.add(feed_url)
            feed_info = self._parse_feed(feed_url, response.text)
            if feed_info:
                feed_info.discovery_method = "common_pattern"
                logger.debug(f"Found feed via pattern: {feed_url}")
                return feed_info
        
        return None

    def _check_common_patterns(self, base_url: str) -> List[FeedInfo]:
        """Check common feed URL patterns in parallel"""
        discovered = []
        print("Checking feed patterns: ", end="", flush=True)
        
        patterns_to_check = self.COMMON_FEED_PATTERNS[:20]  # Check top 20 patterns
        completed = 0
        
        # Use ThreadPoolExecutor for parallel pattern checking
        with ThreadPoolExecutor(max_workers=8) as executor:
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
        
        response = self._make_request(url)
        if not response:
            return discovered
        
        try:
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Look for feed links
            feed_links = soup.find_all('link', attrs={
                'type': re.compile(r'application/(rss|atom|json|feed)')
            })
            
            # Also check for alternate links
            alt_links = soup.find_all('link', attrs={'rel': 'alternate'})
            feed_links.extend([link for link in alt_links 
                             if link.get('type', '').startswith(('application/rss',
                                                                 'application/atom',
                                                                 'application/feed',
                                                                 'application/json'))])
            
            for link in feed_links:
                feed_url = link.get('href')
                if not feed_url:
                    continue
                
                # Make URL absolute
                feed_url = urljoin(url, feed_url)
                
                # Skip if already discovered
                if feed_url in self._discovered_feeds:
                    continue
                
                self._discovered_feeds.add(feed_url)
                
                # Create feed info
                feed_info = FeedInfo(
                    url=feed_url,
                    title=link.get('title'),
                    feed_type=self._detect_feed_type_from_mime(link.get('type')),
                    discovery_method="html_link"
                )
                
                # Try to fetch and parse feed
                feed_response = self._make_request(feed_url)
                if feed_response:
                    parsed = self._parse_feed(feed_url, feed_response.text)
                    if parsed:
                        feed_info = parsed
                        feed_info.discovery_method = "html_link"
                
                discovered.append(feed_info)
                logger.debug(f"Found feed via HTML link: {feed_url}")
        
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
        
        return discovered
    
    def _analyze_meta_tags(self, url: str) -> List[FeedInfo]:
        """Analyze meta tags for feed information"""
        discovered = []
        
        response = self._make_request(url)
        if not response:
            return discovered
        
        try:
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Check Open Graph
            og_feed = soup.find('meta', attrs={'property': 'og:feed'})
            if og_feed and og_feed.get('content'):
                feed_url = urljoin(url, og_feed['content'])
                if feed_url not in self._discovered_feeds:
                    self._discovered_feeds.add(feed_url)
                    feed_info = self._fetch_and_parse_feed(feed_url)
                    if feed_info:
                        feed_info.discovery_method = "meta_tag_og"
                        discovered.append(feed_info)
        
        except Exception as e:
            logger.error(f"Error analyzing meta tags: {e}")
        
        return discovered
    
    def _check_sitemap(self, base_url: str) -> List[FeedInfo]:
        """Check sitemap.xml for feed URLs"""
        discovered = []
        sitemap_urls = [
            urljoin(base_url, '/sitemap.xml'),
            urljoin(base_url, '/sitemap_index.xml'),
        ]
        
        for sitemap_url in sitemap_urls:
            response = self._make_request(sitemap_url)
            if not response:
                continue
            
            try:
                soup = BeautifulSoup(response.text, 'xml')
                urls = soup.find_all('loc')
                
                for url_tag in urls[:50]:  # Limit to 50 URLs for speed
                    url = url_tag.text
                    # Skip sitemap index files and pagination
                    if any(skip in url.lower() for skip in 
                          ['sitemap-page-', 'sitemap_index', 'sitemap-index']):
                        continue
                    
                    # Check if URL looks like a feed (be more specific)
                    if any(indicator in url.lower() for indicator in 
                          ['/feed', '/rss', '/atom', 'feed.xml', 'rss.xml']):
                        if url not in self._discovered_feeds:
                            feed_response = self._make_request(url)
                            if feed_response and self._is_feed_content(feed_response.text):
                                self._discovered_feeds.add(url)
                                feed_info = self._parse_feed(url, feed_response.text)
                                if feed_info:
                                    feed_info.discovery_method = "sitemap"
                                    discovered.append(feed_info)
                                    logger.debug(f"Found feed via sitemap: {url}")
            
            except Exception as e:
                logger.error(f"Error parsing sitemap: {e}")
        
        return discovered
    
    def _sniff_content(self, base_url: str) -> List[FeedInfo]:
        """Sniff content to detect feeds even without proper content-type"""
        discovered = []
        
        # Additional URLs to check
        check_urls = [
            urljoin(base_url, '/blog'),
            urljoin(base_url, '/news'),
        ]
        
        for url in check_urls:
            response = self._make_request(url)
            if not response:
                continue
            
            # Check if the content itself is a feed
            if self._is_feed_content(response.text):
                if url not in self._discovered_feeds:
                    self._discovered_feeds.add(url)
                    feed_info = self._parse_feed(url, response.text)
                    if feed_info:
                        feed_info.discovery_method = "content_sniffing"
                        discovered.append(feed_info)
        
        return discovered
    
    def _is_feed_content(self, content: str) -> bool:
        """Check if content appears to be a feed"""
        if not content:
            return False
        
        content_lower = content[:5000].lower()  # Check first 5KB
        
        # Check for feed indicators
        feed_indicators = [
            '<?xml', '<rss', '<feed', '<atom',
            '<channel>', '<item>', '<entry>',
            'xmlns:atom', 'xmlns:content',
            'application/rss+xml', 'application/atom+xml',
            '"version":"https://jsonfeed.org',  # JSON Feed
        ]
        
        return any(indicator in content_lower for indicator in feed_indicators)
    
    def _detect_feed_type_from_mime(self, mime_type: str) -> str:
        """Detect feed type from MIME type"""
        if not mime_type:
            return "unknown"
        
        mime_lower = mime_type.lower()
        if 'rss' in mime_lower:
            return "rss"
        elif 'atom' in mime_lower:
            return "atom"
        elif 'json' in mime_lower:
            return "json"
        else:
            return "unknown"
    
    def _parse_feed(self, url: str, content: str) -> Optional[FeedInfo]:
        """Parse feed content and extract information"""
        try:
            # Try feedparser first
            parsed = feedparser.parse(content)
            
            if not parsed.bozo or parsed.entries:  # Valid feed or has entries despite bozo
                feed_info = FeedInfo(url=url)
                
                # Extract feed information
                feed = parsed.feed
                feed_info.title = feed.get('title', '')
                feed_info.description = feed.get('description', '')
                feed_info.language = feed.get('language', '')
                feed_info.entry_count = len(parsed.entries)
                
                # Detect feed type
                if parsed.version:
                    if 'rss' in parsed.version.lower():
                        feed_info.feed_type = 'rss'
                    elif 'atom' in parsed.version.lower():
                        feed_info.feed_type = 'atom'
                    else:
                        feed_info.feed_type = parsed.version
                
                # Get last updated
                if parsed.entries:
                    latest_entry = parsed.entries[0]
                    if hasattr(latest_entry, 'published_parsed'):
                        feed_info.last_updated = datetime.fromtimestamp(
                            time.mktime(latest_entry.published_parsed)
                        )
                
                feed_info.validation_status = "valid"
                return feed_info
            
            # Check if it might be JSON Feed
            if content.strip().startswith('{'):
                try:
                    import json
                    json_data = json.loads(content)
                    if json_data.get('version', '').startswith('https://jsonfeed.org'):
                        feed_info = FeedInfo(
                            url=url,
                            title=json_data.get('title', ''),
                            description=json_data.get('description', ''),
                            feed_type='json',
                            entry_count=len(json_data.get('items', [])),
                            validation_status='valid'
                        )
                        return feed_info
                except:
                    pass
        
        except Exception as e:
            logger.warning(f"Error parsing feed {url}: {e}")
        
        return None
    
    def _fetch_and_parse_feed(self, url: str) -> Optional[FeedInfo]:
        """Fetch and parse a feed from URL"""
        response = self._make_request(url)
        if response:
            return self._parse_feed(url, response.text)
        return None
    
    def _deduplicate_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Remove duplicate feeds based on URL and content"""
        seen_urls = set()
        seen_content = {}
        unique = []
        
        for feed in feeds:
            # Normalize URL for comparison
            normalized = feed.url.rstrip('/').replace('//', '/')
            
            # Create content signature
            content_sig = f"{feed.title}:{feed.feed_type}:{feed.entry_count}"
            
            # Check if we've seen this exact URL
            if feed.url in seen_urls:
                continue
                
            # Check if we've seen this content (same feed, different URL)
            if content_sig in seen_content:
                # Keep the one with shorter/cleaner URL
                existing = seen_content[content_sig]
                if len(feed.url) < len(existing.url) or '/feed' in feed.url.lower():
                    # Replace with better URL
                    unique = [f if f.url != existing.url else feed for f in unique]
                    seen_urls.discard(existing.url)
                    seen_urls.add(feed.url)
                    seen_content[content_sig] = feed
                continue
            
            # New unique feed
            seen_urls.add(feed.url)
            seen_content[content_sig] = feed
            unique.append(feed)
        
        return unique
    
    def _validate_and_score_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Validate and score feeds for quality"""
        for feed in feeds:
            score = 0
            
            # Has title and description
            if feed.title:
                score += 10
            if feed.description:
                score += 10
            
            # Has recent content
            if feed.last_updated:
                days_old = (datetime.now() - feed.last_updated).days
                if days_old <= 7:
                    score += 30
                elif days_old <= 30:
                    score += 20
                elif days_old <= 90:
                    score += 10
            
            # Has multiple entries
            if feed.entry_count >= 10:
                score += 20
            elif feed.entry_count >= 5:
                score += 15
            elif feed.entry_count >= 1:
                score += 10
            
            # Valid feed structure
            if feed.validation_status == "valid":
                score += 20
            
            # Known feed type
            if feed.feed_type in ('rss', 'atom', 'json'):
                score += 10
            
            feed.quality_score = min(score, 100)
        
        return feeds
    
    def batch_discover(self, urls: List[str], max_workers: int = 10) -> Dict[str, List[FeedInfo]]:
        """Discover feeds for multiple URLs concurrently"""
        results = {}
        total = len(urls)
        completed = 0
        
        print(f"\n🚀 Batch processing {total} sites with {max_workers} workers\n")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Use quick mode for batch processing
            future_to_url = {
                executor.submit(self.discover, url, quick_mode=True): url 
                for url in urls
            }
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                
                try:
                    feeds = future.result()
                    results[url] = feeds
                    
                    # Progress indicator
                    feed_count = len(feeds)
                    status = "✅" if feed_count > 0 else "❌"
                    print(f"{status} [{completed}/{total}] {url}: {feed_count} feed(s) found")
                    
                except Exception as e:
                    logger.error(f"Error discovering feeds for {url}: {e}")
                    results[url] = []
                    print(f"❌ [{completed}/{total}] {url}: Error")
        
        elapsed = time.time() - start_time
        print(f"\n⏱️  Completed in {elapsed:.1f} seconds ({elapsed/total:.2f}s per site)")
        print(f"📊 Success rate: {sum(1 for v in results.values() if v)}/{total} sites with feeds")
        
        return results
