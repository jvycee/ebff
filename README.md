# EBFF - Even Better Feed Finder

The most comprehensive RSS/Atom/JSON feed discovery tool. EBFF combines multiple discovery techniques with intelligent scoring to find feeds that other tools miss.

## Features

- 🔍 **8+ Discovery Methods** - From common patterns to content sniffing
- 📊 **Quality Scoring** - Rates feeds 0-100 based on freshness, content, and validity
- 🚀 **Fast & Concurrent** - Batch process hundreds of sites efficiently  
- 📰 **Multi-Format Support** - RSS, Atom, JSON Feed, Podcasts
- 🎯 **Smart Detection** - Meta tags, sitemaps, and heuristic analysis
- 📁 **Export Options** - JSON, CSV, or structured data for integration

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Find feeds for a single site
python src/ebff/cli.py techcrunch.com

# Get detailed information
python src/ebff/cli.py bbc.com --detailed

# Only high-quality feeds (score 70+)
python src/ebff/cli.py news.ycombinator.com --min-score 70
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Command Line

```bash
# Basic discovery
python src/ebff/cli.py example.com

# Deep scan with all methods
python src/ebff/cli.py example.com --deep-scan

# Batch processing
python src/ebff/cli.py --batch sites.txt --workers 10
```

### Python API

```python
from ebff import FeedFinder

# Initialize finder
finder = FeedFinder()

# Discover feeds
feeds = finder.discover("techcrunch.com")
```

## Why EBFF?

**Even Better** than existing feed finders because:
- ✅ 8+ discovery methods vs 2-3 in other tools
- ✅ Quality scoring and validation
- ✅ JSON Feed support
- ✅ Batch processing
- ✅ Modern Python 3.8+ codebase

## License

MIT License