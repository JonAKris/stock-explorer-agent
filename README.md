# 🤖 Autonomous Stock Explorer Agent

An AI-powered agent that autonomously explores a PostgreSQL financial database to discover multi-signal stock investment opportunities. Runs on local hardware with local LLMs via Ollama — no API costs, fully private.

## Overview

The Stock Explorer Agent connects to a financial data warehouse (PostgreSQL), executes multiple quantitative investment strategies, cross-references results to find stocks with converging signals, and generates AI-synthesized investment reports — all while you sleep.

**Key Features:**
- 🔍 **10 investment strategies** across value, growth, momentum, sentiment, insider activity, and institutional flows
- 🧠 **Local LLM analysis** via Ollama (Mistral 7B + Mixtral 8x7B) — no API costs
- 🔗 **Multi-signal cross-referencing** — finds stocks appearing across multiple strategies
- 📊 **AI-generated investment reports** with conviction picks, sector themes, and risk factors
- ⏰ **Scheduled autonomous runs** at 2 AM and 2 PM daily via systemd
- 🏠 **100% local** — runs on a Minisforum MS-A1 with 96GB RAM

## Architecture
│ `Stock Explorer Agent`                                    │
|------------|--------------|-----------|-----------------|
│ `database.py`│ `strategies.py`│ `llm.py` │ `agent.py`        │
│ (Postgres  │ (10 strats)  │ (Ollama)  │ (Orchestrator)  │
│ connector) │              │           │                 │
│ PostgreSQL│ │ Strategy │ │ Ollama   │ │ findings/    │
│ (eodhd)   │ │ Results  │ │ Models   │ │ reports/     │

text

## Database Schema

The agent expects a financial data warehouse with these key tables:

| Table | Description | Rows (example) |
|-------|-------------|----------------|
| `fundamentals` | Company fundamentals, ratios, metadata | 38 |
| `eod_prices` | Daily OHLCV price data | 5.5M |
| `income_statements` | Quarterly/yearly income statements | 5,496 |
| `balance_sheets` | Quarterly/yearly balance sheets | 5,518 |
| `cash_flow_statements` | Quarterly/yearly cash flows | 5,080 |
| `earnings_history` | Historical earnings surprises | 3,499 |
| `sentiment_daily` | Daily news sentiment scores | — |
| `insider_transactions` | Insider/congressional trades | 515 |
| `institutional_holders` | Institutional ownership | — |
| `fund_holders` | Mutual fund holdings | — |
| `dividends` | Dividend history | 3,326 |
| `symbols` | Ticker master list | 77,793 |

## Investment Strategies

The agent runs 10 strategies, each with 3 parameter variations (30 total analyses per run):

| Strategy | Factor | What It Finds |
|----------|--------|---------------|
| `value_quality_composite` | Value/Quality | Low P/E, high ROE, strong FCF, good margins |
| `congressional_trading` | Insider | Congressional buy/sell patterns |
| `congressional_selling_alert` | Risk | Heavy congressional selling |
| `sentiment_divergence` | Sentiment | Improving sentiment with lagging price |
| `earnings_beaters` | Growth | Consistent earnings surprises |
| `earnings_miss_opportunity` | Contrarian | Recent misses — potential oversold |
| `fund_holder_conviction` | Institutional | High mutual fund ownership concentration |
| `price_momentum_leaders` | Momentum | Strong 1/3/6 month price trends |
| `dividend_income` | Income | High and sustainable dividend yields |
| `institutional_accumulation` | Smart Money | Heavy institutional ownership |

## Requirements

### Hardware
- **Tested on:** Minisforum MS-A1 with 96GB RAM
- **Minimum:** 32GB RAM (for Mixtral 8x7B model)
- **Storage:** ~50GB for models + database

### Software
- Python 3.11+
- PostgreSQL 16+
- Ollama
- Linux (systemd for scheduling)

### Python Packages
psycopg2-binary>=2.9.9
pandas>=2.2.2
numpy>=1.26.4
ollama>=0.1.9
pydantic>=2.7.4
python-dotenv>=1.0.1
loguru>=0.7.2
schedule>=1.2.1
pyyaml>=6.0.1
rich>=13.7.1

## Installation

### 1. Clone and Set Up

```bash
git clone https://github.com/JonAKris/stock-explorer-agent.git
cd stock-explorer-agent

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
### 2. Configure Database Access
bash
cp config/.env.example config/.env
nano config/.env
Edit with your database credentials:

bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=readonly_user
DB_PASSWORD=your_password
### 3. Create Read-Only Database User
sql
CREATE USER readonly_agent WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE eodhd TO readonly_agent;
GRANT USAGE ON SCHEMA public TO readonly_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_agent;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_agent;
### 4. Install and Start Ollama
bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &

# Pull required models
ollama pull mistral:7b-instruct-v0.2-q8_0    # ~7.7 GB
ollama pull mixtral:8x7b-instruct-v0.1-q5_K_M  # ~33 GB
### 5. Test the Agent
bash
python src/agent.py
### 6. Schedule Automatic Runs
bash
sudo cp systemd/stock-explorer.service /etc/systemd/system/
sudo cp systemd/stock-explorer.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable stock-explorer.timer
sudo systemctl start stock-explorer.timer

Usage
Manual Run
bash
source venv/bin/activate
python src/agent.py

View Latest Report
bash
python src/morningreport.py

Check Timer Status
bash
systemctl list-timers stock-explorer.timer

Add Shell Aliases (Optional)
bash
echo 'alias stocks-report="python ~/stock-explorer-agent/src/morningreport.py"' >> ~/.bashrc
echo 'alias stocks-run="cd ~/stock-explorer-agent && source venv/bin/activate && python src/agent.py"' >> ~/.bashrc
source ~/.bashrc

Output
Findings Directory Structure
text
findings/
├── results_20260601_055950.json    # Raw strategy results
├── report_20260601_055950.md       # AI-generated investment report
└── latest_results.json             # Symlink to most recent results
Sample Report Output

Project Structure
text
stock-explorer-agent/
├── config/
│   ├── .env                    # Database credentials (git-ignored)
│   └── settings.yaml           # Agent configuration
├── src/
│   ├── agent.py                # Main orchestrator
│   ├── database.py             # PostgreSQL connector
│   ├── llm.py                  # Ollama LLM interface
│   ├── morningreport.py        # Generate HTML report for emailing
│   └── strategies.py           # 10 investment strategies
├── systemd/
│   ├── stock-explorer.service  # Systemd service definition
│   └── stock-explorer.timer    # 2 AM / 2 PM schedule
├── findings/                   # Output directory
├── logs/                       # Agent logs
├── requirements.txt
└── README.md

How It Works
Schema Discovery — Agent queries information_schema to understand table structure

Strategy Execution — Runs 10 strategies × 3 parameter variations = 30 SQL analyses

LLM Interpretation — Each result set is analyzed by Mistral 7B for key insights

Cross-Referencing — Tickers appearing in multiple strategies get higher conviction scores

Synthesis — Mixtral 8x7B generates a comprehensive investment report

Scheduling — systemd timer triggers runs at 2 AM and 2 PM daily

Safety
Read-only database access — Agent connects with default_transaction_read_only=on

SQL injection prevention — Only SELECT and WITH queries allowed

No external API calls — All processing is local

No trade execution — Analysis only; no order placement capability

Customization
Adding New Strategies
Add entries to src/strategies.py:

python
"my_new_strategy": {
    "query": """
        SELECT ticker, ... FROM ... WHERE ...
        LIMIT {limit}
    """,
    "params": {"limit": [25, 50]}
}

Changing Models
Edit config/.env:

bash
EXPLORATION_MODEL=llama3:8b-instruct-q8_0
ANALYSIS_MODEL=qwen3.6:27b

Adjusting Schedule
Edit /etc/systemd/system/stock-explorer.timer:

ini
OnCalendar=*-*-* 02:00:00
OnCalendar=*-*-* 14:00:00
Performance
Metric	Value
Database size	6.3M rows across 39 tables
Strategies per run	30 (10 × 3 variations)
Typical runtime	20-35 minutes
RAM usage	~40GB (Mixtral model)
Multi-signal stocks found	35+ per run

Disclaimer
This tool is for research and educational purposes only. It does not constitute financial advice. Past performance does not guarantee future results. Always conduct your own due diligence before making investment decisions.

License
MIT License — see LICENSE file for details.
