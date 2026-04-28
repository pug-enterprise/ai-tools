"""
OSRS news scraper.

Fetches the official RSS feed, then scrapes the full article body for each entry.
Returns a list of Article domain objects.
"""

from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from bs4 import BeautifulSoup

from domain.models import Article

RSS_URL  = "https://secure.runescape.com/m=news/latest_news.rss?oldschool=true"
TIMEOUT  = 15
MIN_DATE = datetime(2026, 4, 23)  # only process articles on or after this date

log = logging.getLogger(__name__)


def fetch_articles() -> list[Article]:
    log.info(f"Fetching OSRS RSS: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)

    if feed.bozo:
        raise RuntimeError(f"RSS parse error: {feed.bozo_exception}")

    articles: list[Article] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for entry in feed.entries:
            try:
                article = _parse_entry(entry, client)
                if article.published_at < MIN_DATE:
                    log.debug(f"Skipping old article ({article.published_at.date()}): {article.title}")
                    continue
                articles.append(article)
            except Exception as e:
                log.warning(f"Skipping entry {entry.get('link', '?')}: {e}")

    log.info(f"Fetched {len(articles)} articles from RSS")
    return articles


def _parse_entry(entry, client: httpx.Client) -> Article:
    url = entry.get("link", "")
    article_id = hashlib.sha1(url.encode()).hexdigest()

    # Parse publication date
    published_at: datetime
    if entry.get("published"):
        try:
            published_at = parsedate_to_datetime(entry["published"]).astimezone(timezone.utc)
        except Exception:
            published_at = datetime.utcnow()
    else:
        published_at = datetime.utcnow()

    category = ""
    if entry.get("tags"):
        category = entry["tags"][0].get("term", "")

    # Scrape full article body
    content = _scrape_body(url, client)

    return Article(
        id=article_id,
        title=entry.get("title", "").strip(),
        url=url,
        published_at=published_at.replace(tzinfo=None),  # store as naive UTC
        category=category,
        content=content,
    )


def _scrape_body(url: str, client: httpx.Client) -> str:
    if not url:
        return ""
    try:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # The news article body is in .news-article or .news-article__content
        body = (
            soup.find(class_="news-article__content")
            or soup.find(class_="news-article")
            or soup.find("article")
        )
        if body:
            return body.get_text(separator="\n", strip=True)

        # Fallback: get all <p> tags
        paragraphs = soup.find_all("p")
        return "\n".join(p.get_text(strip=True) for p in paragraphs)
    except Exception as e:
        log.warning(f"Body scrape failed for {url}: {e}")
        return ""
