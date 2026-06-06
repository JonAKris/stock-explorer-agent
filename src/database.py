"""Database connector with schema discovery"""
import os
import pandas as pd
from typing import Dict, List, Tuple, Optional
import psycopg2
import psycopg2.extras
import psycopg2.pool
from loguru import logger
from dotenv import load_dotenv

load_dotenv('config/.env')


class DatabaseConnector:
    def __init__(self):
        self.pool = None

    def connect(self):
        """Create connection pool"""
        db_name = os.getenv('DB_NAME')
        db_user = os.getenv('DB_USER')
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '5432')

        logger.info(f"Connecting to {db_name} as {db_user}@{db_host}:{db_port}")

        self.pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=os.getenv('DB_PASSWORD'),
            options='-c default_transaction_read_only=on'
        )
        logger.info("Database connection pool established")

    def execute(self, sql: str, params: Optional[Tuple] = None) -> Tuple[List[str], List[Dict]]:
        """Execute read-only query with safety checks"""
        sql_upper = sql.strip().upper()

        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            raise ValueError(f"Only SELECT/WITH queries allowed. Got: {sql_upper[:50]}")

        dangerous = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 'ALTER', 'CREATE', 'GRANT', 'COPY']
        for word in dangerous:
            if word in sql_upper.split():
                raise ValueError(f"Dangerous operation '{word}' detected and blocked")

        conn = None
        try:
            conn = self.pool.getconn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)

                if cur.description:
                    columns = [desc.name for desc in cur.description]
                    rows = cur.fetchall()
                    return columns, rows
                return [], []
        except Exception as e:
            logger.error(f"Query failed: {e}")
            logger.error(f"SQL: {sql[:300]}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)

    def get_schema(self) -> Dict[str, List[Dict]]:
        """Discover all tables and columns"""
        try:
            _, rows = self.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)
        except Exception as e:
            logger.warning(f"Schema discovery failed: {e}")
            return {}

        schema = {}
        for row in rows:
            table = row['table_name']
            if table not in schema:
                schema[table] = []
            schema[table].append({'column': row['column_name'], 'type': row['data_type']})

        return schema

    def get_table_stats(self) -> List[Dict]:
        """Get row counts for all tables"""
        try:
            _, rows = self.execute("""
                SELECT relname as table_name, n_live_tup as row_count
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC;
            """)
            return rows
        except Exception as e:
            logger.warning(f"Table stats failed: {e}")
            return []

    def close(self):
        if self.pool:
            self.pool.closeall()
            logger.info("Database connection pool closed")
