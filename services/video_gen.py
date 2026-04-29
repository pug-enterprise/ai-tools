"""
OpenArt.ai video generator — Playwright browser automation.

Settings applied per run:
  - Character: Zam
  - Aspect ratio: 9:16
  - Visual style: auto-generated from story content
  - Creates a full video (not preview)

Session is saved via `python cli.py openart-login` (reads cookies from Chrome).
"""

from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from domain.models import Summary, VideoJob

log = logging.getLogger(__name__)

STORY_URL     = "https://openart.ai/story/create/script"
SESSION_DIR   = Path.home() / ".ai-tools" / "openart-session"
COOKIES_FILE  = SESSION_DIR / "cookies.json"
POLL_TIMEOUT  = 600   # seconds
POLL_INTERVAL = 5     # seconds


class VideoGenerator(Protocol):
    def generate(self, summary: Summary) -> VideoJob:
        ...


class OpenArtVideoGenerator:
    """Playwright-based OpenArt.ai automation."""

    def generate(self, summary: Summary) -> VideoJob:
        from playwright.sync_api import sync_playwright

        if not _session_exists():
            raise RuntimeError(
                "No OpenArt.ai session found. Run: python cli.py openart-login"
            )

        job_id = str(uuid4())
        log.info(f"Starting OpenArt.ai video generation (job={job_id})")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                channel="chrome",
                slow_mo=300,   # visible pacing so you can follow along
            )
            ctx = browser.new_context()
            ctx.add_cookies(json.loads(COOKIES_FILE.read_text()))
            page = ctx.new_page()

            # ── Navigate fresh page ───────────────────────────────────────
            page.goto(STORY_URL, wait_until="networkidle")

            if "signin" in page.url or "login" in page.url:
                ctx.close()
                browser.close()
                raise RuntimeError(
                    "OpenArt.ai session expired. Run: python cli.py openart-login"
                )

            # Record any video URLs already on the page BEFORE generating
            existing_urls: set[str] = set()
            for el in page.locator("video[src]").all():
                src = el.get_attribute("src") or ""
                if src:
                    existing_urls.add(src)
            log.info(f"Existing video URLs on page before generation: {len(existing_urls)}")

            # Intercept network — only accept URLs we haven't seen before
            video_url_holder: dict = {}

            def handle_response(response):
                url = response.url
                if (
                    "cdn.openart.ai" in url
                    and ".mp4" in url
                    and url not in existing_urls
                ):
                    log.info(f"New video URL captured via network: {url}")
                    video_url_holder["url"] = url

            page.on("response", handle_response)

            # ── Fill script ───────────────────────────────────────────────
            script_selector = 'textarea, [contenteditable="true"]'
            page.wait_for_selector(script_selector, timeout=15_000)
            page.fill(script_selector, summary.text)
            log.info("Script filled")

            # ── Select character: Zam ─────────────────────────────────────
            _select_character(page, "Zam")

            # ── Set aspect ratio: 9:16 ────────────────────────────────────
            _select_aspect_ratio(page, "9:16")

            # ── Apply custom visual style from story content ───────────────
            _apply_visual_style(page, summary.text)

            # ── Click "Create full video" ─────────────────────────────────
            _click_create_full_video(page)
            log.info("Create full video clicked — waiting for generation (this may take a few minutes)…")

            # ── Wait for a NEW video URL ──────────────────────────────────
            video_url = _wait_for_video_url(page, video_url_holder, existing_urls, POLL_TIMEOUT, POLL_INTERVAL)

            ctx.close()
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


# ── UI helpers ────────────────────────────────────────────────────────────────

def _select_character(page, name: str):
    """Click the character selector and choose by name."""
    try:
        # Open character picker — look for a button/thumbnail labelled with the character name
        char_btn = page.locator(f'[data-character="{name}"], img[alt="{name}"], button:has-text("{name}")')
        if char_btn.count() == 0:
            # Try clicking a "Character" label/tab first to reveal the list
            char_tab = page.locator('button:has-text("Character"), [role="tab"]:has-text("Character")')
            if char_tab.count() > 0:
                char_tab.first.click()
                page.wait_for_timeout(800)
            char_btn = page.locator(f'[data-character="{name}"], img[alt="{name}"], button:has-text("{name}")')

        if char_btn.count() > 0:
            char_btn.first.click()
            page.wait_for_timeout(500)
            log.info(f"Character set to: {name}")
        else:
            log.warning(f"Character '{name}' not found — skipping")
    except Exception as e:
        log.warning(f"Could not select character '{name}': {e}")


def _select_aspect_ratio(page, ratio: str):
    """Select aspect ratio (e.g. '9:16')."""
    try:
        ratio_btn = page.locator(f'button:has-text("{ratio}"), [data-ratio="{ratio}"], label:has-text("{ratio}")')
        if ratio_btn.count() > 0:
            ratio_btn.first.click()
            page.wait_for_timeout(500)
            log.info(f"Aspect ratio set to: {ratio}")
        else:
            log.warning(f"Aspect ratio '{ratio}' not found — skipping")
    except Exception as e:
        log.warning(f"Could not set aspect ratio '{ratio}': {e}")


def _apply_visual_style(page, story_text: str):
    """
    Click 'Custom' or 'Style' option and fill in a style prompt
    derived from the story content.
    """
    try:
        # Look for a style input or custom style option
        style_btn = page.locator('button:has-text("Custom"), button:has-text("Style"), [placeholder*="style"]')
        if style_btn.count() > 0:
            style_btn.first.click()
            page.wait_for_timeout(600)

        style_input = page.locator('input[placeholder*="style"], textarea[placeholder*="style"]')
        if style_input.count() > 0:
            # Generate a brief style prompt from the first 100 chars of story
            keywords = story_text[:100].replace("\n", " ").strip()
            style_prompt = f"Dynamic fantasy game news style, OSRS pixel art aesthetic, epic medieval theme — {keywords[:60]}"
            style_input.first.fill(style_prompt)
            page.wait_for_timeout(300)
            log.info("Visual style applied")
        else:
            log.warning("Style input not found — skipping custom style")
    except Exception as e:
        log.warning(f"Could not apply visual style: {e}")


def _click_create_full_video(page):
    """Click the 'Create full video' or primary generate button."""
    try:
        # Prefer "Create full video" over plain "Generate"
        full_btn = page.locator('button:has-text("Create full video"), button:has-text("Create Full Video")')
        if full_btn.count() > 0:
            full_btn.first.click()
            return
        # Fallback to any generate/create button
        btn = page.locator('button:has-text("Generate"), button:has-text("Create")')
        btn.first.click()
    except Exception as e:
        raise RuntimeError(f"Could not click create button: {e}")


def _wait_for_video_url(page, holder: dict, existing_urls: set, timeout: int, interval: int) -> str:
    """
    Wait for a NEW .mp4 URL — either via network intercept or DOM polling.
    Ignores any video URLs that were already present before generation started.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Network intercept hit
        if holder.get("url"):
            return holder["url"]

        # DOM fallback — only accept URLs not in existing_urls
        try:
            videos = page.locator("video[src*='cdn.openart.ai']")
            for i in range(videos.count()):
                src = videos.nth(i).get_attribute("src") or ""
                if src and src not in existing_urls:
                    return src

            links = page.locator('a[href*="cdn.openart.ai"][href*=".mp4"]')
            for i in range(links.count()):
                href = links.nth(i).get_attribute("href") or ""
                if href and href not in existing_urls:
                    return href
        except Exception:
            pass

        remaining = int(deadline - time.time())
        log.info(f"Waiting for video… ({remaining}s remaining)")
        time.sleep(interval)

    raise TimeoutError(f"OpenArt.ai video not ready after {timeout}s")


# ── Session helpers ───────────────────────────────────────────────────────────

def _session_exists() -> bool:
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0


def login_interactively():
    """
    Read OpenArt.ai cookies directly from your real Chrome profile.
    Chrome must be fully quit first (Cmd+Q).
    """
    import browser_cookie3

    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    print("\n  Fully quit Chrome first (Cmd+Q — not just close the window).")
    input("  Press Enter when Chrome is closed > ")

    log.info("Reading OpenArt.ai cookies from Chrome…")
    try:
        raw = list(browser_cookie3.chrome(domain_name="openart.ai"))
    except Exception as e:
        raise RuntimeError(f"Could not read Chrome cookies: {e}")

    if not raw:
        raise RuntimeError(
            "No openart.ai cookies found in Chrome. "
            "Make sure you're logged into openart.ai in Chrome first."
        )

    cookies = []
    for c in raw:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "sameSite": "None",
        })

    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    log.info(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")
    print(f"\n  Done — {len(cookies)} cookies saved. You can now run the pipeline.")
