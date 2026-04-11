"""
bigquery_pusher.py - Push GDS fare and tax data to BigQuery

After each extraction run, this module streams fare_records and tax_records
from local PostgreSQL into the aeropulseintelligence.aviation_intel BigQuery
dataset so the Aero Pulse web platform can display GDS-sourced fare history.

Required env vars:
    BIGQUERY_PROJECT_ID   - GCP project (e.g. aeropulseintelligence)
    BIGQUERY_DATASET      - Dataset (e.g. aviation_intel)
    GOOGLE_APPLICATION_CREDENTIALS - Path to service account JSON key

Tables written:
    fact_gds_fare_snapshot   - one row per run/airline/route/RBD/journey_type
    fact_gds_change_event    - one row per detected fare change
    fact_gds_tax_snapshot    - one row per run/airport/tax_code/section/rate
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("travelport.bigquery")

# ─────────────────────────────────────────────────────────────────────────────
# Lazy import so the whole system works without google-cloud-bigquery installed
# ─────────────────────────────────────────────────────────────────────────────
try:
    from google.cloud import bigquery as _bq

    _BQ_AVAILABLE = True
except ImportError:
    _bq = None  # type: ignore
    _BQ_AVAILABLE = False


def _get_client():
    if not _BQ_AVAILABLE:
        return None
    project = os.environ.get("BIGQUERY_PROJECT_ID", "").strip()
    if not project:
        return None
    try:
        return _bq.Client(project=project)
    except Exception as e:
        logger.warning("  [BQ] Could not create BigQuery client: %s", e)
        return None


def _full_table(table: str) -> str:
    project = os.environ.get("BIGQUERY_PROJECT_ID", "aeropulseintelligence")
    dataset = os.environ.get("BIGQUERY_DATASET", "aviation_intel")
    return f"{project}.{dataset}.{table}"


# ─────────────────────────────────────────────────────────────────────────────
# Push fare snapshot
# ─────────────────────────────────────────────────────────────────────────────

def push_fare_snapshot(all_route_data: dict, run_id: int, run_time: datetime | None = None) -> int:
    """
    Push fare records from a completed run into fact_gds_fare_snapshot.

    all_route_data: the same dict passed to DatabaseManager.record_run()
    run_id:         the fare_runs.id for this run (used as cycle identifier)
    run_time:       timestamp of the run (defaults to now)

    Returns number of rows inserted, or -1 on error.
    """
    client = _get_client()
    if client is None:
        return 0

    captured_at = (run_time or datetime.now(timezone.utc)).isoformat()
    cycle_id = f"gds_run_{run_id}"
    rows: list[dict[str, Any]] = []

    for file_key, data in all_route_data.items():
        # Parse "AL_ORG-DST"
        parts = file_key.split("_", 1)
        airline = parts[0]
        route = parts[1] if len(parts) > 1 else file_key
        route_parts = route.split("-", 1)
        origin = route_parts[0] if len(route_parts) > 1 else route
        destination = route_parts[1] if len(route_parts) > 1 else ""

        currency = data.get("currency", "USD")
        fs_taxes = data.get("fs_taxes", {})
        total_taxes = float(fs_taxes.get("total_taxes", 0)) if fs_taxes else 0.0

        for rbd_key, info in data.get("rbd_data", {}).items():
            rbd = info.get("rbd", rbd_key.replace(" (Unsaleable)", ""))
            is_unsaleable = "Unsaleable" in rbd_key
            cabin = _rbd_to_cabin(rbd)

            for jt, fare_field, basis_field, sold_field in [
                ("OW", "ow_fare", "ow_fare_basis", "ow_sold_out"),
                ("RT", "rt_fare", "rt_fare_basis", "rt_sold_out"),
            ]:
                if info.get(fare_field) is None and not info.get(sold_field):
                    continue
                base = float(info.get(fare_field) or 0.0)
                sold = bool(info.get(sold_field, False))
                rows.append({
                    "cycle_id": cycle_id,
                    "captured_at_utc": captured_at,
                    "airline": airline,
                    "origin": origin,
                    "destination": destination,
                    "route_key": route,
                    "rbd": rbd,
                    "cabin": cabin,
                    "fare_basis": info.get(basis_field) or "",
                    "journey_type": jt,
                    "base_fare": base,
                    "total_taxes": total_taxes,
                    "total_fare": base + total_taxes if not sold else 0.0,
                    "currency": currency,
                    "is_sold_out": sold,
                    "is_unsaleable": is_unsaleable,
                    "source": "gds_travelport",
                })

    if not rows:
        logger.info("  [BQ] No fare rows to push")
        return 0

    try:
        errors = client.insert_rows_json(_full_table("fact_gds_fare_snapshot"), rows)
        if errors:
            logger.error("  [BQ] Insert errors: %s", errors[:3])
            return -1
        logger.info("  [BQ] Pushed %d fare rows to BigQuery (run %s)", len(rows), cycle_id)
        return len(rows)
    except Exception as e:
        logger.error("  [BQ] Failed to push fare snapshot: %s", e)
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Push change events
# ─────────────────────────────────────────────────────────────────────────────

def push_change_events(changes: dict, run_time: datetime | None = None) -> int:
    """
    Push detected fare changes into fact_gds_change_event.

    changes: output of change_detector.detect_changes()
    """
    client = _get_client()
    if client is None:
        return 0

    detected_at = (run_time or datetime.now(timezone.utc)).isoformat()
    report_day = (run_time or datetime.now(timezone.utc)).date().isoformat()
    rows: list[dict[str, Any]] = []

    for file_key, rbd_changes in changes.items():
        parts = file_key.split("_", 1)
        airline = parts[0]
        route = parts[1] if len(parts) > 1 else file_key
        route_parts = route.split("-", 1)
        origin = route_parts[0] if len(route_parts) > 1 else route
        destination = route_parts[1] if len(route_parts) > 1 else ""

        if not isinstance(rbd_changes, dict):
            continue

        for rbd, change in rbd_changes.items():
            if not isinstance(change, dict):
                continue
            rows.append({
                "detected_at_utc": detected_at,
                "report_day": report_day,
                "airline": airline,
                "origin": origin,
                "destination": destination,
                "route_key": route,
                "rbd": rbd,
                "cabin": _rbd_to_cabin(rbd.replace(" (Unsaleable)", "")),
                "change_type": change.get("type", "unknown"),
                "old_ow_fare": change.get("old_ow_fare"),
                "new_ow_fare": change.get("new_ow_fare"),
                "old_rt_fare": change.get("old_rt_fare"),
                "new_rt_fare": change.get("new_rt_fare"),
            })

    if not rows:
        return 0

    try:
        errors = client.insert_rows_json(_full_table("fact_gds_change_event"), rows)
        if errors:
            logger.error("  [BQ] Change event insert errors: %s", errors[:3])
            return -1
        logger.info("  [BQ] Pushed %d change events to BigQuery", len(rows))
        return len(rows)
    except Exception as e:
        logger.error("  [BQ] Failed to push change events: %s", e)
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Push tax snapshot
# ─────────────────────────────────────────────────────────────────────────────

def push_tax_snapshot(tax_data: dict, run_id: int, run_time: datetime | None = None) -> int:
    """
    Push tax records into fact_gds_tax_snapshot.

    tax_data: the all_route_data dict when args.tax is True
    """
    client = _get_client()
    if client is None:
        return 0

    captured_at = (run_time or datetime.now(timezone.utc)).isoformat()
    cycle_id = f"gds_tax_run_{run_id}"
    rows: list[dict[str, Any]] = []

    for airport_code, airport_data in tax_data.items():
        for tax in airport_data.get("taxes", []):
            tax_code = tax.get("code", "")
            tax_name = tax.get("name", "")
            for section in tax.get("sections", []):
                category = section.get("category", "")
                subcategory = section.get("subcategory", "")
                for rate in section.get("rates", []):
                    rows.append({
                        "cycle_id": cycle_id,
                        "captured_at_utc": captured_at,
                        "airport_code": airport_code,
                        "tax_code": tax_code,
                        "tax_name": tax_name,
                        "category": category,
                        "subcategory": subcategory,
                        "condition": rate.get("condition", ""),
                        "currency": rate.get("currency", ""),
                        "amount": rate.get("amount"),
                        "status": rate.get("status", ""),
                        "source": "gds_travelport",
                    })

    if not rows:
        return 0

    try:
        errors = client.insert_rows_json(_full_table("fact_gds_tax_snapshot"), rows)
        if errors:
            logger.error("  [BQ] Tax insert errors: %s", errors[:3])
            return -1
        logger.info("  [BQ] Pushed %d tax rows to BigQuery (run %s)", len(rows), cycle_id)
        return len(rows)
    except Exception as e:
        logger.error("  [BQ] Failed to push tax snapshot: %s", e)
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rbd_to_cabin(rbd: str) -> str:
    """Map RBD code to cabin class name."""
    rbd = rbd.upper().strip()
    first_class = {"P", "F", "A"}
    business = {"J", "C", "D", "I", "Z"}
    premium_economy = {"W", "S", "E"}
    economy = {"Y", "B", "M", "H", "K", "Q", "V", "T", "L", "G", "N", "O", "R", "U", "X"}
    if rbd in first_class:
        return "First"
    if rbd in business:
        return "Business"
    if rbd in premium_economy:
        return "Premium Economy"
    if rbd in economy:
        return "Economy"
    return "Economy"


def is_configured() -> bool:
    """Return True if BigQuery credentials and project are configured."""
    return (
        _BQ_AVAILABLE
        and bool(os.environ.get("BIGQUERY_PROJECT_ID", "").strip())
        and (
            bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip())
            or bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip())
        )
    )
