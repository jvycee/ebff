#!/usr/bin/env python3
"""
EBFF - Even Better Feed Finder
Command Line Interface
"""

import sys
import json
import argparse
import logging
from typing import List
from pathlib import Path

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ebff.feed_finder import FeedFinder, FeedInfo
except ImportError:
    # For development, try direct import
    from feed_finder import FeedFinder, FeedInfo


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def print_feed_info(feed: FeedInfo, detailed: bool = False):
    """Pretty print feed information"""
    print(f"\n{'='*60}")
    print(f"Feed URL: {feed.url}")
    print(f"Title: {feed.title or 'N/A'}")
    print(f"Type: {feed.feed_type or 'Unknown'}")
    print(f"Discovery Method: {feed.discovery_method}")
    print(f"Quality Score: {feed.quality_score}/100")
    print(f"Validation Status: {feed.validation_status}")
    
    if detailed:
        print(f"Description: {feed.description or 'N/A'}")
        print(f"Language: {feed.language or 'N/A'}")
        print(f"Entry Count: {feed.entry_count}")
        print(f"Last Updated: {feed.last_updated or 'Unknown'}")
        if feed.metadata:
            print(f"Metadata: {json.dumps(feed.metadata, indent=2)}")




def print_feed_summary(feeds: List[FeedInfo]):
    """Print a concise summary of discovered feeds"""
    if not feeds:
        return
    
    print(f"\n📊 Feed Summary:")
    print("-" * 40)
    
    # Group by feed type
    by_type = {}
    for feed in feeds:
        feed_type = feed.feed_type or 'unknown'
        if feed_type not in by_type:
            by_type[feed_type] = []
        by_type[feed_type].append(feed)
    
    # Print summary
    for feed_type, type_feeds in by_type.items():
        best_feed = max(type_feeds, key=lambda x: x.quality_score)
        print(f"\n{feed_type.upper()} Feed:")
        print(f"  URL: {best_feed.url}")
        print(f"  Title: {best_feed.title or 'N/A'}")
        print(f"  Score: {best_feed.quality_score}/100")
        print(f"  Entries: {best_feed.entry_count} posts")
        
        if len(type_feeds) > 1:
            print(f"  (+ {len(type_feeds)-1} alternate URL{'s' if len(type_feeds) > 2 else ''})")

def discover_feeds(url: str, args):
    """Discover feeds for a single URL"""
    finder = FeedFinder(timeout=args.timeout)
    
    print(f"\nDiscovering feeds for: {url}")
    print(f"Settings: deep_scan={args.deep_scan}, validate={args.validate}, min_score={args.min_score}")
    
    feeds = finder.discover(
        url,
        deep_scan=args.deep_scan,
        validate_quality=args.validate,
        min_score=args.min_score,
        quick_mode=args.quick if hasattr(args, 'quick') else False
    )
    
    if not feeds:
        print(f"❌ No feeds found for {url}")
        return []
    
    print(f"\n✅ Found {len(feeds)} feed(s) for {url}")
    
    if args.detailed:
        for feed in feeds:
            print_feed_info(feed, detailed=True)
    else:
        print_feed_summary(feeds)
    
    return feeds


def batch_discover(urls: List[str], args) -> List[FeedInfo]:
    """Discover feeds for multiple URLs and return every feed found."""
    finder = FeedFinder(timeout=args.timeout)
    
    results = finder.batch_discover(urls, max_workers=args.workers)
    found: List[FeedInfo] = []
    total_feeds = 0
    for url, feeds in results.items():
        print(f"\n{'='*60}")
        print(f"URL: {url}")
        if feeds:
            print(f"✅ Found {len(feeds)} feed(s)")
            for feed in feeds:
                if args.detailed:
                    print_feed_info(feed, detailed=True)
                else:
                    print(f"  - {feed.url} (Score: {feed.quality_score})")
            found.extend(feeds)
            total_feeds += len(feeds)
        else:
            print(f"❌ No feeds found")
    
    print(f"\n{'='*60}")
    print(f"Total: {total_feeds} feeds found across {len(urls)} URLs")
    return found


def export_results(feeds: List[FeedInfo], output_file: str, format: str = 'json'):
    """Export feed discovery results to file"""
    if format == 'json':
        data = []
        for feed in feeds:
            data.append({
                'url': feed.url,
                'title': feed.title,
                'type': feed.feed_type,
                'discovery_method': feed.discovery_method,
                'quality_score': feed.quality_score,
                'validation_status': feed.validation_status,
                'description': feed.description,
                'language': feed.language,
                'entry_count': feed.entry_count,
                'last_updated': feed.last_updated.isoformat() if feed.last_updated else None,
                'metadata': feed.metadata
            })
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Results exported to {output_file}")
    
    elif format == 'csv':
        import csv
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['url', 'title', 'type', 'discovery_method', 
                         'quality_score', 'validation_status', 'entry_count']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            for feed in feeds:
                writer.writerow({
                    'url': feed.url,
                    'title': feed.title or '',
                    'type': feed.feed_type or '',
                    'discovery_method': feed.discovery_method or '',
                    'quality_score': feed.quality_score,
                    'validation_status': feed.validation_status,
                    'entry_count': feed.entry_count
                })
        
        print(f"\n✅ Results exported to {output_file}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='EBFF - Even Better Feed Finder - Discover RSS/Atom/JSON feeds from websites',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover feeds for a single site
  ebff example.com
  
  # Deep scan with quality validation
  ebff example.com --deep-scan --validate
  
  # Only get high-quality feeds
  ebff example.com --min-score 70
  
  # Batch discovery from file
  ebff --batch urls.txt --workers 10
  
  # Export results to JSON
  ebff example.com --output feeds.json
        """
    )
    
    # Main arguments
    parser.add_argument('url', nargs='?', help='URL to discover feeds from')
    parser.add_argument('--batch', metavar='FILE', help='File containing URLs (one per line)')
    
    # Discovery options
    parser.add_argument('--deep-scan', action='store_true', default=True,
                       help='Use all discovery methods (default: True)')
    parser.add_argument('--quick', action='store_true', default=False,
                       help='Quick mode - stop when valid feeds are found')
    parser.add_argument('--no-deep-scan', dest='deep_scan', action='store_false',
                       help='Use only basic discovery methods')
    parser.add_argument('--validate', action='store_true', default=True,
                       help='Validate and score feed quality (default: True)')
    parser.add_argument('--no-validate', dest='validate', action='store_false',
                       help='Skip feed validation')
    parser.add_argument('--min-score', type=int, default=0, metavar='N',
                       help='Minimum quality score (0-100) to include feed')
    
    # Output options
    parser.add_argument('--detailed', '-d', action='store_true',
                       help='Show detailed feed information')
    parser.add_argument('--output', '-o', metavar='FILE',
                       help='Export results to file (JSON or CSV based on extension)')
    parser.add_argument('--format', choices=['json', 'csv'], default='json',
                       help='Output format when using --output')
    
    # Performance options
    parser.add_argument('--timeout', type=int, default=10, metavar='SEC',
                       help='Request timeout in seconds (default: 10)')
    parser.add_argument('--workers', type=int, default=5, metavar='N',
                       help='Max concurrent workers for batch processing (default: 5)')
    
    # Other options
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--version', action='version', version='EBFF 0.1.0')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    
    # Validate arguments
    if not args.url and not args.batch:
        parser.error('Either provide a URL or use --batch with a file')
    
    if args.url and args.batch:
        parser.error('Cannot use both URL and --batch')
    
    # Process requests
    all_feeds = []
    
    if args.batch:
        # Batch processing
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"❌ Error: File {args.batch} not found")
            sys.exit(1)
        
        urls = []
        with open(batch_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
        
        if not urls:
            print(f"❌ Error: No URLs found in {args.batch}")
            sys.exit(1)
        
        all_feeds = batch_discover(urls, args)
    
    else:
        # Single URL processing
        feeds = discover_feeds(args.url, args)
        all_feeds = feeds
    
    # Export results if requested
    if args.output and all_feeds:
        format = args.format
        if args.output.endswith('.csv'):
            format = 'csv'
        export_results(all_feeds, args.output, format)
    
    sys.exit(0 if all_feeds else 1)


if __name__ == '__main__':
    main()
