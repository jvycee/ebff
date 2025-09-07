"""
Data models for EBFF
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class FeedInfo:
    """Container for discovered feed information"""
    url: str
    title: Optional[str] = None
    feed_type: Optional[str] = None  # rss, atom, json
    discovery_method: Optional[str] = None
    last_updated: Optional[datetime] = None
    entry_count: int = 0
    description: Optional[str] = None
    language: Optional[str] = None
    quality_score: int = 0
    validation_status: str = "unknown"
    metadata: Dict = field(default_factory=dict)