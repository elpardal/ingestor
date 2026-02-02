import asyncio
import pytest
from pathlib import Path
import tempfile
from src.infrastructure.storage.adapter import StorageAdapter
from src.infrastructure.storage.hash_utils import compute_blake2b_from_path

@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_blake2b_deterministic(temp_storage):
    file1 = temp_storage / "a.txt"
    file2 = temp_storage / "b.txt"
    content = b"conteudo de teste para hash"
    
    file1.write_bytes(content)
    file2.write_bytes(content)
    
    hash1 = compute_blake2b_from_path(file1)
    hash2 = compute_blake2b_from_path(file2)
    
    assert hash1 == hash2
    assert len(hash1) == 64  # 32 bytes em hex

def test_storage_persist_deterministic(temp_storage):
    adapter = StorageAdapter(temp_storage / "storage")
    
    # Primeiro arquivo
    temp_file1 = temp_storage / "temp1.rar"
    temp_file1.write_bytes(b"conteudo dummy")
    hash1 = compute_blake2b_from_path(temp_file1)
    final_path1 = asyncio.run(adapter.persist_file(temp_file1, hash1, "teste.rar"))
    
    # Verifica estrutura hierárquica
    assert final_path1.parent.name == hash1
    assert final_path1.parent.parent.name == hash1[2:4]
    assert final_path1.parent.parent.parent.name == hash1[:2]
    assert final_path1.name == "teste.rar"
    assert final_path1.read_bytes() == b"conteudo dummy"
    
    # Segundo arquivo com mesmo conteúdo mas nome diferente
    temp_file2 = temp_storage / "temp2.rar"
    temp_file2.write_bytes(b"conteudo dummy")  # mesmo conteúdo
    hash2 = compute_blake2b_from_path(temp_file2)
    assert hash1 == hash2  # confirma mesmo hash
    
    final_path2 = asyncio.run(adapter.persist_file(temp_file2, hash2, "teste2.rar"))
    
    # Ambos devem estar no MESMO diretório hash, mas com nomes diferentes
    assert final_path2.parent == final_path1.parent  # mesmo diretório hash
    assert final_path2.name == "teste2.rar"
    assert final_path2 != final_path1  # paths diferentes (nomes diferentes)
    
    # Verifica que ambos existem e têm mesmo conteúdo
    assert final_path1.exists()
    assert final_path2.exists()
    assert final_path1.read_bytes() == final_path2.read_bytes()

def test_path_traversal_protection(temp_storage):
    base = temp_storage / "storage"
    base.mkdir()
    
    from src.infrastructure.storage.hash_utils import validate_safe_path
    
    # Casos válidos
    assert validate_safe_path(base, "arquivo.txt").name == "arquivo.txt"
    assert validate_safe_path(base, "pasta/arquivo.txt").parent.name == "pasta"
    
    # Casos maliciosos
    with pytest.raises(ValueError):
        validate_safe_path(base, "../etc/passwd")
    
    with pytest.raises(ValueError):
        validate_safe_path(base, "/etc/passwd")
    
    with pytest.raises(ValueError):
        validate_safe_path(base, "pasta/../../etc/passwd")