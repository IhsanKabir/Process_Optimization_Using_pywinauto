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
import sys
import time as _time
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
    parse_command
)
from tax_breakdown_parser import parse_fs_tax_breakdown
from excel_report import generate_report
from change_detector import (
    detect_changes,
    detect_tax_changes,
    format_tax_change_summary,
    save_snapshot,
    load_latest_snapshot,
    format_change_summary
)
from exceptions import ConfigurationError, ValidationError
from validators import (
    validate_config,
    validate_limit,
    sanitize_command,
    validate_parsed_fares,
    validate_currency_code
)
from credential_manager import CredentialManager
from checkpoint_manager import CheckpointManager
from constants import MAX_RETRIES_COMMAND, MAX_FS_DATE_STEPS, FS_DATE_OFFSET_START

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, skip

logger = logging.getLogger('travelport')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, 'config.json')
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, 'data', 'raw')
REPORTS_DIR = os.path.join(SCRIPT_DIR, 'data', 'reports')
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, 'data', 'archive')
LOG_DIR = os.path.join(SCRIPT_DIR, 'data', 'logs')
CHECKPOINT_DIR = os.path.join(SCRIPT_DIR, 'data', 'checkpoints')


def setup_logging():
    """Configure logging to console (INFO) and file (DEBUG)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log")
    
    root = logging.getLogger('travelport')
    root.setLevel(logging.DEBUG)
    
    # Console: INFO level, concise format
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    root.addHandler(ch)
    
    # File: DEBUG level, full format with timestamps
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    root.addHandler(fh)
    
    return log_file


def load_config(config_path: str) -> dict:
    """Load and validate configuration from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
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
        if filename.endswith('.txt') and not filename.startswith('_') and not filename.startswith('FTAX'):
            filepath = os.path.join(raw_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            if filename.endswith('_FS.txt'):
                file_key = filename[:-7]
                raw_fs_texts[file_key] = content
            else:
                file_key = filename[:-4]
                raw_texts[file_key] = content
            
            logger.info(f"  Loaded: {filename}")
    
    return raw_texts, raw_fs_texts


def process_route_data(raw_texts: dict[str, str], raw_fs_texts: dict[str, str], config: dict, enable_validation: bool = True) -> dict:
    """Process raw text files into route data with optional validation."""
    rbd_sort_order = config.get('rbd_sort_order', [])
    all_route_data = OrderedDict()

    # Combine all file_keys from both raw_texts and raw_fs_texts
    all_file_keys = set(raw_texts.keys()) | set(raw_fs_texts.keys())

    # Use tqdm progress bar if available
    items = sorted(all_file_keys)
    if tqdm:
        items = tqdm(items, desc="Processing routes", unit="route")

    for file_key in items:
        raw_text = raw_texts.get(file_key, '')

        # Parse fare data if available
        fares = []
        currency = None
        if raw_text:
            result = parse_fare_display(raw_text)
            fares = result.get('fares', [])
            currency = result.get('currency')

            # Validate currency code
            if enable_validation and currency:
                validate_currency_code(currency, warn_only=True)

            # Validate parsed fares
            if enable_validation and fares:
                validation_stats = validate_parsed_fares(fares, currency)
                if validation_stats['invalid_fares'] > 0:
                    logger.warning(
                        f"  {file_key}: {validation_stats['invalid_fares']}/{validation_stats['total_fares']} "
                        f"fares have validation issues"
                    )

        # Parse FS tax data if available
        fs_taxes = {}
        if file_key in raw_fs_texts:
            fs_taxes = parse_fs_tax_breakdown(raw_fs_texts[file_key])

            # Debug logging for tax parsing
            if not tqdm:
                if fs_taxes.get('exchange_rate', 0) > 0:
                    logger.debug(f"      [TAX] {file_key}: Rate={fs_taxes.get('exchange_rate'):.4f}, "
                                f"Total={fs_taxes.get('total_taxes', 0)}, YQ={fs_taxes.get('yq_charge', 0)}")
                else:
                    logger.warning(f"      [TAX] {file_key}: Exchange rate is 0 or missing - tax data may not display correctly")
                    logger.warning(f"      [TAX] Base fare={fs_taxes.get('base_fare', 0)}, Equ fare={fs_taxes.get('equ_fare', 0)}")
                    if raw_fs_texts[file_key]:
                        logger.warning(f"      [TAX] First 200 chars of raw FS text: {raw_fs_texts[file_key][:200]}")

        # Add to all_route_data if we have either fares or taxes
        if fares or fs_taxes:
            grouped = group_fares_by_rbd(fares, rbd_sort_order) if fares else {}
            all_route_data[file_key] = {
                'rbd_data': grouped,
                'currency': currency,
                'fs_taxes': fs_taxes
            }

            # Only log if not using tqdm (to avoid cluttering progress bar)
            if not tqdm:
                if fares:
                    ow_count = sum(1 for d in grouped.values() if d.get('ow_fare') is not None)
                    rt_count = sum(1 for d in grouped.values() if d.get('rt_fare') is not None)
                    logger.info(f"  {file_key} → {len(grouped)} RBDs ({ow_count} OW, {rt_count} RT) [{currency or 'N/A'}]")
                elif fs_taxes:
                    logger.info(f"  {file_key} → Tax data only (no fares)")
        else:
            if not tqdm:
                logger.warning(f"  No data parsed from: {file_key}")

    return OrderedDict(sorted(all_route_data.items()))


def show_usage():
    """Show usage instructions when no data files are found."""
    logger.info("")
    logger.info("  [!] No .txt files found in data/raw/")
    logger.info("")
    logger.info("  HOW TO USE:")
    logger.info("  ───────────")
    logger.info("  1. Open Travelport Smartpoint")
    logger.info("  2. Run a fare display command (e.g., FDDACMLE/BG)")
    logger.info("  3. Select all output and copy (Ctrl+C)")
    logger.info(f"  4. Save as .txt in: {RAW_DATA_DIR}")
    logger.info("  5. Run: python main.py")


def main():
    """Main entry point."""
    import time as _time
    start_time = _time.time()
    
    arg_parser = argparse.ArgumentParser(description='Travelport Data Automation')
    arg_parser.add_argument('--config', '-c', default=DEFAULT_CONFIG)
    arg_parser.add_argument('--no-changes', action='store_true', help='Skip change detection')
    arg_parser.add_argument('--output', '-o', default=None, help='Output Excel path')
    arg_parser.add_argument('--auto', action='store_true', help='Extract data from live Smartpoint')
    arg_parser.add_argument('--limit', type=int, default=0, help='Limit commands (testing)')
    arg_parser.add_argument('--route', type=str, help='Filter commands to a specific route (e.g. DAC-MLE)')
    arg_parser.add_argument('--airline', type=str, help='Filter to specific airline(s), comma-separated (e.g. BG or BG,BS)')
    arg_parser.add_argument('--only-fd', action='store_true', help='Extract only basic Fares (skip YQ/Currency FS command)')
    arg_parser.add_argument('--only-yq', action='store_true', help='Extract only YQ and Tax Breakdown (skip Fares)')
    arg_parser.add_argument('--only-currency', action='store_true', help='Extract only exchange rates (alias for --only-yq)')
    arg_parser.add_argument('--tax', action='store_true', help='Extract Tax (FTAX) data instead of fares')
    arg_parser.add_argument('--speed', type=str, choices=['fast', 'safe'], default=None,
                           help='Speed profile: "fast" (aggressive timings, ~50%% faster) or "safe" (conservative timings for slower machines)')
    arg_parser.add_argument('--checkpoint', action='store_true', help='Enable checkpoint/resume mode for long runs')
    arg_parser.add_argument('--resume', type=str, default=None, help='Resume from a specific checkpoint file')
    arg_parser.add_argument('--no-validation', action='store_true', help='Disable data validation and sanity checks')

    args = arg_parser.parse_args()

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

    log_file = setup_logging()

    logger.info("=" * 60)
    logger.info(f"  TRAVELPORT {'TAX' if args.tax else 'FARE'} AUTOMATION TOOL")
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
        logger.info("  Config loaded ✓")
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
    if args.tax:
        tax_airports = config.get('tax_airports', {})
        if not tax_airports:
            logger.error("  No 'tax_airports' defined in config.")
            sys.exit(1)
        if args.limit > 0:
            tax_airports = {k: v for i, (k, v) in enumerate(tax_airports.items()) if i < args.limit}
            logger.info(f"  [TESTING] Limited to first {args.limit} airports")
        logger.info(f"  {len(tax_airports)} tax airports loaded from config")
    else:
        commands_file = os.path.join(SCRIPT_DIR, config.get('commands_file', 'commands.txt'))
        if os.path.exists(commands_file):
            commands = load_commands(commands_file)
            if args.route:
                routes = [r.strip().upper().replace('-', '') for r in args.route.split(',')]
                valid_routes = [r for r in routes if len(r) == 6]
                
                commands = [
                    c for c in commands 
                    if any(f"{rt[:3]}{rt[3:]}" in c['command'] or f"{rt[3:]}{rt[:3]}" in c['command'] for rt in valid_routes)
                ]
                logger.info(f"  [FILTER] Limited to route(s) {args.route}: {len(commands)} commands remaining")
            if args.airline:
                airlines = [a.strip().upper() for a in args.airline.split(',')]
                commands = [c for c in commands if any(f'/{al}' in c['command'].upper() for al in airlines)]
                logger.info(f"  [FILTER] Limited to airline(s) {args.airline}: {len(commands)} commands remaining")
            if args.limit > 0:
                commands = commands[:args.limit]
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
            checkpoint_mgr = CheckpointManager(CHECKPOINT_DIR, session_name=os.path.basename(args.resume).replace('checkpoint_', '').replace('.json', ''))
            if checkpoint_mgr.load_checkpoint():
                logger.info(f"  [CHECKPOINT] Resuming from: {args.resume}")
                stats = checkpoint_mgr.get_progress_stats()
                logger.info(f"  [CHECKPOINT] Previously completed: {stats['completed']} commands")
            else:
                logger.warning(f"  [CHECKPOINT] Could not load checkpoint: {args.resume}")
                logger.info("  [CHECKPOINT] Starting fresh")
        else:
            # New checkpoint session
            checkpoint_mgr = CheckpointManager(CHECKPOINT_DIR)
            logger.info(f"  [CHECKPOINT] Checkpoint mode enabled")
            logger.info(f"  [CHECKPOINT] Session: {checkpoint_mgr.session_name}")

    # [2/4] Extraction
    failed_commands = []
    
    # TAX MODE EXTRACTION
    if args.tax:
        tax_data = {} # airport_code -> {'taxes': [ detail_data... ]}
        
        if args.auto:
            logger.info("[2/4] AUTO MODE: Connecting to Smartpoint UI for FTAX...")
            from smartpoint_automation import SmartpointAutomation
            automation = SmartpointAutomation()
            if not automation.connect():
                logger.error("  Please ensure Smartpoint is open.")
                sys.exit(1)
                
            automation.refresh_terminal()
            from tax_parser import parse_ftax_list, parse_ftax_detail

            # Use tqdm for progress if available
            airport_items = tax_airports.items()
            if tqdm:
                airport_items = tqdm(list(airport_items), desc="Extracting tax data", unit="airport")
            else:
                airport_items = list(airport_items)

            for index, (airport_code, airport_info) in enumerate(airport_items, 1):
                country_code = airport_info['country']

                # Only log if not using tqdm
                if not tqdm:
                    logger.info(f"  [{index}/{len(tax_airports)}] Airport: {airport_code} ({country_code})")
                
                # Get tax types
                list_cmd = f"FTAX-{country_code}"
                list_text = automation.run_command(list_cmd, max_pages=1)
                
                # Debug backup
                os.makedirs(RAW_DATA_DIR, exist_ok=True)
                backup_path = os.path.join(RAW_DATA_DIR, f"{list_cmd}.txt")
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(list_text)
                    
                tax_types = parse_ftax_list(list_text)
                logger.info(f"    Found {len(tax_types)} tax types: {', '.join(t['code'] for t in tax_types)}")
                
                if not tax_types:
                    logger.warning(f"    [DEBUG] Raw list text ({len(list_text)} chars): {list_text[:300]}")
                
                airport_tax_details = []
                for idx, t in enumerate(tax_types, 1):
                    detail_text = automation.run_ftax_command(country_code, t['code'], tax_index=idx)
                    
                    # Save raw detail text for debugging
                    detail_backup = os.path.join(RAW_DATA_DIR, f"FTAX-{country_code}_{t['code']}.txt")
                    with open(detail_backup, 'w', encoding='utf-8') as f:
                        f.write(detail_text)
                    
                    if not detail_text or len(detail_text.strip()) < 20:
                        failed_commands.append(f"{country_code}/{t['code']}")
                        logger.warning(f"    Failed to extract details for {t['code']}")
                        continue
                    
                    logger.debug(f"      [DEBUG] Raw detail text first 200 chars: {detail_text[:200]}")
                        
                    detail_data = parse_ftax_detail(detail_text, t['code'], t['name'])
                    airport_tax_details.append(detail_data)
                    logger.info(f"      {t['code']} → {len(detail_data['sections'])} sections extracted.")
                    
                    if not detail_data['sections']:
                        logger.warning(f"      [DEBUG] 0 sections! Full text ({len(detail_text)} chars): {detail_text[:500]}")
                    
                    # Return to tax list for next tax type
                    if idx < len(tax_types):
                        automation.return_to_tax_list(country_code)
                
                tax_data[airport_code] = {'taxes': airport_tax_details}
            
            automation.show_completion_signal()
        else:
            logger.error("  Manual loading of taxes not implemented. Use --auto.")
            sys.exit(1)
            
        all_route_data = tax_data # Alias for reporting
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
            automation = SmartpointAutomation()
            
            if not automation.connect():
                logger.error("  Please ensure Smartpoint is open and the title matches.")
                sys.exit(1)

            # Try to get credentials from environment
            username, password, pcc = CredentialManager.get_credentials()
            if username and password:
                logger.info("  Credentials loaded from environment")
                try:
                    automation.login(username, password, pcc)
                except Exception as e:
                    logger.error(f"  Login failed: {e}")
                    sys.exit(1)
            else:
                logger.info("  No credentials found - continuing without login")
                logger.info("  To enable automatic login, set environment variables:")
                logger.info("    SMARTPOINT_USERNAME, SMARTPOINT_PASSWORD, SMARTPOINT_PCC")

            logger.debug("  Initializing terminal state...")
            automation.refresh_terminal()

            # Filter commands if resuming from checkpoint
            if checkpoint_mgr:
                original_count = len(commands)
                commands = checkpoint_mgr.get_remaining_commands(commands)
                skipped = original_count - len(commands)
                if skipped > 0:
                    logger.info(f"  [CHECKPOINT] Skipping {skipped} already completed commands")
                    logger.info(f"  [CHECKPOINT] {len(commands)} commands remaining")

            MAX_RETRIES = MAX_RETRIES_COMMAND

            # Use tqdm for progress if available
            if tqdm and not checkpoint_mgr:
                # Use simple progress bar
                command_iter = tqdm(commands, desc="Executing commands", unit="cmd")
            elif tqdm and checkpoint_mgr:
                # Use progress bar with initial progress
                command_iter = tqdm(
                    commands,
                    desc="Executing commands",
                    unit="cmd",
                    initial=len(checkpoint_mgr.completed_commands),
                    total=len(checkpoint_mgr.completed_commands) + len(commands)
                )
            else:
                # No progress bar
                command_iter = commands
                logger.info(f"  Executing {len(commands)} commands...")

            for i, cmd in enumerate(command_iter, 1):
                cmd_str = cmd['command']

                # Skip if already completed (double-check in case of concurrent runs)
                if checkpoint_mgr and checkpoint_mgr.is_completed(cmd_str):
                    continue

                # Only log if not using tqdm
                if not tqdm:
                    logger.info(f"  [{i}/{len(commands)}] {cmd_str}")

                terminal_text = ""
                file_key = generate_file_key(cmd)
                
                # ── FD EXTRACTION ──
                if not args.only_yq and not args.only_currency:
                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            terminal_text = automation.run_command(cmd['command'])
                            if terminal_text and len(terminal_text.strip()) > 50:
                                break
                            logger.warning(f"    Attempt {attempt}: insufficient data ({len(terminal_text)} chars)")
                        except Exception as e:
                            logger.warning(f"    Attempt {attempt} failed: {e}")
                        
                        if attempt < MAX_RETRIES:
                            logger.info(f"    Retrying in 1.5s...")
                            _time.sleep(1.5)
                            automation.refresh_terminal()
                    
                    if terminal_text and len(terminal_text.strip()) > 50:
                        raw_texts[file_key] = terminal_text
                        logger.info(f"    ✓ Fare data captured ({len(terminal_text)} chars)")

                        backup_path = os.path.join(RAW_DATA_DIR, f"{file_key}.txt")
                        os.makedirs(os.path.dirname(backup_path) or '.', exist_ok=True)
                        try:
                            with open(backup_path, 'w', encoding='utf-8') as f:
                                f.write(terminal_text)
                            logger.debug(f"    Backup saved: {backup_path}")
                        except Exception as e:
                            logger.warning(f"    Could not save backup: {e}")
                    else:
                        failed_commands.append(cmd['command'])
                        logger.error(f"    ✗ FAILED after {MAX_RETRIES} attempts: {cmd['command']}")
                        logger.error(f"    Final data length: {len(terminal_text) if terminal_text else 0} chars")
                        logger.error(f"    This command will be skipped in the report")

                        # Mark as failed in checkpoint
                        if checkpoint_mgr:
                            checkpoint_mgr.mark_failed(cmd_str)
                else:
                    logger.info("    [SKIP] Skipping FD extraction (--only-yq/--only-currency)")
                        
                # ── FS EXTRACTION ──
                if not args.only_fd:
                    # Allow extracting YQ/Currency even if FD was skipped or failed
                    base_cmd = cmd['command'].strip()
                    if len(base_cmd) >= 11 and base_cmd.startswith('FD') and '/' in base_cmd and len(base_cmd.split('/')[0]) == 8:
                        src = base_cmd[2:5]
                        dst = base_cmd[5:8]
                        airline = base_cmd.split('/')[1][:2]
                        
                        fs_expanded = ""
                        fs_date_offset = FS_DATE_OFFSET_START
                        max_fs_date_steps = MAX_FS_DATE_STEPS
                        
                        while fs_date_offset <= max_fs_date_steps:
                            date_str = (datetime.now() + timedelta(days=fs_date_offset)).strftime('%d%b').upper()
                            logger.info(f"    [FS Checkout] Extracting tax details for {src}-{dst} on {date_str}...")
                            
                            fs_result = automation.run_fs_command(src, dst, date_str, airline)
                            
                            # Freshness check: ensures terminal actually refreshed
                            if date_str.upper() not in fs_result.upper():
                                logger.warning(f"      [!] Screen hasn't updated to {date_str} yet. Waiting 1.5s...")
                                _time.sleep(1.5)
                                fs_result = automation._copy_terminal_text()

                            # Log raw results for diagnostics
                            with open("fs_debug.log", "a", encoding="utf-8") as f:
                                f.write(f"\n--- {date_str} {src}-{dst} /{airline} ---\n")
                                f.write(fs_result)
                                f.write("\n" + "="*50 + "\n")

                            # Identify Pricing Option blocks
                            options_iter = re.finditer(r'PRICING\s+OPTION\s+(\d+)(.*?(?=PRICING\s+OPTION\s+\d+|$))', fs_result, re.IGNORECASE | re.DOTALL)
                            options = list(options_iter)
                            
                            if not options:
                                if fs_result and any(kw in fs_result.upper() for kw in
                                                     ["NO FARES FOUND", "CHECK ACTION CODE", "INVALID"]):
                                    logger.warning(f"      [!] No valid FS results for {date_str}. Trying next date...")
                                    fs_date_offset += 1
                                    _time.sleep(0.5)
                                    continue  # Retry with next date offset
                                else:
                                    logger.warning(f"      [!] Waiting for terminal content (offset {fs_date_offset})...")
                                    fs_date_offset += 1
                                    _time.sleep(0.5)
                                    continue

                            target_option_index = -1
                            
                            logger.info(f"      [DEBUG] Parsing {len(options)} options for {airline}...")
                            
                            for k, opt_match in enumerate(options):
                                opt_num = opt_match.group(1)
                                block = opt_match.group(2)
                                
                                leg_matches = re.findall(r'^\s*(\d+)\s+([A-Z0-9]{2})\s+', block, re.MULTILINE)
                                
                                if leg_matches:
                                    leg_airlines = [m[1].upper().strip() for m in leg_matches]
                                    logger.debug(f"        Option {opt_num}: {leg_airlines}")
                                    
                                    if all(a == airline.upper() for a in leg_airlines):
                                        logger.info(f"      [✓] Pure {airline} itinerary found in Option {opt_num}.")
                                        target_option_index = k
                                        break
                                else:
                                    logger.debug(f"        Option {opt_num}: No flight legs detected in text block.")

                            if target_option_index == -1:
                                logger.warning(f"      [!] No pure {airline} options found on {date_str}. (Tried {len(options)} items)")
                                fs_date_offset += 1
                                _time.sleep(0.5)
                                continue

                            # Click the D button using text-to-coordinate mapping
                            fs_expanded = automation.click_d_button(target_option_index, fs_result)
                            
                            # Validate: D expansion should contain tax/fare data
                            D_KEYWORDS = ["EQU", "TAXES", "TAX", "YQ", "FARE", "BASIS"]
                            if fs_expanded and any(kw in fs_expanded.upper() for kw in D_KEYWORDS):
                                logger.info(f"      [✓] Tax breakdown extracted via D-click")
                            else:
                                logger.warning(f"      [!] D-click did not return expected tax data.")
                                fs_expanded = ""
                            break  # Exit the date-stepping while loop
                            
                        if fs_expanded and len(fs_expanded.strip()) > 50:
                            raw_fs_texts[file_key] = fs_expanded
                            fs_backup_path = os.path.join(RAW_DATA_DIR, f"{file_key}_FS.txt")
                            try:
                                with open(fs_backup_path, 'w', encoding='utf-8') as f:
                                    f.write(fs_expanded)
                            except Exception:
                                pass

                # Mark command as completed and save checkpoint
                if checkpoint_mgr and cmd_str not in failed_commands:
                    checkpoint_mgr.mark_completed(cmd_str)
                    # Save checkpoint every 10 commands to avoid excessive I/O
                    if len(checkpoint_mgr.completed_commands) % 10 == 0:
                        checkpoint_mgr.save_checkpoint()

            # Final checkpoint save
            if checkpoint_mgr:
                checkpoint_mgr.save_checkpoint()
                logger.info(f"  [CHECKPOINT] Final checkpoint saved: {len(checkpoint_mgr.completed_commands)} completed")

            automation.show_completion_signal()

            # Show execution summary
            total_commands = len(commands)
            successful_commands = total_commands - len(failed_commands)
            logger.info("")
            logger.info("="*60)
            logger.info("  EXECUTION SUMMARY")
            logger.info("="*60)
            logger.info(f"  Total commands: {total_commands}")
            logger.info(f"  Successful: {successful_commands}")
            logger.info(f"  Failed: {len(failed_commands)}")
            if failed_commands:
                logger.warning("  Failed commands:")
                for fc in failed_commands:
                    logger.warning(f"    - {fc}")
                logger.warning("  Note: Failed commands will not appear in the report")
            else:
                logger.info("  ✓ All commands completed successfully!")
            logger.info("="*60)

        else:
            logger.info("[2/4] MANUAL MODE: Loading raw GDS data from disk...")
            raw_texts, raw_fs_texts = load_raw_data(RAW_DATA_DIR)
            if not raw_texts:
                show_usage()
                sys.exit(1)
            logger.info(f"  Loaded {len(raw_texts)} fare file(s) and {len(raw_fs_texts)} tax detail file(s)")
        logger.info("")
        
        # Parse Fares
        logger.info("[3/4] Parsing fare and tax data...")
        all_route_data = process_route_data(raw_texts, raw_fs_texts, config, enable_validation)
        if not all_route_data:
            logger.error("  No fare data could be parsed.")
            sys.exit(1)
        logger.info("")
    
    # [3.5] Change detection (for both modes)
    changes = None
    if not args.no_changes:
        logger.info("[3.5] Detecting changes...")
        archive_subdir = 'tax' if args.tax else 'fare'
        archive_path = os.path.join(ARCHIVE_DIR, archive_subdir)
        os.makedirs(archive_path, exist_ok=True)
        
        previous_data = load_latest_snapshot(archive_path)
        
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
            logger.info("  No previous data found. First run — baseline saved.")
        
        ts = datetime.now().strftime('%Y-%m-%d_%H%M')
        save_snapshot(all_route_data, archive_path, date_str=ts)
        logger.info("")
    
    # [4/4] Generate Report
    logger.info("[4/4] Generating Excel report...")
    
    if args.output:
        output_path = args.output
    else:
        if args.tax:
            timestamp_full = datetime.now().strftime('%Y-%m-%d_%H%M')
            output_name = f"tax_report_{timestamp_full}.xlsx"
            output_path = os.path.join(REPORTS_DIR, output_name)
        else:
            timestamp_full = datetime.now().strftime('%Y-%m-%d_%H%M')
            output_filename = config.get('excel_output_filename', 'fare_report_{date}.xlsx')
            output_filename = output_filename.replace('{date}', timestamp_full)
            output_path = os.path.join(REPORTS_DIR, output_filename)
    
    if args.tax:
        from tax_report import generate_tax_report
        result_path = generate_tax_report(all_route_data, output_path, changes, config)
    else:
        # Pass only_currency flag down to specifically skip the main sheets if needed
        result_path = generate_report(all_route_data, output_path, changes, config, only_currency=args.only_currency)
    
    # Run Summary
    elapsed = _time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    total_changes = sum(len(rc) for rc in changes.values()) if changes else 0
    change_counts = {}
    if changes:
        for rc in changes.values():
            for ci in rc.values():
                ct = ci.get('type', 'unknown')
                change_counts[ct] = change_counts.get(ct, 0) + 1
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("  RUN SUMMARY")
    logger.info("─" * 60)
    logger.info(f"  Report:   {result_path}")
    logger.info(f"  Items:    {len(all_route_data)} {'airports' if args.tax else 'routes'} parsed")
    if failed_commands:
        logger.info(f"  Failed:   {len(failed_commands)} ({', '.join(failed_commands)})")
    if total_changes:
        parts = [f"{v} {k}" for k, v in sorted(change_counts.items())]
        logger.info(f"  Changes:  {total_changes} ({', '.join(parts)})")
    else:
        logger.info("  Changes:  None")
    logger.info(f"  Duration: {minutes}m {seconds}s")
    logger.info(f"  Log:      {log_file}")
    logger.info("=" * 60)
    
    return result_path


if __name__ == '__main__':
    main()

