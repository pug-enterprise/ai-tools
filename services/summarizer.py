"""
Claude CLI summarizer.

Spawns the `claude` binary as a subprocess, pipes the article content,
and returns a Summary domain object.
"""

from __future__ import annotations
import json
import logging
import subprocess
from datetime import datetime
from uuid import uuid4

from config import settings
from domain.models import Article, Summary

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """\
Summarize this Old School RuneScape news article in 150-200 words.
Write in present tense. Be punchy and engaging — this will be read aloud in a TikTok video.
Do NOT include hashtags, emojis, or "In summary".
Start directly with the news.

ARTICLE TITLE: {title}

ARTICLE CONTENT:
{content}
"""


def summarize(article: Article) -> Summary:
    prompt = PROMPT_TEMPLATE.format(
        title=article.title,
        content=article.content[:8000],  # cap to avoid token overrun
    )

    log.info(f"Summarizing: {article.title!r}")

    result = _run_claude(prompt)

    return Summary(
        id=str(uuid4()),
        article_id=article.id,
        text=result.strip(),
        created_at=datetime.utcnow(),
    )


def _run_claude(prompt: str) -> str:
    cli = settings.claude_cli_path
    cmd = [
        cli,
        "-p", prompt,
        "--output-format", "json",
        "--model", "claude-haiku-4-5-20251001",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timed out after 120s")
    except FileNotFoundError:
        raise RuntimeError(f"Claude CLI not found at: {cli}")

    if proc.returncode != 0:
        raise RuntimeError(f"Claude CLI error (rc={proc.returncode}): {proc.stderr[:500]}")

    try:
        data = json.loads(proc.stdout)
        # Stream-json format: { "type": "result", "result": "..." }
        if isinstance(data, dict):
            return data.get("result") or data.get("content") or str(data)
        return str(data)
    except json.JSONDecodeError:
        # Plain text fallback
        return proc.stdout.strip()
