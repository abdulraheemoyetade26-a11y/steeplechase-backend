from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    secret_key: str
    database_url: str = "sqlite:///./steeplechase.db"
    upload_dir: str = "uploads"
    access_token_minutes: int = 60 * 24 * 7
    max_upload_mb: int = 25
    tesseract_cmd: str = ""
    gemini_api_key: str = ""


settings = Settings()
