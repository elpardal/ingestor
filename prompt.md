Você é um **engenheiro de software sênior**, especialista em **Python assíncrono, sistemas de ingestão, concorrência, processamento de arquivos, deduplicação, segurança e threat intelligence**.

Seu objetivo é **projetar e implementar um serviço de ingestão de mídias do Telegram**, pensado para rodar **24/7 em produção**, com foco em:

* confiabilidade
* escalabilidade
* deduplicação
* análise de conteúdo
* auditabilidade

---

## Objetivo do Sistema

Criar um **Telegram Media Ingestor** capaz de:

* Escutar múltiplos canais do Telegram
* Baixar arquivos compactados (.rar) de forma controlada
* Evitar duplicações
* Armazenar arquivos de forma determinística
* Processar arquivos compactados
* Extrair indicadores relevantes de segurança
* Persistir todos os achados para consulta posterior

---

## Requisitos Funcionais

### 1. Listener de Telegram

* Utilizar **Telethon**
* Autenticação via sessão persistente
* Escutar **N canais simultaneamente**
* Canais configurados via `.env`
* Tipos suportados:

  * documentos

---

### 2. Arquitetura Baseada em Fila

* Listener **não executa download**
* Cada documento gera um **job**
* Jobs são inseridos em uma **fila assíncrona**
* A fila alimenta um **pool de workers**
* deve retormar os downloads em caso de indisponibilidade

---

### 3. Worker Pool e Paralelismo

* Implementar **workers reais**
* Número de workers configurável via `.env`
* Cada worker executa:

  1. Download
  2. Hash
  3. Persistência
  4. Pós-processamento
* Paralelismo controlado para evitar flood / ban

---

### 4. Deduplicação Obrigatória (Dupla)

#### Antes do download

* Deduplicar via **ID do arquivo do Telegram**
* Se já processado → descartar o job

#### Após o download

* Calcular **hash blake2b via streaming**
* Evitar duplicação no storage
* Opcional: hardlink

---

### 5. Persistência

* Banco de dados assíncrono, postgresql
* Tabelas para:

  * arquivos processados
  * hashes
  * jobs
  * indicadores extraídos
* Operações idempotentes

---

## 🔹 Pós-Processamento de Arquivos

### 6. Detecção e Descompactação

Após o download e persistência do arquivo:

* Detectar automaticamente arquivos compactados:

  * `.zip`
  * `.rar`

* Criar um **pipeline de descompactação**
* Extrair conteúdo para diretório isolado e temporário

---

### 7. Análise de Conteúdo (IOC Extraction)

Após a descompactação:

* Varredura recursiva do conteúdo de arquivos .txt
* Extração de padrões definidos via `.env`:

  * Domínios
  * Endereços de e-mail
  * IPv4
* Suporte a múltiplos padrões configuráveis

---

### 8. Persistência dos Achados

* Persistir indicadores em tabela dedicada:

  * tipo do indicador (domain, email, ipv4)
  * valor
  * arquivo de origem
  * linha do arquivo
  * canal
  * timestamp
* Evitar duplicação de indicadores
* Manter rastreabilidade completa:

  * indicador → arquivo → mensagem → canal

---

## Configuração

Tudo deve ser configurável via `.env`:

```env
TELEGRAM_PHONE=+5561983820229
TELEGRAM_CHANNELS=CanalT01,CanalT02
WORKER_COUNT=4
STORAGE_PATH=./data/storage

IOC_DOMAINS=gdfnet.df,df.gov.br
IOC_EMAILS=@gdfnet.gov.br,@df.gov.br
IOC_IPV4_CIDRS=200.200.200.0/22,201.100.10.0/24

```

---

## Estrutura Esperada do Projeto

- Aplicação com separação rigorosa de camadas segundo Clean Architecture:
  - Núcleo independente contendo apenas modelos de domínio e regras de negócio
  - Camada de serviços de aplicação orquestrando fluxos sem conhecer detalhes técnicos de infraestrutura
  - Adaptadores de infraestrutura injetados como dependências (não acoplados ao núcleo)

- Processamento orientado a eventos com pipeline assíncrono:
  - Componente receptor de eventos externos (ex.: mensagens Telegram)
  - Sistema de filas internas para buffer e ordenação de tarefas
  - Workers consumindo filas com isolamento de responsabilidades

- Funcionalidades específicas por domínio:
  - Extração de arquivos compactados com suporte a múltiplos formatos
  - Análise de conteúdo para extração de IOCs (Indicators of Compromise)
  - Geração de hashes criptográficos para identificação única de artefatos
  - Persistência auditável com histórico de processamento

- Princípios não funcionais obrigatórios:
  - Inversão de dependência: camada de domínio nunca importa infraestrutura
  - Testabilidade: todos os serviços aceitam mock de adaptadores
  - Substituibilidade: adaptadores externos (Telegram, DB) devem ser intercambiáveis sem alterar lógica de negócio

---

## Observabilidade

* Logs estruturados:

  * download_start / complete
  * extract_start / complete
  * extract_password_required
  * password_retry
  * indicators_found
* Métricas por tipo de arquivo e indicador

---

## Princípios de Qualidade

* Segurança por padrão (path traversal, zip bomb)
* Processamento isolado
* Idempotência total
* Clareza arquitetural
* Código pronto para produção


---

## Entregáveis Esperados

1. Arquitetura explicada
2. Código completo dos módulos principais
3. Exemplo de `.env`
