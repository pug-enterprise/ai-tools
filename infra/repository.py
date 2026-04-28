"""
Repository classes — thin wrappers around SQLite for each domain model.
"""

from __future__ import annotations
from datetime import datetime
from uuid import uuid4

from domain.models import Article, Summary, VideoJob, TikTokPost
from infra.db import get_conn


def _now() -> str:
    return datetime.utcnow().isoformat()


class ArticleRepo:
    def exists(self, article_id: str) -> bool:
        row = get_conn().execute(
            "SELECT 1 FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        return row is not None

    def save(self, article: Article) -> None:
        get_conn().execute(
            """
            INSERT OR IGNORE INTO articles
              (id, title, url, published_at, category, content, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.id,
                article.title,
                article.url,
                article.published_at.isoformat(),
                article.category,
                article.content,
                article.status,
                article.error,
            ),
        )
        get_conn().commit()

    def by_status(self, status: str) -> list[Article]:
        rows = get_conn().execute(
            "SELECT * FROM articles WHERE status = ? ORDER BY published_at", (status,)
        ).fetchall()
        return [_row_to_article(r) for r in rows]

    def set_status(self, article_id: str, status: str, error: str | None = None) -> None:
        get_conn().execute(
            "UPDATE articles SET status = ?, error = ? WHERE id = ?",
            (status, error, article_id),
        )
        get_conn().commit()

    def all(self) -> list[Article]:
        rows = get_conn().execute(
            "SELECT * FROM articles ORDER BY published_at DESC"
        ).fetchall()
        return [_row_to_article(r) for r in rows]

    def get(self, article_id: str) -> Article | None:
        row = get_conn().execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        return _row_to_article(row) if row else None


def _row_to_article(row) -> Article:
    return Article(
        id=row["id"],
        title=row["title"],
        url=row["url"],
        published_at=datetime.fromisoformat(row["published_at"]),
        category=row["category"],
        content=row["content"],
        status=row["status"],
        error=row["error"],
    )


class SummaryRepo:
    def save(self, summary: Summary) -> None:
        get_conn().execute(
            "INSERT OR IGNORE INTO summaries (id, article_id, text, created_at) VALUES (?, ?, ?, ?)",
            (summary.id, summary.article_id, summary.text, summary.created_at.isoformat()),
        )
        get_conn().commit()

    def by_article(self, article_id: str) -> Summary | None:
        row = get_conn().execute(
            "SELECT * FROM summaries WHERE article_id = ? ORDER BY created_at DESC LIMIT 1",
            (article_id,),
        ).fetchone()
        if not row:
            return None
        return Summary(
            id=row["id"],
            article_id=row["article_id"],
            text=row["text"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class VideoJobRepo:
    def save(self, job: VideoJob) -> None:
        get_conn().execute(
            """
            INSERT OR IGNORE INTO video_jobs
              (id, summary_id, openart_job_id, video_url, local_path, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.summary_id,
                job.openart_job_id,
                job.video_url,
                job.local_path,
                job.status,
                job.created_at.isoformat(),
            ),
        )
        get_conn().commit()

    def set_local_path(self, job_id: str, local_path: str) -> None:
        get_conn().execute(
            "UPDATE video_jobs SET local_path = ?, status = 'ready' WHERE id = ?",
            (local_path, job_id),
        )
        get_conn().commit()

    def by_summary(self, summary_id: str) -> VideoJob | None:
        row = get_conn().execute(
            "SELECT * FROM video_jobs WHERE summary_id = ? ORDER BY created_at DESC LIMIT 1",
            (summary_id,),
        ).fetchone()
        if not row:
            return None
        return VideoJob(
            id=row["id"],
            summary_id=row["summary_id"],
            openart_job_id=row["openart_job_id"],
            video_url=row["video_url"],
            local_path=row["local_path"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class PostRepo:
    def save(self, post: TikTokPost) -> None:
        get_conn().execute(
            """
            INSERT OR IGNORE INTO tiktok_posts
              (id, video_job_id, post_mode, tiktok_video_id, status, posted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                post.id,
                post.video_job_id,
                post.post_mode,
                post.tiktok_video_id,
                post.status,
                post.posted_at.isoformat() if post.posted_at else None,
            ),
        )
        get_conn().commit()
