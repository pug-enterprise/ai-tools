"""
OpenArt.ai video generator — Playwright browser automation.

Uses a persistent browser context so login only happens once.
On the first run, a headed browser opens and waits for you to log in
manually (via Google SSO). The session is saved to disk and reused on
all subsequent runs — no login required.

Run `python cli.py openart-login` to (re)authenticate.
"""

from __future__ import annotations
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from domain.models import Summary, VideoJob

log = logging.getLogger(__name__)

STORY_URL    = "https://openart.ai/story/create/script"
SESSION_DIR  = Path.home() / ".ai-tools" / "openart-session"
POLL_TIMEOUT  = 600   # seconds — video generation can be slow
POLL_INTERVAL = 10    # seconds between checks


class VideoGenerator(Protocol):
    def generate(self, summary: Summary) -> VideoJob:
        ...


class OpenArtVideoGenerator:
    """Playwright-based OpenArt.ai automation with persistent session."""

    def generate(self, summary: Summary) -> VideoJob:
        from playwright.sync_api import sync_playwright

        if not _session_exists():
            raise RuntimeError(
                "No OpenArt.ai session found. Run: python cli.py openart-login"
            )

        job_id = str(uuid4())
        log.info(f"Starting OpenArt.ai video generation (job={job_id})")

        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(SESSION_DIR),
                headless=False,
                channel="chrome",   # use real Chrome, not bundled Chromium
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # ── Navigate to story creator ──────────────────────────────────
            page.goto(STORY_URL, wait_until="networkidle")

            # If redirected to login, session has expired
            if "signin" in page.url or "login" in page.url:
                ctx.close()
                raise RuntimeError(
                    "OpenArt.ai session expired. Run: python cli.py openart-login"
                )

            # ── Fill script ───────────────────────────────────────────────
            script_selector = 'textarea, [contenteditable="true"]'
            page.wait_for_selector(script_selector, timeout=15_000)
            page.fill(script_selector, summary.text)
            log.info("Script filled")

            # ── Click Generate ────────────────────────────────────────────
            generate_btn = page.locator('button:has-text("Generate"), button:has-text("Create")')
            generate_btn.first.click()
            log.info("Generate clicked — waiting for video…")

            # ── Poll for video output ─────────────────────────────────────
            video_url = _wait_for_video(page, POLL_TIMEOUT, POLL_INTERVAL)

            ctx.close()

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


def login_interactively():
    """
    Open a headed browser, let the user log in via Google SSO,
    then save the session. Called by `python cli.py openart-login`.
    """
    from playwright.sync_api import sync_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Opening browser — log into OpenArt.ai via Google SSO, then close the browser.")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=False,
            channel="chrome",   # use real Chrome, not bundled Chromium
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://openart.ai/signin", wait_until="networkidle")

        print("\n  Log into OpenArt.ai in the browser window (use 'Continue with Google').")
        print("  Once you're on the OpenArt.ai home page, press Enter here to save the session.")
        input("  Press Enter when logged in > ")

        ctx.close()

    log.info(f"Session saved to {SESSION_DIR}")


def _session_exists() -> bool:
    return SESSION_DIR.exists() and any(SESSION_DIR.iterdir())


def _wait_for_video(page, timeout: int, interval: int) -> str:
    """Poll the page until a video download URL appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            download = page.locator('a[download], a:has-text("Download")')
            if download.count() > 0:
                href = download.first.get_attribute("href")
                if href:
                    return href

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
