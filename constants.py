"""
constants.py - Configuration Constants for Travelport Automation

Centralizes all magic numbers, timeouts, and configuration values used
throughout the automation system. These values were empirically determined
through extensive testing and calibration.

Speed Profile System:
  Set SPEED_PROFILE environment variable or pass --speed flag:
    "fast"  — Aggressive timings for maximum speed (default)
    "safe"  — Conservative timings for reliability on slower machines
"""

import os

# ══════════════════════════════════════════════════════════════
# SPEED PROFILE SYSTEM
# ══════════════════════════════════════════════════════════════
# Reads from environment variable; can be overridden by --speed CLI flag.
# The set_speed_profile() function allows runtime switching.

_SPEED_PROFILES = {
    "fast": {
        # UI interaction delays (seconds)
        "FOCUS_DELAY": 0.15,
        "CLICK_DELAY": 0.02,
        "KEYBOARD_INTERVAL": 0.015,
        "COPY_DELAY": 0.05,
        "ESCAPE_CLEAR_DELAY": 0.08,
        "MOUSE_MOVE_DURATION": 0.0,  # Instant movement — no animation needed
        "PAGEDOWN_SCROLL_DELAY": 0.2,
        # Command execution timeouts
        "COMMAND_WAIT_SHORT": 0.3,
        "COMMAND_WAIT_MEDIUM": 0.4,
        "COMMAND_WAIT_LONG": 0.5,
        "COMMAND_WAIT_FS": 0.8,
        "COMMAND_WAIT_FTAX": 1.2,
        "SCREEN_REFRESH_WAIT": 0.6,
        # Retry delays
        "RETRY_DELAY": 1.0,
        "STUCK_SCREEN_RETRY_DELAY": 0.5,
        # Login sequence delays
        "LOGIN_COMMAND_WAIT": 1.0,
        "LOGIN_USERNAME_WAIT": 0.7,
        "LOGIN_COMPLETION_WAIT": 3.0,
    },
    "safe": {
        # UI interaction delays (seconds) — original conservative values
        "FOCUS_DELAY": 0.3,
        "CLICK_DELAY": 0.05,
        "KEYBOARD_INTERVAL": 0.03,
        "COPY_DELAY": 0.1,
        "ESCAPE_CLEAR_DELAY": 0.15,
        "MOUSE_MOVE_DURATION": 0.1,
        "PAGEDOWN_SCROLL_DELAY": 0.4,
        # Command execution timeouts
        "COMMAND_WAIT_SHORT": 0.5,
        "COMMAND_WAIT_MEDIUM": 0.8,
        "COMMAND_WAIT_LONG": 1.0,
        "COMMAND_WAIT_FS": 1.5,
        "COMMAND_WAIT_FTAX": 2.0,
        "SCREEN_REFRESH_WAIT": 1.5,
        # Retry delays
        "RETRY_DELAY": 1.5,
        "STUCK_SCREEN_RETRY_DELAY": 1.0,
        # Login sequence delays
        "LOGIN_COMMAND_WAIT": 1.5,
        "LOGIN_USERNAME_WAIT": 1.0,
        "LOGIN_COMPLETION_WAIT": 4.0,
    },
}

# Active profile name — default "fast"
ACTIVE_SPEED_PROFILE = os.environ.get("SPEED_PROFILE", "fast").lower()
if ACTIVE_SPEED_PROFILE not in _SPEED_PROFILES:
    ACTIVE_SPEED_PROFILE = "fast"


def set_speed_profile(profile: str):
    """Switch speed profile at runtime (called from --speed CLI flag)."""
    global ACTIVE_SPEED_PROFILE
    global FOCUS_DELAY, CLICK_DELAY, KEYBOARD_INTERVAL, COPY_DELAY
    global ESCAPE_CLEAR_DELAY, MOUSE_MOVE_DURATION, PAGEDOWN_SCROLL_DELAY
    global COMMAND_WAIT_SHORT, COMMAND_WAIT_MEDIUM, COMMAND_WAIT_LONG
    global COMMAND_WAIT_FS, COMMAND_WAIT_FTAX, SCREEN_REFRESH_WAIT
    global RETRY_DELAY, STUCK_SCREEN_RETRY_DELAY
    global LOGIN_COMMAND_WAIT, LOGIN_USERNAME_WAIT, LOGIN_COMPLETION_WAIT

    profile = profile.lower()
    if profile not in _SPEED_PROFILES:
        raise ValueError(f"Unknown speed profile '{profile}'. Use 'fast' or 'safe'.")

    ACTIVE_SPEED_PROFILE = profile
    p = _SPEED_PROFILES[profile]

    FOCUS_DELAY = p["FOCUS_DELAY"]
    CLICK_DELAY = p["CLICK_DELAY"]
    KEYBOARD_INTERVAL = p["KEYBOARD_INTERVAL"]
    COPY_DELAY = p["COPY_DELAY"]
    ESCAPE_CLEAR_DELAY = p["ESCAPE_CLEAR_DELAY"]
    MOUSE_MOVE_DURATION = p["MOUSE_MOVE_DURATION"]
    PAGEDOWN_SCROLL_DELAY = p["PAGEDOWN_SCROLL_DELAY"]
    COMMAND_WAIT_SHORT = p["COMMAND_WAIT_SHORT"]
    COMMAND_WAIT_MEDIUM = p["COMMAND_WAIT_MEDIUM"]
    COMMAND_WAIT_LONG = p["COMMAND_WAIT_LONG"]
    COMMAND_WAIT_FS = p["COMMAND_WAIT_FS"]
    COMMAND_WAIT_FTAX = p["COMMAND_WAIT_FTAX"]
    SCREEN_REFRESH_WAIT = p["SCREEN_REFRESH_WAIT"]
    RETRY_DELAY = p["RETRY_DELAY"]
    STUCK_SCREEN_RETRY_DELAY = p["STUCK_SCREEN_RETRY_DELAY"]
    LOGIN_COMMAND_WAIT = p["LOGIN_COMMAND_WAIT"]
    LOGIN_USERNAME_WAIT = p["LOGIN_USERNAME_WAIT"]
    LOGIN_COMPLETION_WAIT = p["LOGIN_COMPLETION_WAIT"]


# Initialize timing constants from the active profile
_p = _SPEED_PROFILES[ACTIVE_SPEED_PROFILE]

FOCUS_DELAY = _p["FOCUS_DELAY"]
CLICK_DELAY = _p["CLICK_DELAY"]
KEYBOARD_INTERVAL = _p["KEYBOARD_INTERVAL"]
COPY_DELAY = _p["COPY_DELAY"]
ESCAPE_CLEAR_DELAY = _p["ESCAPE_CLEAR_DELAY"]
MOUSE_MOVE_DURATION = _p["MOUSE_MOVE_DURATION"]
PAGEDOWN_SCROLL_DELAY = _p["PAGEDOWN_SCROLL_DELAY"]
COMMAND_WAIT_SHORT = _p["COMMAND_WAIT_SHORT"]
COMMAND_WAIT_MEDIUM = _p["COMMAND_WAIT_MEDIUM"]
COMMAND_WAIT_LONG = _p["COMMAND_WAIT_LONG"]
COMMAND_WAIT_FS = _p["COMMAND_WAIT_FS"]
COMMAND_WAIT_FTAX = _p["COMMAND_WAIT_FTAX"]
SCREEN_REFRESH_WAIT = _p["SCREEN_REFRESH_WAIT"]
RETRY_DELAY = _p["RETRY_DELAY"]
STUCK_SCREEN_RETRY_DELAY = _p["STUCK_SCREEN_RETRY_DELAY"]
LOGIN_COMMAND_WAIT = _p["LOGIN_COMMAND_WAIT"]
LOGIN_USERNAME_WAIT = _p["LOGIN_USERNAME_WAIT"]
LOGIN_COMPLETION_WAIT = _p["LOGIN_COMPLETION_WAIT"]

del _p  # Clean up module namespace

# ══════════════════════════════════════════════════════════════
# UI AUTOMATION - COORDINATE-BASED CLICKING
# ══════════════════════════════════════════════════════════════
# NOTE: These values are the result of extensive trial-and-error testing.
# Keyboard navigation (Tab/Enter) was tested but does not work reliably
# for Smartpoint terminal. Coordinate-based clicking is the most stable
# approach for this application.

# Terminal rendering constants
LINE_HEIGHT = 20  # Pixels per line in Smartpoint terminal (monospace font)
CONTENT_TOP_PADDING = 5  # Pixels from terminal pane top to first line of text
BOTTOM_MARGIN = 0  # Pixels at bottom of terminal (text flush against bottom)

# D button click position (empirically calibrated)
# The 'D' (Details) button in FS results is consistently at ~85.5% of terminal width
D_BUTTON_X_RATIO = 0.855  # Horizontal position ratio (0.0=left, 1.0=right)

# Currency link click position
CURRENCY_LINK_X_RATIO = 0.5  # Click center of "BDT CURRENCY FARES EXISTS" link (changed from 0.3 to avoid clicking Fare section header)

# "More Fares/Flights" link position
MORE_LINK_X_RATIO = 0.04  # Click near left edge to avoid airline codes

# Safe click position (for focus without interaction)
SAFE_CLICK_X_OFFSET = 50  # Pixels from left edge
SAFE_CLICK_Y_OFFSET = 30  # Pixels from top edge

# Click retry tolerance offsets (in pixels)
# Used to handle minor positioning errors due to font rendering variations
CLICK_OFFSET_X = [-15, 0, 15]  # Horizontal offsets to try
CLICK_OFFSET_Y_SINGLE = [0, -9, 9, -18, 18]  # Vertical offsets for single-line elements
CLICK_OFFSET_Y_MULTI = [0, -10, 10, -20, 20, -30, 30]  # For multi-line elements
CLICK_OFFSET_D_BUTTON = [
    (0, 0),
    (-15, 0),
    (15, 0),  # Same line, shift X
    (0, -9),
    (0, 9),  # One line up/down
    (-15, -9),
    (15, -9),  # One line up, shift X
    (-15, 9),
    (15, 9),  # One line down, shift X
]

# ══════════════════════════════════════════════════════════════
# PAGINATION & DATA EXTRACTION
# ══════════════════════════════════════════════════════════════

# Pagination limits
MAX_PAGES_FARE = 10  # Maximum pages to fetch for fare display
MAX_PAGES_TAX = 50  # Maximum pages for tax details (can be very long)
MAX_PAGES_UNSALEABLE = 5  # Maximum pages for unsaleable fares (FU*)

# Retry configuration
MAX_RETRIES_COMMAND = 3  # Maximum retry attempts for failed commands
MAX_FS_DATE_STEPS = 37  # Maximum date offsets to try for FS command

# Data validation thresholds
MIN_TERMINAL_TEXT_LENGTH = 50  # Minimum chars for valid terminal response

# FS (Flight Shopping) configuration
FS_DATE_OFFSET_START = 30  # Start checking from roughly 1 month in the future
FS_DATE_STEP = 2  # Days to jump when a date fails (fast: skip alternate days)
FS_EXPANSION_KEYWORDS = [
    "EQU",
    "TAXES",
    "TAX",
    "YQ",
    "FARE",
    "BASIS",
]  # Expected in D expansion

# ══════════════════════════════════════════════════════════════
# LOGGING & OUTPUT
# ══════════════════════════════════════════════════════════════

# Log levels
LOG_LEVEL_CONSOLE = "INFO"
LOG_LEVEL_FILE = "DEBUG"

# File paths (relative to script directory)
LOG_DIRNAME = "data/logs"
RAW_DATA_DIRNAME = "data/raw"
REPORTS_DIRNAME = "data/reports"
ARCHIVE_DIRNAME = "data/archive"

# ══════════════════════════════════════════════════════════════
# VALIDATION LIMITS
# ══════════════════════════════════════════════════════════════

# Input validation
MAX_COMMAND_LENGTH = 200  # Maximum length for GDS terminal commands
MAX_LIMIT_VALUE = 10000  # Maximum value for --limit argument
MIN_USERNAME_LENGTH = 3  # Minimum characters for username
MIN_PASSWORD_LENGTH = 4  # Minimum characters for password
MAX_PCC_LENGTH = 10  # Maximum characters for PCC

# ══════════════════════════════════════════════════════════════
# TERMINAL PATTERNS & KEYWORDS
# ══════════════════════════════════════════════════════════════

# End-of-data signals
END_SIGNAL = "END"
INVALID_SIGNAL = "INVALID"

# Special conditions
MORE_FARES_KEYWORDS = ["MORE FARES", "MORE FLIGHTS", "MORE OPTIONS"]
UNSALEABLE_FARES_KEYWORD = "UNSALEABLE FARES MAY EXIST"

# FTAX-specific
TAX_RATE_SECTION_KEYWORD = "TAX RATE"
TAX_EXEMPTIONS_KEYWORD = "EXEMPTIONS"

# Currency redirect
CURRENCY_FARES_EXISTS_PATTERN = r"([A-Z]{3})\s+CURRENCY\s+FARES?\s+EXISTS?"

# ══════════════════════════════════════════════════════════════
# EXCEL REPORT FORMATTING
# ══════════════════════════════════════════════════════════════

# Sheet names
MAIN_SHEET_NAME = "Side-by-Side Comparison"
INDIVIDUAL_TABLES_SHEET = "Individual Tables"
CURRENCY_CONVERSION_SHEET = "Currency Conversion"
CHANGES_SUMMARY_SHEET = "Changes Summary"

# Color codes (for change highlighting)
COLOR_INCREASE = "FDE9E9"  # Light red background
COLOR_DECREASE = "E2EFDA"  # Light green background
COLOR_NEW = "FFF2CC"  # Light yellow background
COLOR_SOLD_OUT = "D9D9D9"  # Gray background
COLOR_HEADER = "2F5496"  # Blue background
COLOR_ROUTE_HEADER = "D6E4F0"  # Light blue background

# Font colors
FONT_COLOR_INCREASE = "CC0000"  # Red
FONT_COLOR_DECREASE = "006100"  # Green
FONT_COLOR_NEW = "7F6000"  # Dark yellow
FONT_COLOR_SOLD_OUT = "808080"  # Gray
FONT_COLOR_HEADER = "FFFFFF"  # White

# ══════════════════════════════════════════════════════════════
# WINDOW IDENTIFICATION
# ══════════════════════════════════════════════════════════════

# Default window title for Smartpoint application
DEFAULT_WINDOW_TITLE = "Application Window 1"

# UI Automation IDs
TERMINAL_AUTOMATION_ID = "SmartRichTextBox"

# ══════════════════════════════════════════════════════════════
# FOCUS TRACKING
# ══════════════════════════════════════════════════════════════
# Skip redundant focus() calls if focus was set recently
FOCUS_CACHE_SECONDS = 5.0  # Seconds to trust a previous focus() call

# ══════════════════════════════════════════════════════════════
# CALIBRATION NOTES
# ══════════════════════════════════════════════════════════════

CALIBRATION_NOTES = """
IMPORTANT: Coordinate-based Clicking Calibration

The coordinate-based clicking values in this file (LINE_HEIGHT, D_BUTTON_X_RATIO, etc.)
were empirically determined through extensive testing. They represent the most reliable
approach for interacting with the Smartpoint terminal.

Keyboard navigation alternatives (Tab/Enter) were tested extensively but found to be
unreliable for this application. If clicking fails:

1. Verify Smartpoint window is at normal (not maximized/minimized) state
2. Check screen DPI scaling is 100% (Windows Display Settings)
3. Ensure terminal font hasn't changed
4. Run a calibration test to measure LINE_HEIGHT for your environment:
   - Open Smartpoint
   - Note Y-coordinate of first line of text
   - Note Y-coordinate of second line of text
   - LINE_HEIGHT = difference between these values

5. For D_BUTTON_X_RATIO calibration:
   - Open FS results with D button visible
   - Measure terminal width and D button X position
   - D_BUTTON_X_RATIO = (D button X - terminal left) / terminal width

If you need to adjust these values for your environment, create a local configuration
file or set them via environment variables (feature to be added).

SPEED PROFILES:
  Set environment variable SPEED_PROFILE=fast (default) or SPEED_PROFILE=safe
  Or use CLI: python main.py --auto --speed fast
  
  "fast"  — Aggressive timings for max speed (~50% faster)
  "safe"  — Conservative timings for reliability on slower machines
"""
