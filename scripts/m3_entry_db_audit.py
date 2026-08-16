from __future__ import annotations

import json
from pathlib import Path

import duckdb


DB_PATH = Path(r"C:\project\tw-sepa-screener\data\tw_sepa.duckdb")

QUERIES = {
    "stock_master": """
        SELECT
            count(*) AS rows,
            count(DISTINCT symbol || '|' || market) AS keys,
            min(listed_at) AS min_listed,
            max(listed_at) AS max_listed,
            count(*) FILTER (WHERE listed_at IS NULL) AS null_listed
        FROM stock_master
    """,
    "daily_prices": """
        SELECT
            count(*) AS rows,
            count(DISTINCT symbol || '|' || market || '|' || date) AS keys,
            min(date) AS min_date,
            max(date) AS max_date,
            count(DISTINCT symbol || '|' || market) AS instruments,
            count(*) FILTER (
                WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
            ) AS missing_ohlc
        FROM daily_prices
    """,
    "monthly_revenue": """
        SELECT
            count(*) AS rows,
            min(period_end) AS min_period,
            max(period_end) AS max_period,
            min(available_at) AS min_available,
            max(available_at) AS max_available,
            count(*) FILTER (WHERE available_at IS NULL) AS null_available
        FROM monthly_revenue
    """,
    "quarterly_financials": """
        SELECT
            count(*) AS rows,
            min(period_end) AS min_period,
            max(period_end) AS max_period,
            min(available_at) AS min_available,
            max(available_at) AS max_available,
            count(*) FILTER (WHERE available_at IS NULL) AS null_available
        FROM quarterly_financials
    """,
    "corporate_actions": """
        SELECT
            count(*) AS rows,
            min(action_date) AS min_action,
            max(action_date) AS max_action,
            min(available_at) AS min_available,
            max(available_at) AS max_available,
            count(*) FILTER (WHERE available_at IS NULL) AS null_available
        FROM corporate_actions
    """,
    "market_session_status": """
        SELECT
            count(*) AS rows,
            min(session_date) AS min_date,
            max(session_date) AS max_date
        FROM market_session_status
    """,
}


def main() -> None:
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        core = {}
        for table, query in QUERIES.items():
            if table not in tables:
                core[table] = {"missing": True}
                continue
            cursor = connection.execute(query)
            columns = [item[0] for item in cursor.description]
            core[table] = dict(zip(columns, cursor.fetchone(), strict=True))
        result = {
            "database": str(DB_PATH),
            "database_bytes": DB_PATH.stat().st_size,
            "read_only": True,
            "table_count": len(tables),
            "core": core,
        }
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
