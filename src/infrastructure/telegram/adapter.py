import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator, List, Optional
from telethon import TelegramClient, events
from telethon.tl.types import Document, Message
from telethon.errors import FloodWaitError
from src.domain.models import TelegramFile
from src.config.settings import Settings

logger = logging.getLogger(__name__)

class TelegramAdapter:
    """
    Adaptador assíncrono para Telegram com backpressure e retries automáticos.
    Isolado da lógica de negócio — apenas produz eventos de arquivos.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Optional[TelegramClient] = None
        self._connected = False
    
    async def connect(self) -> None:
        """Conecta ao Telegram com sessão persistente."""
        if self._connected:
            return
        
        self.client = TelegramClient(
            str(self.settings.storage_path / "sessions" / "ingestor.session"),
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
            flood_sleep_threshold=120,  # Dorme automaticamente em flood waits
            request_retries=3,
            connection_retries=5
        )
        
        # Garante diretório de sessão
        (self.settings.storage_path / "sessions").mkdir(parents=True, exist_ok=True)
        
        await self.client.start(phone=self.settings.telegram_phone)
        self._connected = True
        logger.info("Conectado ao Telegram com sucesso")
    
    async def disconnect(self) -> None:
        """Desconecta graceful do Telegram."""
        if self.client and self._connected:
            await self.client.disconnect()
            self._connected = False
            logger.info("Desconectado do Telegram")
    
    async def resolve_channels(self, channel_names: list[str]) -> list[int]:
        """Resolve nomes de canais para IDs numéricos."""
        if not self.client:
            raise RuntimeError("Cliente Telegram não inicializado")
        
        channel_ids = []
        for channel_name in channel_names:
            try:
                entity = await self.client.get_entity(channel_name)
                channel_ids.append(entity.id)
                logger.info(f"Canal resolvido: {entity.title} (ID: {entity.id})")
            except Exception as e:
                logger.error(f"Não foi possível resolver canal '{channel_name}': {e}")
                raise
        
        return channel_ids
    
    async def listen(
        self,
        output_queue: asyncio.Queue,
        channel_ids: List[int]
    ) -> None:
        """
        Inicia listener assíncrono que enfileira arquivos compactados.
        Nunca executa download — apenas produz jobs para workers.
        """
        if not self.client:
            raise RuntimeError("Cliente Telegram não inicializado")
        
        @self.client.on(events.NewMessage(chats=channel_ids))
        async def handler(event: events.NewMessage.Event):
            if not event.message.document:
                return
            
            doc: Document = event.message.document
            
            # Filtro: apenas arquivos compactados
            if not self._is_supported_archive(doc):
                return
            
            try:
                file = await self._extract_file_metadata(event.message, doc)
                
                # Backpressure: aguarda se fila está cheia
                try:
                    await asyncio.wait_for(
                        output_queue.put(file),
                        timeout=30.0
                    )
                    logger.debug(
                        f"Job enfileirado: {file.filename} "
                        f"({file.size_bytes / 1024 / 1024:.2f} MB) "
                        f"do canal {file.channel_title}"
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Fila cheia — descartando arquivo {file.filename} "
                        f"(canal: {file.channel_title}). Aumente WORKER_COUNT ou reduza volume."
                    )
            
            except Exception as e:
                logger.exception(f"Erro ao processar mensagem {event.message.id}: {e}")
        
        logger.info(f"Monitorando {len(channel_ids)} canais...")
        await self.client.run_until_disconnected()
    
    def _is_supported_archive(self, doc: Document) -> bool:
        """Valida se documento é .zip ou .rar dentro dos limites de tamanho."""
        # Verifica tamanho
        if doc.size > self.settings.max_file_size_mb * 1024 * 1024:
            logger.debug(f"Arquivo ignorado por tamanho excessivo: {doc.size} bytes")
            return False
        
        # Extrai nome do arquivo
        filename = ""
        if hasattr(doc, 'attributes'):
            for attr in doc.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    filename = attr.file_name.lower()
                    break
        
        if not filename:
            return False
        
        # Verifica extensão
        return filename.endswith((".zip", ".rar"))
    
    async def _extract_file_metadata(self, msg: Message, doc: Document) -> TelegramFile:
        """Extrai metadados completos da mensagem."""
        chat = await msg.get_chat()
        
        # Extrai nome do arquivo
        filename = "sem_nome"
        if hasattr(doc, 'attributes'):
            for attr in doc.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    filename = attr.file_name
                    break
        
        return TelegramFile(
            telegram_file_id=f"{chat.id}_{msg.id}_{doc.id}",
            channel_id=chat.id,
            channel_title=chat.title or str(chat.id),
            filename=filename,
            size_bytes=doc.size,
            timestamp=msg.date
        )
    
    async def download_file(self, message: Message, dest_path: Path) -> None:
        """
        Executa download com retries exponenciais para lidar com instabilidades.
        """
        if not self.client:
            raise RuntimeError("Cliente Telegram não inicializado")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.client.download_media(message, file=str(dest_path))
                actual_size = dest_path.stat().st_size
                expected_size = message.document.size
                
                # Validação de integridade
                if actual_size != expected_size:
                    dest_path.unlink(missing_ok=True)
                    raise IOError(
                        f"Tamanho incorreto: esperado {expected_size}, obtido {actual_size}"
                    )
                
                logger.info(
                    f"Download concluído: {dest_path.name} "
                    f"({actual_size / 1024 / 1024:.2f} MB)"
                )
                return
            
            except FloodWaitError as e:
                sleep_sec = min(e.seconds, 300)  # Máximo 5 minutos
                logger.warning(f"FloodWait: dormindo {sleep_sec}s (tentativa {attempt + 1})")
                await asyncio.sleep(sleep_sec)
            
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"Erro de conexão no download (tentativa {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Backoff exponencial
                else:
                    raise
            
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        
        raise RuntimeError(f"Download falhou após {max_retries} tentativas")