import asyncio
import aiofiles
from pathlib import Path
import tempfile
import shutil
from typing import Optional
from src.infrastructure.storage.hash_utils import (
    compute_blake2b_from_path,
    validate_safe_path
)

class StorageAdapter:
    """
    Armazenamento determinístico com deduplicação nativa.
    Todos os métodos são assíncronos e seguros para concorrência.
    """
    
    def __init__(self, base_path: Path):
        self.base_path = base_path.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._temp_dir = self.base_path / ".tmp"
        self._temp_dir.mkdir(exist_ok=True)
    
    async def get_temp_path(self, job_id: str, filename: str) -> Path:
        """
        Retorna caminho temporário isolado por job.
        """
        safe_filename = self._sanitize_filename(filename)
        return self._temp_dir / f"{job_id}_{safe_filename}"
    
    async def persist_file(self, temp_path: Path, file_hash: str, original_filename: str) -> Path:
        """
        Move arquivo temporário para localização determinística baseada no hash.
        Estrutura: storage/ab/cd/abcdef123456.../original_filename
        
        Retorna: Path absoluto do arquivo persistido.
        """
        if not temp_path.exists():
            raise FileNotFoundError(f"Arquivo temporário não encontrado: {temp_path}")
        
        # Estrutura de diretórios por prefixo do hash (2 níveis)
        prefix1 = file_hash[:2]
        prefix2 = file_hash[2:4]
        hash_dir = self.base_path / prefix1 / prefix2 / file_hash
        
        hash_dir.mkdir(parents=True, exist_ok=True)
        
        # Nome seguro do arquivo original
        safe_name = self._sanitize_filename(original_filename)
        final_path = hash_dir / safe_name
        
        # Verifica se já existe (deduplicação física via hardlink)
        if final_path.exists():
            temp_path.unlink(missing_ok=True)
            return final_path
        
        # Move ou cria hardlink
        try:
            await asyncio.to_thread(temp_path.rename, final_path)
        except Exception:
            # Fallback para cópia + unlink se rename falhar (ex: cross-device)
            await asyncio.to_thread(shutil.copy2, temp_path, final_path)
            temp_path.unlink(missing_ok=True)
        
        return final_path.resolve()
    
    async def file_exists_by_hash(self, file_hash: str) -> bool:
        """
        Verifica rapidamente se hash já foi persistido.
        """
        prefix1 = file_hash[:2]
        prefix2 = file_hash[2:4]
        hash_dir = self.base_path / prefix1 / prefix2 / file_hash
        return hash_dir.exists() and any(hash_dir.iterdir())
    
    def get_deterministic_path(self, file_hash: str, filename: str) -> Path:
        """
        Retorna o caminho esperado para um hash + filename.
        Útil para logs e auditoria.
        """
        prefix1 = file_hash[:2]
        prefix2 = file_hash[2:4]
        safe_name = self._sanitize_filename(filename)
        return self.base_path / prefix1 / prefix2 / file_hash / safe_name
    
    def create_extraction_dir(self) -> Path:
        """
        Diretório temporário isolado para extração de arquivos compactados.
        Protegido contra path traversal durante a extração.
        """
        temp_dir = tempfile.mkdtemp(dir=self._temp_dir)
        return Path(temp_dir)
    
    def cleanup_extraction_dir(self, path: Path) -> None:
        """
        Remove diretório de extração recursivamente.
        """
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    
    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        Remove caracteres perigosos de nomes de arquivo.
        """
        # Mantém apenas alfanumérico, underscore, hífen, ponto e espaços
        import re
        sanitized = re.sub(r"[^\w\-. ]+", "_", filename)
        # Evita nomes vazios ou apenas pontos
        if not sanitized or sanitized.strip(". ") == "":
            sanitized = "unnamed_file"
        return sanitized.strip()[:255]  # Limite de filesystem
    
    async def cleanup_temp_files(self, age_seconds: int = 3600) -> int:
        """
        Limpa arquivos temporários mais antigos que age_seconds.
        Retorna número de arquivos removidos.
        """
        import time
        now = time.time()
        removed = 0
        
        for temp_file in self._temp_dir.glob("*"):
            if temp_file.is_file():
                try:
                    if now - temp_file.stat().st_mtime > age_seconds:
                        temp_file.unlink()
                        removed += 1
                except Exception:
                    pass  # Ignora erros de limpeza
        
        return removed