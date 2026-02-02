from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List, Set
from ipaddress import ip_network

class Settings(BaseSettings):
    # Telegram
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telegram_channels: str  # STRING BRUTA: "canal1,canal2"
    
    # Performance
    worker_count: int = 4
    max_file_size_mb: int = 100
    
    # Storage
    storage_path: Path = Path("./data/storage")
    
    # Database
    database_url: str = "postgresql:///telegram_ingest_test"
    
    # IOCs (strings brutas)
    ioc_domains: str = ""
    ioc_emails: str = ""
    ioc_ipv4_cidrs: str = ""
    
    # Métodos de acesso (conversão safe em runtime)
    def get_telegram_channels(self) -> List[str]:
        return [ch.strip() for ch in self.telegram_channels.split(",") if ch.strip()]
    
    def get_domain_set(self) -> Set[str]:
        return {d.strip().lower() for d in self.ioc_domains.split(",") if d.strip()}
    
    def get_email_domains_set(self) -> Set[str]:
        return {
            e.strip().lower().lstrip("@")
            for e in self.ioc_emails.split(",")
            if e.strip()
        }
    
    def get_cidr_networks(self) -> List:
        nets = []
        for cidr in self.ioc_ipv4_cidrs.split(","):
            cidr = cidr.strip()
            if cidr:
                try:
                    nets.append(ip_network(cidr, strict=False))
                except ValueError:
                    pass
        return nets
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignora variáveis extras no .env