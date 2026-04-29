# Changelog

All notable changes to AI Tools are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.1.0] - 2026-04-28

### Added
- **OSRS → TikTok pipeline** — fully automated news-to-video content pipeline
- **Scraper** (`services/scraper.py`) — fetches OSRS RSS feed, scrapes full article body per entry
  - Filters to articles published on or after April 23, 2026
- **Summarizer** (`services/summarizer.py`) — Claude CLI generates punchy 150-200 word TikTok-ready summaries
- **Video generator** (`services/video_gen.py`) — Playwright automation on OpenArt.ai story creator
  - Persistent session via Chrome cookie extraction (`python cli.py openart-login`)
  - Selects character Zam, 9:16 aspect ratio, custom visual style from story content
  - Network intercept captures newly generated video URL (ignores pre-existing URLs on page)
- **Downloader** (`services/downloader.py`) — streaming MP4 download to `downloads/`
- **TikTok client** (`services/tiktok.py`) — Content Posting API v2
  - Supports `draft` mode (creator inbox) and `direct` mode (publish immediately)
  - Chunked upload with Content-Range headers, polls for `PUBLISH_COMPLETE`
  - Chunk size auto-adjusts for files smaller than 10MB
- **Pipeline orchestrator** (`domain/pipeline.py`) — 4 resumable stages; failed articles stay at current status and retry next run
- **SQLite persistence** (`infra/db.py`, `infra/repository.py`) — articles, summaries, video jobs, posts
- **CLI** (`cli.py`)
  - `run [--draft|--publish]` — trigger pipeline manually
  - `status` — show all articles with status and short ID
  - `retry <id>` — reset failed article to `new`
  - `openart-login` — extract Chrome cookies for OpenArt.ai session
  - `auth tiktok` — OAuth 2.0 PKCE flow, saves access token to `.env`
- **Scheduler** (`scheduler.py`) — APScheduler cron, configurable interval via `SCHEDULE_INTERVAL_MINUTES`
- **File logging** — all runs saved to `logs/pipeline.log` (rotating, 5MB max, 3 backups)
- GitHub Pages site (`docs/`) for TikTok developer portal requirements (ToS, Privacy Policy, callback)
- App icon (`assets/app-icon.png`) — 1024×1024 PNG for TikTok developer portal

### Fixed
- TikTok `invalid_params: The chunk size is invalid` — chunk size now capped to file size for small files
- OpenArt.ai same-video-URL bug — network intercept tracks pre-existing URLs and ignores them
- Google SSO block in Playwright — replaced browser automation login with direct Chrome cookie extraction
- TikTok OAuth localhost redirect rejected — GitHub Pages `callback.html` forwards params to local server
