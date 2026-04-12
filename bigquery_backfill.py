"""
bigquery_backfill.py - Backfill historical PostgreSQL data into BigQuery

Reads all fare and tax records from PostgreSQL (runs 1 to MAX_RUN_ID)
and pushes them into the three BigQuery GDS tables.

Usage:
    python bigquery_backfill.py              # backfill all runs
    python bigquery_backfill.py --skip 111   # skip run IDs already in BQ
    python bigquery_backfill.py --dry-run    # count rows only, no BQ writes
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timezone

from dotenv import load_dotenv

load_dotenv(override=True)

# ─────────────────────────────────────────────────────────────────────────────
# Validate env before doing anything
# ─────────────────────────────────────────────────────────────────────────────

required = [
    "DATABASE_URL",
    "BIGQUERY_PROJECT_ID",
    "BIGQUERY_DATASET",
    "GOOGLE_APPLICATION_CREDENTIALS",
]
missing = [v for v in required if not os.environ.get(v, "").strip()]
if missing:
    print(f"[ERROR] Missing env vars: {', '.join(missing)}")
    sys.exit(1)

import psycopg2
from google.cloud import bigquery as bq

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PROJECT = os.environ["BIGQUERY_PROJECT_ID"]
DATASET = os.environ["BIGQUERY_DATASET"]

RBD_CABIN = {
    "F": "First",
    "A": "First",
    "P": "First",
    "J": "Business",
    "C": "Business",
    "D": "Business",
    "I": "Business",
    "Z": "Business",
    "W": "Premium Economy",
    "S": "Premium Economy",
    "Y": "Economy",
    "B": "Economy",
    "M": "Economy",
    "H": "Economy",
    "K": "Economy",
    "L": "Economy",
    "Q": "Economy",
    "T": "Economy",
    "E": "Economy",
    "N": "Economy",
    "R": "Economy",
    "U": "Economy",
    "V": "Economy",
    "X": "Economy",
    "O": "Economy",
    "G": "Economy",
}


def _cabin(rbd: str) -> str:
    return RBD_CABIN.get((rbd or "").upper()[:1], "Economy")


def _full_table(name: str) -> str:
    return f"{PROJECT}.{DATASET}.{name}"


def _insert_batch(client: bq.Client, table: str, rows: list[dict]) -> int:
    """Insert rows in chunks of 500. Returns total rows inserted."""
    if not rows:
        return 0
    inserted = 0
    chunk_size = 500
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        errors = client.insert_rows_json(_full_table(table), chunk)
        if errors:
            print(f"  [BQ] Insert errors on {table}: {errors[:2]}")
            return -1
        inserted += len(chunk)
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Backfill fare runs
# ─────────────────────────────────────────────────────────────────────────────


def backfill_fare_runs(pg, bq_client, skip_ids: set[int], dry_run: bool):
    cur = pg.cursor()

    # Fare runs = auto + snapshot-import (not tax)
    cur.execute("""
        SELECT id, run_time, run_mode
        FROM fare_runs
        WHERE run_mode NOT IN ('tax-mode', 'snapshot-import-tax')
        ORDER BY id
    """)
    runs = cur.fetchall()

    total_rows = 0
    for run_id, run_time, run_mode in runs:
        if run_id in skip_ids:
            print(f"  [SKIP] run {run_id} ({run_mode}) — already in BigQuery")
            continue

        # Load fare records for this run
        cur.execute(
            """
            SELECT route, airline, rbd, journey_type, currency,
                   base_fare, total_taxes, total_fare, fare_basis,
                   is_sold_out, is_unsaleable
            FROM fare_records
            WHERE run_id = %s
        """,
            (run_id,),
        )
        records = cur.fetchall()

        if not records:
            print(f"  [SKIP] run {run_id} — no fare records")
            continue

        captured_at = run_time.replace(tzinfo=timezone.utc).isoformat()
        cycle_id = f"gds_run_{run_id}"

        rows = []
        for (
            route,
            airline,
            rbd,
            jt,
            currency,
            base_fare,
            total_taxes,
            total_fare,
            fare_basis,
            is_sold_out,
            is_unsaleable,
        ) in records:

            route_parts = (route or "").split("-", 1)
            origin = route_parts[0] if len(route_parts) > 1 else route or ""
            destination = route_parts[1] if len(route_parts) > 1 else ""

            rows.append(
                {
                    "cycle_id": cycle_id,
                    "captured_at_utc": captured_at,
                    "airline": airline or "",
                    "origin": origin,
                    "destination": destination,
                    "route_key": route or "",
                    "rbd": rbd or "",
                    "cabin": _cabin(rbd),
                    "fare_basis": fare_basis or "",
                    "journey_type": jt or "",
                    "base_fare": float(base_fare) if base_fare is not None else 0.0,
                    "total_taxes": (
                        float(total_taxes) if total_taxes is not None else 0.0
                    ),
                    "total_fare": float(total_fare) if total_fare is not None else 0.0,
                    "currency": currency or "",
                    "is_sold_out": bool(is_sold_out),
                    "is_unsaleable": bool(is_unsaleable),
                    "source": "gds_travelport",
                }
            )

        if dry_run:
            print(f"  [DRY-RUN] run {run_id} ({run_mode}): {len(rows)} fare rows")
            total_rows += len(rows)
            continue

        n = _insert_batch(bq_client, "fact_gds_fare_snapshot", rows)
        if n < 0:
            print(f"  [ERROR] run {run_id} failed — stopping")
            break
        print(f"  [OK] run {run_id} ({run_mode}): pushed {n} fare rows")
        total_rows += n

    return total_rows


# ─────────────────────────────────────────────────────────────────────────────
# Backfill tax runs
# ─────────────────────────────────────────────────────────────────────────────


def backfill_tax_runs(pg, bq_client, skip_ids: set[int], dry_run: bool):
    cur = pg.cursor()

    cur.execute("""
        SELECT id, run_time, run_mode
        FROM fare_runs
        WHERE run_mode IN ('tax-mode', 'snapshot-import-tax')
        ORDER BY id
    """)
    runs = cur.fetchall()

    total_rows = 0
    for run_id, run_time, run_mode in runs:
        if run_id in skip_ids:
            print(f"  [SKIP] tax run {run_id} — already in BigQuery")
            continue

        cur.execute(
            """
            SELECT airport_code, tax_code, tax_name,
                   category, subcategory, condition, currency, amount, status
            FROM tax_records
            WHERE run_id = %s
        """,
            (run_id,),
        )
        records = cur.fetchall()

        if not records:
            print(f"  [SKIP] tax run {run_id} — no tax records")
            continue

        captured_at = run_time.replace(tzinfo=timezone.utc).isoformat()
        cycle_id = f"gds_tax_run_{run_id}"

        rows = []
        for (
            airport_code,
            tax_code,
            tax_name,
            category,
            subcategory,
            condition,
            currency,
            amount,
            status,
        ) in records:
            rows.append(
                {
                    "cycle_id": cycle_id,
                    "captured_at_utc": captured_at,
                    "airport_code": airport_code or "",
                    "tax_code": tax_code or "",
                    "tax_name": tax_name or "",
                    "category": category or "",
                    "subcategory": subcategory or "",
                    "condition": condition or "",
                    "currency": currency or "",
                    "amount": float(amount) if amount is not None else None,
                    "status": status or "",
                    "source": "gds_travelport",
                }
            )

        if dry_run:
            print(f"  [DRY-RUN] tax run {run_id} ({run_mode}): {len(rows)} tax rows")
            total_rows += len(rows)
            continue

        n = _insert_batch(bq_client, "fact_gds_tax_snapshot", rows)
        if n < 0:
            print(f"  [ERROR] tax run {run_id} failed — stopping")
            break
        print(f"  [OK] tax run {run_id} ({run_mode}): pushed {n} tax rows")
        total_rows += n

    return total_rows


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Backfill PostgreSQL GDS data into BigQuery"
    )
    parser.add_argument(
        "--skip",
        type=int,
        nargs="+",
        default=[111],
        metavar="RUN_ID",
        help="Run IDs to skip (default: 111, already in BQ)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows only, do not write to BigQuery",
    )
    args = parser.parse_args()

    skip_ids = set(args.skip)
    dry_run = args.dry_run

    print("=" * 60)
    print("  BigQuery Backfill")
    print(f"  Project : {PROJECT}")
    print(f"  Dataset : {DATASET}")
    print(f"  Skip IDs: {sorted(skip_ids)}")
    print(f"  Dry run : {dry_run}")
    print("=" * 60)

    # Connect to PostgreSQL
    print("\n[1/2] Connecting to PostgreSQL...")
    pg = psycopg2.connect(os.environ["DATABASE_URL"])
    print("  Connected OK")

    # Connect to BigQuery
    print("\n[2/2] Connecting to BigQuery...")
    bq_client = bq.Client(project=PROJECT)
    print("  Connected OK")

    # Backfill fares
    print("\n--- Fare runs ---")
    fare_total = backfill_fare_runs(pg, bq_client, skip_ids, dry_run)

    # Backfill taxes
    print("\n--- Tax runs ---")
    tax_total = backfill_tax_runs(pg, bq_client, skip_ids, dry_run)

    pg.close()

    print("\n" + "=" * 60)
    action = "Would push" if dry_run else "Pushed"
    print(f"  {action} {fare_total} fare rows")
    print(f"  {action} {tax_total} tax rows")
    print("  Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
