# src/domain/models.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pathlib import Path
import uuid

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class IndicatorType(str, Enum):
    DOMAIN = "domain"
    EMAIL = "email"
    IPV4 = "ipv4"

@dataclass(frozen=True)
class TelegramFile:
    telegram_file_id: str  # formato: "{channel_id}_{message_id}_{document_id}"
    channel_id: int
    channel_title: str
    filename: str
    size_bytes: int
    timestamp: datetime

@dataclass
class ProcessingJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file: TelegramFile = field(repr=False)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    error: Optional[str] = None

@dataclass(frozen=True)
class ExtractedIndicator:
    indicator_type: IndicatorType
    value: str
    source_file_hash: str
    source_relative_path: str  # caminho dentro do .zip/.rar
    source_line: int
    channel_id: int
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))