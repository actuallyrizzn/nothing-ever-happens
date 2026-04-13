#!/usr/bin/env python3
"""Create a dashboard admin user in Postgres (same URL as the bot) + bcrypt.

Requires DASHBOARD_AUTH_SECRET (≥32 chars) and DATABASE_URL or
DASHBOARD_AUTH_DATABASE_URL.

Usage:
  python scripts/dashboard_create_user.py --username mark --password 'your-secure-pass'
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create dashboard admin user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    secret = (os.getenv("DASHBOARD_AUTH_SECRET") or "").strip()
    if len(secret) < 32:
        print(
            "ERROR: Set DASHBOARD_AUTH_SECRET in the environment (at least 32 characters).",
            file=sys.stderr,
        )
        return 1
    from bot.dashboard_auth import DashboardAuth, _resolve_dashboard_database_url

    db_url = _resolve_dashboard_database_url()
    if not db_url:
        print(
            "ERROR: Set DATABASE_URL or DASHBOARD_AUTH_DATABASE_URL for dashboard admin storage.",
            file=sys.stderr,
        )
        return 1

    auth = DashboardAuth(secret, db_url)
    res = auth.create_user(args.username, args.password)
    if not res["success"]:
        print(res["error"], file=sys.stderr)
        return 1
    print(f"Created admin user {args.username!r} (table neh_dashboard_admin_users)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
