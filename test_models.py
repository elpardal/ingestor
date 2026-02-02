# test_models.py
from datetime import datetime, timezone
from src.domain.models import TelegramFile, ProcessingJob

file = TelegramFile(
    telegram_file_id="123_456_789",
    channel_id=123,
    channel_title="Teste",
    filename="arquivo.rar",
    size_bytes=1024,
    timestamp=datetime.now(timezone.utc)
)

job = ProcessingJob(file=file)
print(f"Job criado: {job.job_id}, status={job.status}")
assert job.status == "queued"
print("✓ Models validados")