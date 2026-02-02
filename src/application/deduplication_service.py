from src.domain.models import TelegramFile
from src.infrastructure.database.adapter import DatabaseAdapter
from src.infrastructure.storage.hash_utils import compute_blake2b_from_path
from pathlib import Path

class DeduplicationService:
    """
    Lógica de negócio pura de deduplicação.
    Não conhece detalhes de infraestrutura (PostgreSQL, filesystem).
    Recebe abstrações injetadas.
    """
    
    def __init__(self, db_adapter: DatabaseAdapter):
        self.db = db_adapter
    
    async def should_process_by_telegram_id(self, file: TelegramFile) -> bool:
        """
        Verifica se arquivo deve ser processado com base no ID único do Telegram.
        Retorna False se já processado (deduplicação pré-download).
        """
        exists = await self.db.exists_by_telegram_id(file.telegram_file_id)
        return not exists
    
    async def should_process_by_content(self, file_path: Path) -> tuple[bool, str]:
        """
        Calcula hash e verifica se conteúdo já existe.
        Retorna (deve_processar, hash_calculado).
        """
        file_hash = await compute_blake2b_from_path_async(file_path)
        exists = await self.db.exists_by_hash(file_hash)
        return (not exists), file_hash


async def compute_blake2b_from_path_async(path: Path) -> str:
    """
    Wrapper assíncrono para cálculo de hash (evita bloquear event loop).
    """
    import asyncio
    from src.infrastructure.storage.hash_utils import compute_blake2b_from_path
    return await asyncio.to_thread(compute_blake2b_from_path, path)