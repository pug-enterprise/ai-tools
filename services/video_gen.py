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


class DryRunComplete(Exception):
    """Raised when dry-run mode stops before generating a video."""


STORY_URL     = "https://openart.ai/story/create/script"
SESSION_DIR   = Path.home() / ".ai-tools" / "openart-session"
COOKIES_FILE  = SESSION_DIR / "cookies.json"
POLL_TIMEOUT  = 1800  # seconds (30 minutes)
POLL_INTERVAL = 10    # seconds


class VideoGenerator(Protocol):
    def generate(self, summary: Summary) -> VideoJob:
        ...


class OpenArtVideoGenerator:
    """Playwright-based OpenArt.ai automation."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

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

            # ── Dry run — pause for inspection, don't generate ───────────────
            if self.dry_run:
                log.info("DRY RUN — inspect the browser, then close the window to continue.")
                print("\n  *** DRY RUN: Check the browser — verify character, ratio, and style. ***")
                print("  Close the browser window when done inspecting.")
                try:
                    page.wait_for_event("close", timeout=300_000)
                except Exception:
                    pass
                ctx.close()
                browser.close()
                raise DryRunComplete(f"Dry run complete for article: {summary.article_id}")

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
        img = page.locator(f'img[alt="{name}"]')
        if img.count() == 0:
            log.warning(f"Character '{name}' not found — skipping")
            return

        # The img is hidden inside a parent clickable container — click the parent
        img.first.evaluate("el => { const p = el.closest('button, li, [role=\"option\"], [class*=\"character\"], [class*=\"avatar\"], div[tabindex]') || el.parentElement; p.click(); }")
        page.wait_for_timeout(600)
        log.info(f"Character set to: {name}")
    except Exception as e:
        log.warning(f"Could not select character '{name}': {e}")


def _select_aspect_ratio(page, ratio: str):
    """Select aspect ratio by clicking the parent of the <p> text label."""
    try:
        # The ratio is rendered as <p ...>9:16</p> inside a clickable parent
        p = page.locator(f'p:has-text("{ratio}")')
        if p.count() == 0:
            log.warning(f"Aspect ratio '{ratio}' not found — skipping")
            return
        p.first.evaluate("el => { const p = el.closest('button, [role=\"button\"], div[tabindex], li') || el.parentElement; p.click(); }")
        page.wait_for_timeout(500)
        log.info(f"Aspect ratio set to: {ratio}")
    except Exception as e:
        log.warning(f"Could not set aspect ratio '{ratio}': {e}")


def _apply_visual_style(page, story_text: str):
    """
    Click the 'Custom' style card then fill the 'Describe the style' textarea.
    The card's clickable element is div[tabindex="0"] containing img[alt="Custom"].
    """
    try:
        # Target the div[tabindex="0"] that wraps the Custom card directly
        custom_card = page.locator('div[tabindex="0"]:has(img[alt="Custom"])')
        if custom_card.count() == 0:
            log.warning("Custom style card not found — skipping")
            return

        custom_card.first.scroll_into_view_if_needed()
        custom_card.first.click()
        page.wait_for_timeout(1500)

        # Target the visible textarea (not the aria-hidden mirror)
        style_input = page.locator('textarea[placeholder="Describe the style"]:not([aria-hidden])').first
        style_input.wait_for(timeout=8_000)
        style_input.scroll_into_view_if_needed()
        style_input.click()
        page.wait_for_timeout(200)
        # Select all existing text and replace
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(100)
        style_input.press_sequentially(_build_style_prompt(story_text), delay=20)
        page.wait_for_timeout(300)
        log.info("Visual style applied")
    except Exception as e:
        log.warning(f"Could not apply visual style: {e}")


MAX_STYLE_CHARS = 200

def _build_style_prompt(story_text: str) -> str:
    """Ask Claude to generate a visual style prompt for this story, capped at 200 chars."""
    from services.summarizer import _run_claude

    prompt = (
        f"Write a visual style description for an AI video generator. "
        f"It must be under {MAX_STYLE_CHARS} characters. "
        f"Base it on Old School RuneScape's art style (medieval fantasy, pixel-art roots, "
        f"dark atmospheric lighting, runic textures) combined with the mood of this news story. "
        f"Output ONLY the style description, no quotes, no explanation.\n\n"
        f"Story summary:\n{story_text[:500]}"
    )

    try:
        result = _run_claude(prompt).strip().strip('"').strip("'")
        # Hard cap at MAX_STYLE_CHARS, trim to last full word
        if len(result) > MAX_STYLE_CHARS:
            result = result[:MAX_STYLE_CHARS].rsplit(" ", 1)[0]
        log.info(f"AI style prompt: {result!r}")
        return result
    except Exception as e:
        log.warning(f"Claude style generation failed, using fallback: {e}")
        return "Epic fantasy MMORPG news style. Dark medieval aesthetic, dramatic lighting, runic textures, cinematic atmosphere."


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
