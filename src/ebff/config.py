"""
EBFF Configuration Management
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class FeedFinderConfig:
    """Configuration for EBFF feed discovery"""
    
    # Network settings
    timeout: int = 10
    max_retries: int = 3
    pool_connections: int = 20
    pool_maxsize: int = 20
    max_workers: int = 8
    
    # Cache settings
    request_cache_size: int = 100
    
    # Discovery settings
    max_patterns_to_check: int = 20
    deep_scan: bool = True
    validate_quality: bool = True
    min_score: int = 0
    
    # Feed patterns (most common first for speed)
    feed_patterns: List[str] = field(default_factory=lambda: [
        '/feed', '/rss', '/feed/', '/rss/', '/rss.xml', '/feed.xml',
        '/atom.xml', '/feed.atom', '/feed.rss', '/index.xml', '/index.rss',
        '/blog/feed', '/blog/rss', '/news/feed', '/news/rss',
        '/feed/rss2', '/feed/atom', '/rss2.xml', '/atom', '/atom/',
        '/feeds/all.atom.xml', '/feeds', '/feeds/', '/rss/index.xml',
        '/blog/feeds/all.atom.xml', '/blog/feeds', '/feed/atom/',
        '/?feed=rss', '/?feed=rss2', '/?feed=atom', '/rdf.xml',
        '/feeds/posts/default', '/feeds/posts/default?alt=rss',
    ])
    
    # User agents for requests
    user_agents: List[str] = field(default_factory=lambda: [
        'Mozilla/5.0 (compatible; EBFF/1.0; +https://github.com/example/ebff)',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    ])
    
    # Scoring weights
    scoring_weights: Dict[str, int] = field(default_factory=lambda: {
        'title': 10,
        'description': 10,
        'recent_content': {'7_days': 30, '30_days': 20, '90_days': 10},
        'entry_count': {'10_plus': 20, '5_plus': 15, '1_plus': 10},
        'validation': {'valid': 20, 'invalid': -10},
        'discovery_method': {
            'html_link': 15,
            'common_pattern': 10,
            'meta_tag': 8,
            'sitemap': 5,
            'content_sniff': 3
        }
    })
    
    # HTTP headers
    http_headers: Dict[str, str] = field(default_factory=lambda: {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    })


class ConfigManager:
    """Manages EBFF configuration with environment and file overrides"""
    
    def __init__(self, config: FeedFinderConfig = None):
        self.config = config or FeedFinderConfig()
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'ConfigManager':
        """Create ConfigManager from dictionary"""
        config = FeedFinderConfig()
        
        # Update config with provided values
        for key, value in config_dict.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        return cls(config)
    
    @classmethod
    def from_file(cls, config_path: str) -> 'ConfigManager':
        """Load configuration from file"""
        import json
        from pathlib import Path
        
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file) as f:
                config_dict = json.load(f)
            return cls.from_dict(config_dict)
        
        return cls()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return getattr(self.config, key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value"""
        setattr(self.config, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        import json
        from dataclasses import asdict
        return asdict(self.config)
    
    def save_to_file(self, config_path: str) -> None:
        """Save configuration to file"""
        import json
        from pathlib import Path
        
        config_file = Path(config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)