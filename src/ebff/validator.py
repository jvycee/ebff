"""
Feed Validation and Quality Scoring for EBFF
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Set, Optional, Dict
from urllib.parse import urlparse

import feedparser
from dateutil import parser as date_parser

from .models import FeedInfo
from .config import ConfigManager


logger = logging.getLogger(__name__)


class FeedValidator:
    """Handles feed validation and quality scoring"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self._validated_urls: Set[str] = set()
    
    def is_feed_content(self, content: str) -> bool:
        """Detect if content is a valid feed"""
        if not content or not content.strip():
            return False
        
        content = content.strip().lower()
        
        # Check for RSS/Atom XML feeds
        if content.startswith('<?xml'):
            feed_indicators = [
                '<rss', '<feed', '<channel>', '<entry>', 
                '<item>', 'xmlns="http://www.w3.org/2005/atom"'
            ]
            return any(indicator in content for indicator in feed_indicators)
        
        # Check for JSON Feed (stricter validation)
        if content.startswith('{'):
            try:
                data = json.loads(content)
                # Must be proper JSON Feed format
                return (
                    isinstance(data, dict) and
                    'version' in data and
                    ('items' in data or 'entries' in data) and
                    # Exclude WordPress API responses
                    'rest_route' not in data and
                    'wp_json' not in str(data.get('_links', {}))
                )
            except json.JSONDecodeError:
                return False
        
        return False

    def is_junk_feed_url(self, url: str) -> bool:
        """Detect junk feed URLs that should be filtered out"""
        url_lower = url.lower()
        
        # WordPress API endpoints
        if '/wp-json/' in url_lower:
            return True
        
        # oEmbed endpoints  
        if '/oembed/' in url_lower or 'oembed' in url_lower:
            return True
        
        # REST API endpoints
        if '/api/v' in url_lower or '/rest/v' in url_lower:
            return True
            
        # Other junk patterns
        junk_patterns = [
            '/wp-admin/',
            '/wp-content/',
            '?json=',
            '&json=',
            '/json?',
            '/embed?',
            'format=json',
            '.json?url=',
        ]
        
        return any(pattern in url_lower for pattern in junk_patterns)

    def is_comments_feed(self, url: str, title: str = None) -> bool:
        """Detect if this is a comments feed"""
        url_lower = url.lower()
        title_lower = (title or '').lower()
        
        # URL-based detection
        if '/comments/' in url_lower or 'comments/feed' in url_lower:
            return True
            
        # Title-based detection
        if title_lower and ('comments' in title_lower or 'comment' in title_lower):
            return True
            
        return False
    
    def detect_feed_type(self, content: str, mime_type: str = "") -> str:
        """Detect feed type from content and MIME type"""
        # Check MIME type first
        if mime_type:
            mime_lower = mime_type.lower()
            if 'rss' in mime_lower or mime_lower == 'application/rss+xml':
                return 'rss'
            elif 'atom' in mime_lower or mime_lower == 'application/atom+xml':
                return 'atom'
            elif 'json' in mime_lower or mime_lower in ['application/json', 'application/feed+json']:
                return 'json'
        
        # Analyze content
        if not content:
            return 'unknown'
        
        content_lower = content.lower()
        
        # JSON Feed
        if content.strip().startswith('{'):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'version' in data:
                    return 'json'
            except json.JSONDecodeError:
                pass
        
        # XML-based feeds
        if '<rss' in content_lower:
            return 'rss'
        elif '<feed' in content_lower and 'atom' in content_lower:
            return 'atom'
        elif '<channel>' in content_lower and '<item>' in content_lower:
            return 'rss'
        elif '<entry>' in content_lower:
            return 'atom'
        
        return 'unknown'
    
    def parse_feed(self, url: str, content: str) -> Optional[FeedInfo]:
        """Parse feed content and extract information"""
        # Filter out junk URLs before processing
        if self.is_junk_feed_url(url):
            logger.debug(f"Skipping junk feed URL: {url}")
            return None
            
        if not self.is_feed_content(content):
            return None
        
        feed_type = self.detect_feed_type(content)
        
        # Handle JSON feeds separately
        if feed_type == 'json':
            return self._parse_json_feed(url, content)
        
        # Use feedparser for RSS/Atom
        try:
            parsed = feedparser.parse(content)
            
            if parsed.bozo and not parsed.entries:
                logger.warning(f"Malformed feed at {url}: {parsed.bozo_exception}")
                return None
            
            # Extract feed information
            feed_info = FeedInfo(
                url=url,
                feed_type=feed_type,
                validation_status="valid" if not parsed.bozo else "warning"
            )
            
            # Basic feed metadata
            if hasattr(parsed, 'feed'):
                feed_info.title = getattr(parsed.feed, 'title', None)
                feed_info.description = getattr(parsed.feed, 'description', None)
                feed_info.language = getattr(parsed.feed, 'language', None)
                
                # Try to get last updated
                if hasattr(parsed.feed, 'updated_parsed') and parsed.feed.updated_parsed:
                    try:
                        feed_info.last_updated = datetime(*parsed.feed.updated_parsed[:6])
                    except (ValueError, TypeError):
                        pass
            
            # Count entries
            feed_info.entry_count = len(parsed.entries) if parsed.entries else 0
            
            # Store additional metadata
            feed_info.metadata = {
                'bozo': parsed.bozo,
                'bozo_exception': str(parsed.bozo_exception) if parsed.bozo_exception else None,
                'encoding': getattr(parsed, 'encoding', 'utf-8'),
                'version': getattr(parsed, 'version', None),
                'is_comments_feed': self.is_comments_feed(url, feed_info.title)
            }
            
            return feed_info
            
        except Exception as e:
            logger.error(f"Failed to parse feed {url}: {e}")
            return None
    
    def _parse_json_feed(self, url: str, content: str) -> Optional[FeedInfo]:
        """Parse JSON Feed format"""
        try:
            data = json.loads(content)
            
            if not isinstance(data, dict) or 'version' not in data:
                return None
            
            feed_info = FeedInfo(
                url=url,
                feed_type='json',
                validation_status="valid"
            )
            
            # Extract metadata
            feed_info.title = data.get('title')
            feed_info.description = data.get('description')
            feed_info.language = data.get('language')
            
            # Count items
            items = data.get('items', data.get('entries', []))
            feed_info.entry_count = len(items) if items else 0
            
            # Store metadata
            feed_info.metadata = {
                'version': data.get('version'),
                'home_page_url': data.get('home_page_url'),
                'feed_url': data.get('feed_url')
            }
            
            return feed_info
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON feed {url}: {e}")
            return None
    
    def score_feed(self, feed_info: FeedInfo) -> int:
        """Calculate quality score for a feed (0-100) with discriminating algorithm"""
        if not feed_info:
            return 0
        
        # Start from base score
        score = 20  # Base score for being a valid feed
        
        # MAJOR PENALTIES FIRST
        
        # Comments feeds get heavy penalty
        if feed_info.metadata.get('is_comments_feed', False):
            score -= 40  # Comments feeds are much less valuable
        
        # Empty feeds are nearly worthless
        if feed_info.entry_count == 0:
            score -= 50
        
        # Malformed feeds penalty
        if feed_info.validation_status == "warning":
            score -= 15
        elif feed_info.validation_status == "invalid":
            score -= 30
        
        # CONTENT QUALITY SCORING
        
        # Entry count scoring (progressive)
        if feed_info.entry_count >= 20:
            score += 25  # Excellent content volume
        elif feed_info.entry_count >= 10:
            score += 20  # Good content volume  
        elif feed_info.entry_count >= 5:
            score += 15  # Decent content volume
        elif feed_info.entry_count >= 1:
            score += 10  # Some content
        # 0 entries already penalized above
        
        # METADATA QUALITY
        
        # Title quality (strong indicator)
        if feed_info.title and len(feed_info.title.strip()) > 3:
            score += 15
            # Bonus for descriptive titles
            if len(feed_info.title) > 10 and not feed_info.title.lower() in ['json', 'rss', 'atom', 'feed']:
                score += 5
        
        # Description quality
        if feed_info.description and len(feed_info.description.strip()) > 10:
            score += 10
        
        # Language specified (good metadata)
        if feed_info.language:
            score += 5
        
        # FRESHNESS SCORING (critical for feed quality)
        
        if feed_info.last_updated:
            days_ago = (datetime.now() - feed_info.last_updated).days
            
            if days_ago <= 1:
                score += 20  # Very fresh
            elif days_ago <= 7:
                score += 15  # Fresh  
            elif days_ago <= 30:
                score += 10  # Recent
            elif days_ago <= 90:
                score += 5   # Somewhat recent
            # Older than 90 days gets no bonus
        else:
            score -= 10  # No last updated date is bad
        
        # DISCOVERY METHOD QUALITY
        
        if feed_info.discovery_method:
            method_scores = {
                'html_link': 15,      # Best - proper feed advertisement
                'common_pattern': 10, # Good - standard locations
                'meta_tag': 8,        # Decent - inferred from meta
                'sitemap': 5,         # OK - found in sitemap
                'content_sniff': 2    # Weak - just happened to be feed
            }
            score += method_scores.get(feed_info.discovery_method, 0)
        
        # FEED TYPE QUALITY
        
        # JSON feeds are often lower quality in practice
        if feed_info.feed_type == 'json':
            score -= 5
        
        # FINAL ADJUSTMENTS
        
        # Ensure realistic score distribution
        if score > 95:
            score = 95  # Reserve 96-100 for truly exceptional feeds
        
        # Ensure bounds
        return max(0, min(100, score))
    
    def validate_and_score_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Score each feed object from its own fields.

        Remembering a URL must not leave a later object at the default score.
        """
        for feed in feeds:
            feed.quality_score = self.score_feed(feed)
            self._validated_urls.add(feed.url)

        return feeds
    
    def deduplicate_feeds(self, feeds: List[FeedInfo]) -> List[FeedInfo]:
        """Remove duplicate feeds, keeping highest quality"""
        if not feeds:
            return feeds
        
        # Create a mapping of normalized URLs to feeds
        url_to_feeds: Dict[str, List[FeedInfo]] = {}
        
        for feed in feeds:
            normalized_url = self._normalize_feed_url(feed.url)
            if normalized_url not in url_to_feeds:
                url_to_feeds[normalized_url] = []
            url_to_feeds[normalized_url].append(feed)
        
        # Keep the highest scored feed for each URL
        unique_feeds = []
        for feed_list in url_to_feeds.values():
            if len(feed_list) == 1:
                unique_feeds.append(feed_list[0])
            else:
                # Sort by quality score (highest first) and take the best
                best_feed = max(feed_list, key=lambda f: f.quality_score)
                unique_feeds.append(best_feed)
        
        return unique_feeds
    
    def _normalize_feed_url(self, url: str) -> str:
        """Normalize feed URL for deduplication"""
        parsed = urlparse(url)
        
        # Remove common variations
        path = parsed.path.rstrip('/')
        
        # Normalize common feed paths
        path_mappings = {
            '/feed': '/feed',
            '/feeds': '/feed',
            '/rss': '/feed',
            '/atom': '/feed',
            '/feed.xml': '/feed',
            '/rss.xml': '/feed',
            '/atom.xml': '/feed'
        }
        
        normalized_path = path_mappings.get(path, path)
        
        return f"{parsed.scheme}://{parsed.netloc}{normalized_path}"
    
    def clear_validation_cache(self) -> None:
        """Clear validation cache"""
        self._validated_urls.clear()