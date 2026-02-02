from src.config.settings import Settings
s = Settings(_env_file=".env")
print(f"Canais: {s.telegram_channels}")
print(f"Storage: {s.storage_path}")