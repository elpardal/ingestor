import re
from urllib.parse import urlparse
from pathlib import Path
from typing import List
from ipaddress import ip_address
from src.domain.models import ExtractedIndicator, IndicatorType
from src.config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class IOCExtractionService:
    """
    Scanner seguro de indicadores com suporte a URLs estruturadas.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.domain_patterns = self._compile_domain_patterns()
        self.email_pattern = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
        self.ipv4_pattern = re.compile(r"\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b")
        self.url_pattern = re.compile(
            r"(https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s\"'<>\)]*)?)",
            re.IGNORECASE
        )
        self.cidr_networks = settings.get_cidr_networks()
    
    def _compile_domain_patterns(self) -> List[tuple]:
        patterns = []
        for domain in self.settings.get_domain_set():
            escaped = re.escape(domain)
            patterns.append((domain, re.compile(rf"\b([a-zA-Z0-9][a-zA-Z0-9.-]*{escaped})\b", re.IGNORECASE)))
        return patterns
    
    async def scan_directory(
        self,
        extract_path: Path,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        indicators = []
        txt_files = list(extract_path.rglob("*.txt"))
        
        logger.debug(f"Escaneando {len(txt_files)} arquivos .txt")
        
        for txt_file in txt_files:
            try:
                content = self._read_file_safe(txt_file)
                rel_path = txt_file.relative_to(extract_path).as_posix()
                file_indicators = self._scan_content(content, rel_path, source_file_hash, channel_id)
                indicators.extend(file_indicators)
                
                if file_indicators:
                    logger.debug(f"Encontrados {len(file_indicators)} indicadores em {rel_path}")
            except Exception as e:
                logger.warning(f"Não foi possível escanear {txt_file}: {e}")
        
        return indicators
    
    def _read_file_safe(self, path: Path) -> str:
        """Lê arquivo com fallback de encoding."""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="ignore")
    
    def _scan_content(
        self,
        content: str,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        indicators = []
        
        for line_num, line in enumerate(content.splitlines(), start=1):
            # 1. Extrai e processa URLs primeiro
            indicators.extend(
                self._extract_from_urls(line, line_num, relative_path, source_file_hash, channel_id)
            )
            
            # 2. Domínios soltos (texto não-URL)
            indicators.extend(
                self._extract_domains_from_text(line, line_num, relative_path, source_file_hash, channel_id)
            )
            
            # 3. Emails
            indicators.extend(
                self._extract_emails(line, line_num, relative_path, source_file_hash, channel_id)
            )
            
            # 4. IPv4
            indicators.extend(
                self._extract_ipv4(line, line_num, relative_path, source_file_hash, channel_id)
            )
        
        return indicators
    
    def _extract_from_urls(
        self,
        line: str,
        line_num: int,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        """Extrai hostnames de URLs completas E parciais (sem protocolo)."""
        indicators = []
        target_domains = self.settings.get_domain_set()
        
        if not target_domains:
            return indicators
        
        # Regex 1: URLs completas com protocolo (https://dominio/path)
        url_with_proto = re.compile(
            r"(https?://[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?:/[^\s\"'<>\)]*)?)",
            re.IGNORECASE
        )
        
        # Regex 2: URLs sem protocolo mas com path (dominio/path OU dominio:porta/path)
        url_without_proto = re.compile(
            r"\b([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?:[:/][^\s\"'<>\)]+))",
            re.IGNORECASE
        )
        
        # Processa URLs com protocolo
        for match in url_with_proto.finditer(line):
            url = match.group(1)
            hostname = self._extract_hostname(url)
            if hostname:
                for target in target_domains:
                    if target in hostname.lower():
                        indicators.append(ExtractedIndicator(
                            indicator_type=IndicatorType.DOMAIN,
                            value=hostname,
                            source_file_hash=source_file_hash,
                            source_relative_path=relative_path,
                            source_line=line_num,
                            channel_id=channel_id
                        ))
                        break
        
        # Processa URLs sem protocolo (ex: df.gov.br/api)
        for match in url_without_proto.finditer(line):
            candidate = match.group(1)
            # Valida se é realmente um hostname (não número IP puro, não começa com ponto)
            if candidate.startswith(".") or candidate.startswith("/"):
                continue
            
            # Extrai apenas a parte do hostname (remove :porta e /path)
            hostname = self._extract_hostname(f"http://{candidate}")
            if hostname:
                for target in target_domains:
                    if target in hostname.lower():
                        indicators.append(ExtractedIndicator(
                            indicator_type=IndicatorType.DOMAIN,
                            value=hostname,
                            source_file_hash=source_file_hash,
                            source_relative_path=relative_path,
                            source_line=line_num,
                            channel_id=channel_id
                        ))
                        break
        
        return indicators

    def _extract_hostname(self, url: str) -> str | None:
        """Extrai hostname limpo de URL (com ou sem protocolo)."""
        from urllib.parse import urlparse
        
        try:
            # Adiciona protocolo se ausente para urlparse funcionar
            if not url.startswith(("http://", "https://")):
                url = "http://" + url.lstrip("/")
            
            parsed = urlparse(url)
            hostname = parsed.hostname
            
            if not hostname:
                return None
            
            # Remove prefixos www*, mantém estrutura real para rastreabilidade
            return hostname.lower()
        except Exception:
            return None
    
    def _extract_domains_from_text(
        self,
        line: str,
        line_num: int,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        """Extrai domínios de texto não-URL (comportamento original)."""
        indicators = []
        for domain, pattern in self.domain_patterns:
            for match in pattern.finditer(line):
                value = match.group(1).lower().rstrip(".")
                if value and len(value) <= 255:
                    indicators.append(ExtractedIndicator(
                        indicator_type=IndicatorType.DOMAIN,
                        value=value,
                        source_file_hash=source_file_hash,
                        source_relative_path=relative_path,
                        source_line=line_num,
                        channel_id=channel_id
                    ))
        return indicators
    
    def _extract_emails(
        self,
        line: str,
        line_num: int,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        indicators = []
        target_domains = self.settings.get_email_domains_set()
        
        if not target_domains:
            return indicators
        
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
        return indicators
    
    def _extract_ipv4(
        self,
        line: str,
        line_num: int,
        relative_path: str,
        source_file_hash: str,
        channel_id: int
    ) -> List[ExtractedIndicator]:
        indicators = []
        if not self.cidr_networks:
            return indicators
        
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