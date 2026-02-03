import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from aiohttp import web

logger = logging.getLogger(__name__)

class HealthCheckServer:
    """
    Servidor HTTP leve para health checks e métricas.
    Roda em thread separada do event loop principal.
    """
    
    def __init__(self, port: int = 8080):
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/health", self._health_handler)
        self.app.router.add_get("/metrics", self._metrics_handler)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._started_at = datetime.now(timezone.utc)
        self._stats = {
            "jobs_processed": 0,
            "jobs_failed": 0,
            "files_deduplicated": 0,
            "indicators_found": 0
        }
    
    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await self.site.start()
        logger.info(f"Health check server rodando na porta {self.port}")
    
    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
            logger.info("Health check server parado")
    
    async def _health_handler(self, request: web.Request) -> web.Response:
        uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return web.json_response({
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    async def _metrics_handler(self, request: web.Request) -> web.Response:
        uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        metrics = "\n".join([
            "# HELP telegram_ingestor_uptime_seconds Uptime do serviço",
            "# TYPE telegram_ingestor_uptime_seconds gauge",
            f"telegram_ingestor_uptime_seconds {uptime}",
            "",
            "# HELP telegram_ingestor_jobs_processed_total Jobs processados",
            "# TYPE telegram_ingestor_jobs_processed_total counter",
            f'telegram_ingestor_jobs_processed_total {self._stats["jobs_processed"]}',
            "",
            "# HELP telegram_ingestor_jobs_failed_total Jobs falhados",
            "# TYPE telegram_ingestor_jobs_failed_total counter",
            f'telegram_ingestor_jobs_failed_total {self._stats["jobs_failed"]}',
            "",
            "# HELP telegram_ingestor_files_deduplicated_total Arquivos deduplicados",
            "# TYPE telegram_ingestor_files_deduplicated_total counter",
            f'telegram_ingestor_files_deduplicated_total {self._stats["files_deduplicated"]}',
            "",
            "# HELP telegram_ingestor_indicators_found_total Indicadores extraídos",
            "# TYPE telegram_ingestor_indicators_found_total counter",
            f'telegram_ingestor_indicators_found_total {self._stats["indicators_found"]}',
        ])
        return web.Response(text=metrics, content_type="text/plain")
    
    # Métodos para atualizar métricas (chamados pelo ingestion_service)
    def increment_jobs_processed(self) -> None:
        self._stats["jobs_processed"] += 1
    
    def increment_jobs_failed(self) -> None:
        self._stats["jobs_failed"] += 1
    
    def increment_files_deduplicated(self) -> None:
        self._stats["files_deduplicated"] += 1
    
    def increment_indicators_found(self, count: int = 1) -> None:
        self._stats["indicators_found"] += count