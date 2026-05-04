"""
change_detector.py - Fare Change Detection

Compares current fare data with previous day's data to detect
price changes, new fares, and removed fares.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger("travelport.change_detector")


def _list_snapshot_names(archive_dir: str) -> list[str]:
    """Return snapshot filenames in reverse-chronological order."""
    if not os.path.exists(archive_dir):
        return []

    snapshots = [
        f
        for f in os.listdir(archive_dir)
        if f.startswith("snapshot_") and f.endswith(".json")
    ]
    snapshots.sort(reverse=True)
    return snapshots


def _load_snapshot_file(filepath: str, snapshot_name: str) -> Optional[dict]:
    """Load a single snapshot file, returning None when it is invalid.

    Tries UTF-8 first, then UTF-8-sig (handles BOM), then falls back to a
    permissive read with errors='replace' so snapshots written by older
    builds that occasionally used the Windows default code page still load
    instead of aborting the run with UnicodeDecodeError.
    """
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Skipping invalid snapshot '%s': %s", snapshot_name, e)
            return None
        except UnicodeDecodeError:
            continue

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        logger.warning(
            "Snapshot '%s' had non-UTF-8 bytes; loaded with replacement characters.",
            snapshot_name,
        )
        return data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Skipping invalid snapshot '%s': %s", snapshot_name, e)
        return None


def _normalize_snapshot_reference(reference: str) -> tuple[str, bool]:
    """Normalize a user-provided snapshot reference to filename timestamp format."""
    raw_reference = (reference or "").strip()
    if not raw_reference:
        raise ValueError("Snapshot reference cannot be empty.")

    formats = [
        ("%Y-%m-%d_%H%M", True),
        ("%Y-%m-%d %H%M", True),
        ("%Y-%m-%d %H:%M", True),
        ("%Y-%m-%dT%H%M", True),
        ("%Y-%m-%dT%H:%M", True),
        ("%Y-%m-%d", False),
    ]

    for fmt, has_time in formats:
        try:
            parsed = datetime.strptime(raw_reference, fmt)
            normalized = parsed.strftime("%Y-%m-%d_%H%M" if has_time else "%Y-%m-%d")
            return normalized, has_time
        except ValueError:
            continue

    raise ValueError("Invalid snapshot reference. Use YYYY-MM-DD or YYYY-MM-DD_HHMM.")


def detect_changes(current_data: dict, previous_data: dict) -> dict:
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
    all_routes = current_data.keys() | previous_data.keys()

    for route_key in all_routes:
        route_changes = {}

        # Handle both old format (direct rbd_data) and new format (nested dict)
        curr_entry = current_data.get(route_key, {})
        prev_entry = previous_data.get(route_key, {})

        # Support new format: {'rbd_data': ..., 'currency': ...}
        curr_route = (
            curr_entry.get("rbd_data", curr_entry)
            if isinstance(curr_entry, dict) and "rbd_data" in curr_entry
            else curr_entry
        )
        prev_route = (
            prev_entry.get("rbd_data", prev_entry)
            if isinstance(prev_entry, dict) and "rbd_data" in prev_entry
            else prev_entry
        )

        all_rbds = curr_route.keys() | prev_route.keys()

        for rbd in all_rbds:
            curr = curr_route.get(rbd)
            prev = prev_route.get(rbd)

            if curr and not prev:
                # New fare/RBD
                route_changes[rbd] = {
                    "type": "new",
                    "old_ow_fare": None,
                    "new_ow_fare": curr.get("ow_fare"),
                    "old_rt_fare": None,
                    "new_rt_fare": curr.get("rt_fare"),
                }
            elif prev and not curr:
                # Sold Out — RBD disappeared, keep previous values
                route_changes[rbd] = {
                    "type": "sold_out",
                    "old_ow_fare": prev.get("ow_fare"),
                    "new_ow_fare": None,
                    "old_rt_fare": prev.get("rt_fare"),
                    "new_rt_fare": None,
                }
            elif curr and prev:
                # Check for price changes
                ow_changed = curr.get("ow_fare") != prev.get("ow_fare")
                rt_changed = curr.get("rt_fare") != prev.get("rt_fare")

                if ow_changed or rt_changed:
                    # Determine direction of change (using OW as primary indicator)
                    curr_ow = curr.get("ow_fare") or 0
                    prev_ow = prev.get("ow_fare") or 0
                    curr_rt = curr.get("rt_fare") or 0
                    prev_rt = prev.get("rt_fare") or 0

                    if curr_ow > prev_ow or curr_rt > prev_rt:
                        change_type = "increased"
                    elif curr_ow < prev_ow or curr_rt < prev_rt:
                        change_type = "decreased"
                    else:
                        change_type = "changed"

                    route_changes[rbd] = {
                        "type": change_type,
                        "old_ow_fare": prev.get("ow_fare"),
                        "new_ow_fare": curr.get("ow_fare"),
                        "old_rt_fare": prev.get("rt_fare"),
                        "new_rt_fare": curr.get("rt_fare"),
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
        date_str = datetime.now().strftime("%Y-%m-%d")

    os.makedirs(archive_dir, exist_ok=True)

    filepath = os.path.join(archive_dir, f"snapshot_{date_str}.json")
    temp_filepath = f"{filepath}.tmp"

    # Write compact JSON to a temp file first so interrupted saves do not leave
    # behind a partially written snapshot.
    with open(temp_filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    os.replace(temp_filepath, filepath)

    return filepath


def snapshot_has_changed(current_data: dict, previous_data: Optional[dict]) -> bool:
    """
    Return True when the current snapshot differs from the previous archive.

    Identical snapshots do not need a new timestamped archive file.
    """
    if previous_data is None:
        return True

    return current_data != previous_data


def load_latest_snapshot(archive_dir: str) -> Optional[dict]:
    """
    Load the most recent snapshot from the archive directory.

    Returns:
        The parsed data dict, or None if no snapshots exist.
    """
    snapshots = _list_snapshot_names(archive_dir)
    if not snapshots:
        return None

    for snapshot_name in snapshots:
        filepath = os.path.join(archive_dir, snapshot_name)
        snapshot_data = _load_snapshot_file(filepath, snapshot_name)
        if snapshot_data is not None:
            return snapshot_data

    return None


def load_snapshot_by_reference(
    archive_dir: str, reference: str
) -> tuple[Optional[dict], Optional[str]]:
    """
    Load a specific archived snapshot by date or date+time reference.

    Args:
        archive_dir: Snapshot archive directory.
        reference: YYYY-MM-DD for the latest snapshot on that day, or
            YYYY-MM-DD_HHMM for an exact timestamp match.

    Returns:
        Tuple of (parsed snapshot data, snapshot id without prefix/suffix).
    """
    # If reference is a direct file path, load it directly.
    # Special case: when the user browses to an xlsx report instead of the
    # snapshot JSON, try to find the companion snapshot by extracting the
    # YYYY-MM-DD_HHMM timestamp from the xlsx filename and looking in the
    # archive directory.
    if os.path.isfile(reference):
        if reference.lower().endswith(".xlsx"):
            m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{4})", os.path.basename(reference))
            if m:
                ts = m.group(1)
                snap_name = f"snapshot_{ts}.json"
                # Check the current archive dir and all sibling dirs (the
                # archive root has tax/ and fare/ subdirs — scan both so the
                # lookup works regardless of which mode the user ran).
                candidate_dirs = [archive_dir]
                archive_root = os.path.dirname(archive_dir)
                if os.path.isdir(archive_root):
                    try:
                        candidate_dirs += [
                            os.path.join(archive_root, d)
                            for d in os.listdir(archive_root)
                            if os.path.isdir(os.path.join(archive_root, d))
                        ]
                    except OSError:
                        pass
                for cdir in candidate_dirs:
                    snap_path = os.path.join(cdir, snap_name)
                    if os.path.isfile(snap_path):
                        snapshot_data = _load_snapshot_file(snap_path, snap_name)
                        if snapshot_data is not None:
                            return snapshot_data, ts
            logger.warning(
                "The 'Compare against' path is an xlsx report; the matching "
                "snapshot JSON was not found in the archive. Use a date "
                "(YYYY-MM-DD) or a snapshot_*.json file from data/archive/fare/."
            )
            return None, None
        snapshot_data = _load_snapshot_file(reference, os.path.basename(reference))
        snapshot_id = os.path.basename(reference).removeprefix("snapshot_").removesuffix(".json")
        return snapshot_data, snapshot_id

    snapshots = _list_snapshot_names(archive_dir)
    if not snapshots:
        return None, None

    normalized_reference, has_time = _normalize_snapshot_reference(reference)
    matching_snapshots = []

    for snapshot_name in snapshots:
        snapshot_id = snapshot_name.removeprefix("snapshot_").removesuffix(".json")
        if has_time:
            if snapshot_id == normalized_reference:
                matching_snapshots.append(snapshot_name)
        elif snapshot_id.startswith(normalized_reference):
            matching_snapshots.append(snapshot_name)

    for snapshot_name in matching_snapshots:
        filepath = os.path.join(archive_dir, snapshot_name)
        snapshot_data = _load_snapshot_file(filepath, snapshot_name)
        if snapshot_data is not None:
            snapshot_id = snapshot_name.removeprefix("snapshot_").removesuffix(".json")
            return snapshot_data, snapshot_id

    return None, None


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
            change_type = change["type"].upper()

            old_ow = (
                f"${change['old_ow_fare']:.2f}" if change.get("old_ow_fare") else "N/A"
            )
            new_ow = (
                f"${change['new_ow_fare']:.2f}" if change.get("new_ow_fare") else "N/A"
            )
            old_rt = (
                f"${change['old_rt_fare']:.2f}" if change.get("old_rt_fare") else "N/A"
            )
            new_rt = (
                f"${change['new_rt_fare']:.2f}" if change.get("new_rt_fare") else "N/A"
            )

            lines.append(
                f"  {rbd}: [{change_type}] OW: {old_ow} -> {new_ow} | RT: {old_rt} -> {new_rt}"
            )

        lines.append("")

    lines.append(f"Total changes: {total_changes}")

    return "\n".join(lines)


def _extract_rates(tax_data: dict) -> dict:
    """Build a lookup dict from tax sections: (section_label, condition) -> (section, rate)."""
    rates = {}
    for section in tax_data.get("sections", []):
        category = section.get("category", "")
        subcategory = section.get("subcategory", "")
        section_label = f"{category} {subcategory}".strip()
        for rate in section.get("rates", []):
            condition = rate.get("condition", "")
            rates[(section_label, condition)] = (section, rate)
    return rates


def detect_tax_changes(current_data: dict, previous_data: dict) -> dict:
    """
    Compare current tax data with previous data and detect changes.

    Data format: airport_code -> {'taxes': [tax_type_data...]}
    Each tax_type has sections with rates.

    Returns:
        Dict mapping airport_code -> tax_code -> [change_info]
        change_info has keys: type ('new'|'removed'|'amount_changed'),
                              section, condition, old_amount, new_amount, currency
    """
    changes = {}

    # Check all airports in current and previous data
    all_airports = current_data.keys() | previous_data.keys()

    for airport_code in all_airports:
        curr_airport = current_data.get(airport_code, {})
        prev_airport = previous_data.get(airport_code, {})

        curr_taxes = curr_airport.get("taxes", [])
        prev_taxes = prev_airport.get("taxes", [])

        # Create lookup: tax_code -> tax_type_data
        curr_tax_dict = {t.get("code"): t for t in curr_taxes if t.get("code")}
        prev_tax_dict = {t.get("code"): t for t in prev_taxes if t.get("code")}

        all_tax_codes = curr_tax_dict.keys() | prev_tax_dict.keys()

        airport_changes = {}

        for tax_code in all_tax_codes:
            curr_tax = curr_tax_dict.get(tax_code)
            prev_tax = prev_tax_dict.get(tax_code)

            tax_changes = []

            if curr_tax and not prev_tax:
                # Entire tax type is new
                for section in curr_tax.get("sections", []):
                    category = section.get("category", "")
                    subcategory = section.get("subcategory", "")
                    section_label = f"{category} {subcategory}".strip()

                    for rate in section.get("rates", []):
                        tax_changes.append(
                            {
                                "type": "new",
                                "section": section_label,
                                "condition": rate.get("condition", ""),
                                "old_amount": None,
                                "new_amount": rate.get("amount"),
                                "currency": rate.get("currency", ""),
                                "status": rate.get("status", ""),
                            }
                        )

            elif prev_tax and not curr_tax:
                # Entire tax type removed
                for section in prev_tax.get("sections", []):
                    category = section.get("category", "")
                    subcategory = section.get("subcategory", "")
                    section_label = f"{category} {subcategory}".strip()

                    for rate in section.get("rates", []):
                        tax_changes.append(
                            {
                                "type": "removed",
                                "section": section_label,
                                "condition": rate.get("condition", ""),
                                "old_amount": rate.get("amount"),
                                "new_amount": None,
                                "currency": rate.get("currency", ""),
                                "status": rate.get("status", ""),
                            }
                        )

            elif curr_tax and prev_tax:
                # Compare sections and rates within this tax type
                curr_rates = _extract_rates(curr_tax)
                prev_rates = _extract_rates(prev_tax)

                all_rate_keys = curr_rates.keys() | prev_rates.keys()

                for rate_key in all_rate_keys:
                    section_label, condition = rate_key
                    curr_entry = curr_rates.get(rate_key)
                    prev_entry = prev_rates.get(rate_key)

                    if curr_entry and not prev_entry:
                        # New rate
                        section, rate = curr_entry
                        tax_changes.append(
                            {
                                "type": "new",
                                "section": section_label,
                                "condition": condition,
                                "old_amount": None,
                                "new_amount": rate.get("amount"),
                                "currency": rate.get("currency", ""),
                                "status": rate.get("status", ""),
                            }
                        )

                    elif prev_entry and not curr_entry:
                        # Removed rate
                        section, rate = prev_entry
                        tax_changes.append(
                            {
                                "type": "removed",
                                "section": section_label,
                                "condition": condition,
                                "old_amount": rate.get("amount"),
                                "new_amount": None,
                                "currency": rate.get("currency", ""),
                                "status": rate.get("status", ""),
                            }
                        )

                    elif curr_entry and prev_entry:
                        # Compare amounts
                        _, curr_rate = curr_entry
                        _, prev_rate = prev_entry

                        curr_amt = curr_rate.get("amount")
                        prev_amt = prev_rate.get("amount")

                        # Convert to float for comparison
                        try:
                            curr_amt_float = float(curr_amt) if curr_amt else 0
                            prev_amt_float = float(prev_amt) if prev_amt else 0

                            if curr_amt_float != prev_amt_float:
                                tax_changes.append(
                                    {
                                        "type": "amount_changed",
                                        "section": section_label,
                                        "condition": condition,
                                        "old_amount": prev_amt,
                                        "new_amount": curr_amt,
                                        "currency": curr_rate.get("currency", ""),
                                        "status": curr_rate.get("status", ""),
                                    }
                                )
                        except (ValueError, TypeError):
                            # Skip if amounts aren't numeric
                            pass

            if tax_changes:
                if airport_code not in changes:
                    changes[airport_code] = {}
                changes[airport_code][tax_code] = tax_changes

    return changes


def detect_fs_tax_changes(current_data: dict, previous_data: dict) -> dict:
    """Compare FS tax breakdown data between fare-mode runs.

    Detects when tax data is gained, lost, or when key charges change between
    snapshots.  Works on the same ``all_route_data`` dict that ``detect_changes``
    operates on; reads the ``fs_taxes`` sub-key that ``detect_changes`` ignores.

    Returns:
        Dict mapping route_key -> change_info.
        change_info contains one of:
          - ``{"status": "tax_data_lost"}``   — prev had data, curr doesn't
          - ``{"status": "tax_data_gained"}`` — curr has data, prev didn't
          - field-level diffs: ``{field: {"old": v, "new": v}, ...}``
    """
    changes: dict = {}
    all_routes = current_data.keys() | previous_data.keys()

    for route_key in all_routes:
        curr_entry = current_data.get(route_key, {})
        prev_entry = previous_data.get(route_key, {})

        curr_taxes: dict = (
            curr_entry.get("fs_taxes", {}) if isinstance(curr_entry, dict) else {}
        )
        prev_taxes: dict = (
            prev_entry.get("fs_taxes", {}) if isinstance(prev_entry, dict) else {}
        )

        # Skip routes where neither run had any tax data — nothing to compare.
        if not curr_taxes and not prev_taxes:
            continue

        if prev_taxes and not curr_taxes:
            changes[route_key] = {"status": "tax_data_lost"}
            continue

        if curr_taxes and not prev_taxes:
            changes[route_key] = {"status": "tax_data_gained"}
            continue

        route_changes: dict = {}
        for field in ("yq_charge", "yr_charge", "q_charge", "total_taxes"):
            curr_val = curr_taxes.get(field) or 0
            prev_val = prev_taxes.get(field) or 0
            try:
                if float(curr_val) != float(prev_val):
                    route_changes[field] = {"old": prev_val, "new": curr_val}
            except (TypeError, ValueError):
                pass

        if route_changes:
            changes[route_key] = route_changes

    return changes


def format_fs_tax_change_summary(changes: dict) -> str:
    """Format FS tax breakdown changes into a human-readable summary."""
    if not changes:
        return "No FS tax changes detected from previous data."

    lines = ["=" * 50, "FS TAX BREAKDOWN CHANGES", "=" * 50, ""]

    total = 0
    for route_key, route_changes in changes.items():
        status = route_changes.get("status")
        if status == "tax_data_lost":
            lines.append(f"  {route_key}: TAX DATA LOST (FS extraction failed this run)")
            total += 1
        elif status == "tax_data_gained":
            lines.append(f"  {route_key}: Tax data now available (was missing previously)")
            total += 1
        else:
            parts = []
            for field, diff in route_changes.items():
                parts.append(f"{field}: {diff['old']} -> {diff['new']}")
            lines.append(f"  {route_key}: {', '.join(parts)}")
            total += 1

    lines.append("")
    lines.append(f"Total: {total} route(s) with FS tax changes")
    return "\n".join(lines)


def format_tax_change_summary(changes: dict) -> str:
    """
    Format tax changes into a human-readable summary string.
    """
    if not changes:
        return "No changes detected from previous tax data."

    lines = ["=" * 50, "TAX CHANGES SUMMARY", "=" * 50, ""]

    total_changes = 0
    for airport_code, airport_changes in changes.items():
        lines.append(f"Airport: {airport_code}")
        lines.append("-" * 30)

        for tax_code, tax_changes in airport_changes.items():
            lines.append(f"  Tax: {tax_code}")

            for change in tax_changes:
                total_changes += 1
                change_type = change["type"].upper()
                section = change.get("section", "")
                condition = change.get("condition", "")
                currency = change.get("currency", "")

                old_amt = (
                    f"{currency} {change['old_amount']}"
                    if change.get("old_amount")
                    else "N/A"
                )
                new_amt = (
                    f"{currency} {change['new_amount']}"
                    if change.get("new_amount")
                    else "N/A"
                )

                lines.append(
                    f"    [{change_type}] {section} | {condition}: {old_amt} -> {new_amt}"
                )

        lines.append("")

    lines.append(f"Total changes: {total_changes}")

    return "\n".join(lines)


