"""
Plugin architecture for EBFF discovery methods
"""

import json
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Set, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import FeedInfo
from .config import ConfigManager
from .http_client import HTTPClient
from .validator import FeedValidator


logger = logging.getLogger(__name__)


class DiscoveryMethod(ABC):
    """Abstract base class for feed discovery methods"""
    
    def __init__(self, name: str, http_client: HTTPClient, validator: FeedValidator, 
                 config: ConfigManager):
        self.name = name
        self.http_client = http_client
        self.validator = validator
        self.config = config
        self._discovered_urls: Set[str] = set()
    
    @abstractmethod
    def discover(self, url: str) -> List[FeedInfo]:
        """Discover feeds using this method"""
        pass
    
    def is_url_discovered(self, url: str) -> bool:
        """Check if URL was already discovered"""
        return url in self._discovered_urls
    
    def mark_discovered(self, url: str) -> None:
        """Mark URL as discovered"""
        self._discovered_urls.add(url)
    
    def clear_cache(self) -> None:
        """Clear discovery cache"""
        self._discovered_urls.clear()


class PatternDiscovery(DiscoveryMethod):
    """Discovery method using common URL patterns"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        super().__init__("common_pattern", http_client, validator, config)
    
    def discover(self, url: str) -> List[FeedInfo]:
        """Check common feed URL patterns in parallel"""
        discovered = []
        patterns_to_check = self.config.get('feed_patterns')[:self.config.get('max_patterns_to_check')]
        
        # Use ThreadPoolExecutor for parallel pattern checking
        with ThreadPoolExecutor(max_workers=self.config.get('max_workers')) as executor:
            # Submit all pattern checks
            future_to_pattern = {
                executor.submit(self._check_single_pattern, url, pattern): pattern
                for pattern in patterns_to_check
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_pattern):
                try:
                    result = future.result()
                    if result:
                        discovered.append(result)
                except Exception as e:
                    pattern = future_to_pattern[future]
                    logger.warning(f"Pattern check failed for {pattern}: {e}")
        
        return discovered
    
    def _check_single_pattern(self, base_url: str, pattern: str) -> Optional[FeedInfo]:
        """Check a single feed pattern"""
        feed_url = urljoin(base_url, pattern)
        
        # Skip if already checked
        if self.is_url_discovered(feed_url):
            return None
        
        # Try to fetch
        response = self.http_client.get(feed_url)
        if response and response.status_code == 200:
            if self.validator.is_feed_content(response.text):
                self.mark_discovered(feed_url)
                feed_info = self.validator.parse_feed(feed_url, response.text)
                if feed_info:
                    feed_info.discovery_method = self.name
                    logger.debug(f"Found feed via pattern: {feed_url}")
                    return feed_info
        
        return None


class HTMLLinkDiscovery(DiscoveryMethod):
    """Discovery method using HTML <link> tags"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        super().__init__("html_link", http_client, validator, config)
    
    def discover(self, url: str) -> List[FeedInfo]:
        """Parse HTML page for feed links in <link> tags"""
        discovered = []
        
        response = self.http_client.get(url)
        if not response or response.status_code != 200:
            return discovered
        
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            return discovered
        
        try:
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
                    
                    # Pre-filter junk URLs at discovery level
                    if self.validator.is_junk_feed_url(feed_url):
                        logger.debug(f"Skipping junk feed URL during discovery: {feed_url}")
                        continue
                    
                    if not self.is_url_discovered(feed_url):
                        self.mark_discovered(feed_url)
                        
                        # Fetch and parse the feed
                        feed_response = self.http_client.get(feed_url)
                        if feed_response and feed_response.status_code == 200:
                            feed_info = self.validator.parse_feed(feed_url, feed_response.text)
                            if feed_info:
                                feed_info.discovery_method = self.name
                                discovered.append(feed_info)
                                logger.debug(f"Found feed via HTML link: {feed_url}")
        
        except Exception as e:
            logger.warning(f"Failed to parse HTML links for {url}: {e}")
        
        return discovered


class MetaTagDiscovery(DiscoveryMethod):
    """Discovery method using meta tags"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        super().__init__("meta_tag", http_client, validator, config)
    
    def discover(self, url: str) -> List[FeedInfo]:
        """Analyze meta tags for feed information"""
        discovered = []
        
        response = self.http_client.get(url)
        if not response or response.status_code != 200:
            return discovered
        
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for RSS/Atom meta tags
            meta_tags = soup.find_all('meta', attrs={
                'property': ['og:type', 'article:section'],
                'name': ['generator', 'RSS', 'feed']
            })
            
            # Look for generator meta tags indicating feed-capable CMS
            generators = ['WordPress', 'Drupal', 'Joomla', 'Ghost', 'Medium']
            
            for meta in meta_tags:
                content = meta.get('content', '').lower()
                if any(gen.lower() in content for gen in generators):
                    # Try common feed URLs for known generators
                    common_feeds = ['/feed/', '/rss/', '/atom.xml']
                    for feed_path in common_feeds:
                        feed_url = urljoin(url, feed_path)
                        if not self.is_url_discovered(feed_url):
                            feed_response = self.http_client.get(feed_url)
                            if feed_response and feed_response.status_code == 200:
                                if self.validator.is_feed_content(feed_response.text):
                                    self.mark_discovered(feed_url)
                                    feed_info = self.validator.parse_feed(feed_url, feed_response.text)
                                    if feed_info:
                                        feed_info.discovery_method = self.name
                                        discovered.append(feed_info)
                                        logger.debug(f"Found feed via meta tag: {feed_url}")
                                        break
        
        except Exception as e:
            logger.warning(f"Failed to analyze meta tags for {url}: {e}")
        
        return discovered


class SitemapDiscovery(DiscoveryMethod):
    """Discovery method using sitemaps"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        super().__init__("sitemap", http_client, validator, config)
    
    def discover(self, url: str) -> List[FeedInfo]:
        """Check sitemap for feed links"""
        discovered = []
        
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Common sitemap locations
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/robots.txt"
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                response = self.http_client.get(sitemap_url)
                if not response or response.status_code != 200:
                    continue
                
                # Parse sitemap content
                if 'robots.txt' in sitemap_url:
                    # Look for sitemap references in robots.txt
                    for line in response.text.split('\n'):
                        if line.lower().startswith('sitemap:'):
                            actual_sitemap = line.split(':', 1)[1].strip()
                            sitemap_urls.append(actual_sitemap)
                else:
                    # Parse XML sitemap
                    soup = BeautifulSoup(response.text, 'xml')
                    urls = soup.find_all('url')
                    
                    for url_entry in urls[:10]:  # Limit to first 10 URLs
                        loc = url_entry.find('loc')
                        if loc and loc.text:
                            potential_url = loc.text
                            if any(feed_indicator in potential_url.lower() 
                                  for feed_indicator in ['feed', 'rss', 'atom']):
                                if not self.is_url_discovered(potential_url):
                                    feed_response = self.http_client.get(potential_url)
                                    if feed_response and feed_response.status_code == 200:
                                        if self.validator.is_feed_content(feed_response.text):
                                            self.mark_discovered(potential_url)
                                            feed_info = self.validator.parse_feed(potential_url, feed_response.text)
                                            if feed_info:
                                                feed_info.discovery_method = self.name
                                                discovered.append(feed_info)
                                                logger.debug(f"Found feed via sitemap: {potential_url}")
                
            except Exception as e:
                logger.warning(f"Failed to check sitemap {sitemap_url}: {e}")
        
        return discovered


class ContentSniffDiscovery(DiscoveryMethod):
    """Discovery method using content analysis"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        super().__init__("content_sniff", http_client, validator, config)
    
    def discover(self, url: str) -> List[FeedInfo]:
        """Content sniffing for feeds"""
        discovered = []
        
        response = self.http_client.get(url)
        if not response or response.status_code != 200:
            return discovered
        
        # Check if the URL itself might be a feed
        if not self.is_url_discovered(url):
            if self.validator.is_feed_content(response.text):
                self.mark_discovered(url)
                feed_info = self.validator.parse_feed(url, response.text)
                if feed_info:
                    feed_info.discovery_method = self.name
                    discovered.append(feed_info)
                    logger.debug(f"Found feed via content sniff: {url}")
        
        return discovered


class PluginManager:
    """Manages discovery method plugins"""
    
    def __init__(self, http_client: HTTPClient, validator: FeedValidator, config: ConfigManager):
        self.http_client = http_client
        self.validator = validator
        self.config = config
        self._plugins: Dict[str, DiscoveryMethod] = {}
        self._load_default_plugins()
    
    def _load_default_plugins(self):
        """Load default discovery method plugins"""
        self.register_plugin(PatternDiscovery(self.http_client, self.validator, self.config))
        self.register_plugin(HTMLLinkDiscovery(self.http_client, self.validator, self.config))
        self.register_plugin(MetaTagDiscovery(self.http_client, self.validator, self.config))
        self.register_plugin(SitemapDiscovery(self.http_client, self.validator, self.config))
        self.register_plugin(ContentSniffDiscovery(self.http_client, self.validator, self.config))
    
    def register_plugin(self, plugin: DiscoveryMethod):
        """Register a discovery method plugin"""
        self._plugins[plugin.name] = plugin
        logger.debug(f"Registered discovery plugin: {plugin.name}")
    
    def unregister_plugin(self, name: str):
        """Unregister a discovery method plugin"""
        if name in self._plugins:
            del self._plugins[name]
            logger.debug(f"Unregistered discovery plugin: {name}")
    
    def get_plugin(self, name: str) -> Optional[DiscoveryMethod]:
        """Get a specific plugin"""
        return self._plugins.get(name)
    
    def list_plugins(self) -> List[str]:
        """List all registered plugins"""
        return list(self._plugins.keys())
    
    def run_discovery(self, url: str, method_names: List[str] = None) -> List[FeedInfo]:
        """Run discovery using specified methods (or all if None)"""
        if method_names is None:
            method_names = self.list_plugins()
        
        all_feeds = []
        for method_name in method_names:
            if method_name in self._plugins:
                plugin = self._plugins[method_name]
                try:
                    feeds = plugin.discover(url)
                    all_feeds.extend(feeds)
                    logger.debug(f"Plugin {method_name} found {len(feeds)} feeds")
                except Exception as e:
                    logger.error(f"Plugin {method_name} failed: {e}")
        
        return all_feeds
    
    def clear_all_caches(self):
        """Clear caches for all plugins"""
        for plugin in self._plugins.values():
            plugin.clear_cache()