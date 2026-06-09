"""LLM interface for result interpretation"""
import json
import os
import re
import pandas as pd
import ollama
from loguru import logger
from dotenv import load_dotenv

load_dotenv('config/.env')

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
os.environ['OLLAMA_HOST'] = OLLAMA_HOST


class LLMInterface:
    def __init__(self):
        self.exploration_model = os.getenv('EXPLORATION_MODEL', 'mistral:7b-instruct-v0.2-q8_0')
        self.analysis_model = os.getenv('ANALYSIS_MODEL', 'mixtral:8x7b-instruct-v0.1-q5_K_M')
        logger.info(f"LLM initialized: host={OLLAMA_HOST}, analysis={self.analysis_model}")

    def _clean_json(self, text: str) -> str:
        """Clean LLM output to extract valid JSON"""
        # Remove markdown code blocks
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]

        # Remove control characters except newlines and tabs
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

        # Fix common Mixtral JSON issues
        text = text.replace('\n', ' ').replace('\r', '')

        # Try to find JSON object boundaries
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            text = text[start:end]

        return text.strip()

    def interpret_results(self, context: str, df: pd.DataFrame) -> dict:
        """Have LLM analyze query results"""
        if df.empty:
            return {
                "interpretation": "No results found",
                "confidence": 0.0,
                "tickers_of_interest": [],
                "key_insight": "",
                "risk_factors": [],
                "recommended_action": "WATCH",
            }

        # Build concise summary
        tickers = df['ticker'].tolist()[:10] if 'ticker' in df.columns else []
        summary = f"Tickers: {', '.join(tickers)}\n"
        summary += f"Rows: {len(df)}, Columns: {list(df.columns)[:10]}\n"
        summary += f"Sample:\n{df.head(3).to_string()}\n"

        prompt = f"""Analyze these financial query results.

{context}

{summary[:1500]}

Respond ONLY with valid JSON, no markdown:
{{"interpretation":"brief analysis","confidence":0.8,"tickers_of_interest":["TICKER"],"key_insight":"main takeaway","risk_factors":["risk"],"recommended_action":"BUY/HOLD/WATCH"}}"""

        try:
            response = ollama.chat(
                model=self.exploration_model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.1, 'num_predict': 400}
            )
            content = self._clean_json(response['message']['content'])
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed, using fallback: {e}")
            return {
                "interpretation": f"Found {len(df)} results",
                "confidence": 0.5,
                "tickers_of_interest": tickers[:5],
                "key_insight": "See raw data",
                "risk_factors": [],
                "recommended_action": "WATCH",
            }
        except Exception as e:
            logger.error(f"LLM failed: {e}")
            return {
                "interpretation": "LLM error",
                "confidence": 0.0,
                "tickers_of_interest": tickers[:5],
                "key_insight": "",
                "risk_factors": [],
                "recommended_action": "WATCH",
            }

    def synthesize_report(self, all_findings: list, universe_size: int = None) -> str:
        """Create final investment report"""
        # Extract key data
        ticker_signals = {}
        for f in all_findings:
            for t in f.get('tickers_found', [])[:5]:
                ticker_signals.setdefault(t, 0)
                ticker_signals[t] += 1

        top_tickers = sorted(ticker_signals.items(), key=lambda x: x[1], reverse=True)[:10]
        ticker_list = "\n".join([f"- {t}: {c} signals" for t, c in top_tickers])

        strategies_run = list(set(f.get('strategy', '') for f in all_findings))

        universe = f"Database has {universe_size} active stocks. " if universe_size else ""
        prompt = f"""You are a portfolio strategist. Create an investment report.

{universe}{len(all_findings)} strategy variations were run across {len(strategies_run)} strategies.

Top conviction picks by signal count:
{ticker_list}

Write a concise report with:
1. Top 3 stock picks with one-line thesis each
2. Key sector themes observed
3. One risk to watch
4. One actionable trade idea"""

        try:
            response = ollama.chat(
                model=self.analysis_model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.5, 'num_predict': 1024}
            )
            return response['message']['content']
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return f"# Investment Report\n\nError generating report: {e}\n\n## Top Signals\n{ticker_list}"
