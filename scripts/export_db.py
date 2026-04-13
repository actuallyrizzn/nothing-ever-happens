#!/usr/bin/env python3
"""Export tables from the bot SQLite database to CSV.

Usage:
    python scripts/export_db.py                  # exports to trade_events_export.csv
    python scripts/export_db.py -o my_dump.csv   # custom output path

Uses ``DATABASE_URL`` or the default SQLite file (see ``resolve_database_url`` in ``bot.db``).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import sqlalchemy as sa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export bot SQLite tables to CSV")
    parser.add_argument("-o", "--output", default="trade_events_export.csv")
    parser.add_argument(
        "--table",
        default="trade_events",
        choices=["trade_events", "orders", "fills", "positions", "bot_state", "all"],
    )
    args = parser.parse_args()

    from bot.db import create_engine, resolve_database_url

    db_url = resolve_database_url()
    engine = create_engine(db_url)
    meta = sa.MetaData()
    meta.reflect(bind=engine)

    tables = list(meta.tables.keys()) if args.table == "all" else [args.table]

    for table_name in tables:
        if table_name not in meta.tables:
            print(f"Table '{table_name}' not found, skipping", file=sys.stderr)
            continue

        table = meta.tables[table_name]
        out_path = args.output if len(tables) == 1 else f"{table_name}_export.csv"

        with engine.connect() as conn:
            rows = conn.execute(sa.select(table).order_by(sa.text("1"))).fetchall()
            columns = list(table.columns.keys())

        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

        print(f"{table_name}: {len(rows)} rows → {out_path}")


if __name__ == "__main__":
    main()
