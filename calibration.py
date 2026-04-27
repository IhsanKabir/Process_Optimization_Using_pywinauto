"""
calibration.py — Per-machine display calibration for Smartpoint UI automation.

LINE_HEIGHT (pixels per terminal line) varies with Windows DPI scaling and font
size. This module auto-computes it from the system DPI and persists any manual
or learned adjustments to %APPDATA%\\TravelportAuto\\calibration.json.

Usage:
    from calibration import load_calibration, save_calibration, reset_calibration

    cal = load_calibration()
    line_height = cal["line_height"]          # use this instead of constants.LINE_HEIGHT
    top_padding = cal["content_top_padding"]
"""

import ctypes
import json
import logging
import os

logger = logging.getLogger("travelport.calibration")

# ── Baseline constants (measured empirically at 96 DPI / 100% scaling) ───────
_BASE_LINE_HEIGHT = 20
_BASE_CONTENT_TOP_PADDING = 5

# ── Storage path ──────────────────────────────────────────────────────────────
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CALIBRATION_PATH = os.path.join(_APPDATA, "TravelportAuto", "calibration.json")

# Max deltas to retain in the rolling window (Phase C)
_MAX_DELTA_HISTORY = 50


# ── DPI helpers ───────────────────────────────────────────────────────────────

def get_system_dpi() -> int:
    """Return the system DPI (96 = 100 % scaling, 120 = 125 %, 144 = 150 %)."""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi and dpi > 0:
            return int(dpi)
    except Exception:
        pass
    return 96


def compute_line_height(dpi: int | None = None) -> int:
    """Return the empirical line height in physical pixels.

    The Smartpoint terminal is DPI-aware and renders its content at the same
    physical pixel size regardless of display scaling — the baseline of 20px
    was measured in physical pixels on the reference machine and is correct
    across DPI scales.  Phase C delta learning handles any per-machine
    deviation from this baseline.
    """
    if dpi is None:
        dpi = get_system_dpi()
    # Store DPI for reference but do not scale the baseline — Smartpoint
    # renders at the same physical line height regardless of display DPI.
    _ = dpi  # kept so callers that pass dpi= still work
    return _BASE_LINE_HEIGHT


# ── Load / save ───────────────────────────────────────────────────────────────

def load_calibration() -> dict:
    """
    Return calibration values for this machine.

    Priority:
      1. Saved calibration.json (user-adjusted or learned values).
      2. Auto-computed from Windows DPI.
      3. Baseline constants as final fallback.
    """
    if os.path.exists(CALIBRATION_PATH):
        try:
            with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "line_height" in data:
                dpi = get_system_dpi()
                baseline_lh = compute_line_height(dpi)
                saved_lh = int(data.get("line_height") or baseline_lh)
                if saved_lh != baseline_lh:
                    logger.warning(
                        f"[CAL] Ignoring saved line_height={saved_lh}; "
                        f"resetting to stable baseline {baseline_lh}."
                    )
                    data["line_height"] = baseline_lh
                    data["dpi"] = dpi
                    data["source"] = "dpi_auto"
                    data["click_deltas"] = []
                    data["delta_correction"] = 0
                    _write(data)
                logger.debug(
                    f"[CAL] Loaded calibration from {CALIBRATION_PATH}: "
                    f"line_height={data['line_height']}, "
                    f"source={data.get('source', '?')}"
                )
                # Ensure all expected keys exist (backwards compat)
                data.setdefault("content_top_padding", _BASE_CONTENT_TOP_PADDING)
                data.setdefault("click_deltas", [])
                data.setdefault("delta_correction", 0)
                return data
        except Exception as exc:
            logger.warning(f"[CAL] Could not read calibration file: {exc}")

    dpi = get_system_dpi()
    lh = compute_line_height(dpi)
    data = {
        "line_height": lh,
        "content_top_padding": _BASE_CONTENT_TOP_PADDING,
        "dpi": dpi,
        "source": "dpi_auto",
        "click_deltas": [],
        "delta_correction": 0,
    }
    logger.debug(f"[CAL] Auto-calibrated from DPI {dpi}: line_height={lh}")
    _write(data)
    return data


def save_calibration(data: dict) -> None:
    """Persist calibration data to disk."""
    _write(data)


def reset_calibration() -> dict:
    """Delete saved calibration and recompute from DPI."""
    if os.path.exists(CALIBRATION_PATH):
        try:
            os.remove(CALIBRATION_PATH)
        except Exception as exc:
            logger.warning(f"[CAL] Could not remove calibration file: {exc}")
    data = load_calibration()
    logger.info(f"[CAL] Calibration reset. New line_height={data['line_height']}")
    return data


# ── Phase C: delta tracking ───────────────────────────────────────────────────

def record_click_delta(calibration: dict, y_offset_used: int) -> dict:
    """
    Record the Y offset that produced a successful click for diagnostics.

    Returns the updated calibration dict (caller should save it).
    """
    deltas: list = list(calibration.get("click_deltas", []))
    deltas.append(y_offset_used)
    if len(deltas) > _MAX_DELTA_HISTORY:
        deltas = deltas[-_MAX_DELTA_HISTORY:]

    calibration["click_deltas"] = deltas
    calibration["delta_correction"] = sum(deltas) / len(deltas) if deltas else 0
    calibration["line_height"] = compute_line_height(calibration.get("dpi"))
    calibration["source"] = "dpi_auto"
    return calibration


def record_d_click_offset(calibration: dict, x_off: int, y_off: int) -> dict:
    """Persist the (x_off, y_off) tuple that produced a successful D-click
    on this machine. Used as a 'try first' starting point on subsequent
    D-clicks so we don't re-execute the full fan-out every time on PCs
    where the default position is consistently off (e.g. the left-bias
    heuristic over-corrects on a 1920x1080 work laptop). Self-correcting
    if the saved offset stops working — control falls through to the
    standard fan-out which then overwrites the saved offset with whatever
    new position succeeds."""
    calibration["d_click_offset"] = [int(x_off), int(y_off)]
    return calibration


def get_d_click_offset(calibration: dict) -> tuple[int, int] | None:
    """Return the previously-saved D-click offset, or None."""
    raw = calibration.get("d_click_offset")
    if isinstance(raw, list) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
    return None


# ── Internal ──────────────────────────────────────────────────────────────────

def _write(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CALIBRATION_PATH), exist_ok=True)
        with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        logger.warning(f"[CAL] Could not write calibration file: {exc}")
