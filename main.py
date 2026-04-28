#!/usr/bin/env python3
"""
Entrypoint.

  python main.py              → run CLI (same as python cli.py)
  python main.py --scheduler  → start the cron scheduler
"""

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

if "--scheduler" in sys.argv:
    sys.argv.remove("--scheduler")
    from scheduler import start
    start()
else:
    from cli import cli
    cli()
