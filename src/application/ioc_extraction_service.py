import re
from pathlib import Path
from typing import List
from ipaddress import ip_address
from src.domain.models import ExtractedIndicator, IndicatorType
from src.config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class IOCExtractionService:
    """
    Scanner seguro de indicadores em arquivos de texto extraídos.
    Configurável via .env para domínios, emails e CIDRs específicos.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.domain_patterns = self._compile_domain_patterns()
        self.email_pattern = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
        self.ipv4_pattern = re.compile(r"\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b")
        self.cidr_networks = settings.get_cidr_networks()
    
    def _compile_domain_patterns(self) -> List[tuple]:
        patterns = []
        for domain in self.settings.get_domain_set():
            escaped = re.escape(domain)
            # Aceita subdomínios ou domínio exato
            patterns.append((domain, re.compile(rf"\b([a-zA-Z0-9][a-zA-Z0-9.-]*{escaped})\b", re.IGNORECASE)))
        return patterns
    
    async def scan_directory(
        self,
        extract_path: Path,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        """
        Varre recursivamente diretório extraído buscando arquivos .txt.
        """
        indicators = []
        txt_files = list(extract_path.rglob("*.txt"))
        
        logger.debug(f"Escaneando {len(txt_files)} arquivos .txt em {extract_path.name}")
        
        for txt_file in txt_files:
            try:
                # Lê conteúdo com fallback de encoding
                try:
                    content = txt_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = txt_file.read_text(encoding="latin-1", errors="ignore")
                
                rel_path = txt_file.relative_to(extract_path).as_posix()
                file_indicators = self._scan_content(content, rel_path, source_file_hash, channel_id)
                indicators.extend(file_indicators)
                
                if file_indicators:
                    logger.debug(f"Encontrados {len(file_indicators)} indicadores em {rel_path}")
            
            except Exception as e:
                logger.warning(f"Não foi possível escanear {txt_file}: {e}")
        
        return indicators
    
    def _scan_content(
        self,
        content: str,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        indicators = []
        
        for line_num, line in enumerate(content.splitlines(), start=1):
            # Domínios
            for domain, pattern in self.domain_patterns:
                for match in pattern.finditer(line):
                    value = match.group(1).lower().rstrip(".")
                    if value and len(value) <= 255:  # limite de DB
                        indicators.append(ExtractedIndicator(
                            indicator_type=IndicatorType.DOMAIN,
                            value=value,
                            source_file_hash=source_file_hash,
                            source_relative_path=relative_path,
                            source_line=line_num,
                            channel_id=channel_id
                        ))
            
            # Emails com domínios alvo
            target_domains = self.settings.get_email_domains_set()
            if target_domains:
                for match in self.email_pattern.finditer(line):
                    email = match.group().lower()
                    if any(email.endswith(f"@{d}") for d in target_domains):
                        if len(email) <= 255:
                            indicators.append(ExtractedIndicator(
                                indicator_type=IndicatorType.EMAIL,
                                value=email,
                                source_file_hash=source_file_hash,
                                source_relative_path=relative_path,
                                source_line=line_num,
                                channel_id=channel_id
                            ))
            
            # IPv4 em CIDRs alvo
            if self.cidr_networks:
                for match in self.ipv4_pattern.finditer(line):
                    ip_str = match.group()
                    try:
                        ip = ip_address(ip_str)
                        if any(ip in net for net in self.cidr_networks):
                            indicators.append(ExtractedIndicator(
                                indicator_type=IndicatorType.IPV4,
                                value=str(ip),
                                source_file_hash=source_file_hash,
                                source_relative_path=relative_path,
                                source_line=line_num,
                                channel_id=channel_id
                            ))
                    except ValueError:
                        continue
        
        return indicators