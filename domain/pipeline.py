"""
PipelineService — orchestrates all stages of the OSRS → TikTok pipeline.

Each stage is independently resumable. A failed article stays at its current
status and is retried on the next run.
"""

import logging
from typing import Literal

from infra.repository import ArticleRepo, SummaryRepo, VideoJobRepo, PostRepo
from services.scraper import fetch_articles
from services.summarizer import summarize
from services.video_gen import VideoGenerator, DryRunComplete
from services.downloader import download_video
from services.tiktok import TikTokClient

log = logging.getLogger(__name__)

PostMode = Literal["draft", "direct"]


class PipelineService:
    def __init__(
        self,
        articles: ArticleRepo,
        summaries: SummaryRepo,
        video_jobs: VideoJobRepo,
        posts: PostRepo,
        video_gen: VideoGenerator,
        tiktok: TikTokClient,
    ):
        self.articles = articles
        self.summaries = summaries
        self.video_jobs = video_jobs
        self.posts = posts
        self.video_gen = video_gen
        self.tiktok = tiktok

    def run(self, post_mode: PostMode = "draft") -> dict:
        stats = {"scraped": 0, "summarized": 0, "video": 0, "posted": 0, "errors": 0}

        # ── Stage 1: Scrape new articles ─────────────────────────────────────
        log.info("Stage 1: scraping OSRS news")
        try:
            articles = fetch_articles()
            new_count = 0
            for article in articles:
                if not self.articles.exists(article.id):
                    self.articles.save(article)
                    new_count += 1
            stats["scraped"] = new_count
            log.info(f"  {new_count} new articles saved")
        except Exception as e:
            log.error(f"Scrape stage failed: {e}")
            stats["errors"] += 1

        # ── Stage 2: Summarize ───────────────────────────────────────────────
        log.info("Stage 2: summarizing articles")
        for article in self.articles.by_status("new"):
            try:
                summary = summarize(article)
                self.summaries.save(summary)
                self.articles.set_status(article.id, "summarized")
                stats["summarized"] += 1
                log.info(f"  Summarized: {article.title!r}")
            except Exception as e:
                log.error(f"  Summarize failed for {article.id}: {e}")
                self.articles.set_status(article.id, "failed", error=str(e))
                stats["errors"] += 1

        # ── Stage 3: Generate + download video ───────────────────────────────
        log.info("Stage 3: generating videos")
        for article in self.articles.by_status("summarized"):
            try:
                summary = self.summaries.by_article(article.id)
                if not summary:
                    raise RuntimeError("No summary found")

                job = self.video_gen.generate(summary)
                self.video_jobs.save(job)

                local_path = download_video(job.video_url, article.id)
                self.video_jobs.set_local_path(job.id, local_path)

                self.articles.set_status(article.id, "downloaded")
                stats["video"] += 1
                log.info(f"  Video ready: {local_path}")
            except DryRunComplete as e:
                log.info(f"  {e}")
            except Exception as e:
                log.error(f"  Video stage failed for {article.id}: {e}")
                self.articles.set_status(article.id, "failed", error=str(e))
                stats["errors"] += 1

        # ── Stage 4: Post to TikTok ──────────────────────────────────────────
        log.info(f"Stage 4: posting to TikTok (mode={post_mode})")
        for article in self.articles.by_status("downloaded"):
            try:
                job = self.video_jobs.by_summary(
                    self.summaries.by_article(article.id).id
                )
                if not job or not job.local_path:
                    raise RuntimeError("No downloaded video found")

                caption = f"📰 {article.title} #OSRS #RuneScape #Gaming"
                post = self.tiktok.publish(
                    local_path=job.local_path,
                    caption=caption,
                    mode=post_mode,
                )
                self.posts.save(post)
                self.articles.set_status(article.id, "posted")
                stats["posted"] += 1
                log.info(f"  Posted: {article.title!r} (id={post.tiktok_video_id})")
            except Exception as e:
                log.error(f"  Post failed for {article.id}: {e}")
                self.articles.set_status(article.id, "failed", error=str(e))
                stats["errors"] += 1

        return stats
