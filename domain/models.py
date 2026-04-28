from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    id: str              # SHA1 of URL — stable dedup key
    title: str
    url: str
    published_at: datetime
    category: str
    content: str         # Full scraped body text
    status: str = "new"  # new | summarized | video_ready | downloaded | posted | failed
    error: str | None = None


@dataclass
class Summary:
    id: str
    article_id: str
    text: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class VideoJob:
    id: str
    summary_id: str
    openart_job_id: str | None = None
    video_url: str | None = None
    local_path: str | None = None
    status: str = "pending"  # pending | generating | ready | failed
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TikTokPost:
    id: str
    video_job_id: str
    post_mode: str           # draft | direct
    tiktok_video_id: str | None = None
    status: str = "uploading"  # uploading | published | failed
    posted_at: datetime | None = None
