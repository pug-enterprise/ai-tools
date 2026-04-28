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


CHROME_PROFILE = Path.home() / "Library/Application Support/Google/Chrome/Default"


def login_interactively():
    """
    Open Playwright using your real Chrome profile (already logged into OpenArt.ai),
    navigate to openart.ai to confirm the session, then export and save the cookies
    to SESSION_DIR for future headless runs.

    Chrome must be fully quit before running this (Cmd+Q).
    """
    from playwright.sync_api import sync_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    print("\n  Fully quit Chrome first (Cmd+Q — not just close the window).")
    input("  Press Enter when Chrome is closed > ")

    log.info("Launching with your real Chrome profile…")

    with sync_playwright() as pw:
        # Use the real Chrome profile — already logged in everywhere
        ctx = pw.chromium.launch_persistent_context(
            str(CHROME_PROFILE),
            headless=False,
            channel="chrome",
            args=["--profile-directory=Default"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://openart.ai/suite/home", wait_until="networkidle")

        if "signin" in page.url or "login" in page.url:
            print("\n  Not logged in — sign in manually in the browser, then press Enter.")
            input("  Press Enter when you're on the OpenArt.ai home page > ")

        print(f"\n  Logged in at: {page.url}")

        # Export cookies from this context and save to SESSION_DIR
        cookies = ctx.cookies()
        ctx.close()

    # Now start a fresh persistent context in SESSION_DIR and inject the cookies
    log.info(f"Saving session to {SESSION_DIR}…")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=False,
            channel="chrome",
        )
        ctx.add_cookies(cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://openart.ai/suite/home", wait_until="networkidle")
        log.info(f"  Session verified at: {page.url}")
        ctx.close()

    log.info("Session saved. You can now run the pipeline.")


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
