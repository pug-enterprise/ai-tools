from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # TikTok
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_access_token: str = ""
    tiktok_post_mode: str = "draft"       # draft | direct

    # Claude CLI
    claude_cli_path: str = "claude"

    # Storage
    db_path: str = "./ai_tools.db"
    downloads_dir: str = "./downloads"

    # Scheduler
    schedule_interval_minutes: int = 60


settings = Settings()
