#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path
from src.config.settings import Settings
from src.infrastructure.storage.adapter import StorageAdapter
from src.infrastructure.database.adapter import DatabaseAdapter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.application.deduplication_service import DeduplicationService
from src.application.ioc_extraction_service import IOCExtractionService
from src.application.ingestion_service import IngestionService

# Configuração inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")

async def main():
    settings = Settings()
    
    # Garante diretórios base
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    
    # Inicialização de adaptadores
    db = DatabaseAdapter(settings.database_url)
    storage = StorageAdapter(settings.storage_path)
    telegram = TelegramAdapter(settings)
    dedup = DeduplicationService(db)
    ioc_scanner = IOCExtractionService(settings)
    
    # Conexões iniciais
    await db.connect()
    await telegram.connect()
    
    # Resolução de canais
    channel_ids = await telegram.resolve_channels(settings.get_telegram_channels())
    if not channel_ids:
        logger.error("Nenhum canal configurado ou resolvido. Verifique TELEGRAM_CHANNELS no .env")
        return
    
    # Serviço de ingestão
    ingestion = IngestionService(
        storage=storage,
        db=db,
        dedup=dedup,
        telegram=telegram,
        ioc_scanner=ioc_scanner,
        max_workers=settings.worker_count
    )
    
    # Fila com backpressure
    job_queue = asyncio.Queue(maxsize=settings.worker_count * 3)
    
    # Workers
    workers = [
        asyncio.create_task(_worker_loop(job_queue, ingestion))
        for _ in range(settings.worker_count)
    ]
    
    # Listener Telegram (não bloqueante)
    listener = asyncio.create_task(telegram.listen(job_queue, channel_ids))
    
    logger.info(f"Sistema iniciado com {settings.worker_count} workers")
    logger.info(f"Monitorando canais: {', '.join(settings.get_telegram_channels())}")
    
    # Orquestração graceful shutdown
    try:
        await asyncio.gather(listener, *workers)
    except KeyboardInterrupt:
        logger.info("Shutdown iniciado...")
        # Cancela workers
        for w in workers:
            w.cancel()
        # Desconecta Telegram
        await telegram.disconnect()
        # Aguarda cleanup
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        await db.disconnect()
        logger.info("Sistema finalizado")

async def _worker_loop(queue: asyncio.Queue, service: IngestionService):
    while True:
        try:
            file = await queue.get()
            await service.process_file(file)
            queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Worker falhou: {e}")

if __name__ == "__main__":
    asyncio.run(main())