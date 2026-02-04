# Telegram Media Ingestor

Sistema 24/7 de ingestão automatizada de mídias do Telegram para Threat Intelligence, com deduplicação criptográfica e extração de IOCs.

## 🔒 Aviso de Segurança
Este sistema processa dados potencialmente sensíveis. Nunca versione:
- Arquivos de sessão do Telegram (`.session`)
- Credenciais de API (`TELEGRAM_API_HASH`)
- Variáveis de ambiente com senhas

## 📦 Arquitetura
```
ingestor/
├── src/ # Código-fonte (Clean Architecture)
│ ├── domain/ # Modelos imutáveis
│ ├── application/ # Lógica de negócio
│ └── infrastructure/ # Adaptadores (Telegram, PostgreSQL, Storage)
├── data/ # Dados persistentes (excluído do git)
│ └── storage/ # Arquivos processados (estrutura hash-based)
└── .env.example # Template de configuração
```
## ⚙️ Setup Rápido
```bash
git clone https://github.com/elpardal/ingestor
cd ingestor
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Editar .env com credenciais reais

python -m src.main