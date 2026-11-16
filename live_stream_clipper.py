#!/usr/bin/env python3
"""Legacy entry point wrapper for Live Stream AI Clipper.

This script delegates execution directly to the modern `clipper` package,
which provides robust streaming, overlap segmentation, SQLite persistence,
multi-threaded worker pools, and social publishing with manual approval.

Usage:
    python live_stream_clipper.py --config config.yaml
    python live_stream_clipper.py --status
    python -m clipper --config config.yaml
"""

import sys
from clipper.pipeline import main

if __name__ == "__main__":
    main()
