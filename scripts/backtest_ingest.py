#!/usr/bin/env python3
"""Shim: ``python scripts/backtest_ingest.py ...`` → ``python -m bot.backtest ingest ...``."""

from __future__ import annotations

import sys

from bot.backtest.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["ingest", *sys.argv[1:]]))
