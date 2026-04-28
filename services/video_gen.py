"""
OpenArt.ai video generator — Playwright browser automation.

Logs into openart.ai, navigates to the story creator, submits the summary
text, waits for video generation, and returns the video download URL.

This is implemented as a Protocol so it can be swapped for a real API client
when an OpenArt.ai Pro API key is available.
"""

from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from config import settings
from domain.models import Summary, VideoJob

log = logging.getLogger(__name__)

STORY_URL = "https://openart.ai/story/create/script"
LOGIN_URL = "https://openart.ai/signin"
POLL_TIMEOUT = 600   # seconds — video generation can be slow
POLL_INTERVAL = 10   # seconds between checks


class VideoGenerator(Protocol):
    def generate(self, summary: Summary) -> VideoJob:
        ...


class OpenArtVideoGenerator:
    """Playwright-based OpenArt.ai automation."""

    def generate(self, summary: Summary) -> VideoJob:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        job_id = str(uuid4())
        log.info(f"Starting OpenArt.ai video generation (job={job_id})")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)  # headless=False for first-run auth debug
            ctx = browser.new_context()
            page = ctx.new_page()

            # ── Login ─────────────────────────────────────────────────────────
            log.info("Logging into OpenArt.ai")
            page.goto(LOGIN_URL, wait_until="networkidle")
            page.fill('input[type="email"]', settings.openart_email)
            page.fill('input[type="password"]', settings.openart_password)
            page.click('button[type="submit"]')
            page.wait_for_url("**/openart.ai/**", timeout=15_000)

            # ── Navigate to story creator ──────────────────────────────────────
            page.goto(STORY_URL, wait_until="networkidle")

            # ── Fill script ───────────────────────────────────────────────────
            # Try common selectors for the script textarea
            script_selector = 'textarea, [contenteditable="true"]'
            page.wait_for_selector(script_selector, timeout=15_000)
            page.fill(script_selector, summary.text)
            log.info("Script filled")

            # ── Click Generate ─────────────────────────────────────────────────
            generate_btn = page.locator('button:has-text("Generate"), button:has-text("Create")')
            generate_btn.first.click()
            log.info("Generate clicked — waiting for video…")

            # ── Poll for video output ──────────────────────────────────────────
            video_url = _wait_for_video(page, POLL_TIMEOUT, POLL_INTERVAL)

            browser.close()

        log.info(f"Video ready: {video_url}")
        return VideoJob(
            id=job_id,
            summary_id=summary.id,
            openart_job_id=job_id,
            video_url=video_url,
            local_path=None,
            status="ready",
            created_at=datetime.utcnow(),
        )


def _wait_for_video(page, timeout: int, interval: int) -> str:
    """Poll the page until a video download URL appears."""
    from playwright.sync_api import TimeoutError as PWTimeout

    deadline = time.time() + timeout
    while time.time() < deadline:
        # Look for a download button or a <video> element with a src
        try:
            # Try to find a download link
            download = page.locator('a[download], a:has-text("Download")')
            if download.count() > 0:
                href = download.first.get_attribute("href")
                if href:
                    return href

            # Or a <video> element
            video = page.locator("video[src]")
            if video.count() > 0:
                src = video.first.get_attribute("src")
                if src and src.startswith("http"):
                    return src

        except Exception:
            pass

        log.debug(f"Waiting for video… ({int(deadline - time.time())}s remaining)")
        time.sleep(interval)

    raise TimeoutError(f"OpenArt.ai video not ready after {timeout}s")
