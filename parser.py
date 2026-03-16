"""
parser.py - GDS Fare Display Output Parser

Parses raw text output from Travelport Smartpoint fare display commands
into structured data for report generation.

Command format: FD{ORIGIN}{DEST}-{OW|RT}/{AIRLINE}
Example: FDDACMLE-OW/BG -> One-way fares from DAC to MLE on BG
"""

import re
from typing import Optional


def parse_command(command: str) -> Optional[dict]:
    """
    Parse a fare display mother command string into its components.
    
    Example: FDDACMLE/BG
    Returns: {origin: DAC, dest: MLE, airline: BG, route: DAC-MLE}
    """
    pattern = r'^FD([A-Z]{3})([A-Z]{3})/([A-Z0-9]{2})$'
    match = re.match(pattern, command.strip(), re.IGNORECASE)
    
    if not match:
        return None
    
    origin = match.group(1).upper()
    dest = match.group(2).upper()
    airline = match.group(3).upper()
    
    return {
        'origin': origin,
        'destination': dest,
        'airline': airline,
        'route': f"{origin}-{dest}",
        'command': command.strip().upper()
    }


def load_commands(commands_file: str) -> list[dict]:
    """
    Load and parse commands from the commands.txt file.
    Skips comment lines (starting with #) and empty lines.
    
    Returns list of parsed command dicts.
    """
    commands = []
    
    with open(commands_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parsed = parse_command(line)
            if parsed:
                commands.append(parsed)
            else:
                print(f"  [WARNING] Could not parse command: {line}")
    
    return commands


def _extract_currency(raw_text: str):
    """
    Extract the currency code from the fare display header.
    
    Looks for patterns like:
        '         USD    BASIS       MAX'
        '         CNY    BASIS       MAX'
        '         OMR    BASIS       MAX'
    """
    import re
    lines = raw_text.strip().split('\n')
    for line in lines:
        # Match the column header line that shows the currency code
        # e.g. "         USD    BASIS       MAX" or "    CNY    BASIS"
        match = re.search(r'\b([A-Z]{3})\s+BASIS\b', line.upper())
        if match:
            return match.group(1)
    return None


def parse_fare_display(raw_text: str) -> dict:
    """
    Parse raw GDS fare display output into structured fare records.
    
    Extracts currency from the fare display header automatically.
    Handles both sellable and unsaleable fares (O-prefixed line numbers).
    
    Returns:
        Dict with keys:
            'fares': List of fare dicts
            'currency': Extracted currency code (e.g., 'USD', 'CNY', 'OMR')
    """
    if not raw_text or not raw_text.strip():
        return {'fares': [], 'currency': None}
    
    # Extract currency from the header
    # Patterns found in Smartpoint output:
    #   "BDT CURRENCY FARES EXIST"  (alternative currency notice)
    #   "    FARE"  line followed by "    USD    BASIS" or "    CNY    BASIS"
    #   Column header line like: "         USD    BASIS       MAX"
    currency = _extract_currency(raw_text)

    
    fares = []
    lines = raw_text.strip().split('\n')
    
    # Pattern to match fare lines
    # Groups: (line_num) (airline) (fare)(R?) (fare_basis) (rbd) ... rest
    # Line numbers can be normal digits OR O-prefixed (O30, O31) for unsellable fares
    fare_pattern = re.compile(
        r'^\s*O?(\d+)\s+'         # Line number (optionally O-prefixed for unsellable)
        r'-?([A-Z0-9]{2})\s+'    # Optional minus sign, then Airline code (2 chars)
        r'(\d+\.?\d*)(R?)\s+'    # Fare amount + optional R (round-trip marker)
        r'(\S+)\s+'              # Fare basis code
        r'([A-Z])\s+'            # RBD (single letter)
        r'(.*)',                  # Rest of line
        re.IGNORECASE
    )
    
    is_unsellable_section = False
    
    for line in lines:
        stripped = line.strip()
        upper_stripped = stripped.upper()
        if not stripped:
            continue
            
        # Detect unsellable section from two possible markers:
        # 1. "UNSALEABLE FARES MAY EXIST" banner (from main fare display)
        # 2. "UNSALEABLE FARES" header (from FU* command output)
        if "UNSALEABLE FARES" in upper_stripped:
            # Only set unsellable if this is the actual section header, not just the warning
            # The FU* output has "UNSALEABLE FARES" as a distinct header line
            if "MAY EXIST" not in upper_stripped:
                is_unsellable_section = True
            
        # Reset unsellable flag when we re-enter the normal PUBLIC FARES section
        if "PUBLIC FARES" in upper_stripped and is_unsellable_section:
            is_unsellable_section = False
            
        # Skip non-fare lines
        if upper_stripped in ('END', 'MD'):
            continue
        # Match lines starting with a digit or O followed by digits
        if not re.match(r'^\s*O?\d+\s+', line):
            continue
        
        match = fare_pattern.match(line)
        if match:
            line_num = int(match.group(1))
            airline = match.group(2).upper()
            fare_amount = float(match.group(3))
            fare_basis = match.group(5).upper()
            rbd = match.group(6).upper()
            
            # Check if this line was O-prefixed (unsellable indicator)
            is_o_prefixed = bool(re.match(r'^\s*O\d+', line))
            
            fares.append({
                'line': line_num,
                'airline': airline,
                'fare': fare_amount,
                'is_rt': bool(match.group(4)), # Group 4 is (R?)
                'fare_basis': fare_basis,
                'rbd': rbd,
                'is_unsaleable': is_unsellable_section or is_o_prefixed,
                'raw_line': stripped
            })
    
    return {'fares': fares, 'currency': currency}



def group_fares_by_rbd(fares: list[dict], rbd_sort_order: list[str] = None) -> dict:
    """
    Group parsed fares by RBD, extracting both OW and RT fares for each RBD,
    and capturing the lowest fare amount for each type.
    
    Returns:
        Dict keyed by RBD -> {
            'rbd': str,
            'ow_fare': float/None,
            'rt_fare': float/None,
            'ow_fare_basis': str/None,
            'rt_fare_basis': str/None
        }
    """
    rbd_data = {}
    
    for fare in fares:
        rbd = fare['rbd']
        
        if rbd not in rbd_data:
            rbd_data[rbd] = {
                'rbd': rbd,
                'ow_fare': None,
                'rt_fare': None,
                'ow_fare_basis': None,
                'rt_fare_basis': None
            }
            
        if fare['is_rt']:
            if rbd_data[rbd]['rt_fare'] is None or fare['fare'] < rbd_data[rbd]['rt_fare']:
                rbd_data[rbd]['rt_fare'] = fare['fare']
                basis = fare['fare_basis']
                if fare.get('is_unsaleable'):
                    basis += " (Unsaleable)"
                rbd_data[rbd]['rt_fare_basis'] = basis
        else: # is OW
            if rbd_data[rbd]['ow_fare'] is None or fare['fare'] < rbd_data[rbd]['ow_fare']:
                rbd_data[rbd]['ow_fare'] = fare['fare']
                basis = fare['fare_basis']
                if fare.get('is_unsaleable'):
                    basis += " (Unsaleable)"
                rbd_data[rbd]['ow_fare_basis'] = basis
    
    # Sort by RBD order
    if rbd_sort_order:
        def sort_key(item):
            try:
                return rbd_sort_order.index(item[0])
            except ValueError:
                return len(rbd_sort_order)
        rbd_data = dict(sorted(rbd_data.items(), key=sort_key))
    else:
        rbd_data = dict(sorted(rbd_data.items()))
    
    return rbd_data


def generate_file_key(command_info: dict) -> str:
    """
    Generate a consistent file key for a command.
    Used for naming raw data text files.
    
    Example: FDDACMLE/BG -> BG_DAC-MLE
    """
    return f"{command_info['airline']}_{command_info['route']}"


if __name__ == '__main__':
    # Quick test with sample data
    print("=== Command parsing ===")
    test_cmds = ["FDDACMLE/BG", "FDMLEDAC/BG"]
    for c in test_cmds:
        parsed = parse_command(c)
        print(f"  {c} -> {parsed}")
    
    print("\n=== Fare display parsing ===")
    sample = """FARES LAST UPDATED 14MAR 17:04 P
BG        DAC CGP DEPART 14MAR
**ADDITIONAL TAXES/FEES MAY APPLY**
PUBLIC FARES
BDT CURRENCY FARES EXIST
    CX   FARE   FARE   C AP MIN/    SEASONS...... MR GI DT
         USD    BASIS       MAX
DACCGP
  1 -BG  100.00   YOW      Y                            R  EH
  2  BG  200.00R  JRT      J                            R  EH
  3 -BG  150.00   COW      C                            R  EH
  4  BG  80.00    NOW      N                            R  EH
END"""
    
    fares = parse_fare_display(sample)
    for f in fares:
        rt_marker = "RT" if f['is_rt'] else "OW"
        print(f"  Line {f['line']}: {f['airline']} {f['rbd']} ${f['fare']:.2f} {rt_marker} ({f['fare_basis']})")
    
    print("\n=== Group by RBD ===")
    grouped = group_fares_by_rbd(fares)
    for rbd, data in grouped.items():
        print(f"  {rbd}: OW ${data['ow_fare']} RT ${data['rt_fare']}")
