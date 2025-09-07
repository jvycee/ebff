"""
HTTP Client for EBFF with optimized connection pooling and caching
"""

import logging
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ConfigManager


logger = logging.getLogger(__name__)


class HTTPClient:
    """Optimized HTTP client with connection pooling and caching"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self._request_cache: Dict[str, requests.Response] = {}
        self._session = None
        self._setup_session()
    
    def _setup_session(self) -> None:
        """Setup requests session with optimized configuration"""
        self._session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.get('max_retries'),
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1
        )
        
        # Configure HTTP adapter with connection pooling
        adapter = HTTPAdapter(
            pool_connections=self.config.get('pool_connections'),
            pool_maxsize=self.config.get('pool_maxsize'),
            max_retries=retry_strategy
        )
        
        # Mount adapter for both HTTP and HTTPS
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        
        # Set headers
        headers = self.config.get('http_headers').copy()
        headers['User-Agent'] = self.config.get('user_agents')[0]
        self._session.headers.update(headers)
    
    def get(self, url: str, timeout: Optional[int] = None, use_cache: bool = True) -> Optional[requests.Response]:
        """Make GET request with caching and error handling"""
        timeout = timeout or self.config.get('timeout')
        
        # Check cache first if enabled
        if use_cache and url in self._request_cache:
            cached_response = self._request_cache[url]
            if cached_response.status_code == 200:
                logger.debug(f"Cache hit for {url}")
                return cached_response
        
        try:
            response = self._session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                verify=True
            )
            
            # Cache successful responses
            if response.status_code == 200 and use_cache:
                cache_size_limit = self.config.get('request_cache_size')
                if len(self._request_cache) < cache_size_limit:
                    self._request_cache[url] = response
                elif len(self._request_cache) >= cache_size_limit:
                    # Simple cache eviction - remove oldest entry
                    oldest_key = next(iter(self._request_cache))
                    del self._request_cache[oldest_key]
                    self._request_cache[url] = response
            
            return response
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed for {url}: {e}")
            return None
    
    def head(self, url: str, timeout: Optional[int] = None) -> Optional[requests.Response]:
        """Make HEAD request"""
        timeout = timeout or self.config.get('timeout')
        
        try:
            response = self._session.head(
                url,
                timeout=timeout,
                allow_redirects=True,
                verify=True
            )
            return response
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"HEAD request failed for {url}: {e}")
            return None
    
    def clear_cache(self) -> None:
        """Clear request cache"""
        self._request_cache.clear()
        logger.debug("Request cache cleared")
    
    def get_cache_size(self) -> int:
        """Get current cache size"""
        return len(self._request_cache)
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return {
            'size': len(self._request_cache),
            'limit': self.config.get('request_cache_size')
        }
    
    def close(self) -> None:
        """Close session and cleanup resources"""
        if self._session:
            self._session.close()
        self.clear_cache()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()