"""Schema-aware investment strategies - tuned for actual data formats"""
import random
from typing import Dict, List

STRATEGIES = {
    "value_quality_composite": {
        "query": """
        SELECT * FROM (
            WITH ranked AS (
              SELECT f.ticker, f.name, f.sector, f.industry, f.market_cap,
                f.pe_ratio, f.peg_ratio, f.profit_margin, f.operating_margin,
                f.return_on_equity, f.quarterly_revenue_growth, f.quarterly_earnings_growth,
                f.dividend_yield, f.ebitda,
                bs.long_term_debt / NULLIF(bs.total_stockholder_equity,0) as debt_to_equity,
                bs.total_current_assets / NULLIF(bs.total_current_liabilities,0) as current_ratio,
                cf.free_cash_flow, cf.operating_cash_flow,
                NTILE(100) OVER (ORDER BY f.pe_ratio ASC) as pe_rank,
                NTILE(100) OVER (ORDER BY f.return_on_equity DESC) as roe_rank,
                NTILE(100) OVER (ORDER BY f.profit_margin DESC) as margin_rank,
                NTILE(100) OVER (ORDER BY cf.free_cash_flow DESC NULLS LAST) as fcf_rank
              FROM fundamentals f
              JOIN LATERAL (SELECT * FROM balance_sheets WHERE ticker=f.ticker AND period_type='yearly' ORDER BY date DESC LIMIT 1) bs ON true
              JOIN LATERAL (SELECT * FROM cash_flow_statements WHERE ticker=f.ticker AND period_type='yearly' ORDER BY date DESC LIMIT 1) cf ON true
              WHERE f.is_delisted=false AND f.market_cap>{min_mcap} AND f.pe_ratio>0
            )
            SELECT *, (pe_rank+roe_rank+margin_rank+fcf_rank)/4.0 as composite_score
            FROM ranked
        ) sub
        WHERE composite_score<={pctile}
        ORDER BY composite_score ASC LIMIT {limit}
        """,
        "params": {"min_mcap": [100000000, 500000000, 1000000000], "pctile": [25, 30, 40, 50], "limit": [25, 50]}
    },
    "congressional_trading": {
        "query": """
        WITH recent_trades AS (
          SELECT ticker, owner_name, relationship, transaction_code,
            COUNT(*) as trade_count,
            MAX(transaction_date) as last_date
          FROM insider_transactions
          WHERE transaction_date >= CURRENT_DATE - INTERVAL '{days} days'
          GROUP BY ticker, owner_name, relationship, transaction_code
        ),
        ticker_summary AS (
          SELECT ticker,
            COUNT(DISTINCT CASE WHEN transaction_code='P' THEN owner_name END) as buyers,
            COUNT(DISTINCT CASE WHEN transaction_code='S' THEN owner_name END) as sellers,
            SUM(CASE WHEN transaction_code='P' THEN trade_count ELSE 0 END) as buy_trades,
            SUM(CASE WHEN transaction_code='S' THEN trade_count ELSE 0 END) as sell_trades,
            STRING_AGG(DISTINCT CASE WHEN transaction_code='P' THEN owner_name END, ', ') as buyer_names,
            MAX(last_date) as latest_activity
          FROM recent_trades
          GROUP BY ticker
        )
        SELECT t.*, f.name, f.sector, f.market_cap, f.pe_ratio,
          e.close as price,
          CASE WHEN t.buyers > t.sellers THEN 'BUY_SIGNAL'
               WHEN t.sellers > t.buyers THEN 'SELL_SIGNAL'
               ELSE 'MIXED' END as signal,
          t.buy_trades - t.sell_trades as net_trades
        FROM ticker_summary t
        JOIN fundamentals f ON t.ticker=f.ticker
        JOIN eod_prices e ON t.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=t.ticker)
        WHERE f.is_delisted=false AND (t.buyers>0 OR t.sellers>0)
        ORDER BY (t.buy_trades - t.sell_trades) DESC LIMIT {limit}
        """,
        "params": {"days": [30, 60, 90, 180], "limit": [25, 50]}
    },
    "congressional_selling_alert": {
        "query": """
        WITH recent_trades AS (
          SELECT ticker, owner_name, relationship, transaction_code,
            COUNT(*) as trade_count,
            MAX(transaction_date) as last_date
          FROM insider_transactions
          WHERE transaction_date >= CURRENT_DATE - INTERVAL '{days} days'
          GROUP BY ticker, owner_name, relationship, transaction_code
        ),
        ticker_summary AS (
          SELECT ticker,
            COUNT(DISTINCT CASE WHEN transaction_code='P' THEN owner_name END) as buyers,
            COUNT(DISTINCT CASE WHEN transaction_code='S' THEN owner_name END) as sellers,
            SUM(CASE WHEN transaction_code='S' THEN trade_count ELSE 0 END) as sell_trades,
            STRING_AGG(DISTINCT CASE WHEN transaction_code='S' THEN owner_name END, ', ') as seller_names
          FROM recent_trades
          GROUP BY ticker
        )
        SELECT t.*, f.name, f.sector, f.market_cap, f.pe_ratio,
          e.close as price
        FROM ticker_summary t
        JOIN fundamentals f ON t.ticker=f.ticker
        JOIN eod_prices e ON t.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=t.ticker)
        WHERE f.is_delisted=false AND t.sellers > t.buyers
        ORDER BY t.sell_trades DESC LIMIT {limit}
        """,
        "params": {"days": [30, 60, 90, 180], "limit": [25, 50]}
    },
    "sentiment_divergence": {
        "query": """
        WITH sent AS (
          SELECT ticker,
            AVG(normalized) FILTER(WHERE date>=CURRENT_DATE-INTERVAL'{recent}d') as recent_sent,
            AVG(normalized) FILTER(WHERE date>=CURRENT_DATE-INTERVAL'{total}d' AND date<CURRENT_DATE-INTERVAL'{recent}d') as prior_sent,
            COUNT(*) FILTER(WHERE date>=CURRENT_DATE-INTERVAL'{total}d') as article_count
          FROM sentiment_daily WHERE date>=CURRENT_DATE-INTERVAL'{total}d'
          GROUP BY ticker HAVING COUNT(*)>=5
        )
        SELECT s.*, f.name, f.sector, f.market_cap,
          (e.close / NULLIF(e30.close, 0) - 1) * 100 as price_chg_30d
        FROM sent s
        JOIN fundamentals f ON s.ticker=f.ticker
        JOIN eod_prices e ON s.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=s.ticker)
        LEFT JOIN eod_prices e30 ON s.ticker=e30.ticker
          AND e30.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=s.ticker AND date <= CURRENT_DATE - 30)
        WHERE s.recent_sent>s.prior_sent AND f.is_delisted=false
        ORDER BY (s.recent_sent-s.prior_sent) DESC LIMIT {limit}
        """,
        "params": {"recent": [7, 14], "total": [30, 60], "limit": [25, 50]}
    },
    "earnings_beaters": {
        "query": """
        WITH beats AS (
          SELECT ticker, report_date, surprise_pct,
            ROW_NUMBER() OVER(PARTITION BY ticker ORDER BY report_date DESC) as recency
          FROM earnings_history
          WHERE report_date>=CURRENT_DATE-INTERVAL'{months} months' AND surprise_pct>0
        ),
        consistent AS (
          SELECT ticker, AVG(surprise_pct) as avg_beat, COUNT(*) as total_beats
          FROM beats WHERE recency<={quarters}
          GROUP BY ticker HAVING COUNT(*)={quarters}
        )
        SELECT c.*, f.name, f.sector, f.market_cap, f.pe_ratio, f.peg_ratio,
          f.quarterly_revenue_growth, a.target_price, e.close as price,
          (a.target_price/NULLIF(e.close,0)-1)*100 as upside
        FROM consistent c
        JOIN fundamentals f ON c.ticker=f.ticker
        LEFT JOIN LATERAL (SELECT target_price FROM analyst_ratings_history WHERE ticker=c.ticker ORDER BY date DESC LIMIT 1) a ON true
        JOIN eod_prices e ON c.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=c.ticker)
        WHERE f.is_delisted=false
        ORDER BY c.avg_beat DESC LIMIT {limit}
        """,
        "params": {"months": [12, 24], "quarters": [3, 4], "limit": [25, 50]}
    },
    "earnings_miss_opportunity": {
        "query": """
        WITH misses AS (
          SELECT ticker, report_date, surprise_pct,
            ROW_NUMBER() OVER(PARTITION BY ticker ORDER BY report_date DESC) as recency
          FROM earnings_history
          WHERE report_date>=CURRENT_DATE-INTERVAL'12 months' AND surprise_pct<0
        ),
        recent_miss AS (
          SELECT ticker, AVG(surprise_pct) as avg_miss
          FROM misses WHERE recency=1
          GROUP BY ticker
        )
        SELECT m.*, f.name, f.sector, f.market_cap, f.pe_ratio,
          f.quarterly_revenue_growth, f.quarterly_earnings_growth,
          e.close as price,
          (e.close / NULLIF(e90.close, 0) - 1) * 100 as price_chg_90d
        FROM recent_miss m
        JOIN fundamentals f ON m.ticker=f.ticker
        JOIN eod_prices e ON m.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=m.ticker)
        LEFT JOIN eod_prices e90 ON m.ticker=e90.ticker
          AND e90.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=m.ticker AND date <= CURRENT_DATE - 90)
        WHERE f.is_delisted=false AND f.pe_ratio>0
        ORDER BY m.avg_miss ASC LIMIT {limit}
        """,
        "params": {"limit": [25, 50]}
    },
    "fund_holder_conviction": {
        "query": """
        WITH funds AS (
          SELECT ticker, holder_name, MAX(report_date) as last_report,
            MAX(pct_shares) as pct, MAX(shares_held) as shares
          FROM fund_holders
          WHERE report_date>=CURRENT_DATE-INTERVAL'{months} months'
          GROUP BY ticker, holder_name
        )
        SELECT ticker, COUNT(*) as fund_count, SUM(pct) as total_pct,
          AVG(pct) as avg_pct, SUM(shares) as total_shares
        FROM funds
        GROUP BY ticker HAVING COUNT(*)>{min_funds}
        ORDER BY total_pct DESC LIMIT {limit}
        """,
        "params": {"months": [6, 12], "min_funds": [5, 10, 25], "limit": [25, 50]}
    },
    "price_momentum_leaders": {
        "query": """
        WITH returns AS (
          SELECT ticker,
            close / NULLIF(LAG(close, 21) OVER (PARTITION BY ticker ORDER BY date), 0) - 1 as ret_1m,
            close / NULLIF(LAG(close, 63) OVER (PARTITION BY ticker ORDER BY date), 0) - 1 as ret_3m,
            close / NULLIF(LAG(close, 126) OVER (PARTITION BY ticker ORDER BY date), 0) - 1 as ret_6m,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
          FROM eod_prices
          WHERE date >= CURRENT_DATE - INTERVAL '12 months'
        ),
        latest AS (
          SELECT * FROM returns WHERE rn=1 AND ret_1m IS NOT NULL
        )
        SELECT l.*, f.name, f.sector, f.market_cap, f.pe_ratio,
          e.close as price
        FROM latest l
        JOIN fundamentals f ON l.ticker=f.ticker
        JOIN eod_prices e ON l.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=l.ticker)
        WHERE f.is_delisted=false AND l.ret_1m>0 AND l.ret_3m>0
        ORDER BY l.ret_6m DESC LIMIT {limit}
        """,
        "params": {"limit": [25, 50]}
    },
    "dividend_income": {
        "query": """
        WITH div_history AS (
          SELECT ticker,
            MAX(ex_date) as last_div_date,
            SUM(value) FILTER (WHERE ex_date >= CURRENT_DATE - INTERVAL '12 months') as annual_dividend,
            COUNT(*) as payments_12m
          FROM dividends
          GROUP BY ticker
        )
        SELECT d.*, f.name, f.sector, f.market_cap,
          f.dividend_yield, f.pe_ratio,
          e.close as price,
          (d.annual_dividend / NULLIF(e.close, 0)) * 100 as calculated_yield
        FROM div_history d
        JOIN fundamentals f ON d.ticker=f.ticker
        JOIN eod_prices e ON d.ticker=e.ticker AND e.date=(SELECT MAX(date) FROM eod_prices WHERE ticker=d.ticker)
        WHERE f.is_delisted=false AND d.annual_dividend>0 AND f.dividend_yield>0
        ORDER BY f.dividend_yield DESC LIMIT {limit}
        """,
        "params": {"limit": [25, 50]}
    }
}
