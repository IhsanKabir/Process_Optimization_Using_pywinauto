"""
main.py - Travelport Fare Automation Orchestrator

Phase 1 (MVP): Read raw GDS output from text files, parse, and generate Excel report.

Usage:
    python main.py                     # Process all raw files in data/raw/
    python main.py --no-changes        # Skip change detection
    python main.py --output report.xlsx # Custom output path
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time as _time
import constants
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime, timedelta
from collections import OrderedDict

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm is not installed
    tqdm = None

from parser import (
    parse_fare_display,
    group_fares_by_rbd,
    load_commands,
    generate_file_key,
    parse_command,
)
from penalty_parser import parse_penalty_text
from penalty_report import generate_penalty_report
from tax_breakdown_parser import parse_fs_tax_breakdown, looks_like_fs_tax_breakdown
from excel_report import generate_report
from change_detector import (
    detect_changes,
    detect_tax_changes,
    format_tax_change_summary,
    save_snapshot,
    snapshot_has_changed,
    load_latest_snapshot,
    load_snapshot_by_reference,
    format_change_summary,
)
from exceptions import ConfigurationError, ValidationError
from validators import (
    validate_config,
    validate_limit,
    sanitize_command,
    validate_parsed_fares,
    validate_currency_code,
)
from credential_manager import CredentialManager
from checkpoint_manager import CheckpointManager
from constants import MAX_RETRIES_COMMAND, MAX_FS_DATE_STEPS, FS_DATE_OFFSET_START, FS_DATE_STEP

try:
    from database import DatabaseManager
except ImportError:
    DatabaseManager = None

try:
    import bigquery_pusher as _bq_pusher
except ImportError:
    _bq_pusher = None

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass  # python-dotenv not installed, skip

logger = logging.getLogger("travelport")

if getattr(sys, "frozen", False):
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    # But we want to output files next to the installed executable
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "config.json")
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, "data", "raw")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "data", "reports")
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "data", "archive")
LOG_DIR = os.path.join(SCRIPT_DIR, "data", "logs")
CHECKPOINT_DIR = os.path.join(SCRIPT_DIR, "data", "checkpoints")
RAW_PENALTY_DIR = os.path.join(SCRIPT_DIR, "data", "raw_penalty")
PLACEHOLDER_DATABASE_URLS = {
    "postgresql://user:password@localhost/travelport_db",
    "postgresql://user:password@localhost/GDS_Automation",
}
# Remote sources - admin updates these files on GitHub; all users get the
# latest config automatically on next run without needing a new exe.
REMOTE_CONFIG_URL = (
    "https://raw.githubusercontent.com/IhsanKabir/"
    "Process_Optimization_Using_pywinauto/main/config.json"
)
REMOTE_COMMANDS_URL = (
    "https://raw.githubusercontent.com/IhsanKabir/"
    "Process_Optimization_Using_pywinauto/main/commands.txt"
)
DEFAULT_COMMANDS_TEMPLATE = """# TravelportAuto route commands
# Add one Fare Display command per line.
# Examples:
# FDDACMCT/BG
# FDDACBKK/BS
# FDCGPMLE/BG
"""
FS_OPTION_PATTERN = re.compile(
    r"PRICING\s+OPTION\s+(\d+)(.*?(?=PRICING\s+OPTION\s+\d+|$))",
    re.IGNORECASE | re.DOTALL,
)
FS_LEG_PATTERN = re.compile(r"^\s*(\d+)\s+[#@-]?([A-Z0-9]{2})\s+", re.MULTILINE)
_RE_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def setup_logging():
    """Configure logging to console (INFO) and file (DEBUG)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        LOG_DIR, f"run_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log"
    )

    root = logging.getLogger("travelport")
    root.setLevel(logging.DEBUG)

    # Console handler - skip when stdout has been replaced (e.g. by the GUI),
    # otherwise messages would be delivered twice: once via this StreamHandler
    # (writing to the redirected stdout -> queue) and once via the QueueHandler
    # already attached to this logger by the GUI.
    if sys.stdout is sys.__stdout__:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(ch)

    # File: DEBUG level, full format with timestamps
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(fh)

    return log_file


def _resolve_bundled_file(filename: str) -> str | None:
    """Return a bundled file path when running from a PyInstaller build."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return None

    candidate = os.path.join(bundle_dir, filename)
    if os.path.exists(candidate):
        return candidate
    return None


def _seed_runtime_config_if_missing(config_path: str) -> str:
    """
    Seed the runtime config from the bundled default config when available.

    This keeps the packaged app usable even if a desktop only receives the exe.
    """
    if os.path.exists(config_path):
        return config_path

    bundled_config = _resolve_bundled_file("config.json")
    if not bundled_config:
        return config_path

    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        shutil.copyfile(bundled_config, config_path)
        logger.info(f"  Created default config.json at {config_path}")
        return config_path
    except OSError as e:
        logger.warning(
            f"  Could not create local config.json ({e}). Using bundled defaults."
        )
        return bundled_config


def _fetch_remote_config() -> dict | None:
    """Fetch the latest config.json from GitHub. Returns None if offline or invalid."""
    import urllib.request as _ur

    try:
        req = _ur.Request(
            REMOTE_CONFIG_URL, headers={"User-Agent": "TravelportAuto/1.0"}
        )
        with _ur.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _ensure_commands_template(commands_file: str) -> bool:
    """Create a starter commands.txt file for first-run users if missing."""
    if os.path.exists(commands_file):
        return False

    try:
        parent = os.path.dirname(commands_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(commands_file, "w", encoding="utf-8") as f:
            f.write(DEFAULT_COMMANDS_TEMPLATE)
        logger.info(f"  Created starter commands file at {commands_file}")
        return True
    except OSError as e:
        logger.warning(f"  Could not create starter commands file: {e}")
        return False


def _has_writable_stream(stream) -> bool:
    """Return True if tqdm can safely write to this stream."""
    return stream is not None and callable(getattr(stream, "write", None))


def _should_use_tqdm(gui_mode: bool = False) -> bool:
    """Enable tqdm only when a usable console-like stream exists."""
    if tqdm is None or gui_mode:
        return False
    return _has_writable_stream(sys.stderr) or _has_writable_stream(sys.stdout)


def _tqdm_stream():
    """Choose the best available stream for tqdm output."""
    if _has_writable_stream(sys.stderr):
        return sys.stderr
    if _has_writable_stream(sys.stdout):
        return sys.stdout
    return None


def _env_truthy(name: str) -> bool:
    """Return True when an environment variable is set to a truthy value."""
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: str) -> dict:
    """Load config - remote GitHub first (auto-updates), local/bundled fallback."""
    # Try remote first - this keeps airline names, airport lists, etc. current
    # without requiring users to update the exe or edit any files.
    remote = _fetch_remote_config()
    if remote is not None:
        try:
            config = validate_config(remote)
            logger.debug("  Config loaded from remote (ok)")
            return config
        except ConfigurationError:
            logger.warning("  Remote config failed validation - falling back to local.")

    # Fall back to bundled / local config.json
    if os.path.abspath(config_path) == os.path.abspath(DEFAULT_CONFIG):
        config_path = _seed_runtime_config_if_missing(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"  Config file not found: {config_path}")
        raise ConfigurationError(f"Config file not found: {config_path}")
    except json.JSONDecodeError as e:
        logger.error(f"  Invalid JSON in config file: {e}")
        raise ConfigurationError(f"Invalid JSON in config file: {e}")

    # Validate configuration using validators module
    try:
        config = validate_config(config)
        logger.debug("  Configuration validated successfully")
    except ConfigurationError as e:
        logger.error(f"  Configuration validation failed: {e}")
        raise

    return config


def load_raw_data(raw_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    """Load raw GDS output from text files in data/raw/."""
    raw_texts = {}
    raw_fs_texts = {}

    if not os.path.exists(raw_dir):
        return raw_texts, raw_fs_texts

    for filename in sorted(os.listdir(raw_dir)):
        if (
            filename.endswith(".txt")
            and not filename.startswith("_")
            and not filename.startswith("FTAX")
        ):
            filepath = os.path.join(raw_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if filename.endswith("_FS.txt"):
                file_key = filename[:-7]
                raw_fs_texts[file_key] = content
            else:
                file_key = filename[:-4]
                raw_texts[file_key] = content

            logger.info(f"  Loaded: {filename}")

    return raw_texts, raw_fs_texts


def process_route_data(
    raw_texts: dict[str, str],
    raw_fs_texts: dict[str, str],
    config: dict,
    enable_validation: bool = True,
    show_progress: bool = True,
    stop_event=None,
) -> dict:
    """Process raw text files into route data with optional validation."""
    rbd_sort_order = config.get("rbd_sort_order", [])
    all_route_data = OrderedDict()
    progress_active = show_progress and _should_use_tqdm()

    # Combine all file_keys from both raw_texts and raw_fs_texts
    all_file_keys = set(raw_texts.keys()) | set(raw_fs_texts.keys())

    # Use tqdm progress bar if available
    items = sorted(all_file_keys)
    if progress_active:
        items = tqdm(items, desc="Processing routes", unit="route", file=_tqdm_stream())

    for file_key in items:
        if stop_event and stop_event.is_set():
            logger.info("  [STOP] Stop requested during parsing. Stopping early.")
            break
        raw_text = raw_texts.get(file_key, "")

        # Parse fare data if available
        fares = []
        currency = None
        if raw_text:
            result = parse_fare_display(raw_text)
            fares = result.get("fares", [])
            currency = result.get("currency")

            # Validate currency code
            if enable_validation and currency:
                validate_currency_code(currency, warn_only=True)

            # Validate parsed fares
            if enable_validation and fares:
                validation_stats = validate_parsed_fares(fares, currency)
                if validation_stats["invalid_fares"] > 0:
                    logger.warning(
                        f"  {file_key}: {validation_stats['invalid_fares']}/{validation_stats['total_fares']} "
                        f"fares have validation issues"
                    )

        # Parse FS tax data if available
        fs_taxes = {}
        if file_key in raw_fs_texts:
            fs_taxes = parse_fs_tax_breakdown(raw_fs_texts[file_key])

            # Debug logging for tax parsing
            if not progress_active:
                if fs_taxes.get("exchange_rate", 0) > 0:
                    logger.debug(
                        f"      [TAX] {file_key}: Rate={fs_taxes.get('exchange_rate'):.4f}, "
                        f"Total={fs_taxes.get('total_taxes', 0)}, YQ={fs_taxes.get('yq_charge', 0)}"
                    )
                else:
                    logger.warning(
                        f"      [TAX] {file_key}: Exchange rate is 0 or missing - tax data may not display correctly"
                    )
                    logger.warning(
                        f"      [TAX] Base fare={fs_taxes.get('base_fare', 0)}, Equ fare={fs_taxes.get('equ_fare', 0)}"
                    )
                    if raw_fs_texts[file_key]:
                        logger.warning(
                            f"      [TAX] First 200 chars of raw FS text: {raw_fs_texts[file_key][:200]}"
                        )

        # Add to all_route_data if we have either fares or taxes
        if fares or fs_taxes:
            grouped = group_fares_by_rbd(fares, rbd_sort_order) if fares else {}
            all_route_data[file_key] = {
                "rbd_data": grouped,
                "currency": currency,
                "fs_taxes": fs_taxes,
            }

            # Only log if not using tqdm (to avoid cluttering progress bar)
            if not progress_active:
                if fares:
                    ow_count = sum(
                        1 for d in grouped.values() if d.get("ow_fare") is not None
                    )
                    rt_count = sum(
                        1 for d in grouped.values() if d.get("rt_fare") is not None
                    )
                    logger.info(
                        f"  {file_key} -> {len(grouped)} RBDs ({ow_count} OW, {rt_count} RT) [{currency or 'N/A'}]"
                    )
                elif fs_taxes:
                    logger.info(f"  {file_key} -> Tax data only (no fares)")
        else:
            if not progress_active:
                logger.warning(f"  No data parsed from: {file_key}")

    return OrderedDict(sorted(all_route_data.items()))


def record_to_database(all_route_data: dict, config: dict, mode: str = "auto") -> int:
    """Persist the data to PostgreSQL if configured. Returns run_id (>0) or -1."""
    db_url = _resolve_database_url(config)
    if not db_url or "postgresql://" not in db_url:
        return -1

    if not DatabaseManager:
        logger.warning(
            "  [!] Database integration skipped (psycopg2-binary not installed)"
        )
        return -1

    logger.info(f"[DB] Recording {len(all_route_data)} items to history...")
    db = DatabaseManager(db_url)
    if db.connect():
        if mode == "tax-mode":
            run_id = db.record_tax_run(all_route_data, run_mode=mode)
        else:
            run_id = db.record_run(all_route_data, run_mode=mode)
        if run_id > 0:
            logger.info(f"  [OK] Database record created (Run ID: {run_id})")
        db.close()
        return run_id
    else:
        logger.warning("  [!] Database integration skipped (connection failed)")
        return -1


def show_usage():
    """Show usage instructions when no data files are found."""
    logger.info("")
    logger.info("  [!] No .txt files found in data/raw/")
    logger.info("")
    logger.info("  HOW TO USE:")
    logger.info("  " + "-" * 44)
    logger.info("  1. Open Travelport Smartpoint")
    logger.info("  2. Run a fare display command (e.g., FDDACMLE/BG)")
    logger.info("  3. Select all output and copy (Ctrl+C)")
    logger.info(f"  4. Save as .txt in: {RAW_DATA_DIR}")
    logger.info("  5. Run: python main.py")


def _process_airport_taxes(
    automation,
    airports: dict,
    failed_commands: list,
    stop_event=None,
    use_tqdm: bool = False,
    write_backups: bool = False,
    raw_data_dir: str = "",
):
    """Shared logic for extracting FTAX data for a set of airports.

    Returns dict: {airport_code: {"taxes": [detail_data, ...]}}
    """
    from tax_parser import parse_ftax_list, parse_ftax_detail

    result = {}
    airport_items = airports.items()
    if use_tqdm and tqdm:
        airport_items = tqdm(
            list(airport_items),
            desc="Extracting tax data",
            unit="airport",
            file=_tqdm_stream(),
        )
    else:
        airport_items = list(airport_items)

    for index, (airport_code, airport_info) in enumerate(airport_items, 1):
        if stop_event and stop_event.is_set():
            logger.info("  [STOP] Stop requested - finishing after this point.")
            break
        country_code = airport_info["country"]

        if not use_tqdm:
            logger.info(
                f"  [{index}/{len(airports)}] Airport: {airport_code} ({country_code})"
            )

        list_cmd = f"FTAX-{country_code}"
        list_text = automation.run_command(list_cmd, max_pages=1)

        if write_backups and raw_data_dir:
            os.makedirs(raw_data_dir, exist_ok=True)
            backup_path = os.path.join(raw_data_dir, f"{list_cmd}.txt")
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(list_text)

        tax_types = parse_ftax_list(list_text)
        logger.info(
            f"    Found {len(tax_types)} tax types: {', '.join(t['code'] for t in tax_types)}"
        )

        if not tax_types and write_backups:
            logger.warning(
                f"    [DEBUG] Raw list text ({len(list_text)} chars): {list_text[:300]}"
            )

        airport_tax_details = []
        for idx, t in enumerate(tax_types, 1):
            detail_text = automation.run_ftax_command(
                country_code, t["code"], tax_index=idx
            )

            if write_backups and raw_data_dir:
                detail_backup = os.path.join(
                    raw_data_dir, f"FTAX-{country_code}_{t['code']}.txt"
                )
                with open(detail_backup, "w", encoding="utf-8") as f:
                    f.write(detail_text)

            if not detail_text or len(detail_text.strip()) < 20:
                failed_commands.append(f"{country_code}/{t['code']}")
                logger.warning(f"    Failed to extract details for {t['code']}")
                continue

            if write_backups:
                logger.debug(
                    f"      [DEBUG] Raw detail text first 200 chars: {detail_text[:200]}"
                )

            detail_data = parse_ftax_detail(detail_text, t["code"], t["name"])
            airport_tax_details.append(detail_data)
            logger.info(
                f"      {t['code']} -> {len(detail_data['sections'])} sections extracted."
            )

            if not detail_data["sections"] and write_backups:
                logger.warning(
                    f"      [DEBUG] 0 sections! Full text ({len(detail_text)} chars): {detail_text[:500]}"
                )

            if idx < len(tax_types):
                automation.return_to_tax_list(country_code)

        result[airport_code] = {"taxes": airport_tax_details}

    return result


def _safe_filename(value: str) -> str:
    """Convert arbitrary text into a filesystem-safe filename fragment."""
    cleaned = _RE_SAFE_FILENAME.sub("_", str(value or ""))
    return cleaned.strip("_") or "unknown"


def _is_placeholder_database_url(database_url: str | None) -> bool:
    normalized = (database_url or "").strip()
    if not normalized:
        return True
    if normalized in PLACEHOLDER_DATABASE_URLS:
        return True
    return "YOUR_" in normalized.upper()


def _normalize_database_url(database_url: str | None) -> str:
    """Normalize PostgreSQL URLs so psycopg2 can consume them reliably."""
    normalized = (database_url or "").strip()
    if not normalized:
        return ""

    if normalized.startswith("postgresql+"):
        normalized = "postgresql://" + normalized.split("://", 1)[1]

    if normalized.startswith("postgresql://"):
        parts = urlsplit(normalized)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault("connect_timeout", "5")
        normalized = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    return normalized


def _resolve_database_url(config: dict) -> str:
    """Prefer DATABASE_URL, but fall back to config when it isn't a placeholder."""
    env_database_url = _normalize_database_url(os.environ.get("DATABASE_URL"))
    if env_database_url:
        return env_database_url

    config_database_url = config.get("database_url")
    if _is_placeholder_database_url(config_database_url):
        return ""

    return _normalize_database_url(config_database_url)


def _route_variants(route_code: str, one_direction: bool = False) -> set[str]:
    """Return the route directions that should be treated as a match."""
    normalized = (route_code or "").strip().upper().replace("-", "")
    if len(normalized) != 6:
        return set()
    if one_direction:
        return {normalized}
    return {normalized, f"{normalized[3:]}{normalized[:3]}"}


def _command_matches_route(
    command_entry: dict, route_code: str, one_direction: bool = False
) -> bool:
    """Check whether a command matches a route filter."""
    route_variants = _route_variants(route_code, one_direction=one_direction)
    if not route_variants:
        return False

    origin = str(command_entry.get("origin") or "").upper()
    destination = str(command_entry.get("destination") or "").upper()
    if origin and destination:
        return f"{origin}{destination}" in route_variants

    raw_command = str(command_entry.get("command") or "").upper().replace("-", "")
    return any(route_variant in raw_command for route_variant in route_variants)


def _fd_output_has_fares(raw_text: str) -> bool:
    """Return True when FD output contains actual fare rows."""
    if not raw_text or not raw_text.strip():
        return False
    parsed = parse_fare_display(raw_text)
    return bool(parsed.get("fares"))


def _should_run_fs_extraction(args, fd_terminal_text: str) -> bool:
    """Skip FS when normal FD extraction produced no fare rows."""
    if getattr(args, "only_fd", False):
        return False
    if getattr(args, "only_yq", False) or getattr(args, "only_currency", False):
        return True
    return _fd_output_has_fares(fd_terminal_text)


def _find_pure_airline_option_in_fs_page(
    fs_text: str, airline: str
) -> tuple[int | None, str | None, int]:
    """Find the first pricing option on the current FS page containing only the target airline."""
    options = list(FS_OPTION_PATTERN.finditer(fs_text or ""))
    airline_upper = (airline or "").upper()

    for option_index, opt_match in enumerate(options):
        opt_num = opt_match.group(1)
        block = opt_match.group(2)
        leg_matches = FS_LEG_PATTERN.findall(block)
        if not leg_matches:
            continue

        leg_airlines = [match[1].upper().strip() for match in leg_matches]
        if all(code == airline_upper for code in leg_airlines):
            return option_index, opt_num, len(options)

    return None, None, len(options)


def _should_recheck_same_fs_page(
    current_fs_page: str, refreshed_fs_page: str, airline: str
) -> bool:
    """Return True when a same-date FS page looks more complete after settling."""
    current_text = (current_fs_page or "").strip()
    refreshed_text = (refreshed_fs_page or "").strip()
    if not refreshed_text or refreshed_text == current_text:
        return False

    (
        current_option_index,
        _current_option_number,
        current_option_count,
    ) = _find_pure_airline_option_in_fs_page(current_text, airline)
    (
        refreshed_option_index,
        _refreshed_option_number,
        refreshed_option_count,
    ) = _find_pure_airline_option_in_fs_page(refreshed_text, airline)

    if refreshed_option_index is not None and current_option_index is None:
        return True

    if refreshed_option_count > current_option_count:
        return True

    return (
        "PRICING OPTION" in refreshed_text.upper()
        and len(refreshed_text) > len(current_text) + 40
    )


def run_with_args(args, stop_event=None):
    """Entry point for the GUI: run extraction with a pre-built args Namespace."""
    if args.config is None:
        args.config = DEFAULT_CONFIG
    args._gui_mode = True
    return main(prebuilt_args=args, stop_event=stop_event)


def main(prebuilt_args=None, stop_event=None):
    """Main entry point. Called directly from CLI or via run_with_args() from GUI."""
    import time as _time

    start_time = _time.time()
    _stop = stop_event  # shorthand used in command loops below

    arg_parser = argparse.ArgumentParser(description="Travelport Data Automation")
    arg_parser.add_argument("--config", "-c", default=DEFAULT_CONFIG)
    arg_parser.add_argument(
        "--no-changes", action="store_true", help="Skip change detection"
    )
    arg_parser.add_argument("--output", "-o", default=None, help="Output Excel path")
    arg_parser.add_argument(
        "--auto", action="store_true", help="Extract data from live Smartpoint"
    )
    arg_parser.add_argument(
        "--limit", type=int, default=0, help="Limit commands (testing)"
    )
    arg_parser.add_argument(
        "--route", type=str, help="Filter commands to a specific route (e.g. DAC-MLE)"
    )
    arg_parser.add_argument(
        "-1d",
        "--one-direction",
        action="store_true",
        help="With --route, match only the exact route direction instead of both directions",
    )
    arg_parser.add_argument(
        "--airline",
        type=str,
        help="Filter to specific airline(s), comma-separated (e.g. BG or BG,BS)",
    )
    arg_parser.add_argument(
        "--only-fd",
        action="store_true",
        help="Extract only basic Fares (skip YQ/Currency FS command)",
    )
    arg_parser.add_argument(
        "--only-yq",
        action="store_true",
        help="Extract only YQ and Tax Breakdown (skip Fares)",
    )
    arg_parser.add_argument(
        "--only-currency",
        action="store_true",
        help="Extract only exchange rates (alias for --only-yq)",
    )
    arg_parser.add_argument(
        "--tax", action="store_true", help="Extract Tax (FTAX) data instead of fares"
    )
    arg_parser.add_argument(
        "--penalty",
        action="store_true",
        help="Extract Rule 16 penalties per fare basis in a separate run",
    )
    arg_parser.add_argument(
        "--include-ftax",
        action="store_true",
        help="Extract global FTAX data alongside the specific route fares",
    )
    arg_parser.add_argument(
        "--quick-paste",
        action="store_true",
        help="Interactive mode: paste terminal texts physically from clipboard",
    )
    arg_parser.add_argument(
        "--speed",
        type=str,
        choices=["fast", "safe"],
        default=None,
        help='Speed profile: "fast" (aggressive timings, ~50%% faster) or "safe" (conservative timings for slower machines)',
    )
    arg_parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable checkpoint/resume mode for long runs",
    )
    arg_parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Resume from a specific checkpoint file",
    )
    arg_parser.add_argument(
        "--compare-snapshot",
        type=str,
        default=None,
        help="Compare against a specific archived snapshot by date or date+time (e.g. 2026-04-08 or 2026-04-08_1805)",
    )
    arg_parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Disable data validation and sanity checks",
    )

    if prebuilt_args is not None:
        # Called from GUI with a ready-made Namespace - skip argparse entirely
        args = prebuilt_args
    elif len(sys.argv) == 1 and getattr(sys, "frozen", False):
        # Double-clicked exe with no flags - default to --auto
        args = arg_parser.parse_args(["--auto"])
    else:
        args = arg_parser.parse_args()

    use_tqdm = _should_use_tqdm(getattr(args, "_gui_mode", False))

    # QUICK PASTE MODE INTERCEPT
    if getattr(args, "quick_paste", False):
        # GUI mode: data was collected interactively before this function was
        # called and stored on args._quick_paste_data.  Skip all input() calls
        # so we never touch sys.stdin (which is None in the frozen exe).
        gui_qp = getattr(args, "_quick_paste_data", None)
        if gui_qp is not None:
            valid_commands = gui_qp["commands"]
            raw_texts = gui_qp["raw_texts"]
            raw_fs_texts = gui_qp["raw_fs_texts"]
        else:
            # CLI fallback - normal interactive flow
            from clipboard_util import clipboard_paste

            commands_input = input(
                "\n  Enter Commands (e.g., FDDACDOH/QR, FDDOHDAC/QR, FDDACMCT/WY): "
            ).strip()
            if not commands_input:
                print("  [!] Commands are required. Exiting.")
                sys.exit(1)

            raw_commands = [c.strip().upper() for c in commands_input.split(",")]

            valid_commands = []
            for c in raw_commands:
                parsed = parse_command(c)
                if parsed:
                    valid_commands.append(parsed)
                else:
                    print(f"  [!] Invalid command skipped: {c}")

            if not valid_commands:
                print("  [!] No valid commands provided. Exiting.")
                sys.exit(1)

            raw_texts = {}
            raw_fs_texts = {}

            for i, cmd in enumerate(valid_commands):
                airline = cmd["airline"]
                route = cmd["route"]
                print(f"\n" + "-" * 40)
                print(
                    f"  GATHERING DATA FOR {airline} {route} ({i+1}/{len(valid_commands)})"
                )
                print("-" * 40)

                input(
                    f"  [1/2] Please highlight and COPY the FD terminal output for {route}, then press ENTER..."
                )
                fd_text = clipboard_paste()
                if not fd_text or len(fd_text.strip()) < 10:
                    print(
                        "  [!] Clipboard seems empty or too short. Continuing anyway..."
                    )

                input(
                    f"  [2/2] Now, highlight and COPY the FS (Tax) terminal output for {route}, then press ENTER..."
                )
                fs_text = clipboard_paste()

                file_key = f"{airline}_{route}"
                raw_texts[file_key] = fd_text
                raw_fs_texts[file_key] = fs_text

        print("\n  Parsing manual data...")
        config = load_config(args.config)
        all_route_data = process_route_data(
            raw_texts,
            raw_fs_texts,
            config,
            enable_validation=False,
            show_progress=use_tqdm,
            stop_event=stop_event,
        )

        if not all_route_data:
            print("  [!] Failed to parse data. Ensure your copied text is valid.")
            if prebuilt_args is not None:
                return None  # GUI mode: don't sys.exit() in worker thread
            sys.exit(1)

        # Use first route for filename
        primary_route = f"{valid_commands[0]['airline']}_{valid_commands[0]['route'].replace('-', '')}"
        suffix = "etc" if len(valid_commands) > 1 else ""
        output_name = f"quick_report_{primary_route}_{suffix}_{datetime.now().strftime('%H%M')}.xlsx".replace(
            "__", "_"
        )
        output_path = os.path.join(REPORTS_DIR, output_name)

        result_path = generate_report(
            all_route_data, output_path, changes=None, config=config
        )

        # Record to Database
        record_to_database(all_route_data, config, mode="quick-paste")

        logger.info(f"\n  [OK] Successfully generated: {result_path}")
        try:
            os.startfile(result_path)
            logger.info("  Opening file automatically...")
        except Exception:
            pass
        if prebuilt_args is not None:
            return result_path  # GUI mode: return path instead of sys.exit()
        sys.exit(0)

    log_file = setup_logging()

    # Apply speed profile if specified (must be done before any automation imports)
    if args.speed:
        from constants import set_speed_profile

        set_speed_profile(args.speed)

    # Validate limit argument
    if args.limit:
        try:
            args.limit = validate_limit(args.limit)
        except ValidationError as e:
            logger.error(f"  {e}")
            sys.exit(1)

    logger.info("=" * 60)
    mode_label = "PENALTY" if args.penalty else ("TAX" if args.tax else "FARE")
    logger.info(f"  TRAVELPORT {mode_label} AUTOMATION TOOL")
    logger.info(f"  {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    logger.info("=" * 60)

    # Show active speed profile
    from constants import ACTIVE_SPEED_PROFILE

    if args.speed:
        logger.info(f"  Speed Profile: {ACTIVE_SPEED_PROFILE.upper()} (CLI override)")
    else:
        logger.info(f"  Speed Profile: {ACTIVE_SPEED_PROFILE.upper()} (default)")
    logger.info("")

    try:
        # [1/4] Config
        logger.info("[1/4] Loading configuration...")
        config = load_config(args.config)
        logger.info("  [OK] Config loaded")
    except ConfigurationError as e:
        logger.error(f"  Configuration error: {e}")
        logger.error("  Please check your config.json file and try again.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"  Unexpected error loading configuration: {e}")
        sys.exit(1)

    # Route Commands or Tax Airports
    commands = []
    tax_airports = {}
    if args.penalty and args.tax:
        logger.error("  Use either --tax or --penalty, not both together.")
        sys.exit(1)

    if args.tax:
        tax_airports = config.get("tax_airports", {})
        if not tax_airports:
            logger.error("  No 'tax_airports' defined in config.")
            sys.exit(1)

        # Filter tax_airports to only those appearing in configured routes
        commands_file = os.path.join(
            SCRIPT_DIR, config.get("commands_file", "commands.txt")
        )
        if os.path.exists(commands_file):
            route_airports = set()
            with open(commands_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FD") and "/" in line and len(line) >= 8:
                        route_airports.add(line[2:5].upper())
                        route_airports.add(line[5:8].upper())
            if route_airports:
                filtered = {
                    k: v for k, v in tax_airports.items()
                    if k.upper() in route_airports
                }
                if filtered:
                    skipped = len(tax_airports) - len(filtered)
                    tax_airports = filtered
                    if skipped > 0:
                        logger.info(
                            f"  Filtered to {len(tax_airports)} airports matching configured routes "
                            f"(skipped {skipped} unrelated)"
                        )

        if args.limit > 0:
            tax_airports = {
                k: v for i, (k, v) in enumerate(tax_airports.items()) if i < args.limit
            }
            logger.info(f"  [TESTING] Limited to first {args.limit} airports")
        logger.info(f"  {len(tax_airports)} tax airports loaded from config")
    else:
        import urllib.request as _ur
        from parser import load_commands_from_text

        commands_file = os.path.join(
            SCRIPT_DIR, config.get("commands_file", "commands.txt")
        )

        if os.path.exists(commands_file):
            # User's local commands.txt - may have been customised; always prefer it.
            logger.info(f"  Loading local commands from {commands_file}")
            commands = load_commands(commands_file)
        else:
            # First run - download the default command list from GitHub and save
            # it next to the exe so the user can edit it later.
            remote_url = config.get("commands_url", REMOTE_COMMANDS_URL)
            logger.info("  No commands.txt found - downloading defaults from remote...")
            try:
                req = _ur.Request(
                    remote_url, headers={"User-Agent": "TravelportAuto/1.0"}
                )
                with _ur.urlopen(req, timeout=10) as resp:
                    content = resp.read().decode("utf-8")
                with open(commands_file, "w", encoding="utf-8") as fh:
                    fh.write(content)
                commands = load_commands_from_text(content)
                logger.info(
                    f"  Downloaded {len(commands)} default commands -> saved to {commands_file}"
                )
                logger.info("  You can edit commands.txt to add or remove routes.")
            except Exception as exc:
                logger.error(f"  Could not download default commands: {exc}")
                logger.error(
                    f"  Create a commands.txt file in {SCRIPT_DIR} with your FD commands."
                )
                sys.exit(1)

        if not commands:
            logger.error(
                "  No valid route commands are configured. Please update commands.txt and try again."
            )
            sys.exit(1)

        # Apply filters
        if commands:
            if args.route:
                routes = [
                    r.strip().upper().replace("-", "") for r in args.route.split(",")
                ]
                valid_routes = [r for r in routes if len(r) == 6]

                commands = [
                    c
                    for c in commands
                    if any(
                        _command_matches_route(c, rt, one_direction=args.one_direction)
                        for rt in valid_routes
                    )
                ]
                direction_scope = (
                    "exact direction only" if args.one_direction else "both directions"
                )
                logger.info(
                    f"  [FILTER] Limited to route(s) {args.route} ({direction_scope}): {len(commands)} commands remaining"
                )
            if args.airline:
                airlines = [a.strip().upper() for a in args.airline.split(",")]
                commands = [
                    c
                    for c in commands
                    if any(f"/{al}" in c["command"].upper() for al in airlines)
                ]
                logger.info(
                    f"  [FILTER] Limited to airline(s) {args.airline}: {len(commands)} commands remaining"
                )
            if args.limit > 0:
                commands = commands[: args.limit]
                logger.info(f"  [TESTING] Limited to first {args.limit} commands")
            if not args.route and args.limit == 0:
                logger.info(f"  {len(commands)} route commands loaded")
    logger.info("")

    # Initialize checkpoint manager if enabled
    checkpoint_mgr = None
    enable_validation = not args.no_validation

    if args.checkpoint or args.resume:
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)

        if args.resume:
            # Resume from specific checkpoint
            checkpoint_mgr = CheckpointManager(
                CHECKPOINT_DIR,
                session_name=os.path.basename(args.resume)
                .replace("checkpoint_", "")
                .replace(".json", ""),
            )
            if checkpoint_mgr.load_checkpoint():
                logger.info(f"  [CHECKPOINT] Resuming from: {args.resume}")
                stats = checkpoint_mgr.get_progress_stats()
                logger.info(
                    f"  [CHECKPOINT] Previously completed: {stats['completed']} commands"
                )
            else:
                logger.warning(
                    f"  [CHECKPOINT] Could not load checkpoint: {args.resume}"
                )
                logger.info("  [CHECKPOINT] Starting fresh")
        else:
            # New checkpoint session
            checkpoint_mgr = CheckpointManager(CHECKPOINT_DIR)
            logger.info(f"  [CHECKPOINT] Checkpoint mode enabled")
            logger.info(f"  [CHECKPOINT] Session: {checkpoint_mgr.session_name}")

    def _stop_run(message: str, partial_data: dict | None = None):
        logger.info(message)
        if checkpoint_mgr:
            checkpoint_mgr.save_checkpoint()
            logger.info(
                f"  [CHECKPOINT] Final checkpoint saved: {len(checkpoint_mgr.completed_commands)} completed"
            )

        # Generate partial report with whatever data was collected
        if partial_data:
            try:
                timestamp_full = datetime.now().strftime("%Y-%m-%d_%H%M")
                if getattr(args, "tax", False):
                    partial_path = os.path.join(
                        REPORTS_DIR, f"tax_report_{timestamp_full}_partial.xlsx"
                    )
                    from tax_report import generate_tax_report

                    result = generate_tax_report(partial_data, partial_path, None, config)
                else:
                    partial_path = os.path.join(
                        REPORTS_DIR, f"fare_report_{timestamp_full}_partial.xlsx"
                    )
                    result = generate_report(
                        partial_data, partial_path, None, config,
                        only_currency=getattr(args, "only_currency", False),
                    )
                logger.info(f"  [PARTIAL] Partial report saved: {result}")
                return result
            except Exception as exc:
                logger.warning(f"  [PARTIAL] Could not generate partial report: {exc}")

        return None

    # [2/4] Extraction
    failed_commands = []

    # PENALTY MODE EXTRACTION
    if args.penalty:
        penalty_records = []

        if not args.auto:
            logger.error("  Penalty mode currently requires --auto.")
            sys.exit(1)

        logger.info("[2/3] AUTO MODE: Connecting to Smartpoint UI for penalties...")
        if not commands:
            logger.error("  No commands found to auto-run.")
            sys.exit(1)

        from smartpoint_automation import SmartpointAutomation, StopRequested

        automation = SmartpointAutomation(stop_event=_stop)
        try:
            if not automation.connect():
                logger.error("  Please ensure Smartpoint is open and the title matches.")
                sys.exit(1)

            username, password, pcc = CredentialManager.get_credentials()
            if username and password:
                logger.info("  Credentials loaded from environment")
                if _env_truthy("SMARTPOINT_SKIP_AUTO_LOGIN"):
                    logger.info(
                        "  Automatic login skipped because SMARTPOINT_SKIP_AUTO_LOGIN is enabled."
                    )
                else:
                    try:
                        if not automation.login(username, password, pcc):
                            logger.error(
                                "  Automatic login did not complete. Please sign in manually and try again."
                            )
                            sys.exit(1)
                    except Exception as e:
                        logger.error(f"  Login failed: {e}")
                        sys.exit(1)
            else:
                logger.info("  No credentials found - continuing without login")

            automation.refresh_terminal()
            os.makedirs(RAW_PENALTY_DIR, exist_ok=True)

            if use_tqdm:
                command_iter = tqdm(
                    commands, desc="Extracting penalties", unit="cmd", file=_tqdm_stream()
                )
            else:
                command_iter = commands
                logger.info(f"  Executing {len(commands)} commands...")

            for i, cmd in enumerate(command_iter, 1):
                if _stop and _stop.is_set():
                    logger.info("  [STOP] Stop requested - finishing after this point.")
                    break
                cmd_str = cmd["command"]
                if not use_tqdm:
                    logger.info(f"  [{i}/{len(commands)}] {cmd_str}")

                command_penalties = automation.run_penalty_command(cmd_str)
                if not command_penalties:
                    failed_commands.append(cmd_str)
                    logger.warning(f"    [!] No penalty popups captured for {cmd_str}")
                    continue

                file_key = generate_file_key(cmd)
                for penalty_capture in command_penalties:
                    fare_basis = penalty_capture.get("fare_basis")
                    journey_type = "RT" if penalty_capture.get("is_rt") else "OW"
                    parsed_penalty = parse_penalty_text(
                        penalty_capture.get("raw_penalty_text", ""),
                        airline=penalty_capture.get("airline", cmd.get("airline")),
                        route=cmd.get("route"),
                        fare_basis=fare_basis,
                        rbd=penalty_capture.get("rbd"),
                        fare_amount=penalty_capture.get("fare"),
                        journey_type=journey_type,
                    )

                    if not parsed_penalty.get("rules"):
                        logger.warning(
                            f"    [!] No structured penalty rules parsed for {fare_basis}"
                        )

                    penalty_records.append(parsed_penalty)

                    backup_name = f"{file_key}_{journey_type}_{_safe_filename(fare_basis)}_penalty.txt"
                    backup_path = os.path.join(RAW_PENALTY_DIR, backup_name)
                    try:
                        with open(backup_path, "w", encoding="utf-8") as f:
                            f.write(parsed_penalty.get("raw_penalty_text", ""))
                    except Exception as e:
                        logger.warning(f"    Could not save penalty backup: {e}")

            automation.show_completion_signal()
            logger.info("")
        except StopRequested:
            return _stop_run("  [STOP] Stop requested - penalty extraction stopped.")

        if _stop and _stop.is_set():
            return _stop_run("  [STOP] Stop requested - skipping penalty report generation.")

        logger.info("[3/3] Generating penalty report...")
        timestamp_full = datetime.now().strftime("%Y-%m-%d_%H%M")
        output_path = (
            args.output
            if args.output
            else os.path.join(REPORTS_DIR, f"penalty_report_{timestamp_full}.xlsx")
        )
        result_path = generate_penalty_report(penalty_records, output_path)

        elapsed = _time.time() - start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        logger.info("")
        logger.info("=" * 60)
        logger.info("  RUN SUMMARY")
        logger.info("-" * 60)
        logger.info(f"  Report:   {result_path}")
        logger.info(f"  Items:    {len(penalty_records)} fare basis records parsed")
        if failed_commands:
            logger.info(
                f"  Failed:   {len(failed_commands)} ({', '.join(failed_commands)})"
            )
        else:
            logger.info("  Failed:   None")
        logger.info(f"  Changes:  Skipped")
        logger.info(f"  Duration: {minutes}m {seconds}s")
        logger.info(f"  Log:      {log_file}")
        logger.info("=" * 60)

        return result_path

    # TAX MODE EXTRACTION
    if args.tax:
        tax_data = {}  # airport_code -> {'taxes': [ detail_data... ]}

        if args.auto:
            logger.info("[2/4] AUTO MODE: Connecting to Smartpoint UI for FTAX...")
            from smartpoint_automation import SmartpointAutomation, StopRequested

            automation = SmartpointAutomation(stop_event=_stop)
            try:
                if not automation.connect():
                    logger.error("  Please ensure Smartpoint is open.")
                    sys.exit(1)

                automation.refresh_terminal()
                from tax_parser import parse_ftax_list, parse_ftax_detail

                # Use tqdm for progress if available
                airport_items = tax_airports.items()
                if use_tqdm:
                    airport_items = tqdm(
                        list(airport_items),
                        desc="Extracting tax data",
                        unit="airport",
                        file=_tqdm_stream(),
                    )
                else:
                    airport_items = list(airport_items)

                for index, (airport_code, airport_info) in enumerate(airport_items, 1):
                    if _stop and _stop.is_set():
                        logger.info("  [STOP] Stop requested - finishing after this point.")
                        break
                    country_code = airport_info["country"]

                    # Only log if not using tqdm
                    if not use_tqdm:
                        logger.info(
                            f"  [{index}/{len(tax_airports)}] Airport: {airport_code} ({country_code})"
                        )

                    # Get tax types
                    list_cmd = f"FTAX-{country_code}"
                    list_text = automation.run_command(list_cmd, max_pages=1)

                    # Debug backup
                    os.makedirs(RAW_DATA_DIR, exist_ok=True)
                    backup_path = os.path.join(RAW_DATA_DIR, f"{list_cmd}.txt")
                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write(list_text)

                    tax_types = parse_ftax_list(list_text)
                    logger.info(
                        f"    Found {len(tax_types)} tax types: {', '.join(t['code'] for t in tax_types)}"
                    )

                    if not tax_types:
                        logger.warning(
                            f"    [DEBUG] Raw list text ({len(list_text)} chars): {list_text[:300]}"
                        )

                    airport_tax_details = []
                    for idx, t in enumerate(tax_types, 1):
                        detail_text = automation.run_ftax_command(
                            country_code, t["code"], tax_index=idx
                        )

                        # Save raw detail text for debugging
                        detail_backup = os.path.join(
                            RAW_DATA_DIR, f"FTAX-{country_code}_{t['code']}.txt"
                        )
                        with open(detail_backup, "w", encoding="utf-8") as f:
                            f.write(detail_text)

                        if not detail_text or len(detail_text.strip()) < 20:
                            failed_commands.append(f"{country_code}/{t['code']}")
                            logger.warning(f"    Failed to extract details for {t['code']}")
                            continue

                        logger.debug(
                            f"      [DEBUG] Raw detail text first 200 chars: {detail_text[:200]}"
                        )

                        detail_data = parse_ftax_detail(detail_text, t["code"], t["name"])
                        airport_tax_details.append(detail_data)
                        logger.info(
                            f"      {t['code']} -> {len(detail_data['sections'])} sections extracted."
                        )

                        if not detail_data["sections"]:
                            logger.warning(
                                f"      [DEBUG] 0 sections! Full text ({len(detail_text)} chars): {detail_text[:500]}"
                            )

                        # Return to tax list for next tax type
                        if idx < len(tax_types):
                            automation.return_to_tax_list(country_code)

                    tax_data[airport_code] = {"taxes": airport_tax_details}

                automation.show_completion_signal()
            except StopRequested:
                return _stop_run("  [STOP] Stop requested - tax extraction stopped.", partial_data=tax_data if tax_data else None)
        else:
            logger.error("  Manual loading of taxes not implemented. Use --auto.")
            sys.exit(1)

        all_route_data = tax_data  # Alias for reporting
        if _stop and _stop.is_set():
            return _stop_run("  [STOP] Stop requested - skipping tax report generation.", partial_data=all_route_data)
        logger.info("")

    # FARE MODE EXTRACTION
    else:
        raw_texts = {}
        raw_fs_texts = {}
        if args.auto:
            logger.info("[2/4] AUTO MODE: Connecting to Smartpoint UI...")
            if not commands:
                logger.error("  No commands found to auto-run.")
                sys.exit(1)

            from smartpoint_automation import SmartpointAutomation

            automation = SmartpointAutomation(stop_event=_stop)

            if not automation.connect():
                logger.error(
                    "  Please ensure Smartpoint is open and the title matches."
                )
                sys.exit(1)

            # Try to get credentials from environment
            username, password, pcc = CredentialManager.get_credentials()
            if username and password:
                logger.info("  Credentials loaded from environment")
                if _env_truthy("SMARTPOINT_SKIP_AUTO_LOGIN"):
                    logger.info(
                        "  Automatic login skipped because SMARTPOINT_SKIP_AUTO_LOGIN is enabled."
                    )
                else:
                    try:
                        if not automation.login(username, password, pcc):
                            logger.error(
                                "  Automatic login did not complete. Please sign in manually and try again."
                            )
                            sys.exit(1)
                    except Exception as e:
                        logger.error(f"  Login failed: {e}")
                        sys.exit(1)
            else:
                logger.info("  No credentials found - continuing without login")
                logger.info("  To enable automatic login, set environment variables:")
                logger.info(
                    "    SMARTPOINT_USERNAME, SMARTPOINT_PASSWORD, SMARTPOINT_PCC"
                )

            logger.debug("  Initializing terminal state...")
            automation.refresh_terminal()

            # Filter commands if resuming from checkpoint
            if checkpoint_mgr:
                original_count = len(commands)
                commands = checkpoint_mgr.get_remaining_commands(commands)
                skipped = original_count - len(commands)
                if skipped > 0:
                    logger.info(
                        f"  [CHECKPOINT] Skipping {skipped} already completed commands"
                    )
                    logger.info(f"  [CHECKPOINT] {len(commands)} commands remaining")

            MAX_RETRIES = MAX_RETRIES_COMMAND

            # Use tqdm for progress if available
            if use_tqdm and not checkpoint_mgr:
                # Use simple progress bar
                command_iter = tqdm(
                    commands,
                    desc="Executing commands",
                    unit="cmd",
                    file=_tqdm_stream(),
                )
            elif use_tqdm and checkpoint_mgr:
                # Use progress bar with initial progress
                command_iter = tqdm(
                    commands,
                    desc="Executing commands",
                    unit="cmd",
                    initial=len(checkpoint_mgr.completed_commands),
                    total=len(checkpoint_mgr.completed_commands) + len(commands),
                    file=_tqdm_stream(),
                )
            else:
                # No progress bar
                command_iter = commands
                logger.info(f"  Executing {len(commands)} commands...")

            commands_attempted = 0
            for i, cmd in enumerate(command_iter, 1):
                if _stop and _stop.is_set():
                    logger.info("  [STOP] Stop requested - finishing after this point.")
                    break
                cmd_str = cmd["command"]

                # Skip if already completed (double-check in case of concurrent runs)
                if checkpoint_mgr and checkpoint_mgr.is_completed(cmd_str):
                    continue

                commands_attempted += 1

                # Only log if not using tqdm
                if not use_tqdm:
                    logger.info(f"  [{i}/{len(commands)}] {cmd_str}")

                terminal_text = ""
                file_key = generate_file_key(cmd)

                # -- FD EXTRACTION --
                if not args.only_yq and not args.only_currency:
                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            terminal_text = automation.run_command(cmd["command"])
                            if terminal_text and len(terminal_text.strip()) > 50:
                                break
                            logger.warning(
                                f"    Attempt {attempt}: insufficient data ({len(terminal_text)} chars)"
                            )
                        except Exception as e:
                            logger.warning(f"    Attempt {attempt} failed: {e}")

                        if attempt < MAX_RETRIES:
                            delay = constants.RETRY_DELAY
                            logger.info(f"    Retrying in {delay}s...")
                            _time.sleep(delay)
                            automation.refresh_terminal()

                    if terminal_text and len(terminal_text.strip()) > 50:
                        raw_texts[file_key] = terminal_text
                        logger.info(
                            f"    [OK] Fare data captured ({len(terminal_text)} chars)"
                        )

                        backup_path = os.path.join(RAW_DATA_DIR, f"{file_key}.txt")
                        os.makedirs(os.path.dirname(backup_path) or ".", exist_ok=True)
                        try:
                            with open(backup_path, "w", encoding="utf-8") as f:
                                f.write(terminal_text)
                            logger.debug(f"    Backup saved: {backup_path}")
                        except Exception as e:
                            logger.warning(f"    Could not save backup: {e}")
                    else:
                        failed_commands.append(cmd["command"])
                        logger.error(
                            f"    [FAILED] FAILED after {MAX_RETRIES} attempts: {cmd['command']}"
                        )
                        logger.error(
                            f"    Final data length: {len(terminal_text) if terminal_text else 0} chars"
                        )
                        logger.error(f"    This command will be skipped in the report")

                        # Mark as failed in checkpoint
                        if checkpoint_mgr:
                            checkpoint_mgr.mark_failed(cmd_str)
                else:
                    logger.info(
                        "    [SKIP] Skipping FD extraction (--only-yq/--only-currency)"
                    )

                # -- FS EXTRACTION --
                if _should_run_fs_extraction(args, terminal_text):
                    base_cmd = cmd["command"].strip()
                    if (
                        len(base_cmd) >= 11
                        and base_cmd.startswith("FD")
                        and "/" in base_cmd
                        and len(base_cmd.split("/")[0]) == 8
                    ):
                        src = base_cmd[2:5]
                        dst = base_cmd[5:8]
                        airline = base_cmd.split("/")[1][:2]

                        fs_expanded = ""
                        fs_date_offset = FS_DATE_OFFSET_START
                        max_fs_date_steps = MAX_FS_DATE_STEPS

                        while fs_date_offset <= max_fs_date_steps:
                            date_str = (
                                (datetime.now() + timedelta(days=fs_date_offset))
                                .strftime("%d%b")
                                .upper()
                            )
                            logger.info(
                                f"    [FS Checkout] Extracting tax details for {src}-{dst} on {date_str}..."
                            )

                            fs_result = automation.run_fs_command(
                                src, dst, date_str, airline
                            )

                            # Freshness check: poll until the terminal shows the
                            # expected date, rather than sleeping a fixed 1.5s.
                            if date_str.upper() not in fs_result.upper():
                                logger.warning(
                                    f"      [!] Screen hasn't updated to {date_str} yet, polling..."
                                )
                                fs_result = automation._wait_for_response(
                                    fs_result,
                                    timeout=constants.RETRY_DELAY * 2,
                                    min_wait=0.2,
                                    poll_interval=0.15,
                                    stability_checks=1,
                                )

                            # Log raw results for diagnostics
                            with open(os.path.join(LOG_DIR, "fs_debug.log"), "a", encoding="utf-8") as f:
                                f.write(
                                    f"\n--- {date_str} {src}-{dst} /{airline} ---\n"
                                )
                                f.write(fs_result)
                                f.write("\n" + "=" * 50 + "\n")

                            current_fs_page = fs_result
                            target_option_index = None
                            target_option_number = None
                            fs_page_number = 1
                            max_fs_pages = 5
                            rechecked_current_fs_page = False

                            while True:
                                (
                                    target_option_index,
                                    target_option_number,
                                    option_count,
                                ) = _find_pure_airline_option_in_fs_page(
                                    current_fs_page, airline
                                )

                                logger.info(
                                    f"      [DEBUG] Parsing {option_count} options for {airline} on FS page {fs_page_number}..."
                                )

                                if target_option_index is not None:
                                    logger.info(
                                        f"      [OK] Pure {airline} itinerary found in Option {target_option_number} on FS page {fs_page_number}."
                                    )
                                    fs_result = current_fs_page
                                    break

                                if not rechecked_current_fs_page:
                                    settled_fs_page = (
                                        automation._wait_for_stable_screen(
                                            max_polls=4, interval=0.25
                                        )
                                    )
                                    rechecked_current_fs_page = True

                                    if _should_recheck_same_fs_page(
                                        current_fs_page, settled_fs_page, airline
                                    ):
                                        logger.info(
                                            f"      [DEBUG] Rechecking FS page {fs_page_number} for {airline} after additional settle..."
                                        )
                                        current_fs_page = settled_fs_page
                                        continue

                                if option_count == 0:
                                    if current_fs_page and any(
                                        kw in current_fs_page.upper()
                                        for kw in [
                                            "NO FARES FOUND",
                                            "CHECK ACTION CODE",
                                            "INVALID",
                                        ]
                                    ):
                                        logger.warning(
                                            f"      [!] No valid FS results for {date_str}. Trying next date..."
                                        )
                                        break

                                    logger.warning(
                                        f"      [!] Waiting for terminal content (offset {fs_date_offset})..."
                                    )
                                    break

                                if (
                                    fs_page_number >= max_fs_pages
                                    or automation._has_end_signal(current_fs_page)
                                ):
                                    logger.warning(
                                        f"      [!] No pure {airline} options found on {date_str} after {fs_page_number} FS page(s)."
                                    )
                                    break

                                logger.info(
                                    f"      [DEBUG] No pure {airline} option on FS page {fs_page_number}; checking next FS page on the same date..."
                                )

                                if automation.click_more_prompt_link(current_fs_page):
                                    next_fs_page = automation._wait_for_response(
                                        current_fs_page,
                                        timeout=constants.COMMAND_WAIT_MEDIUM + 0.5,
                                        min_wait=0.0,
                                        stability_checks=1,
                                    )
                                    next_fs_page = automation._wait_for_stable_screen(
                                        max_polls=3, interval=0.2
                                    )
                                else:
                                    logger.warning(
                                        f"      [!] More Flights was not clickable on {date_str}; staying off MD and trying next date."
                                    )
                                    break

                                if (
                                    not next_fs_page
                                    or automation._has_invalid(next_fs_page)
                                    or next_fs_page.strip() == current_fs_page.strip()
                                ):
                                    logger.warning(
                                        f"      [!] Could not advance FS pagination on {date_str}; trying next date."
                                    )
                                    break

                                current_fs_page = next_fs_page
                                fs_page_number += 1
                                rechecked_current_fs_page = False

                            if target_option_index is None:
                                fs_date_offset += FS_DATE_STEP
                                _time.sleep(0.5)
                                continue

                            # Click the D button using text-to-coordinate mapping
                            fs_expanded = automation.click_d_button(
                                target_option_index, fs_result
                            )

                            # Validate: accept both classic fare/tax lines and airline-
                            # specific detail screens that still parse into usable tax data.
                            if fs_expanded and looks_like_fs_tax_breakdown(fs_expanded):
                                logger.info(
                                    f"      [OK] Tax breakdown extracted via D-click"
                                )
                            else:
                                logger.warning(
                                    f"      [!] D-click did not return expected tax data."
                                )
                                fs_expanded = ""
                            break  # Exit the date-stepping while loop

                        if fs_expanded and len(fs_expanded.strip()) > 50:
                            raw_fs_texts[file_key] = fs_expanded
                            fs_backup_path = os.path.join(
                                RAW_DATA_DIR, f"{file_key}_FS.txt"
                            )
                            try:
                                with open(fs_backup_path, "w", encoding="utf-8") as f:
                                    f.write(fs_expanded)
                            except Exception:
                                pass
                else:
                    logger.info(
                        "    [SKIP] Skipping FS extraction because FD returned no fare data."
                    )

                # Mark command as completed and save checkpoint
                if checkpoint_mgr and cmd_str not in failed_commands:
                    checkpoint_mgr.mark_completed(cmd_str)
                    # Save checkpoint every 10 commands to avoid excessive I/O
                    if len(checkpoint_mgr.completed_commands) % 10 == 0:
                        checkpoint_mgr.save_checkpoint()

            # Final checkpoint save
            if checkpoint_mgr:
                checkpoint_mgr.save_checkpoint()
                logger.info(
                    f"  [CHECKPOINT] Final checkpoint saved: {len(checkpoint_mgr.completed_commands)} completed"
                )

            # -- MERGED FTAX EXTRACTION --
            ftax_data = None
            if getattr(args, "include_ftax", False):
                logger.info(
                    "\n  --include-ftax: Extracting FTAX data for involved airports..."
                )
                unique_airports = set()
                for c in commands:
                    if "-" in c.get("route", ""):
                        orig, dest = c["route"].split("-")
                        unique_airports.add(orig)
                        unique_airports.add(dest)

                tax_airports_config = config.get("tax_airports", {})
                target_airports = {}
                for a in unique_airports:
                    if a in tax_airports_config:
                        target_airports[a] = tax_airports_config[a]
                    else:
                        logger.warning(
                            f"    Skipping FTAX for {a}: missing in config.json 'tax_airports'"
                        )

                if target_airports:
                    from tax_parser import parse_ftax_list, parse_ftax_detail

                    ftax_data = {}

                    logger.info(
                        f"  Found {len(target_airports)} airports for FTAX profiling: {', '.join(target_airports.keys())}"
                    )

                    for index, (acode, ainfo) in enumerate(target_airports.items(), 1):
                        ccode = ainfo["country"]
                        logger.info(
                            f"  [{index}/{len(target_airports)}] Airport: {acode} ({ccode})"
                        )

                        list_cmd = f"FTAX-{ccode}"
                        list_text = automation.run_command(list_cmd, max_pages=1)
                        tax_types = parse_ftax_list(list_text)
                        logger.info(
                            f"    Found {len(tax_types)} tax types: {', '.join(t['code'] for t in tax_types)}"
                        )

                        airport_tax_details = []
                        for idx, t in enumerate(tax_types, 1):
                            detail_text = automation.run_ftax_command(
                                ccode, t["code"], tax_index=idx
                            )
                            if not detail_text or len(detail_text.strip()) < 20:
                                logger.warning(
                                    f"    Failed to extract details for {t['code']}"
                                )
                                continue

                            detail_data = parse_ftax_detail(
                                detail_text, t["code"], t["name"]
                            )
                            airport_tax_details.append(detail_data)
                            logger.info(
                                f"      {t['code']} -> {len(detail_data['sections'])} sections extracted."
                            )

                            if idx < len(tax_types):
                                automation.return_to_tax_list(ccode)

                        ftax_data[acode] = {"taxes": airport_tax_details}

            automation.show_completion_signal()

            # Show execution summary
            total_commands = len(commands)
            successful_commands = commands_attempted - len(failed_commands)
            skipped_commands = total_commands - commands_attempted
            logger.info("")
            logger.info("=" * 60)
            logger.info("  EXECUTION SUMMARY")
            logger.info("=" * 60)
            logger.info(f"  Total commands: {total_commands}")
            logger.info(f"  Attempted: {commands_attempted}")
            logger.info(f"  Successful: {successful_commands}")
            logger.info(f"  Failed: {len(failed_commands)}")
            if skipped_commands > 0:
                logger.info(f"  Skipped (stopped early): {skipped_commands}")
            if failed_commands:
                logger.warning("  Failed commands:")
                for fc in failed_commands:
                    logger.warning(f"    - {fc}")
                logger.warning("  Note: Failed commands will not appear in the report")
            elif commands_attempted == total_commands:
                logger.info("  [OK] All commands completed successfully!")
            logger.info("=" * 60)

            if _stop and _stop.is_set():
                return _stop_run(
                    "  [STOP] Stop requested - skipping parsing and report generation."
                )

        else:
            logger.info("[2/4] MANUAL MODE: Loading raw GDS data from disk...")
            raw_texts, raw_fs_texts = load_raw_data(RAW_DATA_DIR)
            if not raw_texts:
                show_usage()
                sys.exit(1)
            logger.info(
                f"  Loaded {len(raw_texts)} fare file(s) and {len(raw_fs_texts)} tax detail file(s)"
            )
        logger.info("")

        # Parse Fares
        logger.info("[3/4] Parsing fare and tax data...")
        all_route_data = process_route_data(
            raw_texts,
            raw_fs_texts,
            config,
            enable_validation,
            show_progress=use_tqdm,
            stop_event=_stop,
        )
        if _stop and _stop.is_set():
            return _stop_run("  [STOP] Stop requested - parsing stopped.", partial_data=all_route_data)
        if not all_route_data:
            logger.error("  No fare data could be parsed.")
            sys.exit(1)
        logger.info("")

    # [3.5] Change detection (for both modes)
    changes = None
    if _stop and _stop.is_set():
        return _stop_run("  [STOP] Stop requested - skipping change detection.", partial_data=all_route_data)
    if not args.no_changes:
        logger.info("[3.5] Detecting changes...")
        archive_subdir = "tax" if args.tax else "fare"
        archive_path = os.path.join(ARCHIVE_DIR, archive_subdir)
        os.makedirs(archive_path, exist_ok=True)

        latest_snapshot_data = load_latest_snapshot(archive_path)
        previous_data = latest_snapshot_data
        comparison_snapshot_id = None
        using_db_snapshot = False

        # Try to load previous snapshot from DB first
        if DatabaseManager and _resolve_database_url(config):
            try:
                _db_check = DatabaseManager(_resolve_database_url(config))
                if _db_check.connect():
                    _run_mode_for_check = "tax-mode" if args.tax else None
                    prev_run_id = _db_check.get_previous_run_id(
                        run_mode=_run_mode_for_check
                    )
                    if prev_run_id > 0:
                        if args.tax:
                            db_snapshot = _db_check.load_tax_snapshot(prev_run_id)
                        else:
                            db_snapshot = _db_check.load_fare_snapshot(prev_run_id)
                        if db_snapshot:
                            previous_data = db_snapshot
                            using_db_snapshot = True
                            logger.info(f"  Using DB snapshot from run {prev_run_id}")
                    _db_check.close()
            except Exception as _db_snap_err:
                logger.debug("  DB snapshot load failed: %s", _db_snap_err)

        if not previous_data:
            # Fall back to JSON archive
            previous_data = latest_snapshot_data
            if previous_data:
                logger.info("  Using JSON archive snapshot (no DB history yet)")

        if args.compare_snapshot:
            try:
                previous_data, comparison_snapshot_id = load_snapshot_by_reference(
                    archive_path, args.compare_snapshot
                )
            except ValueError as e:
                logger.error(f"  {e}")
                sys.exit(1)

            if previous_data is None:
                logger.error(
                    f"  No archived snapshot found for '{args.compare_snapshot}'."
                )
                sys.exit(1)

            logger.info(f"  Comparing against snapshot: {comparison_snapshot_id}")

        if previous_data:
            if args.tax:
                changes = detect_tax_changes(all_route_data, previous_data)
                if changes and any(changes.values()):
                    logger.info(format_tax_change_summary(changes))
                else:
                    logger.info("  No changes from previous tax data.")
            else:
                changes = detect_changes(all_route_data, previous_data)
                if changes and any(changes.values()):
                    logger.info(format_change_summary(changes))
                else:
                    logger.info("  No changes from previous data.")
        else:
            logger.info("  No previous data found. First run - baseline saved.")

        # Only write JSON snapshot when NOT using DB as primary source
        if not using_db_snapshot:
            if snapshot_has_changed(all_route_data, latest_snapshot_data):
                ts = datetime.now().strftime("%Y-%m-%d_%H%M")
                save_snapshot(all_route_data, archive_path, date_str=ts)
            else:
                logger.info("  Snapshot unchanged; skipping archive write.")
        else:
            logger.info("  DB is primary snapshot source; skipping JSON archive write.")
        logger.info("")

    # -- FZS EXTRACTION (Exchange Rates) --
    fzs_data = {}
    if args.auto and not args.tax and not (_stop and _stop.is_set()):
        # Collect unique currency pairs from parsed data
        currency_pairs = set()
        local_currency = config.get("local_currency", "BDT")
        for route_key, route_info in all_route_data.items():
            if isinstance(route_info, dict):
                fs_taxes = route_info.get("fs_taxes", {})
                base_cur = fs_taxes.get("base_currency")
                if base_cur and base_cur != local_currency:
                    currency_pairs.add((base_cur, local_currency))

        if currency_pairs:
            logger.info(f"  [FZS] Extracting exchange rates for {len(currency_pairs)} currency pair(s)...")
            from fzs_parser import parse_fzs_output

            try:
                for from_cur, to_cur in sorted(currency_pairs):
                    if _stop and _stop.is_set():
                        break
                    fzs_text = automation.run_fzs_command(from_cur, to_cur)
                    parsed = parse_fzs_output(fzs_text, from_cur, to_cur)
                    fzs_data[f"{from_cur}-{to_cur}"] = parsed
                    if parsed["rate"] > 0:
                        logger.info(f"    [OK] {from_cur} -> {to_cur}: {parsed['rate']}")
                    else:
                        logger.warning(f"    [!] Could not parse rate for {from_cur} -> {to_cur}")
            except Exception as exc:
                logger.warning(f"  [FZS] FZS extraction failed: {exc}")

    # [4/4] Generate Report
    if _stop and _stop.is_set():
        return _stop_run("  [STOP] Stop requested - skipping report generation.", partial_data=all_route_data)
    logger.info("[4/4] Generating Excel report...")

    if args.output:
        output_path = args.output
    else:
        if args.tax:
            timestamp_full = datetime.now().strftime("%Y-%m-%d_%H%M")
            output_name = f"tax_report_{timestamp_full}.xlsx"
            output_path = os.path.join(REPORTS_DIR, output_name)
        else:
            timestamp_full = datetime.now().strftime("%Y-%m-%d_%H%M")
            output_filename = config.get(
                "excel_output_filename", "fare_report_{date}.xlsx"
            )
            output_filename = output_filename.replace("{date}", timestamp_full)
            output_path = os.path.join(REPORTS_DIR, output_filename)

    if args.tax:
        from tax_report import generate_tax_report

        result_path = generate_tax_report(all_route_data, output_path, changes, config)
    else:
        # Pass only_currency flag down to specifically skip the main sheets if needed
        result_path = generate_report(
            all_route_data,
            output_path,
            changes,
            config,
            only_currency=args.only_currency,
        )

        # Merge FTAX if enabled
        if (
            getattr(args, "include_ftax", False)
            and "ftax_data" in locals()
            and ftax_data
        ):
            logger.info("  Appending FTAX sheets to Fare Report...")
            import openpyxl
            from tax_report import _build_summary_sheet, _build_details_sheet

            try:
                wb = openpyxl.load_workbook(result_path)
                ws_summary = wb.create_sheet("FTAX Summary")
                ws_details = wb.create_sheet("FTAX Detailed Rates")
                _build_summary_sheet(ws_summary, ftax_data, config)
                _build_details_sheet(ws_details, ftax_data, config)
                wb.save(result_path)
                logger.info(f"  [OK] Attached FTAX to {result_path}")
            except Exception as e:
                logger.error(f"  Failed to append FTAX sheets: {e}")

        # Append FZS Exchange Rates sheet
        if fzs_data:
            logger.info("  Appending FZS Exchange Rates sheet...")
            import openpyxl
            from excel_report import _write_fzs_sheet

            try:
                wb = openpyxl.load_workbook(result_path)
                ws_fzs = wb.create_sheet("Exchange Rates (FZS)")
                _write_fzs_sheet(ws_fzs, fzs_data)
                wb.save(result_path)
                logger.info(f"  [OK] Attached FZS rates to {result_path}")
            except Exception as e:
                logger.error(f"  Failed to append FZS sheet: {e}")

    # [DB] Optional persistence - keep current file/report flow unchanged
    _run_mode = "auto" if not args.tax else "tax-mode"
    _db_run_id = record_to_database(all_route_data, config, mode=_run_mode)

    # [BQ] Push to BigQuery if configured
    if _bq_pusher and _bq_pusher.is_configured():
        _run_time = datetime.now()
        try:
            if args.tax:
                _bq_pusher.push_tax_snapshot(all_route_data, _db_run_id, _run_time)
            else:
                _bq_pusher.push_fare_snapshot(all_route_data, _db_run_id, _run_time)
                if changes:
                    _bq_pusher.push_change_events(changes, _run_time)
        except Exception as _bq_err:
            logger.warning("  [BQ] Push failed (non-fatal): %s", _bq_err)

    # Run Summary
    elapsed = _time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    total_changes = sum(len(rc) for rc in changes.values()) if changes else 0
    change_counts = {}
    if changes:
        for rc in changes.values():
            for ci in rc.values():
                # Tax changes are lists of change dicts; fare changes are plain dicts
                items = ci if isinstance(ci, list) else [ci]
                for item in items:
                    if isinstance(item, dict):
                        ct = item.get("type", "unknown")
                        change_counts[ct] = change_counts.get(ct, 0) + 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("  RUN SUMMARY")
    logger.info("-" * 60)
    logger.info(f"  Report:   {result_path}")
    logger.info(
        f"  Items:    {len(all_route_data)} {'airports' if args.tax else 'routes'} parsed"
    )
    if failed_commands:
        logger.info(
            f"  Failed:   {len(failed_commands)} ({', '.join(failed_commands)})"
        )
    if total_changes:
        parts = [f"{v} {k}" for k, v in sorted(change_counts.items())]
        logger.info(f"  Changes:  {total_changes} ({', '.join(parts)})")
    else:
        logger.info("  Changes:  None")
    logger.info(f"  Duration: {minutes}m {seconds}s")
    logger.info(f"  Log:      {log_file}")
    logger.info("=" * 60)

    return result_path


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        import traceback

        logger.error(
            "Run interrupted by KeyboardInterrupt. Smartpoint may not have had focus and Ctrl+C may have reached the console."
        )
        traceback.print_exc()
        sys.exit(130)
    except Exception as e:
        import traceback

        logger.error(f"Fatal error occurred:\n{traceback.format_exc()}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if getattr(sys, "frozen", False):
            input("\nPress Enter to exit...")
