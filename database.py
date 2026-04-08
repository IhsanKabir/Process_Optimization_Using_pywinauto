"""
database.py - PostgreSQL Database Connector

Responsible for persisting extracted fare and tax records directly
into a relational database for historical analysis and forecasting.
"""

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
            return True
        except psycopg2.Error as e:
            logger.error(f"  [DB] PostgreSQL connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"  [DB] Unexpected database error: {e}")
            return False

    def _init_schema(self):
        """Create the necessary tables if they don't already exist."""
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

            # Optional: A dedicated tax breakdown table can be added here in the future
            self.conn.commit()

    def record_run(self, all_route_data: Dict[str, Any], run_mode: str = "auto") -> int:
        """
        Flatten the hierarchical `all_route_data` dictionary into SQL rows
        and confidently insert them into the fare_records table.
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
                    # Format: AL_ORG-DST
                    parts = file_key.split("_")
                    airline = parts[0]
                    route = parts[1] if len(parts) > 1 else "UNKNOWN"

                    currency = data.get("currency", "USD")

                    # Compute total taxes
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
                                (run_id, route, airline, rbd, journey_type, currency, base_fare, total_taxes, total_fare, fare_basis, is_sold_out, is_unsaleable)
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
                                (run_id, route, airline, rbd, journey_type, currency, base_fare, total_taxes, total_fare, fare_basis, is_sold_out, is_unsaleable)
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
            logger.error(f"  [DB] Failed to insert records into database: {e}")
            return -1

    def close(self):
        """Cleanly close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
