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


def process_route_data(raw_texts: dict[str, str], raw_fs_texts: dict[str, str], config: dict) -> dict:
    """Process raw text files into route data."""
    rbd_sort_order = config.get('rbd_sort_order', [])
    all_route_data = OrderedDict()
    
    for file_key, raw_text in raw_texts.items():
        result = parse_fare_display(raw_text)
        fares = result.get('fares', [])
        currency = result.get('currency')
        
        fs_taxes = {}
        if file_key in raw_fs_texts:
            fs_taxes = parse_fs_tax_breakdown(raw_fs_texts[file_key])
            
        if fares:
            grouped = group_fares_by_rbd(fares, rbd_sort_order)
            all_route_data[file_key] = {
                'rbd_data': grouped,
                'currency': currency,
                'fs_taxes': fs_taxes
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
    arg_parser.add_argument('--route', type=str, help='Filter commands to a specific route (e.g. DAC-MLE)')
    arg_parser.add_argument('--airline', type=str, help='Filter to specific airline(s), comma-separated (e.g. BG or BG,BS)')
    arg_parser.add_argument('--only-fd', action='store_true', help='Extract only basic Fares (skip YQ/Currency FS command)')
    arg_parser.add_argument('--only-yq', action='store_true', help='Extract only YQ and Tax Breakdown (skip Fares)')
    arg_parser.add_argument('--only-currency', action='store_true', help='Extract only exchange rates (alias for --only-yq)')
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
            if args.route:
                rt = args.route.upper().replace('-', '')
                if len(rt) == 6:
                    srf1 = f"{rt[:3]}{rt[3:]}"
                    srf2 = f"{rt[3:]}{rt[:3]}"
                    commands = [c for c in commands if srf1 in c['command'] or srf2 in c['command']]
                logger.info(f"  [FILTER] Limited to route {args.route}: {len(commands)} commands remaining")
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
            
            if args.username and args.password:
                automation.login(args.username, args.password, args.pcc)
            
            logger.debug("  Initializing terminal state...")
            automation.refresh_terminal()
            
            MAX_RETRIES = 3
            logger.info(f"  Executing {len(commands)} commands...")
            for i, cmd in enumerate(commands, 1):
                logger.info(f"  [{i}/{len(commands)}] {cmd['command']}")
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
                        fs_date_offset = 7
                        max_fs_date_steps = 14
                        
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
                                    logger.warning(f"      [!] No valid FS results for {date_str}. Skipping.")
                                    break  # Don't retry — move on
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
            
            automation.show_completion_signal()
        
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
        all_route_data = process_route_data(raw_texts, raw_fs_texts, config)
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

