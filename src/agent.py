#!/usr/bin/env python3
"""Autonomous Stock Explorer - Main Agent"""
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter
import pandas as pd
from loguru import logger
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from dotenv import load_dotenv

from database import DatabaseConnector
from llm import LLMInterface
from strategies import STRATEGIES

load_dotenv('config/.env')
console = Console()


class StockExplorer:
    def __init__(self):
        self.db = DatabaseConnector()
        self.llm = LLMInterface()
        self.findings = []
        self.start_time = datetime.now()
        self.universe_size = None

        # Setup logging
        logger.add("logs/agent_{time}.log", rotation="1 day", retention="7 days")

    def run(self):
        """Main execution"""
        console.rule("[bold blue]🚀 Stock Explorer Agent Starting")
        console.print(f"[dim]Start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

        try:
            self.db.connect()

            # Discover schema
            schema = self.db.get_schema()
            stats = self.db.get_table_stats()
            total_rows = sum(s['row_count'] for s in stats)
            # Real universe size for the report (falls back to None if table absent)
            self.universe_size = next(
                (s['row_count'] for s in stats if s['table_name'] == 'fundamentals'), None
            )
            console.print(f"[green]✓[/green] Connected: {len(schema)} tables, {total_rows:,} total rows")

            # Show key tables
            for s in stats[:10]:
                console.print(f"  [dim]• {s['table_name']}: {s['row_count']:,} rows[/dim]")

            # Run all strategies
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                task = progress.add_task("[cyan]Executing investment strategies...", total=len(STRATEGIES) * 3)

                all_results = []
                for strategy_name, strategy in STRATEGIES.items():
                    for i in range(3):
                        params = {k: random.choice(v) for k, v in strategy.get('params', {}).items()}

                        try:
                            query = strategy['query'].format(**params)
                            columns, rows = self.db.execute(query)

                            if rows:
                                df = pd.DataFrame(rows, columns=columns)
                                interpretation = self.llm.interpret_results(
                                    f"Strategy: {strategy_name} (variation {i+1})",
                                    df
                                )

                                all_results.append({
                                    'strategy': strategy_name,
                                    'params': params,
                                    'tickers_found': df['ticker'].tolist() if 'ticker' in df.columns else [],
                                    'row_count': len(df),
                                    'interpretation': interpretation,
                                    'timestamp': datetime.now().isoformat()
                                })

                                tickers = df['ticker'].tolist()[:5] if 'ticker' in df.columns else []
                                console.print(f"  [green]✓[/green] {strategy_name} v{i+1}: {len(df)} results - {', '.join(tickers)}")
                            else:
                                console.print(f"  [yellow]○[/yellow] {strategy_name} v{i+1}: no results")

                        except Exception as e:
                            console.print(f"  [red]✗[/red] {strategy_name} v{i+1}: {str(e)[:80]}")
                            logger.error(f"{strategy_name} failed: {e}")

                        progress.advance(task)

            # Cross-reference findings
            console.print("\n[bold]Cross-referencing multi-signal stocks...[/bold]")
            ticker_signals = {}
            for r in all_results:
                for t in r.get('tickers_found', []):
                    ticker_signals.setdefault(t, []).append(r['strategy'])

            multi_signal = {t: list(set(s)) for t, s in ticker_signals.items() if len(set(s)) >= 2}
            console.print(f"[green]✓[/green] Found {len(multi_signal)} stocks with multiple signals")

            # Deep dive top multi-signal stocks
            top_tickers = []
            if multi_signal:
                top_tickers = sorted(multi_signal.items(), key=lambda x: len(x[1]), reverse=True)[:10]
                console.print(f"\n[bold]Deep diving top {len(top_tickers)} conviction picks:[/bold]")

                for ticker, signals in top_tickers:
                    signals_str = ', '.join(signals)
                    console.print(f"  [cyan]🔍 {ticker}[/cyan] - {len(signals)} signals: {signals_str}")

            # Save results
            self.save_results(all_results, multi_signal, top_tickers)

            # Synthesize report
            console.print("\n[bold]Generating investment report...[/bold]")
            report = self.llm.synthesize_report(all_results, universe_size=self.universe_size)
            self.save_report(report)

            console.rule("[bold green]✅ Exploration Complete!")
            duration = (datetime.now() - self.start_time).total_seconds() / 60
            console.print(f"[green]Duration: {duration:.1f} minutes[/green]")
            console.print(f"[green]Findings saved to: findings/[/green]")

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            console.print(f"[red]Fatal: {e}[/red]")
        finally:
            self.db.close()

    def save_results(self, results, multi_signal, top_tickers):
        """Save raw findings"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        output = {
            'timestamp': timestamp,
            'total_strategies_run': len(results),
            'total_tickers_found': len(set(t for r in results for t in r.get('tickers_found', []))),
            'multi_signal_stocks': {t: s for t, s in multi_signal.items()},
            'top_conviction': [{'ticker': t, 'signals': s} for t, s in top_tickers],
            'results': [{
                'strategy': r['strategy'],
                'params': r['params'],
                'tickers': r['tickers_found'][:10],
                'count': r['row_count'],
                'insight': r['interpretation'].get('key_insight', ''),
                'confidence': r['interpretation'].get('confidence', 0)
            } for r in results]
        }

        filepath = f"findings/results_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        # Update latest symlink
        latest = Path("findings/latest_results.json")
        if latest.exists():
            latest.unlink()
        latest.symlink_to(f"results_{timestamp}.json")

        logger.info(f"Results saved to {filepath}")

    def save_report(self, report):
        """Save markdown report"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        with open(f"findings/report_{timestamp}.md", 'w') as f:
            f.write(f"# Investment Research Report\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(report)
            f.write(f"\n\n---\n*Report generated by Stock Explorer Agent on MS-A1*\n")


if __name__ == "__main__":
    explorer = StockExplorer()
    explorer.run()
