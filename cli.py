#!/usr/bin/env python3
"""
AI Tools CLI — manual pipeline trigger + utilities.

Usage:
  python cli.py run [--draft|--publish]
  python cli.py status
  python cli.py retry <article_id>
  python cli.py auth tiktok
"""

import logging
import sys
from typing import Optional

import click

# Ensure project root is on path when running directly
sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")

from config import settings
from infra.db import get_conn
from infra.repository import ArticleRepo, SummaryRepo, VideoJobRepo, PostRepo
from domain.pipeline import PipelineService
from services.video_gen import OpenArtVideoGenerator
from services.tiktok import TikTokClient

import os
from logging.handlers import RotatingFileHandler

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "pipeline.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(_log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ],
)


def _build_pipeline(dry_run: bool = False) -> PipelineService:
    return PipelineService(
        articles=ArticleRepo(),
        summaries=SummaryRepo(),
        video_jobs=VideoJobRepo(),
        posts=PostRepo(),
        video_gen=OpenArtVideoGenerator(dry_run=dry_run),
        tiktok=TikTokClient(),
    )


@click.group()
def cli():
    """AI Tools — OSRS news → TikTok video pipeline."""


@cli.command()
@click.option("--draft/--publish", default=None, help="Override post mode (default: from .env)")
@click.option("--dry-run", is_flag=True, default=False, help="Open browser and set options but don't generate video")
def run(draft: Optional[bool], dry_run: bool):
    """Run the full pipeline once."""
    if draft is None:
        post_mode = settings.tiktok_post_mode
    else:
        post_mode = "draft" if draft else "direct"

    if dry_run:
        click.echo("Running pipeline (DRY RUN — will not generate videos)")
    else:
        click.echo(f"Running pipeline (post_mode={post_mode})")

    pipeline = _build_pipeline(dry_run=dry_run)
    stats = pipeline.run(post_mode=post_mode)

    click.echo("\nResults:")
    for key, val in stats.items():
        click.echo(f"  {key:12s}: {val}")


@cli.command()
def status():
    """Show all articles and their pipeline status."""
    repo = ArticleRepo()
    articles = repo.all()

    if not articles:
        click.echo("No articles in database.")
        return

    # Count by status
    from collections import Counter
    counts = Counter(a.status for a in articles)
    click.echo(f"\nTotal: {len(articles)} articles")
    for status_name, count in sorted(counts.items()):
        click.echo(f"  {status_name:15s}: {count}")

    click.echo("\nRecent articles:")
    for a in articles[:20]:
        err = f"\n    ✗ {a.error[:80]}" if a.error else ""
        click.echo(f"  [{a.status:12s}] {a.title[:55]}  ({a.id[:12]}){err}")


@cli.command()
@click.argument("article_id")
def retry(article_id: str):
    """Reset a failed article back to 'new' so it reruns next pipeline execution."""
    repo = ArticleRepo()
    article = repo.get(article_id)
    if not article:
        click.echo(f"Article not found: {article_id}", err=True)
        sys.exit(1)

    repo.set_status(article_id, "new", error=None)
    click.echo(f"Reset {article.title!r} → status=new")


@cli.command("openart-login")
def openart_login():
    """Open a browser to log into OpenArt.ai via Google SSO and save the session."""
    from services.video_gen import login_interactively
    login_interactively()
    click.echo("Session saved. You won't need to log in again unless the session expires.")


@cli.command("auth")
@click.argument("service", type=click.Choice(["tiktok"]))
def auth(service: str):
    """Run OAuth flow for a service and save the access token."""
    if service == "tiktok":
        _tiktok_oauth()


def _tiktok_oauth():
    """Minimal TikTok OAuth 2.0 PKCE flow (opens browser, captures redirect)."""
    import base64
    import hashlib
    import os
    import secrets
    import urllib.parse
    import webbrowser
    from http.server import HTTPServer, BaseHTTPRequestHandler

    client_key = settings.tiktok_client_key
    if not client_key:
        click.echo("TIKTOK_CLIENT_KEY is not set in .env", err=True)
        sys.exit(1)

    # PKCE
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    scopes = "video.publish,video.upload"
    redirect_uri = "https://pug-enterprise.github.io/ai-tools/callback.html"

    params = {
        "client_key": client_key,
        "scope": scopes,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)

    click.echo(f"Opening TikTok authorization page…\n{auth_url}")
    webbrowser.open(auth_url)

    # Capture the code via a local redirect server
    code_holder: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_holder["code"] = qs.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Auth complete. Close this tab.</h1>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", 8765), Handler)
    click.echo("Waiting for redirect… (authorize in your browser)")
    server.handle_request()

    code = code_holder.get("code")
    if not code:
        click.echo("No code received.", err=True)
        sys.exit(1)

    # Exchange code for access token
    import httpx as _httpx
    resp = _httpx.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={
            "client_key": client_key,
            "client_secret": settings.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    token_data = resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        click.echo(f"Token exchange failed: {token_data}", err=True)
        sys.exit(1)

    # Write to .env
    _update_env("TIKTOK_ACCESS_TOKEN", access_token)
    click.echo(f"\nAccess token saved to .env")
    click.echo(f"Expires in: {token_data.get('expires_in', '?')}s")
    click.echo(f"Scopes: {token_data.get('scope', '?')}")


def _update_env(key: str, value: str):
    env_path = ".env"
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


if __name__ == "__main__":
    cli()
