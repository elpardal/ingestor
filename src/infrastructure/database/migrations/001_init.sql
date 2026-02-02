-- Tabela de arquivos processados (deduplicação por Telegram ID + hash)
CREATE TABLE IF NOT EXISTS processed_files (
    telegram_file_id TEXT PRIMARY KEY,          -- "{channel_id}_{message_id}_{document_id}"
    channel_id BIGINT NOT NULL,
    channel_title TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    file_hash TEXT NOT NULL,                    -- BLAKE2b 256-bit em hex
    storage_path TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_processed_files_hash ON processed_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_processed_files_channel ON processed_files(channel_id, first_seen_at);

-- Tabela de jobs (auditabilidade de processamento)
CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id UUID PRIMARY KEY,
    telegram_file_id TEXT NOT NULL REFERENCES processed_files(telegram_file_id),
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_file ON processing_jobs(telegram_file_id);

-- Tabela de indicadores extraídos (IOCs)
CREATE TABLE IF NOT EXISTS extracted_indicators (
    id BIGSERIAL PRIMARY KEY,
    indicator_type TEXT NOT NULL CHECK (indicator_type IN ('domain', 'email', 'ipv4')),
    value TEXT NOT NULL,
    source_file_hash TEXT NOT NULL,             -- Hash do arquivo .zip/.rar original
    source_relative_path TEXT NOT NULL,         -- Caminho dentro do arquivo compactado
    source_line INTEGER NOT NULL,
    channel_id BIGINT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (indicator_type, value, source_file_hash, source_line)
);

CREATE INDEX IF NOT EXISTS idx_indicators_value ON extracted_indicators(value);
CREATE INDEX IF NOT EXISTS idx_indicators_channel ON extracted_indicators(channel_id, first_seen_at);
CREATE INDEX IF NOT EXISTS idx_indicators_hash ON extracted_indicators(source_file_hash);