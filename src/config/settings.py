from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telegram_channels: str
    
    worker_count: int = 4
    max_file_size_mb: int = 100
    storage_path: Path = Path("./data/storage")
    
    database_url: str = "postgresql://ingestor:ingestor@localhost:5432/telegram_ingest"
    
    ioc_domains: str = ""
    ioc_emails: str = ""
    ioc_ipv4_cidrs: str = ""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"