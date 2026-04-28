"""
Video downloader — streams a video URL to disk.
"""

from __future__ import annotations
import logging
from pathlib import Path

import httpx

from config import settings

log = logging.getLogger(__name__)

TIMEOUT = 300  # large files may take a while


def download_video(url: str, article_id: str) -> str:
    """Download video from `url` and return the local file path."""
    downloads_dir = Path(settings.downloads_dir)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    dest = downloads_dir / f"{article_id}.mp4"

    if dest.exists():
        log.info(f"Video already downloaded: {dest}")
        return str(dest)

    log.info(f"Downloading video → {dest}")
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        log.debug(f"  {pct:.0f}% ({downloaded}/{total} bytes)")

    log.info(f"Download complete: {dest} ({dest.stat().st_size} bytes)")
    return str(dest)
