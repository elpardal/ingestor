import asyncio
import logging
import tempfile
import rarfile
import zipfile
from pathlib import Path
from typing import Optional
from src.domain.models import TelegramFile, ProcessingJob, JobStatus, ExtractedIndicator
from src.application.deduplication_service import DeduplicationService
from src.infrastructure.storage.adapter import StorageAdapter
from src.infrastructure.database.adapter import DatabaseAdapter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.application.ioc_extraction_service import IOCExtractionService
from src.infrastructure.healthcheck import HealthCheckServer  # Import opcional

logger = logging.getLogger(__name__)

class IngestionService:
    """
    Orquestrador do pipeline completo de ingestão.
    Coordena download, deduplicação, persistência e extração de IOCs.
    """
    
    def __init__(
        self,
        storage: StorageAdapter,
        db: DatabaseAdapter,
        dedup: DeduplicationService,
        telegram: TelegramAdapter,
        ioc_scanner: IOCExtractionService,
        max_workers: int,
        health_server: Optional[HealthCheckServer] = None  # Parâmetro opcional
    ):
        self.storage = storage
        self.db = db
        self.dedup = dedup
        self.telegram = telegram
        self.ioc_scanner = ioc_scanner
        self.semaphore = asyncio.Semaphore(max_workers)
        self.health_server = health_server
        self._running_jobs: set[str] = set()
    
    async def process_file(self, file: TelegramFile) -> None:
        """
        Pipeline completo de processamento de um arquivo.
        Totalmente idempotente — reexecução não gera efeitos colaterais.
        """
        async with self.semaphore:
            job = ProcessingJob(file=file)
            self._running_jobs.add(job.job_id)
            
            try:
                await self.db.log_job(job)
                logger.info(f"Iniciando job {job.job_id[:8]}: {file.filename}")
                
                # === ETAPA 1: Deduplicação pré-download ===
                if not await self.dedup.should_process_by_telegram_id(file):
                    logger.info(
                        f"Job {job.job_id[:8]} ignorado — Telegram ID já processado: "
                        f"{file.telegram_file_id}"
                    )
                    if self.health_server:
                        self.health_server.increment_files_deduplicated()
                    await self.db.update_job_status(job.job_id, JobStatus.COMPLETED.value)
                    return
                
                # === ETAPA 2: Download ===
                message = await self._fetch_message(file)
                if not message:
                    raise ValueError(f"Mensagem não encontrada para {file.telegram_file_id}")
                
                temp_path = await self._download_with_isolation(file, message, job.job_id)
                
                # === ETAPA 3: Deduplicação pós-download ===
                should_process, file_hash = await self.dedup.should_process_by_content(temp_path)
                if not should_process:
                    logger.info(
                        f"Job {job.job_id[:8]} ignorado — conteúdo já existe (hash: {file_hash[:16]})"
                    )
                    temp_path.unlink(missing_ok=True)
                    if self.health_server:
                        self.health_server.increment_files_deduplicated()
                    # Registra hash mesmo em deduplicação
                    await self.db.update_job_status(
                        job.job_id, 
                        JobStatus.COMPLETED.value, 
                        file_hash=file_hash
                    )
                    return
                
                # === ETAPA 4: Persistência ===
                final_path = await self.storage.persist_file(temp_path, file_hash, file.filename)
                await self.db.record_processed_file(file, file_hash, str(final_path))
                await self.db.update_job_status(
                    job.job_id, 
                    JobStatus.COMPLETED.value, 
                    file_hash=file_hash  # Registra hash no job
                )
                logger.info(
                    f"Arquivo persistido: {final_path.relative_to(self.storage.base_path)}"
                )
                
                # === ETAPA 5: Extração de IOCs ===
                indicators = await self._extract_and_scan(file, final_path, file_hash, job.job_id)
                
                await self.db.update_job_status(job.job_id, JobStatus.COMPLETED.value)
                if self.health_server:
                    self.health_server.increment_jobs_processed()
                    if indicators:
                        self.health_server.increment_indicators_found(len(indicators))
                
                logger.info(
                    f"Job {job.job_id[:8]} concluído: {len(indicators)} indicadores extraídos"
                )
            
            except asyncio.CancelledError:
                logger.warning(f"Job {job.job_id[:8]} cancelado por shutdown")
                raise
            
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)[:200]}"
                logger.exception(f"Job {job.job_id[:8]} falhou: {error_msg}")
                if self.health_server:
                    self.health_server.increment_jobs_failed()
                # Registra erro SEM hash (ainda não calculado ou falhou antes)
                await self.db.update_job_status(
                    job.job_id, 
                    JobStatus.FAILED.value, 
                    error=error_msg
                )
            
            finally:
                self._running_jobs.discard(job.job_id)
    
    async def _fetch_message(self, file: TelegramFile):
        """Busca mensagem original pelo ID."""
        try:
            parts = file.telegram_file_id.split("_")
            channel_id = int(parts[0])
            msg_id = int(parts[1])
            
            return await self.telegram.client.get_messages(channel_id, ids=msg_id)
        except Exception as e:
            logger.warning(f"Não foi possível buscar mensagem {file.telegram_file_id}: {e}")
            return None
    
    async def _download_with_isolation(self, file: TelegramFile, message, job_id: str) -> Path:
        """Download em diretório temporário isolado."""
        temp_dir = Path(tempfile.mkdtemp(dir=self.storage.base_path / ".tmp"))
        temp_path = temp_dir / self.storage._sanitize_filename(file.filename)
        
        try:
            await self.telegram.download_file(message, temp_path)
            return temp_path
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise
    
    async def _extract_and_scan(
        self,
        file: TelegramFile,
        archive_path: Path,
        file_hash: str,
        job_id: str
    ) -> list[ExtractedIndicator]:
        """Extrai arquivo compactado e escaneia por IOCs."""
        extract_dir = self.storage.create_extraction_dir()
        indicators: list[ExtractedIndicator] = []
        
        try:
            await self._safe_extract(archive_path, extract_dir)
            indicators = await self.ioc_scanner.scan_directory(
                extract_dir,
                source_file_hash=file_hash,
                channel_id=file.channel_id
            )
            
            # Persistência dos indicadores
            for ind in indicators:
                await self.db.persist_indicator(ind)
            
            return indicators
        
        finally:
            self.storage.cleanup_extraction_dir(extract_dir)
    
    async def _safe_extract(self, archive_path: Path, extract_dir: Path) -> None:
        """
        Extração com proteção contra zip bombs e path traversal.
        """
        max_files = 1000
        max_total_size = 10 * 1024 * 1024 * 1024  # 10 GB
        
        if archive_path.suffix.lower() == ".rar":
            with rarfile.RarFile(archive_path, "r") as rf:
                if len(rf.namelist()) > max_files:
                    raise ValueError(f"Arquivo RAR suspeito: {len(rf.namelist())} arquivos")
                
                total_size = sum(info.file_size for info in rf.infolist())
                if total_size > max_total_size:
                    raise ValueError(f"Tamanho total suspeito: {total_size / 1024**3:.2f} GB")
                
                for member in rf.infolist():
                    target_path = (extract_dir / member.filename).resolve()
                    if not str(target_path).startswith(str(extract_dir.resolve())):
                        raise ValueError(f"Path traversal detectado em: {member.filename}")
                
                rf.extractall(path=extract_dir)
        
        elif archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                if len(zf.namelist()) > max_files:
                    raise ValueError(f"Arquivo ZIP suspeito: {len(zf.namelist())} arquivos")
                
                total_size = sum(info.file_size for info in zf.infolist())
                if total_size > max_total_size:
                    raise ValueError(f"Tamanho total suspeito: {total_size / 1024**3:.2f} GB")
                
                for member in zf.infolist():
                    member_path = (extract_dir / member.filename).resolve()
                    if not str(member_path).startswith(str(extract_dir.resolve())):
                        raise ValueError(f"Path traversal detectado em: {member.filename}")
                
                zf.extractall(path=extract_dir)
        
        else:
            raise ValueError(f"Formato não suportado: {archive_path.suffix}")