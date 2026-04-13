"""
database.py - PostgreSQL Database Connector

Responsible for persisting extracted fare and tax records directly
into a relational database for historical analysis and forecasting.
"""

import re
import logging
import psycopg2
from typing import Dict, Any

logger = logging.getLogger("travelport.database")


class DatabaseManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = None

    def connect(self) -> bool:
        """Attempt to connect to the internal database and initialize the schema."""
        try:
            self.conn = psycopg2.connect(self.dsn)
            self._init_schema()
            logger.info("  [DB] Connected to database successfully")
            return True
        except psycopg2.Error as e:
            logger.error(f"  [DB] PostgreSQL connection error: {e}")
            self.close()  # Clean up the partially-initialised connection
            return False
        except Exception as e:
            logger.error(f"  [DB] Unexpected database error: {e}")
            self.close()
            return False

    def __enter__(self):
        """Support `with DatabaseManager(...) as db:` usage."""
        return self

    def __exit__(self, *exc):
        self.close()

    def _init_schema(self):
        """Create the necessary tables and indexes if they don't already exist."""
        try:
            with self.conn.cursor() as cur:
                # 1. Run Metadata
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fare_runs (
                        id SERIAL PRIMARY KEY,
                        run_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        run_mode VARCHAR(50),
                        total_routes INT
                    )
                """)

                # 2. Fare Granular Records
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fare_records (
                        id SERIAL PRIMARY KEY,
                        run_id INT REFERENCES fare_runs(id),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        route VARCHAR(15),
                        airline VARCHAR(5),
                        rbd VARCHAR(20),
                        journey_type VARCHAR(5),
                        currency VARCHAR(5),
                        base_fare NUMERIC(15, 2),
                        total_taxes NUMERIC(15, 2),
                        total_fare NUMERIC(15, 2),
                        fare_basis VARCHAR(50),
                        is_sold_out BOOLEAN,
                        is_unsaleable BOOLEAN
                    )
                """)

                # 3. Tax Records
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tax_records (
                        id SERIAL PRIMARY KEY,
                        run_id INT REFERENCES fare_runs(id),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        airport_code VARCHAR(5),
                        tax_code VARCHAR(20),
                        tax_name VARCHAR(200),
                        category VARCHAR(200),
                        subcategory VARCHAR(200),
                        condition VARCHAR(200),
                        currency VARCHAR(5),
                        amount NUMERIC(10, 4),
                        status VARCHAR(20)
                    )
                """)

                # Indexes for common query patterns
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fare_records_route
                    ON fare_records(route)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fare_records_airline
                    ON fare_records(airline)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fare_records_run_id
                    ON fare_records(run_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fare_records_timestamp
                    ON fare_records(timestamp)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_tax_records_airport
                    ON tax_records(airport_code)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_tax_records_run_id
                    ON tax_records(run_id)
                """)

            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Schema initialization failed: {e}") from e

    def _parse_file_key(self, file_key: str):
        """Parse 'AL_ORG-DST' file keys robustly using regex."""
        match = re.match(r"^([A-Z0-9]{2,3})_(.+)$", file_key)
        if match:
            return match.group(1), match.group(2)
        return "UNK", file_key

    def record_run(self, all_route_data: Dict[str, Any], run_mode: str = "auto") -> int:
        """
        Flatten the hierarchical `all_route_data` dictionary into SQL rows
        and insert them into the fare_records table.
        """
        if not self.conn:
            logger.error("  [DB] Cannot record run, no database connection.")
            return -1

        try:
            with self.conn.cursor() as cur:
                # 1. Create a Run record
                cur.execute(
                    "INSERT INTO fare_runs (run_mode, total_routes) VALUES (%s, %s) RETURNING id",
                    (run_mode, len(all_route_data)),
                )
                run_id = cur.fetchone()[0]

                # 2. Extract and format records
                for file_key, data in all_route_data.items():
                    airline, route = self._parse_file_key(file_key)
                    currency = data.get("currency", "USD")

                    fs_taxes = data.get("fs_taxes", {})
                    total_taxes = (
                        float(fs_taxes.get("total_taxes", 0)) if fs_taxes else 0.0
                    )

                    rbd_data = data.get("rbd_data", {})
                    for rbd_key, info in rbd_data.items():
                        rbd = info.get("rbd", "UNKNOWN")
                        is_unsaleable = "Unsaleable" in rbd_key

                        # One-Way (OW) Fare
                        if info.get("ow_fare") is not None or info.get("ow_sold_out"):
                            base_fare = float(info.get("ow_fare") or 0.0)
                            is_sold_out = bool(info.get("ow_sold_out", False))
                            total_fare = (
                                base_fare + total_taxes if not is_sold_out else 0.0
                            )
                            fare_basis = info.get("ow_fare_basis", "")
                            cur.execute(
                                """
                                INSERT INTO fare_records
                                (run_id, route, airline, rbd, journey_type, currency,
                                 base_fare, total_taxes, total_fare, fare_basis,
                                 is_sold_out, is_unsaleable)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    run_id,
                                    route,
                                    airline,
                                    rbd,
                                    "OW",
                                    currency,
                                    base_fare,
                                    total_taxes,
                                    total_fare,
                                    fare_basis,
                                    is_sold_out,
                                    is_unsaleable,
                                ),
                            )

                        # Round-Trip (RT) Fare
                        if info.get("rt_fare") is not None or info.get("rt_sold_out"):
                            base_fare = float(info.get("rt_fare") or 0.0)
                            is_sold_out = bool(info.get("rt_sold_out", False))
                            total_fare = (
                                base_fare + total_taxes if not is_sold_out else 0.0
                            )
                            fare_basis = info.get("rt_fare_basis", "")
                            cur.execute(
                                """
                                INSERT INTO fare_records
                                (run_id, route, airline, rbd, journey_type, currency,
                                 base_fare, total_taxes, total_fare, fare_basis,
                                 is_sold_out, is_unsaleable)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    run_id,
                                    route,
                                    airline,
                                    rbd,
                                    "RT",
                                    currency,
                                    base_fare,
                                    total_taxes,
                                    total_fare,
                                    fare_basis,
                                    is_sold_out,
                                    is_unsaleable,
                                ),
                            )

            self.conn.commit()
            return run_id

        except Exception as e:
            self.conn.rollback()
            logger.error(f"  [DB] Failed to insert fare records: {e}")
            return -1

    def record_tax_run(
        self, tax_data: Dict[str, Any], run_mode: str = "tax-mode"
    ) -> int:
        """
        Persist tax rate data extracted from FTAX commands.

        tax_data structure:
            {
                "SIN": {
                    "taxes": [
                        {
                            "code": "L7",
                            "name": "AIRPORT DEVELOPMENT LEVY",
                            "sections": [
                                {
                                    "category": "DEPARTURES FROM CHANGI SIN",
                                    "subcategory": "INTERNATIONAL DEPARTURES...",
                                    "rates": [
                                        {
                                            "condition": "TKT ON/BEFORE 31MAR25",
                                            "currency": "SGD",
                                            "amount": 46.40,
                                            "status": "expired|current|future"
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        """
        if not self.conn:
            logger.error("  [DB] Cannot record tax run, no database connection.")
            return -1

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO fare_runs (run_mode, total_routes) VALUES (%s, %s) RETURNING id",
                    (run_mode, len(tax_data)),
                )
                run_id = cur.fetchone()[0]

                for airport_code, airport_data in tax_data.items():
                    taxes = airport_data.get("taxes", [])
                    for tax in taxes:
                        tax_code = tax.get("code", "")
                        tax_name = tax.get("name", "")
                        for section in tax.get("sections", []):
                            category = section.get("category", "")
                            subcategory = section.get("subcategory", "")
                            for rate in section.get("rates", []):
                                cur.execute(
                                    """
                                    INSERT INTO tax_records
                                    (run_id, airport_code, tax_code, tax_name,
                                     category, subcategory, condition, currency,
                                     amount, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """,
                                    (
                                        run_id,
                                        airport_code,
                                        tax_code,
                                        tax_name,
                                        category,
                                        subcategory,
                                        rate.get("condition", ""),
                                        rate.get("currency", ""),
                                        rate.get("amount"),
                                        rate.get("status", ""),
                                    ),
                                )

            self.conn.commit()
            return run_id

        except Exception as e:
            self.conn.rollback()
            logger.error(f"  [DB] Failed to insert tax records: {e}")
            return -1

    def get_previous_run_id(self, current_run_id=None, run_mode=None):
        """Return run_id of the most recent fare run before current_run_id.
        Returns -1 if no previous run found."""
        if not self.conn:
            return -1
        try:
            with self.conn.cursor() as cur:
                if current_run_id is not None:
                    if run_mode:
                        cur.execute(
                            "SELECT id FROM fare_runs WHERE id < %s AND run_mode = %s ORDER BY id DESC LIMIT 1",
                            (current_run_id, run_mode),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM fare_runs WHERE id < %s AND run_mode != 'tax-mode' ORDER BY id DESC LIMIT 1",
                            (current_run_id,),
                        )
                else:
                    if run_mode:
                        cur.execute(
                            "SELECT id FROM fare_runs WHERE run_mode = %s ORDER BY id DESC LIMIT 1",
                            (run_mode,),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM fare_runs WHERE run_mode != 'tax-mode' ORDER BY id DESC LIMIT 1"
                        )
                row = cur.fetchone()
                return row[0] if row else -1
        except Exception as e:
            logger.error(f"  [DB] Failed to get previous run id: {e}")
            return -1

    def load_fare_snapshot(self, run_id):
        """Reconstruct an all_route_data-compatible dict from a previous DB run.
        Returns {} if run_id not found or on error."""
        if not self.conn or run_id < 0:
            return {}
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT route, airline, rbd, journey_type, currency,
                              base_fare, fare_basis, is_sold_out, is_unsaleable
                       FROM fare_records WHERE run_id = %s
                       ORDER BY airline, route, rbd, journey_type""",
                    (run_id,),
                )
                rows = cur.fetchall()

            snapshot = {}
            for (
                route,
                airline,
                rbd,
                journey_type,
                currency,
                base_fare,
                fare_basis,
                is_sold_out,
                is_unsaleable,
            ) in rows:
                file_key = f"{airline}_{route}"
                rbd_key = f"{rbd} (Unsaleable)" if is_unsaleable else rbd

                if file_key not in snapshot:
                    snapshot[file_key] = {"rbd_data": {}, "currency": currency or "USD"}

                if rbd_key not in snapshot[file_key]["rbd_data"]:
                    snapshot[file_key]["rbd_data"][rbd_key] = {
                        "rbd": rbd,
                        "ow_fare": None,
                        "rt_fare": None,
                        "ow_fare_basis": None,
                        "rt_fare_basis": None,
                        "ow_sold_out": False,
                        "rt_sold_out": False,
                    }

                entry = snapshot[file_key]["rbd_data"][rbd_key]
                if journey_type == "OW":
                    entry["ow_fare"] = (
                        float(base_fare) if base_fare and not is_sold_out else None
                    )
                    entry["ow_fare_basis"] = fare_basis
                    entry["ow_sold_out"] = bool(is_sold_out)
                elif journey_type == "RT":
                    entry["rt_fare"] = (
                        float(base_fare) if base_fare and not is_sold_out else None
                    )
                    entry["rt_fare_basis"] = fare_basis
                    entry["rt_sold_out"] = bool(is_sold_out)

            logger.info(
                f"  [DB] Loaded fare snapshot from run {run_id}: {len(snapshot)} routes"
            )
            return snapshot

        except Exception as e:
            logger.error(f"  [DB] Failed to load fare snapshot for run {run_id}: {e}")
            return {}

    def load_tax_snapshot(self, run_id):
        """Reconstruct a tax_data-compatible dict from a previous DB run.
        Returns {} if run_id not found or on error."""
        if not self.conn or run_id < 0:
            return {}
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT airport_code, tax_code, tax_name,
                              category, subcategory, condition, currency, amount, status
                       FROM tax_records WHERE run_id = %s
                       ORDER BY airport_code, tax_code, category, subcategory""",
                    (run_id,),
                )
                rows = cur.fetchall()

            snapshot = {}
            tax_index = {}
            section_index = {}

            for (
                airport,
                tax_code,
                tax_name,
                category,
                subcategory,
                condition,
                currency,
                amount,
                status,
            ) in rows:
                if airport not in snapshot:
                    snapshot[airport] = {"taxes": []}

                tax_key = (airport, tax_code)
                if tax_key not in tax_index:
                    snapshot[airport]["taxes"].append(
                        {"code": tax_code, "name": tax_name, "sections": []}
                    )
                    tax_index[tax_key] = len(snapshot[airport]["taxes"]) - 1

                tax_entry = snapshot[airport]["taxes"][tax_index[tax_key]]

                sec_key = (airport, tax_code, category, subcategory)
                if sec_key not in section_index:
                    tax_entry["sections"].append(
                        {"category": category, "subcategory": subcategory, "rates": []}
                    )
                    section_index[sec_key] = len(tax_entry["sections"]) - 1

                section = tax_entry["sections"][section_index[sec_key]]
                section["rates"].append(
                    {
                        "condition": condition or "",
                        "currency": currency or "",
                        "amount": float(amount) if amount else None,
                        "status": status or "",
                    }
                )

            logger.info(
                f"  [DB] Loaded tax snapshot from run {run_id}: {len(snapshot)} airports"
            )
            return snapshot

        except Exception as e:
            logger.error(f"  [DB] Failed to load tax snapshot for run {run_id}: {e}")
            return {}

    def close(self):
        """Cleanly close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
