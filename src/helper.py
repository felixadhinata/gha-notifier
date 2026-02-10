"""Shared helpers (logging, etc.)."""

import sys
import time


def log(message):
    """Print timestamp and message to stderr (visible when running from terminal)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    sys.stderr.write(f"[{ts}] {message}\n")
    sys.stderr.flush()
