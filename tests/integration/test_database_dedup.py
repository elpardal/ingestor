import pytest
from pathlib import Path
import tempfile
from src.config.settings import Settings
from src.infrastructure.database.adapter import DatabaseAdapter
from src.application.deduplication_service import DeduplicationService
from src.domain.models import TelegramFile
from datetime import datetime, timezone

# Configure seu banco de teste no .env.test ou use fixture abaixo
TEST_DSN = "postgresql://ingestor:ingestor@localhost:5432/telegram_ingest_test"

@pytest.fixture(scope="session")
async def db_adapter():
    adapter = DatabaseAdapter(TEST_DSN)
    await adapter.connect()
    
    # Limpa tabelas antes dos testes
    async with adapter.transaction() as conn:
        await conn.execute("TRUNCATE TABLE extracted_indicators, processing_jobs, processed_files RESTART IDENTITY CASCADE")
    
    yield adapter
    await adapter.disconnect()

def test_telegram_file_model():
    file = TelegramFile(
        telegram_file_id="12345_67890_111",
        channel_id=12345,
        channel_title="CanalTeste",
        filename="teste.rar",
        size_bytes=1024,
        timestamp=datetime.now(timezone.utc)
    )
    assert file.telegram_file_id == "12345_67890_111"
    assert file.filename == "teste.rar"

@pytest.mark.asyncio
async def test_deduplication_by_telegram_id(db_adapter):
    service = DeduplicationService(db_adapter)
    
    file1 = TelegramFile(
        telegram_file_id="99999_11111_222",
        channel_id=99999,
        channel_title="Teste",
        filename="arquivo1.rar",
        size_bytes=500,
        timestamp=datetime.now(timezone.utc)
    )
    
    # Primeira vez: deve processar
    should = await service.should_process_by_telegram_id(file1)
    assert should == True
    
    # Registra no banco
    await db_adapter.record_processed_file(file1, "dummy_hash_1", "/tmp/storage/aa/bb/dummy1")
    
    # Segunda vez: não deve processar
    should = await service.should_process_by_telegram_id(file1)
    assert should == False

@pytest.mark.asyncio
async def test_deduplication_by_content(db_adapter):
    service = DeduplicationService(db_adapter)
    
    # Cria arquivo temporário
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "teste.bin"
        path.write_bytes(b"conteudo identico para teste de hash")
        
        # Primeira verificação
        should1, hash1 = await service.should_process_by_content(path)
        assert should1 == True
        assert len(hash1) == 64
        
        # Registra no banco
        dummy_file = TelegramFile(
            telegram_file_id="88888_22222_333",
            channel_id=88888,
            channel_title="OutroCanal",
            filename="dummy.rar",
            size_bytes=100,
            timestamp=datetime.now(timezone.utc)
        )
        await db_adapter.record_processed_file(dummy_file, hash1, "/tmp/storage/aa/bb/dummy2")
        
        # Segunda verificação com mesmo conteúdo
        should2, hash2 = await service.should_process_by_content(path)
        assert should2 == False
        assert hash1 == hash2