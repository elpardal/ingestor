#!/usr/bin/env python3
import asyncio
import logging
import sys
import signal
from pathlib import Path
from src.config.settings import Settings
from src.infrastructure.storage.adapter import StorageAdapter
from src.infrastructure.database.adapter import DatabaseAdapter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.application.deduplication_service import DeduplicationService
from src.application.ioc_extraction_service import IOCExtractionService
from src.application.ingestion_service import IngestionService
from src.infrastructure.healthcheck import HealthCheckServer


# Configuração inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")

async def main():
    settings = Settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    
    # Inicialização de adaptadores
    db = DatabaseAdapter(settings.database_url)
    storage = StorageAdapter(settings.storage_path)
    telegram = TelegramAdapter(settings)
    dedup = DeduplicationService(db)
    ioc_scanner = IOCExtractionService(settings)
    health_server = HealthCheckServer(port=8080)  # Nova instância
    
    # Conexões iniciais
    await db.connect()
    await telegram.connect()
    await health_server.start()  # Inicia health check
    
    # Resolução de canais
    channel_ids = await telegram.resolve_channels(settings.get_telegram_channels())
    if not channel_ids:
        logger.error("Nenhum canal configurado ou resolvido")
        await health_server.stop()
        return
    
    # Serviço de ingestão
    ingestion = IngestionService(
        storage=storage,
        db=db,
        dedup=dedup,
        telegram=telegram,
        ioc_scanner=ioc_scanner,
        max_workers=settings.worker_count,
        health_server=health_server  # Passa para atualizar métricas
    )
    
    # Fila com backpressure
    job_queue = asyncio.Queue(maxsize=settings.worker_count * 3)
    
    # Workers
    workers = [
        asyncio.create_task(_worker_loop(job_queue, ingestion))
        for _ in range(settings.worker_count)
    ]
    
    # Listener Telegram
    listener = asyncio.create_task(telegram.listen(job_queue, channel_ids))
    
    logger.info(f"Sistema iniciado com {settings.worker_count} workers")
    logger.info(f"Monitorando canais: {', '.join(settings.get_telegram_channels())}")  # Corrigido!
    
    try:
        await asyncio.gather(listener, *workers)
    except KeyboardInterrupt:
        logger.info("Shutdown iniciado...")
        for w in workers:
            w.cancel()
        await telegram.disconnect()
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        # Tempo máximo para workers finalizarem
        await asyncio.wait_for(
            asyncio.gather(*workers, return_exceptions=True),
            timeout=30.0
        )
        await health_server.stop()
        await db.disconnect()
        await telegram.disconnect()
        logger.info("Sistema finalizado com segurança")


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

def handle_sigterm():
    logger.info("Recebido SIGTERM - iniciando shutdown gracioso...")
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, lambda sig, frame: handle_sigterm())
signal.signal(signal.SIGINT, lambda sig, frame: handle_sigterm())

if __name__ == "__main__":
    asyncio.run(main())