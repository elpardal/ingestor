import asyncpg
from typing import Optional, List
from contextlib import asynccontextmanager
from src.domain.models import TelegramFile, ProcessingJob, ExtractedIndicator

class DatabaseAdapter:
    """
    Adaptador assíncrono para PostgreSQL com operações idempotentes.
    Nunca expõe detalhes de conexão para camadas superiores.
    """
    
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
    
    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    @asynccontextmanager
    async def transaction(self):
        if not self._pool:
            raise RuntimeError("Database not connected")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    async def exists_by_telegram_id(self, telegram_file_id: str) -> bool:
        """
        Deduplicação pré-download: verifica se arquivo já foi processado pelo ID do Telegram.
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        row = await self._pool.fetchrow(
            "SELECT 1 FROM processed_files WHERE telegram_file_id = $1 LIMIT 1",
            telegram_file_id
        )
        return row is not None
    
    async def exists_by_hash(self, file_hash: str) -> bool:
        """
        Deduplicação pós-download: verifica se conteúdo já existe no storage.
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        row = await self._pool.fetchrow(
            "SELECT 1 FROM processed_files WHERE file_hash = $1 LIMIT 1",
            file_hash
        )
        return row is not None
    
    async def record_processed_file(
        self,
        file: TelegramFile,
        file_hash: str,
        storage_path: str
    ) -> None:
        """
        Registra arquivo processado com UPSERT idempotente.
        Atualiza last_seen_at se já existir (reaparecimento do mesmo arquivo).
        """
        async with self.transaction() as conn:
            await conn.execute("""
                INSERT INTO processed_files (
                    telegram_file_id, channel_id, channel_title, filename,
                    size_bytes, file_hash, storage_path, first_seen_at, last_seen_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                ON CONFLICT (telegram_file_id) DO UPDATE
                SET last_seen_at = NOW()
                WHERE processed_files.telegram_file_id = $1
            """,
                file.telegram_file_id,
                file.channel_id,
                file.channel_title,
                file.filename,
                file.size_bytes,
                file_hash,
                storage_path
            )
    
    async def log_job(self, job: ProcessingJob) -> None:
        """Registra job SEM depender de processed_files existir."""
        async with self.transaction() as conn:
            await conn.execute("""
                INSERT INTO processing_jobs (
                    job_id, telegram_file_id, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (job_id) DO NOTHING
            """,
                job.job_id,
                job.file.telegram_file_id,
                job.status.value,
                job.created_at,
                job.created_at
            )
    
    async def update_job_status(
        self,
        job_id: str,
        status: str,
        error: Optional[str] = None,
        file_hash: Optional[str] = None
    ) -> None:
        """Atualiza status do job, opcionalmente registrando hash mesmo em falhas."""
        async with self.transaction() as conn:
            await conn.execute("""
                UPDATE processing_jobs
                SET status = $1, error = $2, updated_at = NOW(), file_hash = COALESCE($3, file_hash)
                WHERE job_id = $4
            """,
                status,
                error,
                file_hash,
                job_id
            )
    
    async def persist_indicator(self, indicator: ExtractedIndicator) -> bool:
        """
        Persiste indicador com UPSERT idempotente.
        Retorna True se novo, False se já existia.
        """
        async with self.transaction() as conn:
            result = await conn.execute("""
                INSERT INTO extracted_indicators (
                    indicator_type, value, source_file_hash, source_relative_path,
                    source_line, channel_id, first_seen_at, last_seen_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                ON CONFLICT (indicator_type, value, source_file_hash, source_line) DO UPDATE
                SET last_seen_at = NOW()
                WHERE extracted_indicators.indicator_type = $1
                  AND extracted_indicators.value = $2
                  AND extracted_indicators.source_file_hash = $3
                  AND extracted_indicators.source_line = $5
            """,
                indicator.indicator_type.value,
                indicator.value,
                indicator.source_file_hash,
                indicator.source_relative_path,
                indicator.source_line,
                indicator.channel_id
            )
            # asyncpg retorna "INSERT 0 1" para novo, "UPDATE 1" para existente
            return result.startswith("INSERT")
    
    async def count_indicators_by_type(self) -> dict:
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        rows = await self._pool.fetch("""
            SELECT indicator_type, COUNT(*) as count
            FROM extracted_indicators
            GROUP BY indicator_type
        """)
        return {row["indicator_type"]: row["count"] for row in rows}