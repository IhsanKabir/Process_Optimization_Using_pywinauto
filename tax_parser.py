"""
tax_parser.py - FTAX Tax Display Output Parser

Parses raw text output from Travelport Smartpoint FTAX commands
into structured data for tax report generation.

Command flow:
  FTAX-SG          → list of tax types for Singapore
  FTAX-SG/L7       → detail for tax type L7
  MD               → paginate through details
"""

import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger('travelport.tax_parser')


def parse_ftax_list(raw_text: str) -> list[dict]:
    """
    Parse the output of FTAX-{CC} to extract available tax type codes.
    
    Example lines:
        L7 - AIRPORT DEVELOPMENT LEVY        SIN
        OP - PASSENGER SERVICE CHARGE         SIN
        C8 - AVIATION LEVY                    SIN
    
    Returns list of: {'code': 'L7', 'name': 'AIRPORT DEVELOPMENT LEVY', 'airports': 'SIN'}
    """
    tax_types = []
    lines = raw_text.strip().split('\n')
    
    # Pattern expects format like:
    # AIRPORT DEVELOPMENT LEVY              >FTAX-SG/L7·
    # Name...                              >FTAX-{CC}/{CODE}[junk]
    pattern = re.compile(r'(.+?)>FTAX-[A-Z]{2}/([A-Z0-9]{2,3})')
    
    for line in lines:
        match = pattern.search(line.strip())
        if match:
            name = match.group(1).strip()
            code = match.group(2).strip()
            
            tax_types.append({
                'code': code,
                'name': name,
                'airports': '' # Airport info isn't in this format
            })
    
    return tax_types


def parse_ftax_detail(raw_text: str, tax_code: str = '', tax_name: str = '') -> dict:
    """
    Parse the output of FTAX-{CC}/{TYPE} (after MD pagination) 
    into structured tax rate data.
    
    The input may contain multiple pages joined by '--- PAGE BREAK ---'.
    Each page is a Ctrl+A/Ctrl+C capture, so pages may have overlapping content.
    
    The FTAX detail output has this structure:
        TAX RATE section header
        Departure category headers (e.g., "DEPARTURES FROM CHANGI SIN")
        Terminal groupings (e.g., "INTERNATIONAL DEPARTURES FROM TERMINAL 1 2 3")
        Condition lines with amounts (e.g., "-TKT ON/BEFORE 31MAR25    SGD 46.40")
    
    Returns:
        {
            'code': 'L7',
            'name': 'AIRPORT DEVELOPMENT LEVY',
            'sections': [
                {
                    'category': 'DEPARTURES FROM CHANGI SIN',
                    'subcategory': 'INTERNATIONAL DEPARTURES FROM TERMINAL 1 2 3',
                    'rates': [
                        {
                            'condition': 'TKT ON/BEFORE 31MAR25',
                            'currency': 'SGD',
                            'amount': 46.40,
                            'status': 'expired' | 'current' | 'future'
                        },
                        ...
                    ]
                }
            ]
        }
    """
    result = {
        'code': tax_code,
        'name': tax_name,
        'sections': []
    }
    
    # Combine all pages into one stream of lines, removing page break markers
    # and deduplicating lines that appear in overlapping page captures
    all_lines = []
    seen_lines = set()
    
    for line in raw_text.split('\n'):
        stripped = line.strip()
        if stripped == '--- PAGE BREAK ---':
            continue
        if not stripped:
            continue
        # Deduplicate: skip lines we've already seen, unless they're rate lines
        # (rate lines with amounts can repeat legitimately for different categories)
        amount_match_check = re.search(r'(?:\s|^)[A-Z]{3}\s*\d+(?:\.\d+)?\s*$', stripped)
        line_key = stripped.rstrip()
        if not amount_match_check and line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        all_lines.append(stripped)
    
    in_tax_rate = False
    seen_tax_rate_block = False
    current_category = ''
    current_subcategory = ''
    current_rates = []
    pending_condition = ''  # For multi-line conditions
    
    # Amount pattern: e.g. "SGD 46.40" or "SGD10.00" (no space) at the end of the line
    amount_pattern = re.compile(r'(?:\s|^)([A-Z]{3})\s*(\d+(?:\.\d+)?)\s*$')
    
    for i, stripped in enumerate(all_lines):
        upper = stripped.upper()
        
        # Detect TAX RATE section (multiple possible formats)
        entry_headers = ['TAX RATE', 'TAX RATES', 'TAX ASSESSMENT', 'TAXES APPLY']
        if any(h in upper for h in entry_headers) and not amount_pattern.search(stripped):
            in_tax_rate = True
            seen_tax_rate_block = True
            continue
        
        # Fallback entry: if we see "ADULTS" or "CHILDREN" with an amount, force entry
        if not in_tax_rate and any(k in upper for k in ['ADULTS', 'CHILDREN', 'INFANTS']):
            if amount_pattern.search(stripped):
                in_tax_rate = True
                seen_tax_rate_block = True
                # Don't continue; let it parse this line as a rate below
        
        if not in_tax_rate:
            # Try to extract tax name from header if we don't have it
            if not result['name'] and result['code']:
                name_match = re.search(
                    rf'{re.escape(result["code"])}\s*[-–]\s+(.+)',
                    stripped
                )
                if name_match:
                    result['name'] = name_match.group(1).strip()
            continue
        
        # Skip noise lines
        if upper in ('END', 'MD', ')>', '>', '', '.'):
            continue
        if upper.startswith('FTAX'):
            continue
        if upper == 'INVALID':
            continue
        # Skip EXEMPTIONS section and everything after it (not rate data)
        if upper.startswith('EXEMPTIONS'):
            # BUT only if we've ACTUALLY seen the tax rate!
            if seen_tax_rate_block:
                # If we already have rates, save the current section first
                if current_rates:
                    result['sections'].append({
                        'category': current_category,
                        'subcategory': current_subcategory,
                        'rates': current_rates
                    })
                    current_rates = []
                in_tax_rate = False  # Stop parsing rates until next TAX RATE
            continue
        # Skip other FTAX metadata sections
        if any(upper.startswith(prefix) for prefix in [
            'TAX CODE:', 'TAX DEFINITION:', 'TAX SPECIAL:', 'TAX COMMENTS:',
            'TAX APPLICATION:', 'NAME OF COUNTRY:', 'NAME OF TAX:',
            '***', '//1A.'
        ]):
            continue
        
        # Check if this line has an amount (currency + number)
        amount_match = amount_pattern.search(stripped)
        
        if amount_match:
            currency = amount_match.group(1)
            amount = float(amount_match.group(2))
            
            # Extract the condition text (everything before the currency)
            condition_text = stripped[:amount_match.start()].strip()
            
            # Handle multi-line conditions:
            # previous line might be the start (e.g., "TVL ON/AFTER 01APR28 AND")
            if pending_condition:
                condition_text = f"{pending_condition} {condition_text}"
                pending_condition = ''
            
            # Clean up condition: remove leading dash/hyphen
            condition_text = re.sub(r'^[-–]\s*', '', condition_text).strip()
            
            # Determine status based on dates in the condition
            status = _determine_status(condition_text)
            
            current_rates.append({
                'condition': condition_text,
                'currency': currency,
                'amount': amount,
                'status': status
            })
        
        elif upper.endswith('AND'):
            # Multi-line condition: "TVL ON/AFTER 01APR28 AND" → next line has the rest
            text = re.sub(r'^[-–]\s*', '', stripped).strip()
            pending_condition = text
        
        elif _is_category_line(stripped):
            # Save previous section if it has rates
            if current_rates:
                result['sections'].append({
                    'category': current_category,
                    'subcategory': current_subcategory,
                    'rates': current_rates
                })
                current_rates = []
            
            # Determine if this is a category or subcategory
            if _is_main_category(stripped):
                current_category = stripped
                current_subcategory = ''
            else:
                current_subcategory = stripped
    
    # Don't forget the last section
    if current_rates:
        result['sections'].append({
            'category': current_category,
            'subcategory': current_subcategory,
            'rates': current_rates
        })
    
    # Debug logging if nothing was extracted
    if not result['sections']:
        logger.warning(f"    parse_ftax_detail: 0 sections for {tax_code}. "
                       f"in_tax_rate reached: {in_tax_rate}, "
                       f"total lines processed: {len(all_lines)}")
        if all_lines:
            logger.debug(f"    First 10 lines: {all_lines[:10]}")
    
    return result


def _is_category_line(line: str) -> bool:
    """Check if a line is a category/subcategory header (no amount, descriptive text)."""
    upper = line.strip().upper()
    
    # Skip very short lines or noise
    if len(upper) < 3:
        return False
    
    # Airport code pattern: "SIN - CHANGI", "XSP", "SELETAR XSP"
    airport_pattern = re.match(r'^[A-Z]{3}\s*[-–]\s+[A-Z]', upper)
    if airport_pattern:
        return True
    
    # Category indicators
    category_keywords = [
        'DEPARTURES', 'ARRIVALS', 'INTERNATIONAL', 'DOMESTIC',
        'TERMINAL', 'TRANSIT', 'TRANSFER', 'PASSENGER',
        'EMBARKATION', 'APPLICABLE', 'EXEMPT', 'EXCEPT',
        'SELETAR', 'ADULTS', 'CHILDREN', 'INFANTS', 'PERSON', 'FLIGHTS.'
    ]
    
    # Must contain a keyword and NOT contain an amount at the end
    has_keyword = any(kw in upper for kw in category_keywords)
    has_amount = bool(re.search(r'(?:\s|^)[A-Z]{3}\s*\d+\.\d+\s*$', upper))
    
    return has_keyword and not has_amount


def _is_main_category(line: str) -> bool:
    """Check if this is a top-level category (e.g., DEPARTURES FROM CHANGI SIN)."""
    upper = line.strip().upper()
    # Airport code pattern like "SIN - CHANGI" is a main location
    if re.match(r'^[A-Z]{3}\s*[-–]\s+[A-Z]', upper):
        return True
    return ('DEPARTURES FROM' in upper or 'ARRIVALS AT' in upper or
            'DEPARTURES' == upper or 'ARRIVALS' == upper)


def _determine_status(condition: str) -> str:
    """
    Determine if a tax rate is expired, current, or future based on
    date conditions in the text.
    
    Examples:
        "TKT ON/BEFORE 31MAR25"          → expired (past date)
        "TVL ON/AFTER 01APR25 AND ON/BEFORE 31MAR27" → current (includes today)
        "TVL ON/AFTER 01APR29"            → future
    """
    today = datetime.now()
    
    # Extract all dates from the condition
    date_pattern = re.compile(r'(\d{2})([A-Z]{3})(\d{2,4})')
    dates = []
    for match in date_pattern.finditer(condition.upper()):
        day = int(match.group(1))
        month_str = match.group(2)
        year_str = match.group(3)
        
        month_map = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        
        month = month_map.get(month_str)
        if not month:
            continue
        
        year = int(year_str)
        if year < 100:
            year += 2000
        
        try:
            dates.append(datetime(year, month, day))
        except ValueError:
            continue
    
    if not dates:
        return 'current'  # No dates = always applicable
    
    upper_cond = condition.upper()
    
    if 'ON/BEFORE' in upper_cond and 'ON/AFTER' not in upper_cond:
        # Pure "on/before" → expired if the date is past
        end_date = max(dates)
        return 'expired' if today > end_date else 'current'
    
    if 'ON/AFTER' in upper_cond and 'ON/BEFORE' not in upper_cond:
        # Pure "on/after" → future if start date is in the future
        start_date = min(dates)
        return 'future' if today < start_date else 'current'
    
    if 'ON/AFTER' in upper_cond and 'ON/BEFORE' in upper_cond:
        # Range: on/after X and on/before Y
        start_date = min(dates)
        end_date = max(dates)
        if today < start_date:
            return 'future'
        elif today > end_date:
            return 'expired'
        else:
            return 'current'
    
    return 'current'


def get_current_rate(sections: list[dict]) -> Optional[dict]:
    """
    From a list of sections, find the currently applicable rate.
    Returns the first rate with status='current', or None.
    """
    for section in sections:
        for rate in section.get('rates', []):
            if rate.get('status') == 'current':
                return rate
    return None


def get_next_rate(sections: list[dict]) -> Optional[dict]:
    """
    From a list of sections, find the next upcoming rate change.
    Returns the first rate with status='future', or None.
    """
    for section in sections:
        for rate in section.get('rates', []):
            if rate.get('status') == 'future':
                return rate
    return None


if __name__ == '__main__':
    # Quick test with sample FTAX output
    sample_list = """
THE FOLLOWING TAX ASSESSMENTS APPLY TO SINGAPORE:
AIRPORT DEVELOPMENT LEVY                >FTAX-SG/L7·
AVIATION LEVY                           >FTAX-SG/OP·
PASSENGER SERVICE CHARGE                >FTAX-SG/SG·
    """
    
    print("=== Tax type list ===")
    types = parse_ftax_list(sample_list)
    for t in types:
        print(f"  {t['code']}: {t['name']} ({t['airports']})")
    
    sample_detail = """
FTAX-SG/L7
L7 - AIRPORT DEVELOPMENT LEVY
TAX RATE
    DEPARTURES FROM CHANGI SIN
    INTERNATIONAL DEPARTURES FROM
    TERMINAL 1 2 3
    -TKT/TVL ON/BEFORE 31MAR25              SGD 46.40
    -TKT ON/AFTER 01JAN25 AND
     TVL ON/AFTER 01APR25 AND
     ON/BEFORE 31MAR27                       SGD 46.40
    TLV ON/AFTER 01APR27 AND
     ON/BEFORE 31MAR28                       SGD 49.40
    TVL ON/AFTER 01APR28 AND
     ON/BEFORE 31MAR29                       SGD 52.40
    TVL ON/AFTER 01APR29 AND
END
    """
    
    print("\n=== Tax detail ===")
    detail = parse_ftax_detail(sample_detail, 'L7', 'AIRPORT DEVELOPMENT LEVY')
    for section in detail['sections']:
        print(f"  Category: {section['category']}")
        print(f"  Subcategory: {section['subcategory']}")
        for rate in section['rates']:
            print(f"    {rate['condition']} → {rate['currency']} {rate['amount']} [{rate['status']}]")
