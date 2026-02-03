-- Remove foreign key problemática
ALTER TABLE processing_jobs 
DROP CONSTRAINT IF EXISTS processing_jobs_telegram_file_id_fkey;

-- Mantém índice para performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_telegram_file_id 
ON processing_jobs(telegram_file_id);

-- Adiciona coluna para rastrear hash mesmo em jobs falhos (útil para debug)
ALTER TABLE processing_jobs 
ADD COLUMN IF NOT EXISTS file_hash TEXT;

COMMENT ON TABLE processing_jobs IS 'Histórico de tentativas de processamento (incluindo falhas). Não requer FK para processed_files.';
COMMENT ON TABLE processed_files IS 'Apenas arquivos concluídos com sucesso. Deduplicação baseada em telegram_file_id + file_hash.';