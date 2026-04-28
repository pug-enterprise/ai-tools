"""
APScheduler — runs the pipeline on a cron interval.
"""

import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from config import settings
from infra.repository import ArticleRepo, SummaryRepo, VideoJobRepo, PostRepo
from domain.pipeline import PipelineService
from services.video_gen import OpenArtVideoGenerator
from services.tiktok import TikTokClient

log = logging.getLogger(__name__)


def _build_pipeline() -> PipelineService:
    return PipelineService(
        articles=ArticleRepo(),
        summaries=SummaryRepo(),
        video_jobs=VideoJobRepo(),
        posts=PostRepo(),
        video_gen=OpenArtVideoGenerator(),
        tiktok=TikTokClient(),
    )


def _run_job():
    log.info("Scheduled pipeline run starting")
    try:
        pipeline = _build_pipeline()
        stats = pipeline.run(post_mode=settings.tiktok_post_mode)
        log.info(f"Pipeline complete: {stats}")
    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)


def start():
    interval = settings.schedule_interval_minutes
    log.info(f"Starting scheduler — interval={interval}m, post_mode={settings.tiktok_post_mode}")

    scheduler = BlockingScheduler()
    scheduler.add_job(_run_job, "interval", minutes=interval, id="pipeline")

    # Run once immediately on start
    _run_job()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")
