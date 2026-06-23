# 🤖 Autonomous Stock Explorer Agent

An AI-powered agent that autonomously explores a PostgreSQL financial database to discover multi-signal stock investment opportunities. Runs on local hardware with local LLMs via Ollama — no API costs, fully private.

## Overview

The Stock Explorer Agent connects to a financial data warehouse (PostgreSQL), executes multiple quantitative investment strategies, cross-references results to find stocks with converging signals, and generates AI-synthesized investment reports — all while you sleep.

**Key Features:**
- 🔍 **9 investment strategies** across value, growth, momentum, sentiment, insider activity, and institutional flows
- 🧠 **Local LLM analysis** via Ollama (Mistral 7B + llama3.2:latest) — no API costs
- 🔗 **Multi-signal cross-referencing** — finds stocks appearing across multiple strategies
- 📊 **AI-generated investment reports** with conviction picks, sector themes, and risk factors
- ⏰ **Scheduled autonomous runs** at 2 AM and 2 PM daily via systemd
- 🏠 **100% local** — runs on a Minisforum MS-A1 with 96GB RAM

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Stock Explorer Agent                      │
├───────────────┬────────────────┬───────────┬─────────────────┤
│  database.py  │  strategies.py │   llm.py  │    agent.py     │
│  (Postgres    │  (9 strategies)│  (Ollama  │  (orchestrator) │
│   connector)  │                │ interface)│                 │
└───────┬───────┴────────┬───────┴─────┬─────┴────────┬────────┘
        │                │             │              │
        ▼                ▼             ▼              ▼
  ┌───────────┐   ┌─────────────┐ ┌──────────┐ ┌─────────────┐
  │ PostgreSQL│   │  Strategy   │ │  Ollama  │ │  findings/  │
  │  (eodhd)  │   │   results   │ │  models  │ │  (md+json)  │
  └───────────┘   └─────────────┘ └──────────┘ └─────────────┘
```

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

The agent runs 9 strategies, each with 3 parameter variations (27 total analyses per run):

| Strategy | Factor | What It Finds |
|----------|--------|---------------|
| `value_quality_composite` | Value/Quality | Low P/E, high ROE, strong FCF, good margins |
| `congressional_trading` | Insider | Insider/congressional buy/sell patterns |
| `congressional_selling_alert` | Risk | Heavy insider/congressional selling |
| `sentiment_divergence` | Sentiment | Improving sentiment with lagging price |
| `earnings_beaters` | Growth | Consistent earnings surprises |
| `earnings_miss_opportunity` | Contrarian | Recent misses — potential oversold |
| `fund_holder_conviction` | Institutional | High mutual fund ownership concentration |
| `price_momentum_leaders` | Momentum | Strong 1/3/6 month price trends |
| `dividend_income` | Income | High and sustainable dividend yields |

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

Pinned in `requirements.txt`:

```
psycopg2-binary==2.9.9
numpy==1.26.4
ollama==0.1.9
pydantic==2.7.4
python-dotenv==1.0.1
schedule==1.2.1
pyyaml==6.0.1
loguru==0.7.3
pandas==3.0.3
pypandoc==1.17
rich==15.0.0
```

> Note: `pandas==3.0.3` requires `numpy>=1.26.0` on Python <3.14; the pinned numpy satisfies this. `pypandoc` is used by `morning_report.py` for Markdown→HTML conversion (install `pypandoc-binary` if you don't have a system `pandoc`).

## Installation

### 1. Clone and Set Up

```bash
git clone https://github.com/JonAKris/stock-explorer-agent.git
cd stock-explorer-agent

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Database Access

```bash
cp config/.env.example config/.env
nano config/.env
```

Edit with your database credentials:

```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=readonly_user
DB_PASSWORD=your_password
```

### 3. Create Read-Only Database User

```sql
CREATE USER readonly_agent WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE eodhd TO readonly_agent;
GRANT USAGE ON SCHEMA public TO readonly_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_agent;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_agent;
```

### 4. Install and Start Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &

# Pull required models
ollama pull mistral:7b-instruct-v0.2-q8_0      # ~7.7 GB
ollama pull llama3.2:latest                    # ~2 GB
```

### 5. Test the Agent

```bash
python src/agent.py
```

### 6. Schedule Automatic Runs

```bash
sudo cp systemd/stock-explorer.service /etc/systemd/system/
sudo cp systemd/stock-explorer.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-explorer.timer
```

> The unit files assume the repo lives at `/home/jon/stock-explorer-agent` and the venv at `./venv`. Adjust `WorkingDirectory` and `ExecStart` in `stock-explorer.service` if your paths differ.

## Usage

### Manual Run

```bash
source venv/bin/activate
python src/agent.py
```

### Email the Latest Report

`morning_report.py` finds the newest `findings/report_*.md` + `results_*.json`, converts to HTML, and emails it. SMTP settings are read from a `.env` file (see `.env.example` at the repo root for `SMTP_HOST`, `MAIL_TO`, etc.).

```bash
python src/morning_report.py              # build and email
python src/morning_report.py --no-email   # build and print to stdout only
python src/morning_report.py --out report.html
```

### Check Timer Status

```bash
systemctl list-timers stock-explorer.timer
```

### Add Shell Aliases (Optional)

```bash
echo 'alias stocks-report="python ~/stock-explorer-agent/src/morning_report.py"' >> ~/.bashrc
echo 'alias stocks-run="cd ~/stock-explorer-agent && source venv/bin/activate && python src/agent.py"' >> ~/.bashrc
source ~/.bashrc
```

## Output

### Findings Directory Structure

```
findings/
├── results_20260601_055950.json    # Raw strategy results
├── report_20260601_055950.md       # AI-generated investment report
└── latest_results.json             # Symlink to most recent results
```

### Sample Report Output

See `report.html` in the repo root for an example of the rendered morning report.

## Project Structure

```
stock-explorer-agent/
├── config/
│   ├── .env.example            # DB + Ollama settings template
│   └── settings.yaml           # Reference configuration (not yet wired in)
├── src/
│   ├── agent.py                # Main orchestrator
│   ├── database.py             # PostgreSQL connector
│   ├── llm.py                  # Ollama LLM interface
│   ├── morning_report.py       # Build + email the HTML report
│   └── strategies.py           # 9 investment strategies
├── systemd/
│   ├── stock-explorer.service  # Systemd service definition
│   └── stock-explorer.timer    # 2 AM / 2 PM schedule
├── findings/                   # Output directory
├── logs/                       # Agent logs
├── .env.example                # SMTP settings template (for morning_report.py)
├── requirements.txt
└── README.md
```

## How It Works

1. **Schema Discovery** — Agent queries `information_schema` to understand table structure
2. **Strategy Execution** — Runs 9 strategies × 3 parameter variations = 27 SQL analyses
3. **LLM Interpretation** — Each result set is analyzed by Mistral 7B for key insights
4. **Cross-Referencing** — Tickers appearing in multiple strategies get higher conviction scores
5. **Synthesis** — Mixtral 8x7B generates a comprehensive investment report
6. **Scheduling** — systemd timer triggers runs at 2 AM and 2 PM daily

## Safety

- **Read-only database access** — Agent connects with `default_transaction_read_only=on`
- **Query allow-list** — Only `SELECT` and `WITH` queries are permitted
- **No external API calls** — All processing is local
- **No trade execution** — Analysis only; no order placement capability

## Customization

### Adding New Strategies

Add entries to `src/strategies.py`:

```python
"my_new_strategy": {
    "query": """
        SELECT ticker, ... FROM ... WHERE ...
        LIMIT {limit}
    """,
    "params": {"limit": [25, 50]}
}
```

### Changing Models

Edit `config/.env`:

```bash
EXPLORATION_MODEL=llama3.1:8b-instruct-q8_0
ANALYSIS_MODEL=qwen2.5:32b-instruct
```

### Adjusting Schedule

Edit `/etc/systemd/system/stock-explorer.timer`:

```ini
OnCalendar=*-*-* 02:00:00
OnCalendar=*-*-* 14:00:00
```

## Performance

| Metric | Value |
|--------|-------|
| Database size | 6.3M rows across 39 tables |
| Strategies per run | 27 (9 × 3 variations) |
| Typical runtime | 20–35 minutes |
| RAM usage | ~40GB (Mixtral model) |
| Multi-signal stocks found | 35+ per run |

## Disclaimer

This tool is for research and educational purposes only. It does not constitute financial advice. Past performance does not guarantee future results. Always conduct your own due diligence before making investment decisions.

## License

MIT License — see LICENSE file for details.