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
import sys
from datetime import datetime
from collections import OrderedDict

from parser import (
    parse_fare_display,
    group_fares_by_rbd,
    load_commands,
    generate_file_key,
    parse_command
)
from excel_report import generate_report
from change_detector import (
    detect_changes,
    save_snapshot,
    load_latest_snapshot,
    format_change_summary
)

logger = logging.getLogger('travelport')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, 'config.json')
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, 'data', 'raw')
REPORTS_DIR = os.path.join(SCRIPT_DIR, 'data', 'reports')
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, 'data', 'archive')
LOG_DIR = os.path.join(SCRIPT_DIR, 'data', 'logs')


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
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Config validation
    required_keys = ['commands_file', 'airline_names', 'city_names', 'rbd_sort_order']
    missing = [k for k in required_keys if k not in config]
    if missing:
        logger.warning(f"  Config missing keys: {', '.join(missing)} — using defaults")
    
    if not config.get('domestic_airports'):
        logger.warning("  Config missing 'domestic_airports' — defaulting to ['DAC']")
        config['domestic_airports'] = ['DAC']
    
    return config


def load_raw_data(raw_dir: str) -> dict[str, str]:
    """Load raw GDS output from text files in data/raw/."""
    raw_texts = {}
    
    if not os.path.exists(raw_dir):
        return raw_texts
    
    for filename in sorted(os.listdir(raw_dir)):
        if filename.endswith('.txt') and not filename.startswith('_'):
            filepath = os.path.join(raw_dir, filename)
            file_key = filename[:-4]
            
            with open(filepath, 'r', encoding='utf-8') as f:
                raw_texts[file_key] = f.read()
            
            logger.info(f"  Loaded: {filename}")
    
    return raw_texts


def process_route_data(raw_texts: dict[str, str], config: dict) -> dict:
    """Process raw text files into route data."""
    rbd_sort_order = config.get('rbd_sort_order', [])
    all_route_data = OrderedDict()
    
    for file_key, raw_text in raw_texts.items():
        result = parse_fare_display(raw_text)
        fares = result.get('fares', [])
        currency = result.get('currency')
        
        if fares:
            grouped = group_fares_by_rbd(fares, rbd_sort_order)
            all_route_data[file_key] = {
                'rbd_data': grouped,
                'currency': currency
            }
            ow_count = sum(1 for d in grouped.values() if d.get('ow_fare') is not None)
            rt_count = sum(1 for d in grouped.values() if d.get('rt_fare') is not None)
            logger.info(f"  {file_key} → {len(grouped)} RBDs ({ow_count} OW, {rt_count} RT) [{currency or 'N/A'}]")
        else:
            logger.warning(f"  No fares parsed from: {file_key}")
    
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
    arg_parser.add_argument('--username', help='Smartpoint username')
    arg_parser.add_argument('--password', help='Smartpoint password')
    arg_parser.add_argument('--pcc', help='Pseudo City Code')
    arg_parser.add_argument('--tax', action='store_true', help='Extract Tax (FTAX) data instead of fares')
    
    args = arg_parser.parse_args()
    log_file = setup_logging()
    
    logger.info("=" * 60)
    logger.info(f"  TRAVELPORT {'TAX' if args.tax else 'FARE'} AUTOMATION TOOL")
    logger.info(f"  {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    logger.info("=" * 60)
    logger.info("")
    
    # [1/4] Config
    logger.info("[1/4] Loading configuration...")
    config = load_config(args.config)
    logger.info("  Config loaded ✓")
    
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
            if args.limit > 0:
                commands = commands[:args.limit]
                logger.info(f"  [TESTING] Limited to first {args.limit} commands")
            logger.info(f"  {len(commands)} route commands loaded")
    logger.info("")
    
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
            
            for index, (airport_code, airport_info) in enumerate(tax_airports.items(), 1):
                country_code = airport_info['country']
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
            
            if args.username and args.password:
                automation.login(args.username, args.password, args.pcc)
            
            logger.debug("  Initializing terminal state...")
            automation.refresh_terminal()
            
            MAX_RETRIES = 3
            logger.info(f"  Executing {len(commands)} commands...")
            for i, cmd in enumerate(commands, 1):
                logger.info(f"  [{i}/{len(commands)}] {cmd['command']}")
                
                terminal_text = ""
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        terminal_text = automation.run_command(cmd['command'])
                        if terminal_text and len(terminal_text.strip()) > 50:
                            break
                        logger.warning(f"    Attempt {attempt}: insufficient data ({len(terminal_text)} chars)")
                    except Exception as e:
                        logger.warning(f"    Attempt {attempt} failed: {e}")
                    
                    if attempt < MAX_RETRIES:
                        logger.info(f"    Retrying in 3s...")
                        _time.sleep(3)
                        automation.refresh_terminal()
                
                if terminal_text and len(terminal_text.strip()) > 50:
                    file_key = generate_file_key(cmd)
                    raw_texts[file_key] = terminal_text
                    
                    backup_path = os.path.join(RAW_DATA_DIR, f"{file_key}.txt")
                    os.makedirs(os.path.dirname(backup_path) or '.', exist_ok=True)
                    try:
                        with open(backup_path, 'w', encoding='utf-8') as f:
                            f.write(terminal_text)
                    except Exception:
                        pass
                else:
                    failed_commands.append(cmd['command'])
                    logger.error(f"    FAILED after {MAX_RETRIES} attempts: {cmd['command']}")
            
            automation.show_completion_signal()
        
        else:
            logger.info("[2/4] MANUAL MODE: Loading raw GDS data from disk...")
            raw_texts = load_raw_data(RAW_DATA_DIR)
            if not raw_texts:
                show_usage()
                sys.exit(1)
            logger.info(f"  Loaded {len(raw_texts)} file(s)")
        logger.info("")
        
        # Parse Fares
        logger.info("[3/4] Parsing fare data...")
        all_route_data = process_route_data(raw_texts, config)
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
                logger.info("  [TODO] Tax change detection logic not yet implemented.")
                changes = {}
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
        result_path = generate_report(all_route_data, output_path, changes, config)
    
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

