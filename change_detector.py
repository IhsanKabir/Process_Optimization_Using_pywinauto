"""
change_detector.py - Fare Change Detection

Compares current fare data with previous day's data to detect
price changes, new fares, and removed fares.
"""

import json
import os
from datetime import datetime
from typing import Optional


def detect_changes(
    current_data: dict,
    previous_data: dict
) -> dict:
    """
    Compare current fare data with previous data and detect changes.
    
    Data format: route_key -> {'rbd_data': {rbd -> fare_info}, 'currency': str}
    
    Returns:
        Dict mapping route_key -> {rbd -> change_info}
        change_info has keys: type ('new'|'sold_out'|'increased'|'decreased'),
                              old_ow_fare, new_ow_fare, old_rt_fare, new_rt_fare
    """
    changes = {}
    
    # Check all routes in current data
    all_routes = set(list(current_data.keys()) + list(previous_data.keys()))
    
    for route_key in all_routes:
        route_changes = {}
        
        # Handle both old format (direct rbd_data) and new format (nested dict)
        curr_entry = current_data.get(route_key, {})
        prev_entry = previous_data.get(route_key, {})
        
        # Support new format: {'rbd_data': ..., 'currency': ...}
        curr_route = curr_entry.get('rbd_data', curr_entry) if isinstance(curr_entry, dict) and 'rbd_data' in curr_entry else curr_entry
        prev_route = prev_entry.get('rbd_data', prev_entry) if isinstance(prev_entry, dict) and 'rbd_data' in prev_entry else prev_entry
        
        all_rbds = set(list(curr_route.keys()) + list(prev_route.keys()))
        
        for rbd in all_rbds:
            curr = curr_route.get(rbd)
            prev = prev_route.get(rbd)
            
            if curr and not prev:
                # New fare/RBD
                route_changes[rbd] = {
                    'type': 'new',
                    'old_ow_fare': None,
                    'new_ow_fare': curr.get('ow_fare'),
                    'old_rt_fare': None,
                    'new_rt_fare': curr.get('rt_fare'),
                }
            elif prev and not curr:
                # Sold Out — RBD disappeared, keep previous values
                route_changes[rbd] = {
                    'type': 'sold_out',
                    'old_ow_fare': prev.get('ow_fare'),
                    'new_ow_fare': None,
                    'old_rt_fare': prev.get('rt_fare'),
                    'new_rt_fare': None,
                }
            elif curr and prev:
                # Check for price changes
                ow_changed = curr.get('ow_fare') != prev.get('ow_fare')
                rt_changed = curr.get('rt_fare') != prev.get('rt_fare')
                
                if ow_changed or rt_changed:
                    # Determine direction of change (using OW as primary indicator)
                    curr_ow = curr.get('ow_fare') or 0
                    prev_ow = prev.get('ow_fare') or 0
                    curr_rt = curr.get('rt_fare') or 0
                    prev_rt = prev.get('rt_fare') or 0
                    
                    if curr_ow > prev_ow or curr_rt > prev_rt:
                        change_type = 'increased'
                    elif curr_ow < prev_ow or curr_rt < prev_rt:
                        change_type = 'decreased'
                    else:
                        change_type = 'changed'
                    
                    route_changes[rbd] = {
                        'type': change_type,
                        'old_ow_fare': prev.get('ow_fare'),
                        'new_ow_fare': curr.get('ow_fare'),
                        'old_rt_fare': prev.get('rt_fare'),
                        'new_rt_fare': curr.get('rt_fare'),
                    }
        
        if route_changes:
            changes[route_key] = route_changes
    
    return changes



def save_snapshot(data: dict, archive_dir: str, date_str: Optional[str] = None):
    """
    Save a snapshot of the current data for future comparison.
    
    Args:
        data: The grouped fare data to save
        archive_dir: Directory to save snapshots
        date_str: Optional date string (defaults to today)
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    os.makedirs(archive_dir, exist_ok=True)
    
    filepath = os.path.join(archive_dir, f"snapshot_{date_str}.json")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return filepath


def load_latest_snapshot(archive_dir: str) -> Optional[dict]:
    """
    Load the most recent snapshot from the archive directory.
    
    Returns:
        The parsed data dict, or None if no snapshots exist.
    """
    if not os.path.exists(archive_dir):
        return None
    
    snapshots = [
        f for f in os.listdir(archive_dir)
        if f.startswith('snapshot_') and f.endswith('.json')
    ]
    
    if not snapshots:
        return None
    
    # Sort by filename (date-based naming ensures chronological order)
    snapshots.sort(reverse=True)
    latest = snapshots[0]
    
    filepath = os.path.join(archive_dir, latest)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_change_summary(changes: dict) -> str:
    """
    Format changes into a human-readable summary string.
    """
    if not changes:
        return "No changes detected from previous data."
    
    lines = ["=" * 50, "FARE CHANGES SUMMARY", "=" * 50, ""]
    
    total_changes = 0
    for route_key, route_changes in changes.items():
        lines.append(f"Route: {route_key}")
        lines.append("-" * 30)
        
        for rbd, change in route_changes.items():
            total_changes += 1
            change_type = change['type'].upper()
            
            old_ow = f"${change['old_ow_fare']:.2f}" if change.get('old_ow_fare') else "N/A"
            new_ow = f"${change['new_ow_fare']:.2f}" if change.get('new_ow_fare') else "N/A"
            old_rt = f"${change['old_rt_fare']:.2f}" if change.get('old_rt_fare') else "N/A"
            new_rt = f"${change['new_rt_fare']:.2f}" if change.get('new_rt_fare') else "N/A"
            
            lines.append(f"  {rbd}: [{change_type}] OW: {old_ow} -> {new_ow} | RT: {old_rt} -> {new_rt}")
        
        lines.append("")
    
    lines.append(f"Total changes: {total_changes}")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # Quick test
    previous = {
        "BG_DAC-CGP": {
            "Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200},
            "J": {"rbd": "J", "ow_fare": 200, "rt_fare": 400},
            "C": {"rbd": "C", "ow_fare": 150, "rt_fare": 300},
        }
    }
    
    current = {
        "BG_DAC-CGP": {
            "Y": {"rbd": "Y", "ow_fare": 110, "rt_fare": 200},  # OW increased
            "J": {"rbd": "J", "ow_fare": 200, "rt_fare": 400},  # No change
            "D": {"rbd": "D", "ow_fare": 180, "rt_fare": 360},  # New RBD
            # C removed
        }
    }
    
    changes = detect_changes(current, previous)
    print(format_change_summary(changes))
