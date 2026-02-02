import hashlib
import os
from pathlib import Path
from typing import BinaryIO

def compute_blake2b_streaming(
    file_obj: BinaryIO,
    chunk_size: int = 65536  # 64KB
) -> str:
    """
    Calcula BLAKE2b de forma segura via streaming.
    Evita carregar arquivos grandes na memória.
    """
    hasher = hashlib.blake2b(digest_size=32)  # 256 bits
    
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        hasher.update(chunk)
    
    return hasher.hexdigest()


def compute_blake2b_from_path(path: Path) -> str:
    """
    Wrapper conveniente para cálculo a partir de Path.
    """
    with open(path, "rb") as f:
        return compute_blake2b_streaming(f)


def validate_safe_path(base_path: Path, user_path: str) -> Path:
    """
    Proteção rigorosa contra path traversal.
    Lança ValueError se tentar escapar do diretório base.
    """
    resolved = (base_path / user_path).resolve()
    if not str(resolved).startswith(str(base_path.resolve())):
        raise ValueError(f"Path traversal detectado: {user_path}")
    return resolved