"""
smartpoint_automation.py - Travelport Smartpoint UI Automation

Controls the Travelport Smartpoint terminal using pywinauto.
Connects to the application, sends commands via keyboard, captures output via clipboard,
and handles MD (More Data) pagination automatically.
"""

import re
import time
import logging
import ctypes
import threading
from pywinauto import Desktop
from pywinauto import keyboard as _pw_kb
from pywinauto import mouse as _pw_mouse
from pywinauto.application import Application as _PWApp
from clipboard_util import clipboard_paste, clipboard_clear, clipboard_copy

try:
    import pyautogui as _real_pyautogui
    import pyperclip as _real_pyperclip
except Exception:
    _real_pyautogui = None
    _real_pyperclip = None

import constants
import calibration as _calibration_mod
from constants import (
    # Terminal rendering
    LINE_HEIGHT,
    CONTENT_TOP_PADDING,
    BOTTOM_MARGIN,
    # Click positions
    D_BUTTON_X_RATIO,
    CURRENCY_LINK_X_RATIO,
    MORE_LINK_X_RATIO,
    SAFE_CLICK_X_OFFSET,
    SAFE_CLICK_Y_OFFSET,
    # Click offsets
    CLICK_OFFSET_D_BUTTON,
    CLICK_OFFSET_Y_SINGLE,
    CLICK_OFFSET_Y_MULTI,
    # Pagination
    MAX_PAGES_FARE,
    MAX_PAGES_TAX,
    MAX_PAGES_UNSALEABLE,
    # Keywords
    END_SIGNAL,
    INVALID_SIGNAL,
    MORE_FARES_KEYWORDS,
    UNSALEABLE_FARES_KEYWORD,
    # Window identification
    DEFAULT_WINDOW_TITLE,
    SMARTPOINT_WINDOW_TITLES,
    SELF_WINDOW_KEYWORDS,
    TERMINAL_AUTOMATION_ID,
    # Data validation
    FS_EXPANSION_KEYWORDS,
    # Focus tracking
    FOCUS_CACHE_SECONDS,
)

# ── Drop-in replacements for pyautogui/pyperclip ─────────────────────────────
# Uses pywinauto keyboard/mouse + Win32 clipboard instead.  Eliminates:
#   - PIL/screenshot initialisation that causes exe startup hangs
#   - Clipboard deadlocks from pyperclip's ctypes OpenClipboard calls
#
# The class instances below (pyautogui / pyperclip) shadow the removed
# imports, so all existing call-sites work without modification.

_SEND_KEYS_SPECIAL = {
    '+': '{+}', '^': '{^}', '%': '{%}', '~': '{~}',
    '{': '{{', '}': '}}', '(': '{(}', ')': '{)}',
}


def _escape_keys(text: str) -> str:
    """Escape pywinauto send_keys() special characters in literal text."""
    return ''.join(_SEND_KEYS_SPECIAL.get(c, c) for c in text)


class _KeyboardMouse:
    """Minimal drop-in replacement for pyautogui using pywinauto primitives."""

    FAILSAFE = True  # no-op attribute kept so old code doesn't crash

    _KEY_MAP = {
        "enter": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}",
        "pagedown": "{PGDN}", "space": "{SPACE}", "backspace": "{BACKSPACE}",
        "delete": "{DELETE}", "up": "{UP}", "down": "{DOWN}",
        "left": "{LEFT}", "right": "{RIGHT}", "home": "{HOME}", "end": "{END}",
    }

    @staticmethod
    def typewrite(text, interval=0.02):
        _pw_kb.send_keys(_escape_keys(text), pause=interval, with_spaces=True)

    @staticmethod
    def press(key, presses=1, interval=0.02):
        pk = _KeyboardMouse._KEY_MAP.get(key.lower(), key)
        for i in range(presses):
            if i > 0:
                time.sleep(interval)
            _pw_kb.send_keys(pk)

    @staticmethod
    def hotkey(*keys):
        _mod = {"ctrl": "^", "alt": "%", "shift": "+"}
        combo = ""
        for k in keys:
            combo += _mod.get(k.lower(), k)
        _pw_kb.send_keys(combo)

    @staticmethod
    def click(x=None, y=None):
        if x is not None and y is not None:
            _pw_mouse.click(button='left', coords=(int(x), int(y)))

    @staticmethod
    def moveTo(x, y, duration=0.0):
        _pw_mouse.move(coords=(int(x), int(y)))
        if duration > 0:
            time.sleep(duration)


class _Clipboard:
    """Resilient clipboard adapter for Smartpoint terminal capture."""

    @staticmethod
    def copy(text):
        try:
            clipboard_copy(text)
            return
        except Exception:
            pass
        if _real_pyperclip is not None:
            try:
                _real_pyperclip.copy(text)
            except Exception:
                pass

    @staticmethod
    def paste():
        try:
            text = clipboard_paste()
            if text:
                return text
        except Exception:
            text = ""
        if _real_pyperclip is not None:
            try:
                fallback = _real_pyperclip.paste()
                if fallback:
                    return fallback
            except Exception:
                pass
        return text


# Prefer the original pyautogui stack when available because it has matched
# Smartpoint's typing/clicking behavior more reliably in packaged builds.
if _real_pyautogui is not None:
    pyautogui = _real_pyautogui
    pyautogui.FAILSAFE = True
    _INPUT_BACKEND = "pyautogui"
else:
    pyautogui = _KeyboardMouse()
    _INPUT_BACKEND = "pywinauto-fallback"
pyperclip = _Clipboard()
_CLIPBOARD_BACKEND = "clipboard-util-hybrid"

# Pre-compiled regex patterns for UI automation
_RE_WHITESPACE = re.compile(r"\s+")
_RE_PRICING_OPTION = re.compile(r"PRICING\s+OPTION\s+\d+", re.IGNORECASE)
_RE_CURRENCY_FARES = re.compile(r"CURRENCY\s+FARES?\s+EXISTS?", re.IGNORECASE)
_RE_CURRENCY_CODE_FARES = re.compile(r"([A-Z]{3})\s+CURRENCY\s+FARES?\s+EXISTS?")
_RE_FARE_LINE = re.compile(r"^\s*O?\d+\s+-?[A-Z0-9]{2}\s+\d+\.?\d*R?\s+\S+\s+[A-Z]\s+")
_RE_MORE_FARES = re.compile(r"More|More\s+Fares", re.IGNORECASE)
_RE_MORE_PROMPT = re.compile(r"(MORE\s+(?:FARES|FLIGHTS|OPTIONS))", re.IGNORECASE)
_SMARTPOINT_WINDOW_HINTS = (
    "travelport smartpoint",
    "travelport smartpoint desktop",
    "smartpoint desktop",
    "smartpoint",
    "galileo desktop",
)


class StopRequested(SystemExit):
    """Raised when the GUI requests that automation should stop immediately."""


class SmartpointAutomation:
    def __init__(self, window_title=DEFAULT_WINDOW_TITLE, stop_event=None):
        """Initialize the Smartpoint automation class."""
        self.window_title = window_title
        self.app = None
        self.window = None
        self.connected = False
        self.logged_in = False
        self.stop_event = stop_event
        self.logger = logging.getLogger("travelport.automation")
        self._cached_terminal_rect = None  # Cache for SmartRichTextBox rect
        self._cached_terminal_hwnd = None  # Cache for SmartRichTextBox Win32 HWND
        self._last_focus_time = 0.0  # Timestamp of last successful focus()
        self._last_terminal_text = ""  # Cache for deduplicating reads
        self._cal = _calibration_mod.load_calibration()
        self._line_height = self._cal["line_height"]
        self._content_top_padding = self._cal.get("content_top_padding", CONTENT_TOP_PADDING)
        self.logger.debug("Using Smartpoint input backend: %s", _INPUT_BACKEND)
        self.logger.debug("Using Smartpoint clipboard backend: %s", _CLIPBOARD_BACKEND)
        self.logger.debug(
            "Display calibration: line_height=%d, source=%s",
            self._line_height, self._cal.get("source", "?")
        )

    def _raise_if_stopped(self) -> None:
        """Abort long-running automation steps promptly after a Stop request."""
        if self.stop_event and self.stop_event.is_set():
            raise StopRequested("Stop requested by user.")

    def _sleep(self, seconds: float, quantum: float = 0.05) -> None:
        """Sleep in short slices so Stop requests are honored quickly."""
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            self._raise_if_stopped()
            chunk = min(quantum, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _is_self_window(self, window_text: str) -> bool:
        """Return True if *window_text* belongs to this automation tool, not Smartpoint."""
        upper = window_text.upper()
        return any(kw.upper() in upper for kw in SELF_WINDOW_KEYWORDS)

    def _looks_like_smartpoint_window(self, window_text: str) -> bool:
        """Return True when *window_text* looks like a Smartpoint top-level window."""
        normalized = _RE_WHITESPACE.sub(" ", (window_text or "")).strip().lower()
        if not normalized or self._is_self_window(normalized):
            return False

        known_titles = {
            _RE_WHITESPACE.sub(" ", title).strip().lower()
            for title in [self.window_title] + list(SMARTPOINT_WINDOW_TITLES)
        }
        if normalized in known_titles:
            return True

        return any(hint in normalized for hint in _SMARTPOINT_WINDOW_HINTS)

    def connect(self) -> bool:
        """Connect to the running instance of Smartpoint.

        Uses four complementary strategies so it works across all Smartpoint
        versions and Windows configurations:

        1. Application.connect(title_re=...)  substring / regex match against
           the actual Win32 window title.  Handles composite titles like
           "Travelport Smartpoint - Application Window 1".

        2. Application.connect(title=...)  exact Win32 title match (legacy
           fallback for older Smartpoint builds).

        3. Desktop.window(best_match=...)  UIA fuzzy-name matching.

        4. Enumerate visible top-level windows and attach by handle when the
           automation-reported title is a known Smartpoint alias, such as
           "Galileo Desktop - Window 1".

        All strategies reject windows that belong to this automation tool
        itself (e.g. "TravelportAuto v1.3.0").
        """
        # Build the list of titles to try: configured title first, then all
        # known variants (deduped, preserving order).
        seen: set = set()
        titles_to_try: list[str] = []
        for t in [self.window_title] + list(SMARTPOINT_WINDOW_TITLES):
            if t not in seen:
                seen.add(t)
                titles_to_try.append(t)

        desktop = Desktop(backend="uia")

        for title in titles_to_try:
            # Strategy 1: Win32 substring/regex match (handles composite titles)
            try:
                self.logger.info(
                    f"  Attempting to connect to '{title}' (win32 title_re match)..."
                )
                # Escape regex special chars so the title is matched literally as substring
                title_pattern = re.escape(title)
                app = _PWApp(backend="uia").connect(title_re=f".*{title_pattern}.*", timeout=0.5)
                candidate = app.window(title_re=f".*{title_pattern}.*")
                if candidate.exists():
                    wtext = candidate.window_text()
                    if self._is_self_window(wtext):
                        self.logger.info(
                            f"    Skipping self-match: '{wtext}'"
                        )
                    else:
                        self.window = candidate
                        self.window_title = title
                        self.connected = True
                        self.logger.info(
                            f"  Successfully connected to Smartpoint ({wtext})."
                        )
                        return True
            except Exception:
                pass

            # Strategy 2: Win32 exact title match (legacy fallback)
            try:
                self.logger.info(
                    f"  Attempting to connect to '{title}' (win32 exact title)..."
                )
                app = _PWApp(backend="uia").connect(title=title, timeout=0.5)
                candidate = app.window(title=title)
                if candidate.exists():
                    wtext = candidate.window_text()
                    if self._is_self_window(wtext):
                        self.logger.info(
                            f"    Skipping self-match: '{wtext}'"
                        )
                    else:
                        self.window = candidate
                        self.window_title = title
                        self.connected = True
                        self.logger.info(
                            f"  Successfully connected to Smartpoint ({wtext})."
                        )
                        return True
            except Exception:
                pass

            #  Strategy 3: UIA best_match (fuzzy accessibility name)
            try:
                self.logger.info(
                    f"  Attempting to connect to '{title}' (UIA best_match)..."
                )
                candidate = desktop.window(best_match=title)
                if candidate.exists():
                    wtext = candidate.window_text()
                    if self._is_self_window(wtext):
                        self.logger.info(
                            f"    Skipping self-match: '{wtext}'"
                        )
                    else:
                        self.window = candidate
                        self.window_title = title
                        self.connected = True
                        self.logger.info(
                            f"  Successfully connected to Smartpoint ({wtext})."
                        )
                        return True
            except Exception:
                pass

        # Nothing worked — list every visible window title to aid diagnosis.
        # Strategy 4: Visible-window scan + handle attach for alias titles.
        try:
            for visible_window in desktop.windows():
                try:
                    wtext = (visible_window.window_text() or "").strip()
                except Exception:
                    continue

                if not self._looks_like_smartpoint_window(wtext):
                    continue

                handle = getattr(
                    getattr(visible_window, "element_info", None), "handle", None
                )
                if not handle:
                    try:
                        handle = visible_window.wrapper_object().handle
                    except Exception:
                        handle = None
                if not handle:
                    continue

                self.logger.info(
                    f"  Attempting to connect to visible Smartpoint alias '{wtext}' (handle attach)..."
                )
                app = _PWApp(backend="uia").connect(handle=handle, timeout=0.5)
                candidate = app.window(handle=handle)
                if candidate.exists():
                    resolved_title = (candidate.window_text() or wtext).strip()
                    if self._is_self_window(resolved_title):
                        self.logger.info(f"    Skipping self-match: '{resolved_title}'")
                        continue

                    self.window = candidate
                    self.window_title = resolved_title or wtext
                    self.connected = True
                    self.logger.info(
                        f"  Successfully connected to Smartpoint ({resolved_title or wtext})."
                    )
                    return True
        except Exception:
            pass

        try:
            visible_titles = sorted(
                {w.window_text() for w in desktop.windows() if w.window_text().strip()}
            )
            self.logger.info(
                "  [ERROR] Smartpoint window not found. "
                "Make sure Travelport Smartpoint is open and fully signed in.\n"
                f"  Windows currently visible: {', '.join(visible_titles) or '(none)'}\n"
                "  If Smartpoint is open but not in the list above, please share "
                "this log so the correct window title can be added."
            )
        except Exception:
            self.logger.info(
                "  [ERROR] Smartpoint window not found. "
                "Make sure Travelport Smartpoint is open and fully signed in."
            )
        return False

    def focus(self, force: bool = False) -> bool:
        """Bring the Smartpoint window to the foreground forcefully.

        Uses focus caching: skips the expensive Win32 calls if focus was
        set recently (within FOCUS_CACHE_SECONDS). Pass force=True to
        bypass the cache.

        The cache also verifies that Smartpoint is still the foreground
        window (RACE-2 fix: detects user alt-tabbing away).
        """
        if not self.connected or not self.window:
            return False

        self._raise_if_stopped()

        # Skip if focus was set recently AND Smartpoint is still foreground
        now = time.time()
        if not force and (now - self._last_focus_time) < FOCUS_CACHE_SECONDS:
            if self._is_window_foreground():
                return True
            # Smartpoint lost focus — fall through to re-focus

        try:
            # Get the raw Windows handle manually
            hwnd = self.window.wrapper_object().handle
            if hwnd:
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                current_thread = kernel32.GetCurrentThreadId()
                target_thread = user32.GetWindowThreadProcessId(hwnd, None)
                attached = False
                if target_thread and target_thread != current_thread:
                    user32.AttachThreadInput(current_thread, target_thread, True)
                    attached = True
                # ALT-key trick: convinces Windows this process has had recent
                # user input, which lifts the SetForegroundWindow UIPI block
                # when Smartpoint runs elevated and we don't.
                VK_MENU = 0x12
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_MENU, 0, 0, 0)
                user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                user32.BringWindowToTop(hwnd)
                # SW_RESTORE = 9
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                if attached:
                    user32.AttachThreadInput(current_thread, target_thread, False)
            self._sleep(constants.FOCUS_DELAY)  # Brief wait for window to come forward
            if not self._is_window_foreground():
                focus_x, focus_y = self._get_terminal_focus_point()
                pyautogui.click(x=focus_x, y=focus_y)
                self._sleep(constants.CLICK_DELAY)
            if self._is_window_foreground():
                self._last_focus_time = time.time()
                return True
            self.logger.warning(
                "      [FOCUS] Window foreground not confirmed after Win32 focus attempt."
            )
            return False
        except Exception as e:
            self.logger.info(f"  [ERROR] Could not focus Smartpoint window: {e}")
            return False

    def _is_window_foreground(self) -> bool:
        """Return True when Smartpoint is the active foreground window."""
        if not self.window:
            return False
        try:
            user32 = ctypes.windll.user32
            hwnd = self.window.wrapper_object().handle
            fg_hwnd = user32.GetForegroundWindow()
            if not hwnd or not fg_hwnd:
                return False
            if fg_hwnd == hwnd:
                return True

            ga_root = 2
            hwnd_root = user32.GetAncestor(hwnd, ga_root) or hwnd
            fg_root = user32.GetAncestor(fg_hwnd, ga_root) or fg_hwnd
            if fg_root in {hwnd, hwnd_root} or hwnd_root == fg_hwnd:
                return True
            if user32.IsChild(hwnd, fg_hwnd):
                return True

            hwnd_pid = ctypes.c_ulong()
            fg_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(hwnd_pid))
            user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
            return bool(hwnd_pid.value) and hwnd_pid.value == fg_pid.value
        except Exception:
            return False

    def _get_terminal_focus_point(self) -> tuple[int, int]:
        """Return a safe click point inside the terminal pane when possible."""
        rect = None
        try:
            rect = self._get_terminal_rect()
        except Exception:
            rect = None

        if rect is None and self.window:
            try:
                rect = self.window.rectangle()
            except Exception:
                rect = None

        if rect is None:
            return SAFE_CLICK_X_OFFSET, SAFE_CLICK_Y_OFFSET

        left = int(getattr(rect, "left", 0))
        top = int(getattr(rect, "top", 0))
        right = getattr(rect, "right", None)
        bottom = getattr(rect, "bottom", None)

        try:
            width = int(rect.width())
        except Exception:
            width = None
        try:
            height = int(rect.height())
        except Exception:
            height = None

        if right is None:
            right = left + max(width or 0, SAFE_CLICK_X_OFFSET + 10)
        else:
            right = int(right)
        if bottom is None:
            bottom = top + max(height or 0, SAFE_CLICK_Y_OFFSET + 10)
        else:
            bottom = int(bottom)

        width = max(0, right - left)
        height = max(0, bottom - top)

        x_offset = max(10, min(SAFE_CLICK_X_OFFSET, max(10, width - 10)))
        y_offset = max(10, min(SAFE_CLICK_Y_OFFSET, max(10, height - 10)))
        x = left + x_offset
        y = top + y_offset

        # Guard against pyautogui fail-safe corners. Clamp to at least 5px
        # inside the rect itself so the point is never at a screen edge.
        x_min = left + 5
        y_min = top + 5
        x_max = right - 5
        y_max = bottom - 5
        if x_max < x_min:
            x_min = x_max = left + width // 2
        if y_max < y_min:
            y_min = y_max = top + height // 2
        clamped_x = max(x_min, min(x, x_max))
        clamped_y = max(y_min, min(y, y_max))
        if (clamped_x, clamped_y) != (x, y):
            self.logger.debug(
                f"      [FOCUS] Clamping focus point ({x}, {y}) -> "
                f"({clamped_x}, {clamped_y}) to avoid fail-safe corner."
            )
        return clamped_x, clamped_y

    def _safe_focus_click(self, x: int, y: int) -> None:
        """Click via pywinauto (no pyautogui fail-safe) for terminal focus-only clicks."""
        try:
            _pw_mouse.click(button="left", coords=(int(x), int(y)))
        except Exception as exc:
            self.logger.debug(f"      [FOCUS] _safe_focus_click failed: {exc}")

    def _send_clipboard_shortcuts(self) -> None:
        """Send Ctrl+A / Ctrl+C using pywinauto, not pyautogui."""
        self._raise_if_stopped()
        _pw_kb.send_keys("^a")
        self._sleep(constants.CLICK_DELAY)
        self._raise_if_stopped()
        _pw_kb.send_keys("^c")
        self._sleep(constants.COPY_DELAY)

    def _get_terminal_hwnd(self):
        """Return the Win32 HWND of the SmartRichTextBox terminal control.

        Returns None if the control isn't a real Win32 window (e.g. a XAML
        virtual element) or can't be located. Cached after first lookup.
        """
        if self._cached_terminal_hwnd:
            return self._cached_terminal_hwnd
        if not self.window:
            return None
        try:
            for doc in self.window.descendants(control_type="Document"):
                try:
                    if doc.element_info.automation_id == TERMINAL_AUTOMATION_ID:
                        h = doc.element_info.handle
                        if h:
                            self._cached_terminal_hwnd = int(h)
                            return self._cached_terminal_hwnd
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _copy_via_messages(self) -> str:
        """Focus-independent clipboard read for RichEdit-based controls.

        Sends EM_SETSEL + WM_COPY directly to the SmartRichTextBox HWND.
        Works regardless of whether Smartpoint has foreground focus and
        regardless of UAC/UIPI elevation differences — needed on locked-down
        work laptops where the user can't run TravelportAuto as Administrator.

        Only works for controls derived from RichEdit. WPF/XAML controls
        will return "" — fall back to `_read_text_via_uia` for those.
        """
        target_hwnd = self._get_terminal_hwnd()
        if not target_hwnd:
            self.logger.debug(
                "      [WM_COPY] No Win32 HWND for SmartRichTextBox — likely "
                "a WPF/XAML virtual element. Will need UIA TextPattern."
            )
            return ""
        try:
            user32 = ctypes.windll.user32
            EM_SETSEL = 0x00B1
            WM_COPY = 0x0301

            pyperclip.copy("")
            sel_result = user32.SendMessageW(target_hwnd, EM_SETSEL, 0, -1)
            self._sleep(0.05)
            copy_result = user32.SendMessageW(target_hwnd, WM_COPY, 0, 0)
            self._sleep(max(0.15, constants.COPY_DELAY))
            text = pyperclip.paste() or ""
            if not text.strip():
                self.logger.debug(
                    f"      [WM_COPY] HWND={hex(target_hwnd)} EM_SETSEL={sel_result} "
                    f"WM_COPY={copy_result} but clipboard empty — control likely "
                    "doesn't respond to RichEdit messages."
                )
            return text
        except Exception as exc:
            self.logger.debug(f"      [WM_COPY] Exception: {exc}")
            return ""

    def _read_text_via_uia(self) -> str:
        """Focus-independent text read via UI Automation TextPattern.

        Works on .NET/WPF/XAML text controls that don't respond to legacy
        RichEdit messages (EM_SETSEL/WM_COPY). UIA is the modern Windows
        accessibility API and works across UAC/UIPI boundaries — no admin
        required.

        Returns "" if the control doesn't expose a usable text pattern.
        """
        if not self.window:
            return ""
        try:
            for doc in self.window.descendants(control_type="Document"):
                try:
                    if doc.element_info.automation_id != TERMINAL_AUTOMATION_ID:
                        continue

                    # Path 1: UIA TextPattern via pywinauto's iface_text helper
                    try:
                        pattern = getattr(doc, "iface_text", None)
                        if pattern is not None:
                            rng = pattern.DocumentRange
                            text = rng.GetText(-1)
                            if text and text.strip():
                                return text
                    except Exception as exc:
                        self.logger.debug(f"      [UIA] iface_text failed: {exc}")

                    # Path 2: Direct UIA TextPattern via comtypes (more robust)
                    try:
                        UIA_TextPatternId = 10014
                        elem = doc.element_info.element
                        get_pattern = getattr(elem, "GetCurrentPattern", None)
                        if get_pattern is not None:
                            raw_pattern = get_pattern(UIA_TextPatternId)
                            if raw_pattern is not None:
                                # Try common attribute access patterns
                                for attr in ("DocumentRange", "documentRange"):
                                    rng = getattr(raw_pattern, attr, None)
                                    if rng is not None:
                                        get_text = getattr(rng, "GetText", None) or getattr(rng, "getText", None)
                                        if get_text is not None:
                                            text = get_text(-1)
                                            if text and text.strip():
                                                return text
                                        break
                    except Exception as exc:
                        self.logger.debug(f"      [UIA] direct GetCurrentPattern failed: {exc}")

                    # Path 3: Legacy IAccessible Value (smaller text but sometimes works)
                    try:
                        legacy = doc.legacy_properties()
                        val = (legacy or {}).get("Value", "")
                        if val and val.strip():
                            return val
                    except Exception as exc:
                        self.logger.debug(f"      [UIA] legacy_properties failed: {exc}")

                    break  # found the right element, no point checking siblings
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug(f"      [UIA] descendants() walk failed: {exc}")
        return ""

    def _read_text_focus_independent(self) -> str:
        """Try every focus-independent text read in order. Returns first hit."""
        text = self._copy_via_messages()
        if text.strip():
            return text
        text = self._read_text_via_uia()
        if text.strip():
            self.logger.info(
                "      [COPY] Captured terminal text via UIA TextPattern."
            )
            return text
        return ""

    def _get_terminal_rect(self):
        """
        Get the bounding rectangle of the main terminal text area (SmartRichTextBox).

        Caches the result after the first successful scan to avoid repeated
        slow UI tree walks (~2-5s each via descendants()).
        """
        if self._cached_terminal_rect:
            return self._cached_terminal_rect

        try:
            best_rect = None
            best_area = 0
            for doc in self.window.descendants(control_type="Document"):
                try:
                    if doc.element_info.automation_id == TERMINAL_AUTOMATION_ID:
                        r = doc.rectangle()
                        area = r.width() * r.height()
                        if area > best_area and r.width() > 100 and r.height() > 100:
                            best_rect = r
                            best_area = area
                except Exception:
                    pass

            if best_rect:
                self.logger.debug(
                    f"      [RECT] Terminal pane: L={best_rect.left} T={best_rect.top} "
                    f"R={best_rect.right} B={best_rect.bottom}"
                )
                self._cached_terminal_rect = best_rect
                return best_rect
        except Exception as e:
            self.logger.debug(f"      [RECT] Error finding SmartRichTextBox: {e}")

        # Fallback: use window rect (don't cache this)
        self.logger.debug("      [RECT] Falling back to window rectangle")
        return self.window.rectangle()

    def login(self, username: str, password: str, pcc: str | None = None) -> bool:
        """
        Automate the Smartpoint login process.
        Assumes the terminal is ready to accept the sign-on command.
        Command format: SON/Z{PCC}[enter]{USERNAME}[enter]{PASSWORD}[enter]
        """
        if self.logged_in:
            self.logger.debug("Already logged in, skipping login sequence.")
            return True

        if not self.focus():
            self.logger.error("Cannot login, window not focused.")
            return False

        self.logger.debug("Starting login sequence...")
        self.clear_screen()

        try:
            self._raise_if_stopped()
            # 1. Initiate Sign-On
            sign_on_cmd = f"SON/Z{pcc}" if pcc else "SON/Z"
            self.logger.info(f"Sending sign-on command: {sign_on_cmd}")
            pyautogui.typewrite(sign_on_cmd, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            self._sleep(constants.COMMAND_WAIT_FS)  # Wait for username prompt

            # 2. Enter Username
            self._raise_if_stopped()
            self.logger.info("Entering username...")
            pyautogui.typewrite(username, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            self._sleep(constants.COMMAND_WAIT_LONG)  # Wait for password prompt

            # 3. Enter Password
            self._raise_if_stopped()
            self.logger.info("Entering password...")
            pyautogui.typewrite(password, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")

            # Wait for login to complete
            self.logger.info("Waiting for login to complete...")
            self._sleep(constants.LOGIN_COMPLETION_WAIT)

            # Check for success by reading terminal text
            terminal_text = self._copy_terminal_text()
            if (
                "RESTRICTED" in terminal_text.upper()
                or "SIGN-ON" in terminal_text.upper()
                or "WELCOME" in terminal_text.upper()
            ):
                self.logger.info("Login successful.")
                self.logged_in = True
                return True
            else:
                self.logger.warning(
                    "Login might have failed. Please check the terminal."
                )
                self.logger.debug(f"Terminal output: {terminal_text[:100]}...")
                return False

        except StopRequested:
            raise
        except Exception as e:
            self.logger.error(f"Login automation failed: {e}")
            return False

    def clear_screen(self):
        """Clear the terminal screen or input buffer by sending 'I'"""
        # Ensure focus first
        self._raise_if_stopped()
        self.focus(force=True)

        # Sending 'I' completely refreshes the Travelport Smartpoint terminal
        print("  [DEBUG] Refreshing terminal with 'I' command...")
        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        self._sleep(constants.COMMAND_WAIT_LONG)  # Wait for refresh to complete

    def refresh_terminal(self):
        """Alias for clear_screen for compatibility."""
        self.clear_screen()

    def _copy_terminal_text(self) -> str:
        """Helper to copy text from the terminal via clipboard using mouse automation."""
        self._raise_if_stopped()
        pyperclip.copy("")

        # Ensure focus hasn't been lost (cached — nearly free if recent)
        self.focus(force=True)

        if not self.window:
            return ""

        safe_x, safe_y = self._get_terminal_focus_point()

        # Use pywinauto for all focus-only clicks so pyautogui's fail-safe
        # cannot trigger when the window is near a screen corner.
        _failsafe_exc = getattr(_real_pyautogui, "FailSafeException", None)

        def _focus_click(x: int, y: int) -> None:
            self._safe_focus_click(x, y)

        try:
            # Click to focus the terminal area (safe position)
            _focus_click(safe_x, safe_y)
            self._sleep(constants.CLICK_DELAY)

            if not self._is_window_foreground():
                self.logger.warning(
                    "      [FOCUS] Smartpoint is not foreground before clipboard hotkeys; retrying focus."
                )
                self.focus(force=True)
                _focus_click(safe_x, safe_y)
                self._sleep(constants.CLICK_DELAY)

            if not self._is_window_foreground():
                # Focus failed — common on locked-down work laptops where
                # SetForegroundWindow is blocked by UIPI. Fall back to
                # focus-independent paths (WM_COPY, then UIA TextPattern).
                self.logger.warning(
                    "      [FOCUS] Smartpoint not foreground; trying focus-independent text read."
                )
                text = self._read_text_focus_independent()
                if text.strip():
                    self._last_terminal_text = text
                    return text
                self.logger.warning(
                    "      [COPY] All focus-independent paths returned empty — clipboard remains empty."
                )
                return ""

            def _copy_once(wait_after_copy: float = 0.0) -> str:
                try:
                    self._send_clipboard_shortcuts()
                except KeyboardInterrupt as exc:
                    raise RuntimeError(
                        "Clipboard hotkeys were interrupted. Smartpoint may not have had focus and Ctrl+C likely reached the console."
                    ) from exc
                if wait_after_copy > 0:
                    self._sleep(wait_after_copy)
                return pyperclip.paste() or ""

            # 1. Normal copy attempt
            text = _copy_once()

            # 2. One slower retry if the clipboard was still empty
            if not text.strip():
                self._sleep(max(0.15, constants.COPY_DELAY * 2))
                text = _copy_once()

            # 3. Heavier fallback: refocus, reclick terminal pane, then try once more
            if not text.strip():
                self.logger.debug(
                    "      [COPY] Clipboard empty after two attempts; using heavy fallback."
                )
                pyperclip.copy("")
                self.focus(force=True)
                safe_x, safe_y = self._get_terminal_focus_point()
                _focus_click(safe_x, safe_y)
                self._sleep(max(constants.CLICK_DELAY, 0.1))

                if self._is_window_foreground():
                    text = _copy_once(wait_after_copy=max(0.15, constants.COPY_DELAY * 2))
                else:
                    self.logger.warning(
                        "      [FOCUS] Heavy clipboard fallback could not confirm foreground; trying focus-independent paths."
                    )
                    text = self._read_text_focus_independent()
                    if text.strip():
                        self.logger.info(
                            "      [COPY] Heavy fallback recovered text via focus-independent path."
                        )

        except Exception as exc:
            if _failsafe_exc and isinstance(exc, _failsafe_exc):
                self.logger.warning(
                    "      [FOCUS] PyAutoGUI fail-safe triggered during focus click — "
                    "retrying via window centre."
                )
                try:
                    self.focus(force=True)
                    safe_x, safe_y = self._get_terminal_focus_point()
                    self._safe_focus_click(safe_x, safe_y)
                    self._sleep(constants.CLICK_DELAY)
                    self._send_clipboard_shortcuts()
                    self._sleep(max(0.15, constants.COPY_DELAY * 2))
                    text = pyperclip.paste() or ""
                except Exception as retry_exc:
                    self.logger.warning(
                        f"      [FOCUS] Fail-safe retry also failed: {retry_exc}. Returning empty."
                    )
                    text = ""
            else:
                raise

        # Final safety net: if every keystroke path returned empty, try the
        # focus-independent paths as a last resort.
        if not text or not text.strip():
            fallback = self._read_text_focus_independent()
            if fallback.strip():
                self.logger.info(
                    "      [COPY] Final fallback recovered text via focus-independent path."
                )
                text = fallback

        # Click once to deselect
        pyautogui.press("escape")

        # Cache for deduplication
        self._last_terminal_text = text

        return text

    def _wait_for_response(
        self,
        text_before: str,
        timeout: float = 2.0,
        poll_interval: float = 0.15,
        min_wait: float = 0.1,
        stability_checks: int = 2,
    ) -> str:
        """
        Adaptive polling: wait until terminal content changes AND stabilizes.

        Returns as soon as the screen changes and stops changing (stable), or after timeout.
        This is dramatically faster than fixed time.sleep() for fast-responding commands
        while ensuring data is fully loaded.

        Args:
            text_before: The terminal text captured before the action.
            timeout: Maximum seconds to wait.
            poll_interval: Seconds between polls.
            min_wait: Minimum time to wait before checking (prevents race conditions).
            stability_checks: Number of consecutive identical reads to confirm stability.

        Returns:
            The new terminal text (changed and stable, or timed-out).
        """
        # Always wait at least min_wait to avoid race conditions
        if min_wait > 0:
            self._sleep(min_wait)

        deadline = time.time() + timeout
        current = None
        stable_count = 0

        while time.time() < deadline:
            self._raise_if_stopped()
            self._sleep(poll_interval)
            new_text = self._copy_terminal_text()

            # Skip blank reads — these are clipboard/focus failures, not a real
            # empty screen. Treating empty as "screen changed" causes click_d_button
            # to think a successful D-click missed (the tax breakdown just opened
            # but the read lost focus transiently), then issue an unwanted "I" reset.
            if not new_text.strip():
                continue

            # First check: has screen changed from original?
            if new_text.strip() != text_before.strip():
                # Screen has changed - now verify it's stable
                if current is None or new_text.strip() != current.strip():
                    # Screen is still changing
                    current = new_text
                    stable_count = 1
                else:
                    stable_count += 1

                if stable_count >= stability_checks:
                    # Screen has changed and is now stable
                    return new_text

        # Final read after timeout
        return self._copy_terminal_text()

    def _wait_for_stable_screen(
        self,
        initial_text: str | None = None,
        max_polls: int = 3,
        interval: float = 0.3,
    ) -> str:
        """
        Wait until the terminal screen content stabilizes (stops changing).

        Polls the clipboard multiple times and returns when two consecutive
        reads produce identical content. Prevents clicking while data is
        still rendering.

        Args:
            initial_text: Optional already-captured terminal text to treat as
                the first read, avoiding one redundant clipboard pass.
            max_polls: Maximum number of follow-up polls.
            interval: Delay between polls.

        Returns the stable terminal text.
        """
        self._raise_if_stopped()
        prev = initial_text if initial_text is not None else self._copy_terminal_text()
        for _ in range(max_polls):
            self._raise_if_stopped()
            self._sleep(interval)
            curr = self._copy_terminal_text()
            if curr.strip() == prev.strip():
                return curr
            prev = curr
        return prev

    def show_completion_signal(self):
        """Show a clear completion signal in the terminal (no popup)."""
        self.logger.debug("\n" + "=" * 50)
        self.logger.debug("       TRAVELPORT AUTOMATION TASK COMPLETE ")
        self.logger.debug("=" * 50 + "\n")

    def run_command(self, command: str, max_pages: int = MAX_PAGES_FARE) -> str:
        """
        Execute a complete command in Smartpoint, handling pagination if necessary.

        SPEED-OPTIMIZED: Uses adaptive polling instead of fixed sleeps,
        eliminates redundant terminal reads, and uses cached focus.

        Smartpoint pagination flow:
          1. Run command  first page of fares appears
          2. Check for "CURRENCY FARES EXISTS"  re-run in alternate currency
          3. If no "END" at the bottom  type MD + Enter
          4. If MD returns "INVALID"  stop (no more data)
          5. A "More Fares" prompt may appear  press Enter again
          6. Remaining data loads; repeat until "END" is found
          7. Check for UNSALEABLE_FARES_KEYWORD  send FU*
          8. Ctrl+A, Ctrl+C to capture the full text

        Returns the full combined text output from all pages.
        """
        if not self.focus():
            self.logger.debug("  [ERROR] Cannot run command, window not focused.")
            return ""

        self._raise_if_stopped()
        self.logger.debug(f"    Running: {command}")

        # Send 'I' first to clear any previous terminal state cleanly
        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        self._sleep(constants.COMMAND_WAIT_LONG)

        # Capture state BEFORE sending command (for adaptive polling)
        text_before_cmd = self._copy_terminal_text()

        # Send the actual command
        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        # SPEED: Adaptive polling " exits as soon as screen changes
        initial_text = self._wait_for_response(
            text_before_cmd, timeout=constants.COMMAND_WAIT_FS
        )

        # If terminal returned INVALID immediately, stop " no point retrying
        if self._has_invalid(initial_text):
            self.logger.warning(
                f"    [!] Command returned INVALID immediately: {command}"
            )
            return initial_text

        # Check for "CURRENCY FARES EXISTS" (e.g., "BDT CURRENCY FARES EXISTS")
        # This means no fares in the requested currency; we must CLICK the link
        # (typed commands like FD*BDT do not work for this redirect)
        currency_match = self._has_currency_redirect(initial_text)
        if currency_match:
            self.logger.info(
                f"      [CURRENCY] {currency_match} CURRENCY FARES EXISTS detected - clicking redirect link..."
            )

            # Click the currency link ONCE - do not retry to avoid toggle loops
            clicked_text = self.click_currency_link(initial_text)

            # Check if screen changed after clicking
            if clicked_text and clicked_text.strip() != initial_text.strip():
                initial_text = clicked_text
                self.logger.info(
                    f"      [CURRENCY] Clicked {currency_match} redirect, screen updated ({len(initial_text)} chars)"
                )
            else:
                self.logger.warning(
                    f"      [CURRENCY] Screen did not change after clicking {currency_match} redirect"
                )
                self.logger.warning(
                    f"      [CURRENCY] Continuing with current screen content, may have incorrect data"
                )

        current_page = 1
        previous_md_text = initial_text

        # Pagination loop: ACCUMULATE all pages into full_text
        # Critical: use += not = so page 1 fares aren't lost when MD scrolls to page 2
        all_pages = [initial_text]

        # SPEED: Use last known text as the current screen text to avoid redundant read
        screen_text = initial_text

        while current_page < max_pages:
            self._raise_if_stopped()
            if self._has_end_signal(screen_text):
                self.logger.debug(
                    "      [DEBUG] 'END' signal detected. Pagination complete."
                )
                if screen_text.strip() != all_pages[-1].strip():
                    all_pages.append(screen_text)
                break

            settled_text = self._wait_for_stable_screen(
                initial_text=screen_text, max_polls=2, interval=0.2
            )
            if settled_text.strip() != screen_text.strip():
                screen_text = settled_text

                if self._has_end_signal(screen_text):
                    self.logger.debug(
                        "      [DEBUG] 'END' signal detected after settling. Pagination complete."
                    )
                    if screen_text.strip() != all_pages[-1].strip():
                        all_pages.append(screen_text)
                    break

            # Attempt to click "More Flights / Fares"
            if self.click_more_prompt_link(screen_text):
                self.logger.debug(f"      Page {current_page}: Clicked 'More' link.")
                md_response = self._wait_for_response(
                    screen_text,
                    timeout=constants.COMMAND_WAIT_MEDIUM + 0.5,
                    min_wait=0.0,
                    stability_checks=1,
                )
                md_response = self._wait_for_stable_screen(
                    initial_text=md_response, max_polls=3, interval=0.2
                )
            else:
                # Fallback to standard MD " use adaptive polling
                self.logger.debug(
                    f"      Page {current_page}: No 'More' link found. Sending MD..."
                )
                text_before_md = screen_text
                pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
                pyautogui.press("enter")
                # SPEED: Adaptive polling instead of fixed sleep
                md_response = self._wait_for_response(
                    text_before_md, timeout=constants.COMMAND_WAIT_MEDIUM + 0.5
                )

            # Check if MD/click returned "INVALID" (no more data)
            if self._has_invalid(md_response):
                self.logger.debug(
                    "      [DEBUG] MD returned 'INVALID'. No more data to paginate."
                )
                break  # Don't add INVALID page to results

            # Detect stuck screen: same text as previous MD
            if md_response.strip() == previous_md_text.strip():
                self.logger.debug(
                    "      [DEBUG] Same text as previous page. Stopping pagination."
                )
                break
            previous_md_text = md_response

            # After MD/click, Smartpoint may show ANOTHER "More Fares" or "More Flights" prompt
            # that requires pressing Enter to clear BEFORE the actual data displays.
            if self._has_more_prompt(md_response):
                self.logger.debug(
                    "      [DEBUG] 'More Fares/Flights' prompt detected. Pressing Enter..."
                )
                pyautogui.press("enter")
                md_response = self._wait_for_response(
                    md_response, timeout=constants.COMMAND_WAIT_FS
                )

            all_pages.append(md_response)
            screen_text = md_response  # SPEED: Carry forward for next iteration
            current_page += 1

        if current_page >= max_pages and max_pages > 1:
            self.logger.debug(
                f"      [WARNING] Reached max_pages ({max_pages}). Stopping."
            )

        # Join all pages " use separator so parser can handle overlapping headers
        full_text = "\n--- PAGE BREAK ---\n".join(all_pages)

        # Check for unsaleable fares
        if UNSALEABLE_FARES_KEYWORD in full_text.upper():
            self.logger.debug(
                "      [DEBUG] 'UNSALEABLE FARES' detected. Sending FU* command..."
            )
            try:
                fu_text_before = self._copy_terminal_text()
                pyautogui.typewrite("FU*", interval=constants.KEYBOARD_INTERVAL)
                pyautogui.press("enter")
                # SPEED: Adaptive polling
                fu_first = self._wait_for_response(
                    fu_text_before, timeout=constants.COMMAND_WAIT_LONG + 0.5
                )
            except StopRequested:
                self.logger.info(
                    "      [STOP] Stop requested during FU* expansion; keeping captured FD page."
                )
                return full_text
            except Exception as exc:
                self.logger.warning(
                    f"      [WARNING] FU* expansion failed ({exc}); keeping captured FD page."
                )
                return full_text

            if (
                not fu_first.strip()
                or self._has_invalid(fu_first)
                or fu_first.strip() == fu_text_before.strip()
            ):
                self.logger.warning(
                    "      [WARNING] FU* did not return usable unsaleable fare data; "
                    "keeping captured FD page."
                )
                return full_text

            fu_pages = [fu_first]
            fu_page = 1
            while fu_page < MAX_PAGES_UNSALEABLE:
                self._raise_if_stopped()
                if self._has_end_signal(fu_pages[-1]):
                    break
                fu_before = fu_pages[-1]
                pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
                pyautogui.press("enter")
                fu_response = self._wait_for_response(
                    fu_before, timeout=constants.COMMAND_WAIT_MEDIUM + 0.3
                )
                if (
                    self._has_invalid(fu_response)
                    or fu_response.strip() == fu_pages[-1].strip()
                ):
                    break
                fu_pages.append(fu_response)
                fu_page += 1

            full_text += (
                "\n--- UNSALEABLE FARES BREAK ---\n"
                + "\n--- PAGE BREAK ---\n".join(fu_pages)
            )
            self.logger.debug(
                f"      [DEBUG] Unsaleable fares captured ({len(fu_pages)} pages appended)."
            )
        return full_text

    def click_fare_amount_for_penalty(
        self, page_text: str, fare: dict
    ) -> tuple[str, str]:
        """
        Click the fare amount for a visible fare line and capture the Rule 16 popup text.

        Returns:
            (popup_text, restored_page_text)
        """


        if not self.focus():
            return "", page_text

        target_line_idx = None
        target_char_idx = None
        fare_basis = str(fare.get("fare_basis", "")).upper()
        airline = str(fare.get("airline", "")).upper()
        line_number = fare.get("line")
        line_token = str(fare.get("line_token", "")).upper()
        amount_pattern = rf"{fare.get('fare', 0):.2f}(?:R)?"
        raw_line = str(fare.get("raw_line", "")).strip().upper()

        for index, line in enumerate(page_text.split("\n")):
            upper_line = line.upper()
            if fare_basis not in upper_line or airline not in upper_line:
                continue

            if raw_line:
                normalized_line = _RE_WHITESPACE.sub(" ",upper_line.strip())
                normalized_raw_line = _RE_WHITESPACE.sub(" ",raw_line)
                if normalized_line == normalized_raw_line:
                    amount_match = re.search(amount_pattern, line)
                    if amount_match:
                        target_line_idx = index
                        target_char_idx = (
                            amount_match.start() + amount_match.end()
                        ) // 2
                        break

            if line_token:
                if not re.search(
                    rf"^\s*{re.escape(line_token)}\s+", line, re.IGNORECASE
                ):
                    continue
            elif line_number is not None and not re.search(
                rf"^\s*O?{int(line_number)}\s+", line, re.IGNORECASE
            ):
                continue

            amount_match = re.search(amount_pattern, line)
            if not amount_match:
                continue

            target_line_idx = index
            target_char_idx = (amount_match.start() + amount_match.end()) // 2
            break

        if target_line_idx is None or target_char_idx is None:
            self.logger.warning(
                f"      [PENALTY] Could not locate clickable fare line for {fare_basis}"
            )
            return "", page_text

        base_x, base_y = self._text_line_to_pixel(
            page_text, target_line_idx, char_idx=target_char_idx
        )

        text_before = page_text
        offsets = [(0, 0), (8, 0), (-8, 0)]

        def close_penalty_popup(click_x: int, click_y: int, popup_text: str) -> str:
            """Close the popup by toggling the same fare click, then fall back to Escape."""
            pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
            pyautogui.click()

            restored_text = self._wait_for_response(
                popup_text,
                timeout=constants.COMMAND_WAIT_SHORT + 0.8,
                poll_interval=0.15,
                min_wait=0.05,
                stability_checks=1,
            )

            if "16. PENALTIES" in restored_text.upper():
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)
                restored_text = self._copy_terminal_text()

            return restored_text

        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(
                f"      [PENALTY] Trying fare click at ({click_x}, {click_y}) [offset=({x_off},{y_off})]"
            )

            pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
            pyautogui.click()
            result = self._wait_for_response(
                text_before,
                timeout=constants.COMMAND_WAIT_SHORT + 0.8,
                poll_interval=0.15,
                min_wait=0.05,
                stability_checks=1,
            )
            upper_result = result.upper()
            if "16. PENALTIES" in upper_result or (
                "PENALTIES" in upper_result
                and ("CHANGES" in upper_result or "CANCELLATIONS" in upper_result)
            ):
                restored_text = close_penalty_popup(click_x, click_y, result)
                return result, restored_text

            if result.strip() != text_before.strip():
                self.logger.debug(
                    f"      [PENALTY] Unexpected screen change for {fare_basis}; restoring before moving on."
                )
                restored_text = close_penalty_popup(click_x, click_y, result)
                return "", restored_text

        self.logger.warning(
            f"      [PENALTY] No Rule 16 popup captured for {fare_basis}"
        )
        return "", self._copy_terminal_text()

    def _extract_penalties_from_visible_page(
        self, page_text: str, seen_fares: set[tuple], visible_fares: list[dict] = None
    ) -> tuple[list[dict], str]:
        """Extract penalty popup text for each visible fare line on the current page."""
        from parser import parse_fare_display, select_report_fare_targets

        if visible_fares is None:
            parsed = parse_fare_display(page_text)
            visible_fares = select_report_fare_targets(parsed.get("fares", []))

        extracted = []
        current_page_text = page_text

        for fare in visible_fares:
            fare_key = (
                fare.get("fare_basis"),
                fare.get("rbd"),
                fare.get("is_rt"),
                fare.get("fare"),
                bool(fare.get("is_unsaleable")),
            )
            if fare_key in seen_fares:
                continue

            self.logger.info(
                f"      [PENALTY] Line {fare.get('line')}: {fare.get('fare_basis')} "
                f"{'RT' if fare.get('is_rt') else 'OW'} {fare.get('fare'):.2f}"
            )
            popup_text, current_page_text = self.click_fare_amount_for_penalty(
                current_page_text, fare
            )
            seen_fares.add(fare_key)

            if popup_text and "16. PENALTIES" in popup_text.upper():
                fare_with_penalty = dict(fare)
                fare_with_penalty["raw_penalty_text"] = popup_text
                extracted.append(fare_with_penalty)

        return extracted, current_page_text

    def run_penalty_command(
        self, command: str, max_pages: int = MAX_PAGES_FARE
    ) -> list[dict]:
        """
        Run an FD command page-by-page and capture a Rule 16 popup for each fare basis.
        """
        if not self.focus():
            self.logger.debug(
                "  [ERROR] Cannot run penalty command, window not focused."
            )
            return []

        self._raise_if_stopped()
        self.logger.debug(f"    Running penalty extraction: {command}")

        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        self._sleep(constants.COMMAND_WAIT_LONG)

        text_before_cmd = self._copy_terminal_text()
        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        screen_text = self._wait_for_response(
            text_before_cmd, timeout=constants.COMMAND_WAIT_FS
        )
        if self._has_invalid(screen_text):
            self.logger.warning(
                f"    [!] Penalty command returned INVALID immediately: {command}"
            )
            return []

        currency_match = self._has_currency_redirect(screen_text)
        if currency_match:
            self.logger.info(
                f"      [PENALTY] {currency_match} currency redirect detected - clicking..."
            )
            clicked_text = self.click_currency_link(screen_text)
            if clicked_text and clicked_text.strip() != screen_text.strip():
                screen_text = clicked_text

        previous_page_text = screen_text
        current_page = 1
        seen_fares = set()
        penalty_records = []

        while current_page <= max_pages:
            self._raise_if_stopped()
            if not self._has_end_signal(screen_text):
                settled_text = self._wait_for_stable_screen(
                    initial_text=screen_text, max_polls=2, interval=0.2
                )
                if settled_text.strip() != screen_text.strip():
                    screen_text = settled_text

            from parser import parse_fare_display, select_report_fare_targets

            parsed_page = parse_fare_display(screen_text)
            visible_targets = select_report_fare_targets(parsed_page.get("fares", []))

            if not visible_targets:
                refreshed_text = self._wait_for_stable_screen(
                    initial_text=screen_text, max_polls=3, interval=0.25
                )
                if refreshed_text.strip() != screen_text.strip():
                    screen_text = refreshed_text
                    parsed_page = parse_fare_display(screen_text)
                    visible_targets = select_report_fare_targets(
                        parsed_page.get("fares", [])
                    )

            self.logger.info(
                f"      [PENALTY] {len(visible_targets)} report-target fare(s) on page {current_page}"
            )

            page_records, screen_text = self._extract_penalties_from_visible_page(
                screen_text, seen_fares, visible_targets
            )
            penalty_records.extend(page_records)

            if self._has_end_signal(screen_text):
                break

            if not visible_targets and not self._has_more_prompt(screen_text):
                self.logger.warning(
                    "      [PENALTY] No report-target fare rows detected on this page; stopping before MD."
                )
                break

            if self.click_more_prompt_link(screen_text):
                md_response = self._wait_for_response(
                    screen_text,
                    timeout=constants.COMMAND_WAIT_MEDIUM + 0.5,
                    min_wait=0.0,
                    stability_checks=1,
                )
                md_response = self._wait_for_stable_screen(
                    initial_text=md_response, max_polls=3, interval=0.2
                )
            else:
                text_before_md = screen_text
                pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
                pyautogui.press("enter")
                md_response = self._wait_for_response(
                    text_before_md, timeout=constants.COMMAND_WAIT_MEDIUM + 0.5
                )

            if self._has_invalid(md_response):
                break

            if md_response.strip() == previous_page_text.strip():
                break

            if self._has_more_prompt(md_response):
                pyautogui.press("enter")
                md_response = self._wait_for_response(
                    md_response, timeout=constants.COMMAND_WAIT_FS
                )

            previous_page_text = md_response
            screen_text = md_response
            current_page += 1

        return penalty_records

    def run_ftax_command(
        self,
        country_code: str,
        tax_code: str,
        tax_index: int = 1,
        max_pages: int = MAX_PAGES_TAX,
    ) -> str:
        """
        Run an FTAX details command and paginate through results,
        ACCUMULATING text from every page.

        Strategy:
          1. Try direct command FTAX-{CC}/{CODE} first
          2. If INVALID, fall back to Tab navigation from the tax list
          3. Capture each page's text and accumulate into a combined result
          4. Detect end via END, INVALID on MD, or stuck (same content twice)
          5. Return the full accumulated text
        """
        if not self.focus():
            self.logger.error("  [ERROR] Cannot run command, window not focused.")
            return ""

        self._raise_if_stopped()
        self.logger.info(f"    Extracting tax detail: FTAX-{country_code}/{tax_code}")

        # --- Navigate to the tax detail ---
        # Try direct command first (simpler and more reliable)
        direct_cmd = f"FTAX-{country_code}/{tax_code}"
        self.logger.debug(f"      Trying direct command: {direct_cmd}")

        text_before = self._copy_terminal_text()

        pyautogui.typewrite(direct_cmd, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        # Use adaptive waiting for FTAX (can be slow)
        first_page = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_FTAX + 1.5,
            min_wait=constants.COMMAND_WAIT_FTAX * 0.8,
            stability_checks=2,
        )

        # If direct command returned INVALID, fall back to Tab navigation
        if self._has_invalid(first_page):
            self.logger.debug(
                f"      Direct command returned INVALID. Falling back to Tab navigation (index {tax_index})..."
            )
            # Re-send the list command to get back to the tax list
            list_cmd = f"FTAX-{country_code}"

            text_before = first_page

            pyautogui.typewrite(list_cmd, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")

            list_result = self._wait_for_response(
                text_before,
                timeout=constants.COMMAND_WAIT_FTAX + 1.5,
                min_wait=constants.COMMAND_WAIT_FTAX * 0.8,
                stability_checks=2,
            )

            # Tab to the correct link
            for _ in range(tax_index):
                pyautogui.press("tab", interval=constants.KEYBOARD_INTERVAL)

            text_before = list_result

            pyautogui.press("enter")

            first_page = self._wait_for_response(
                text_before,
                timeout=constants.COMMAND_WAIT_FTAX + 1.5,
                min_wait=constants.COMMAND_WAIT_FTAX * 0.8,
                stability_checks=2,
            )

            if self._has_invalid(first_page):
                self.logger.warning(
                    f"      Tab navigation also returned INVALID for {tax_code}."
                )
                return first_page

        # --- Accumulate text across pages ---
        all_pages_text = [first_page]
        previous_text = first_page
        current_page = 1

        seen_tax_rate = False

        while current_page <= max_pages:
            self._raise_if_stopped()
            # Check if current screen already has END
            if self._has_end_signal(previous_text):
                self.logger.debug("      'END' detected. Pagination complete.")
                break

            # Record if we've seen TAX RATE
            if "TAX RATE" in previous_text.upper():
                seen_tax_rate = True

            # Check if we reached EXEMPTIONS (which always follows TAX RATE)
            # Only trigger this AFTER we have seen the TAX RATE block, as EXEMPTIONS
            # can also appear on page 1 before the rates!
            if seen_tax_rate and (
                "EXEMPTIONS:" in previous_text.upper()
                or "EXEMPTION:" in previous_text.upper()
            ):
                self.logger.debug(
                    "      'EXEMPTIONS:' section reached after TAX RATE. Rates are fully captured. Stopping."
                )
                break

            # Send MD
            self.logger.debug(f"      Page {current_page}: Sending MD...")

            pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")

            # Use adaptive waiting for MD pagination
            page_text = self._wait_for_response(
                previous_text,
                timeout=constants.COMMAND_WAIT_FS + 1.0,
                min_wait=constants.COMMAND_WAIT_FS * 0.6,
                stability_checks=2,
            )

            # Check if MD returned INVALID
            if self._has_invalid(page_text):
                self.logger.debug("      MD returned 'INVALID'. End of pagination.")
                break

            # Check if we're stuck (same content as previous page)
            if page_text.strip() == previous_text.strip():
                # Retry once with adaptive wait and longer timeout
                self.logger.debug(
                    "      Same text detected. Retrying with extended wait..."
                )
                page_text = self._wait_for_response(
                    previous_text,
                    timeout=constants.COMMAND_WAIT_LONG + 1.0,
                    min_wait=0.8,
                    poll_interval=0.2,
                    stability_checks=3,  # More stability checks for stuck retry
                )
                if page_text.strip() == previous_text.strip():
                    self.logger.debug(
                        "      Stuck: same content after retry. Stopping."
                    )
                    break

            # Handle More Fares/Flights prompt
            if self._has_more_prompt(page_text):
                text_before_prompt = page_text

                pyautogui.press("enter")

                page_text = self._wait_for_response(
                    text_before_prompt,
                    timeout=constants.COMMAND_WAIT_FS + 0.5,
                    min_wait=constants.COMMAND_WAIT_FS * 0.6,
                    stability_checks=2,
                )

            all_pages_text.append(page_text)
            previous_text = page_text
            current_page += 1

        if current_page > max_pages:
            self.logger.warning(f"      Reached max_pages ({max_pages}). Stopping.")

        # Combine all pages into one block of text
        # Each page may have overlapping header lines; we join with a separator
        combined = "\n--- PAGE BREAK ---\n".join(all_pages_text)
        self.logger.debug(
            f"      Accumulated {len(all_pages_text)} pages, {len(combined)} total chars."
        )

        return combined

    def run_fs_command(self, src: str, dst: str, date: str, airline: str) -> str:
        """
        Run an FS (Flight Shopping) command.
        Example: FSDAC28MAYMLE/BS

        Returns the raw terminal output showing the Pricing Options.
        """
        if not self.focus():
            return ""

        self._raise_if_stopped()
        command = f"FS{src}{date}{dst}/{airline}"
        self.logger.info(f"    Extracting FS pricing: {command}")

        # Capture screen before command
        text_before = self._copy_terminal_text()

        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        # Use adaptive waiting with FS timeout as ceiling
        # Wait for screen to change AND stabilize
        result = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_FS + 1.0,
            min_wait=constants.COMMAND_WAIT_FS * 0.8,  # 80% of expected time as minimum
            stability_checks=2,
        )

        return result

    def run_fzs_command(self, from_currency: str, to_currency: str, amount: int = 1) -> str:
        """
        Run an FZS (Currency Conversion) command.
        Example: FZSUSD1BDT

        Returns the raw terminal output with exchange rate info.
        """
        if not self.focus():
            return ""

        self._raise_if_stopped()
        command = f"FZS{from_currency}{amount}{to_currency}"
        self.logger.info(f"    Extracting FZS rate: {command}")

        text_before = self._copy_terminal_text()

        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        result = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_MEDIUM + 1.0,
            min_wait=constants.COMMAND_WAIT_MEDIUM * 0.8,
            stability_checks=1,
        )

        return result

    def run_fq_command(self, option_number: int) -> str:
        """
        Run FQ*{N} to get the full fare quote / tax breakdown for a Pricing Option.

        This replaces the fragile 'D' button click approach. After an FS command
        has loaded Pricing Options on screen, typing FQ*{N} (where N is the
        pricing option number) returns the same tax breakdown data that clicking
        the 'D' button would show.

        Args:
            option_number: The Pricing Option number (1-based, as shown on screen)

        Returns:
            Raw terminal text containing base fare, equiv fare, YQ, taxes, total.
        """
        if not self.focus():
            return ""

        fq_cmd = f"FQ*{option_number}"
        self.logger.info(f"      Extracting tax breakdown: {fq_cmd}")

        # Capture screen before command
        text_before = self._copy_terminal_text()

        pyautogui.typewrite(fq_cmd, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        # Use adaptive waiting - ensure stability
        result = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_FS + 1.0,
            min_wait=constants.COMMAND_WAIT_FS * 0.8,
            stability_checks=2,
        )

        # If FQ* returned INVALID, this option might not support it
        if self._has_invalid(result):
            self.logger.warning(
                f"      FQ*{option_number} returned INVALID. Trying FQP*{option_number}..."
            )
            # Fallback: try FQP* (pricing-specific variant)
            text_before = result

            pyautogui.typewrite(
                f"FQP*{option_number}", interval=constants.KEYBOARD_INTERVAL
            )
            pyautogui.press("enter")

            result = self._wait_for_response(
                text_before,
                timeout=constants.COMMAND_WAIT_FS + 1.0,
                min_wait=constants.COMMAND_WAIT_FS * 0.8,
                stability_checks=2,
            )

        # Paginate if needed (fare quotes can span multiple pages)
        page = 1
        while page < 5:
            if self._has_end_signal(result):
                break
            if self._has_invalid(result):
                break

            prev_result = result

            pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")

            md_result = self._wait_for_response(
                prev_result,
                timeout=constants.COMMAND_WAIT_FS + 0.5,
                min_wait=constants.COMMAND_WAIT_FS * 0.6,
                stability_checks=2,
            )

            if self._has_invalid(md_result) or md_result.strip() == result.strip():
                break
            result = md_result
            page += 1

        self.logger.debug(f"      FQ result: {len(result)} chars captured.")
        return result

    def click_book_link(self, option_index: int, fs_text: str) -> str:
        """
        Click the «BOOK» hyperlink for a Pricing Option in FS results.

        Returns the booking confirmation screen text (used to then run FQC for
        baggage data).  The caller must send_ignore_command() after use.
        """
        if not self.focus():
            return ""

        lines = fs_text.split("\n")
        option_headers = [
            idx for idx, line in enumerate(lines) if _RE_PRICING_OPTION.search(line)
        ]

        target_line = None
        if option_index < len(option_headers):
            block_start = option_headers[option_index]
            block_end = (
                option_headers[option_index + 1]
                if option_index + 1 < len(option_headers)
                else len(lines)
            )
            for idx in range(block_start, block_end):
                if "+TQ" in lines[idx] or "BOOK" in lines[idx] or "\xabBOOK\xbb" in lines[idx]:
                    target_line = idx
                    break

        if target_line is None:
            self.logger.warning("      [BOOK] Could not locate BOOK/+TQ line in FS text.")
            return ""

        line_text = lines[target_line]
        m = re.search(r"\xabBOOK\xbb|(?<!\w)BOOK(?!\w)", line_text)
        book_col = m.start() if m else 0
        line_len = max(len(line_text), 1)
        x_ratio = max(0.01, min(book_col / line_len, 0.40))

        click_x, click_y = self._text_line_to_pixel(
            fs_text, target_line, x_ratio=x_ratio
        )

        text_before = self._copy_terminal_text()
        self._safe_focus_click(click_x, click_y)
        time.sleep(0.4)

        result = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_FS + 1.5,
            min_wait=0.4,
            stability_checks=2,
        )

        self.logger.info(
            f"      [BOOK] Clicked at line {target_line}, col {book_col} "
            f"→ {len(result)} chars"
        )
        return result

    def run_fqc_command(self, airline_code: str) -> str:
        """
        Send FQC{airline}/ET to get fare quote with baggage allowance info.
        Requires an active booking context created by click_book_link().
        """
        if not self.focus():
            return ""

        command = f"FQC{airline_code.upper()}/ET"
        self.logger.info(f"      Sending: {command}")

        text_before = self._copy_terminal_text()
        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        accumulated = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_FS + 2.0,
            min_wait=0.5,
            stability_checks=2,
        )

        # Paginate through multi-page responses (baggage note sections can be long)
        for _ in range(8):
            if self._has_end_signal(accumulated) or self._has_invalid(accumulated):
                break
            prev = accumulated
            pyautogui.typewrite("MD", interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            page = self._wait_for_response(
                prev,
                timeout=constants.COMMAND_WAIT_FS,
                min_wait=0.3,
                stability_checks=1,
            )
            if not page or page.strip() == prev.strip() or self._has_invalid(page):
                break
            accumulated += "\n" + page

        self.logger.debug(f"      FQC: {len(accumulated)} chars captured.")
        return accumulated

    def send_ignore_command(self) -> str:
        """Send 'I' (Ignore) to cancel the current booking context and return to a clean prompt."""
        if not self.focus():
            return ""

        text_before = self._copy_terminal_text()
        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        result = self._wait_for_response(
            text_before,
            timeout=constants.COMMAND_WAIT_SHORT + 0.5,
            min_wait=0.2,
            stability_checks=1,
        )
        self.logger.info("      [BOOK] Sent I (Ignore) — booking context cleared.")
        return result

    def expand_fs_tax_breakdown(self, tabs_to_press: int) -> str:
        """
        Press Tab 'tabs_to_press' times to reach the 'D' (Tax Breakdown)
        button for a specific Pricing Option in an FS display, and press Enter.

        Returns the expanded terminal text containing YQ and Tax Breakdown.
        """
        if not self.focus():
            return ""

        self.logger.debug(f"      Tabbing {tabs_to_press} times to reach 'D' button...")

        # Reset tab position by clicking the terminal to ensure focus is at the top
        self.focus()
        pyautogui.press("escape")
        time.sleep(constants.CLICK_DELAY)

        for _ in range(tabs_to_press):
            pyautogui.press("tab", interval=constants.KEYBOARD_INTERVAL)

        pyautogui.press("enter")
        time.sleep(
            constants.COMMAND_WAIT_LONG
        )  # Wait for the inline tax breakdown to expand
        return self._copy_terminal_text()

    def _text_line_to_pixel(
        self,
        text: str,
        target_line_idx: int,
        char_idx: int = None,
        x_ratio: float = 0.5,
    ):
        """
        Convert a text line number to pixel screen coordinates.

        Uses FIXED line height (LINE_HEIGHT constant, typically 20px) based on the terminal's monospaced font,
        NOT calculated from total text lines (which would be wrong when the
        terminal has many blank lines below the content).

        Args:
            text: The full terminal text (from Ctrl+A, Ctrl+C)
            target_line_idx: 0-based index of the target line in the text
            char_idx: Optional character column index for precise X positioning
            x_ratio: Fallback horizontal position (0.0=left, 1.0=right) if char_idx not given

        Returns:
            (pixel_x, pixel_y) screen coordinates
        """
        # Use the SmartRichTextBox rect, NOT the window rect
        rect = self._get_terminal_rect()

        # Content starts ~5px below the terminal pane top edge
        content_top = rect.top + self._content_top_padding

        # Y: center of the target line (uses calibrated line height)
        pixel_y = int(content_top + (target_line_idx + 0.5) * self._line_height)

        # X: from character column if available, otherwise from ratio
        if char_idx is not None:
            # monospaced terminal: text width is proportional to column index
            # Divide by maximum line length to find terminal's total character columns
            lines = text.split("\n")
            # Filter out trailing separators or breadcrumbs if present
            clean_lines = [l.strip("\r") for l in lines if len(l.strip()) > 0]
            if clean_lines:
                # Get the max length which represents the terminal's column count
                # (since Ctrl+A, Ctrl+C usually captures the full grid width)
                terminal_width_chars = max(len(l) for l in clean_lines)
                terminal_width_chars = max(terminal_width_chars, 1)  # Avoid div by zero

                # Position pixel_x as a proportion of total characters
                x_ratio_from_char = (char_idx + 0.5) / terminal_width_chars
                pixel_x = int(rect.left + rect.width() * x_ratio_from_char)
            else:
                pixel_x = int(rect.left + rect.width() * x_ratio)
        else:
            pixel_x = int(rect.left + rect.width() * x_ratio)

        return (pixel_x, pixel_y)

    def click_element_by_text_position(
        self,
        text: str,
        search_pattern: str,
        x_ratio: float = 0.5,
        occurrence: int = 0,
        y_offsets: list = None,
        use_2d_offsets: bool = False,
    ) -> str:
        """
        Find text in the terminal output, calculate its screen position, and click it.

        Uses fixed line height (20px) and regex to find the target line,
        then clicks with retry offsets for tolerance.

        Args:
            text: Terminal text to search
            search_pattern: Regex pattern to find target text
            x_ratio: Horizontal position ratio (0.0=left, 1.0=right)
            occurrence: Which match to click (0=first, -1=last)
            y_offsets: List of vertical pixel offsets to try (deprecated if use_2d_offsets=True)
            use_2d_offsets: If True, use 2D (x,y) offset tuples for better tolerance
        """


        if not self.focus():
            return ""

        # Determine offset strategy
        if use_2d_offsets:
            # Use 2D offsets for both horizontal and vertical tolerance
            offsets = [
                (0, 0),
                (0, -9),
                (0, 9),  # Vertical only
                (-10, 0),
                (10, 0),  # Horizontal only
                (0, -18),
                (0, 18),  # More vertical
                (-10, -9),
                (10, -9),  # Diagonal combinations
                (-10, 9),
                (10, 9),
                (-20, 0),
                (20, 0),  # More horizontal
            ]
        else:
            # Legacy: vertical offsets only
            if y_offsets is None:
                y_offsets = [0, -9, 9, -18, 18]
            offsets = [(0, y) for y in y_offsets]

        # Clear any text selection first
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        time.sleep(constants.ESCAPE_CLEAR_DELAY)

        # Find matching lines and character positions
        lines = text.split("\n")
        matches = []  # List of (line_idx, char_idx) tuples
        for idx, line in enumerate(lines):
            match = re.search(search_pattern, line, re.IGNORECASE)
            if match:
                # Calculate middle character of the match for best click target
                match_char_idx = (match.start() + match.end()) // 2
                matches.append((idx, match_char_idx))

        if not matches:
            self.logger.error(
                f"      [CLICK] Pattern '{search_pattern}' not found in {len(lines)} lines"
            )
            return ""

        if occurrence >= len(matches) or (
            occurrence < 0 and abs(occurrence) > len(matches)
        ):
            self.logger.error(
                f"      [CLICK] Only {len(matches)} matches, need #{occurrence}"
            )
            return ""

        target_line, target_char = matches[occurrence]
        base_x, base_y = self._text_line_to_pixel(
            text, target_line, char_idx=target_char
        )

        self.logger.info(
            f"      [CLICK] Line {target_line}, Col {target_char} -> ({base_x}, {base_y})"
        )

        text_before = text
        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(
                f"      [CLICK] Trying ({click_x}, {click_y}) [offset=({x_off},{y_off})]"
            )

            pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
            pyautogui.click()
            time.sleep(constants.COMMAND_WAIT_SHORT)

            result = self._copy_terminal_text()

            # Check if we accidentally activated a dropdown
            if self._has_dropdown_activated(result):
                self.logger.debug(
                    "      [CLICK] Dropdown detected - capturing text before closing..."
                )
                # IMPORTANT: Capture the dropdown text (may contain fare basis details)
                dropdown_text = result
                # Close the dropdown
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)
                # Return the captured dropdown text instead of discarding it
                # This ensures fare basis info in dropdowns is included in the report
                self.logger.info(
                    f"      [CLICK] Dropdown text captured ({len(dropdown_text)} chars)"
                )
                return dropdown_text

            if result.strip() != text_before.strip():
                self.logger.info(
                    f"      [CLICK] Screen changed at offset=({x_off},{y_off})"
                )
                return result

        self.logger.warning(f"      [CLICK] All offsets tried, screen unchanged.")
        return self._copy_terminal_text()

    # ── Landmark helpers (Phase B) ────────────────────────────────────────────

    _RE_D_BUTTON_COL = re.compile(r"\bD\b")

    def _find_d_char_column(self, line: str) -> int | None:
        """Return column of the D button on a +TQ/BOOK line, or None."""
        # The D button sits in the right ~30 % of the line.
        min_col = max(0, len(line) * 7 // 10)
        matches = list(self._RE_D_BUTTON_COL.finditer(line))
        for m in reversed(matches):
            if m.start() >= min_col:
                return m.start()
        # Fallback: rightmost D in right half
        for m in reversed(matches):
            if m.start() >= len(line) // 2:
                return m.start()
        return None

    @staticmethod
    def _find_link_char_column(line: str, pattern: re.Pattern) -> int | None:
        """Return the start column of a hyperlink regex match in a terminal line."""
        m = pattern.search(line)
        return m.start() if m else None

    # ── Manual D-click validation (v1.5.17) ───────────────────────────────────
    #
    # Before v1.5.17, *any* mouse click captured by the background monitor
    # while click_d_button was running could be attributed as "the user
    # clicked D and we should learn that position".  In practice the OS
    # sometimes fires stray clicks (focus recovery, accidental moves, the
    # fail-safe pulling the cursor briefly out of the app and back) — and
    # those got mis-attributed, persisting offsets like (-554, -385) that
    # broke the next run entirely.  These bounds reject any click that is
    # not plausibly on the D button row.

    _MANUAL_D_CLICK_X_TOLERANCE_PX = 100
    # Raised from 1.5 to 4.0 (±80 px at 20 px/line).  The tight 1.5-line
    # value accumulated calibration error for deep options (option 3/4 at
    # text line 20+) and rejected valid manual clicks that were 44+ px from
    # the computed base_y.  4.0 lines still rejects title-bar/tab-strip
    # clicks while absorbing ~5 px/line of drift over 16 lines.
    _MANUAL_D_CLICK_Y_TOLERANCE_LINES = 4.0

    def _is_manual_click_in_d_region(
        self,
        ux: int,
        uy: int,
        base_x: int,
        base_y: int,
    ) -> bool:
        """Return True when (ux, uy) is plausibly a click on the D button.

        The bounds (in physical pixels) are intentionally loose enough that
        a slightly-misaimed real click still counts, but tight enough to
        reject:
          * tab strip / title bar clicks above the terminal pane,
          * focus-recovery clicks far from the BOOK/+TQ/D row,
          * accidental clicks elsewhere on screen.

        We require the click to be inside the SmartRichTextBox terminal
        pane, within ±100 px of base_x (the +TQ → D column range), and
        within ±line_height·4.0 of base_y.  When base_y is outside the
        visible rect (option 3/4 off-screen), we skip the Y check entirely
        since the user had to scroll to find the D button — any in-pane,
        in-column click counts."""
        try:
            rect = self._get_terminal_rect()
        except Exception:
            return False

        if not (rect.left <= ux <= rect.right):
            return False
        if not (rect.top <= uy <= rect.bottom):
            return False
        # When base_y is off-screen (option scrolled below visible terminal
        # edge), skip the Y proximity check — the user had to scroll and we
        # cannot know the exact rendered Y from captured text coordinates.
        base_y_in_rect = rect.top <= base_y <= rect.bottom
        if base_y_in_rect:
            y_tol = int(self._line_height * self._MANUAL_D_CLICK_Y_TOLERANCE_LINES)
            if abs(uy - base_y) > y_tol:
                return False
        if abs(ux - base_x) > self._MANUAL_D_CLICK_X_TOLERANCE_PX:
            return False
        return True

    @staticmethod
    def _saved_offset_is_sane(
        offset_x: int,
        offset_y: int,
        rect_width: int,
        line_height: int,
    ) -> bool:
        """Reject saved offsets that are obviously bogus (learned from a
        stray click, e.g. a focus-recovery click on a tab outside the D
        row).  Used at the start of click_d_button to defang corrupted
        calibration files instead of replaying offsets that point off-pane."""
        if abs(offset_x) > rect_width // 2:
            return False
        if abs(offset_y) > 4 * max(1, line_height):
            return False
        return True

    @staticmethod
    def _post_click_screen_matches_option(text: str, option_index: int) -> bool:
        """Tighter version of looks_like_fs_tax_breakdown that also requires
        the FS-N marker for the option we tried to expand.  Guards against
        accidental +TQ clicks that produce a tax-breakdown-shaped screen
        for a *different* option (or no FS-N at all)."""
        from tax_breakdown_parser import looks_like_fs_tax_breakdown

        if not looks_like_fs_tax_breakdown(text):
            return False
        # Smartpoint marks the FS detail with `FS-{N} ADT` where N is the
        # human-readable option number (option_index 0 → "FS-1 ADT").
        expected_marker = f"FS-{option_index + 1} ADT"
        return expected_marker in text.upper()

    def click_d_button(self, option_index: int, fs_text: str) -> str:
        """
        Click the 'D' (Details) button for a specific Pricing Option in FS results.

        Finds the D button by looking for lines containing the "D  R" pattern
        (which appears on the BOOK +TQ line of each Pricing Option), then
        calculates the exact pixel position from the character column.
        """

        from tax_breakdown_parser import looks_like_fs_tax_breakdown

        if not self.focus():
            return ""

        lines = fs_text.split("\n")

        # First anchor to the selected PRICING OPTION block. The unique-airline
        # itinerary is often option 1, but can appear in the middle of the page.
        option_headers = [
            idx for idx, line in enumerate(lines) if _RE_PRICING_OPTION.search(line)
        ]

        target_line = None
        if option_index < len(option_headers):
            block_start = option_headers[option_index]
            block_end = (
                option_headers[option_index + 1]
                if option_index + 1 < len(option_headers)
                else len(lines)
            )
            for idx in range(block_start, block_end):
                line = lines[idx]
                if "+TQ" in line or "BOOK" in line or "\xabBOOK\xbb" in line:
                    target_line = idx
                    break

            if target_line is not None:
                self.logger.info(
                    f"      [D-CLICK] Option {option_index+1}: block lines "
                    f"{block_start}-{block_end - 1}, D row={target_line}"
                )

        # Fallback: Find lines containing BOOK or +TQ. These markers are
        # normally on the same line as the D button. Using "D  R" is unreliable
        # because the clipboard sometimes splits D and R across lines.
        d_button_lines = []
        for idx, line in enumerate(lines):
            if "+TQ" in line or "BOOK" in line or "\xabBOOK\xbb" in line:
                d_button_lines.append(idx)

        self.logger.info(
            f"      [D-CLICK] Found {len(d_button_lines)} BOOK/+TQ lines: {d_button_lines}"
        )

        if target_line is None and not d_button_lines:
            # Final fallback: search near PRICING OPTION headers.
            self.logger.warning(
                "      [D-CLICK] No 'D  R' pattern found. Trying PRICING OPTION fallback..."
            )

            if option_index < len(option_headers):
                target_line = option_headers[option_index] + 4
            else:
                self.logger.error(
                    f"      [D-CLICK] Cannot locate D button for option {option_index}"
                )
                return ""
        elif target_line is None:
            if option_index >= len(d_button_lines):
                self.logger.error(
                    f"      [D-CLICK] Only {len(d_button_lines)} D buttons, need index {option_index}"
                )
                return ""

            target_line = d_button_lines[option_index]

        # Phase B: resolve the exact column of the D character on the target line.
        # Fall back to the empirical ratio only when char detection fails.
        ratio_x, base_y = self._text_line_to_pixel(
            fs_text, target_line, x_ratio=D_BUTTON_X_RATIO
        )
        d_char_col = self._find_d_char_column(lines[target_line])
        char_x: int | None = None
        if d_char_col is not None:
            char_x, _ = self._text_line_to_pixel(
                fs_text, target_line, char_idx=d_char_col
            )
            clean_lines = [line.strip("\r") for line in lines if line.strip()]
            terminal_width_chars = max((len(line) for line in clean_lines), default=0)
            if terminal_width_chars > 0:
                char_width = self._get_terminal_rect().width() / terminal_width_chars
                d_left_bias = max(12, min(28, int(round(char_width * 4.0))))
            else:
                d_left_bias = 18
            char_biased_x = char_x - d_left_bias
            base_x = min(char_biased_x, ratio_x)
            self.logger.info(
                f"      [D-CLICK] Option {option_index+1}: line {target_line}, "
                f"D at col {d_char_col} -> char_x={char_x}, ratio_x={ratio_x}, "
                f"using x={base_x} [left-bias={d_left_bias}px]"
            )
        else:
            base_x = ratio_x
            self.logger.info(
                f"      [D-CLICK] Option {option_index+1}: line {target_line}, "
                f"D col not found — using ratio {D_BUTTON_X_RATIO} -> ({base_x}, {base_y})"
            )

        # Clear selection
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        time.sleep(constants.ESCAPE_CLEAR_DELAY)

        # Try clicking with combined X and Y offsets for tolerance
        text_before = fs_text
        offsets = [
            (0, 0),
            (-15, 0),
            (15, 0),
            (0, -9),
            (0, 9),
            (-15, -9),
            (15, -9),
            (-15, 9),
            (15, 9),
        ]

        # Secondary wave: if char detection found D meaningfully right of
        # the left-biased base_x, also try positions centred on char_x.
        if char_x is not None:
            char_x_delta = char_x - base_x
            if char_x_delta >= 10:
                offsets.extend([
                    (char_x_delta, 0),
                    (char_x_delta, -9),
                    (char_x_delta, 9),
                    (char_x_delta - 12, 0),
                    (char_x_delta + 12, 0),
                ])

        # Tertiary wave: wider Y (±18 ≈ ±1 line) for miscalibrated line_height.
        offsets.extend([(0, -18), (0, 18)])
        if char_x is not None and (char_x - base_x) >= 10:
            char_x_delta = char_x - base_x
            offsets.extend([(char_x_delta, -18), (char_x_delta, 18)])

        # Phase D: prepend saved X prefix so the known-good column is tried
        # first; falls through to full fan-out if the saved offset stops working.
        #
        # Two saved offsets may be present:
        #   * d_click_char_x_offset (preferred when char_x detected this run):
        #     stable across terminal-width changes because char_x is detected
        #     per line.  Convert to a base_x-relative offset before feeding
        #     the offsets list machinery, which clicks at base_x + x_off.
        #   * d_click_offset: legacy base_x-relative offset, used as fallback.
        saved_offset = _calibration_mod.get_d_click_offset(self._cal)
        saved_char_x_offset = _calibration_mod.get_d_click_char_x_offset(self._cal)

        # v1.5.17 — defang corrupted calibration files.  If the saved
        # offset is obviously absurd (e.g. learned from a stray click on
        # a tab outside the terminal pane), drop it and start fresh
        # rather than replaying a click at off-pane coordinates.
        try:
            _rect_for_sanity = self._get_terminal_rect()
            _rect_width = _rect_for_sanity.width()
        except Exception:
            _rect_width = 0
        if (
            _rect_width > 0
            and saved_offset is not None
            and not self._saved_offset_is_sane(
                saved_offset[0], saved_offset[1], _rect_width, self._line_height
            )
        ):
            self.logger.warning(
                f"      [D-CLICK] Saved offset {saved_offset} is outside sane bounds "
                f"for rect width={_rect_width}; clearing and re-learning."
            )
            self._cal = _calibration_mod.clear_d_click_offset(self._cal)
            _calibration_mod.save_calibration(self._cal)
            saved_offset = None
            saved_char_x_offset = None

        effective_saved_offset: tuple[int, int] | None = None
        saved_offset_source: str = ""
        if saved_char_x_offset is not None and char_x is not None:
            cx_off, cy_off = saved_char_x_offset
            effective_saved_offset = ((char_x - base_x) + cx_off, cy_off)
            saved_offset_source = "char_x"
        elif saved_offset is not None:
            effective_saved_offset = saved_offset
            saved_offset_source = "base_x"

        if effective_saved_offset is not None:
            saved_x, saved_y = effective_saved_offset
            saved_x_prefix = [
                (saved_x, saved_y),
                (saved_x, 0),
                (saved_x, -9),
                (saved_x, 9),
                (saved_x, -18),
                (saved_x, 18),
            ]
            seen: set[tuple[int, int]] = set()
            reordered: list[tuple[int, int]] = []
            for off in saved_x_prefix + offsets:
                if off not in seen:
                    seen.add(off)
                    reordered.append(off)
            offsets = reordered
            self.logger.debug(
                f"      [D-CLICK] Trying saved-X variants first "
                f"(saved_x={saved_x}, source={saved_offset_source})."
            )

        # --- Background click monitor (runs for the whole duration) ----------
        # Records every left-button release so manual clicks can be detected
        # at any point during the fan-out, not just after exhaustion.
        # Thread only reads Win32 state — no clipboard access, thread-safe.

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        _mon_clicks: list[tuple[float, int, int]] = []  # (timestamp, x, y)
        _mon_stop = threading.Event()

        def _monitor_clicks() -> None:
            _get_key = ctypes.windll.user32.GetAsyncKeyState
            _get_pos = ctypes.windll.user32.GetCursorPos
            prev_dn = bool(_get_key(0x01) & 0x8000)
            while not _mon_stop.is_set():
                time.sleep(0.02)
                dn = bool(_get_key(0x01) & 0x8000)
                if prev_dn and not dn:
                    _pt = _POINT()
                    _get_pos(ctypes.byref(_pt))
                    _mon_clicks.append((time.time(), _pt.x, _pt.y))
                prev_dn = dn

        _mon_thread = threading.Thread(target=_monitor_clicks, daemon=True)
        _mon_thread.start()
        # ----------------------------------------------------------------------

        def _record_success(learned_x: int, learned_y: int, source: str) -> None:
            # When a Y offset is known for a specific text row, derive the
            # implied line height and update calibration.  A single stored
            # y_off is row-specific: an offset correct for row 22 is far too
            # large for row 8 (error = y_off/row × other_row).  Baking the
            # correction into line_height and storing y_off=0 lets every
            # subsequent row compute its own base_y accurately.
            store_y = learned_y
            if store_y != 0 and target_line > 0:
                implied_lh = self._line_height + store_y / target_line
                new_lh = round(max(17.0, min(28.0, implied_lh)), 1)
                self.logger.debug(
                    f"      [D-CLICK] line_height {self._line_height} → {new_lh} "
                    f"(y_off={store_y} at row {target_line}); storing y_off=0."
                )
                self._cal["line_height"] = new_lh
                self._line_height = new_lh
                store_y = 0
            elif store_y != 0 and source == "auto":
                self._cal = _calibration_mod.record_click_delta(self._cal, store_y)
                self._line_height = self._cal["line_height"]
            # When the per-line D-glyph landmark was detectable, also store
            # the offset relative to char_x so subsequent runs at different
            # terminal widths still click on the right glyph.
            char_x_off: int | None = None
            if char_x is not None:
                char_x_off = learned_x - (char_x - base_x)
            self._cal = _calibration_mod.record_d_click_offset(
                self._cal, learned_x, store_y, char_x_off=char_x_off
            )
            _calibration_mod.save_calibration(self._cal)

        try:
            # Initial manual window — only on machines with no saved offset yet.
            # Gives the user 5 seconds to click D before the mouse is moved.
            # Once an offset is learned and saved, this window is skipped entirely
            # (Phase D's saved prefix fires first instead).
            if effective_saved_offset is None:
                self.logger.warning(
                    "      [D-CLICK] No saved position for this PC. "
                    "Click the D button now (5 s) — auto-click starts after."
                )
                init_deadline = time.time() + 5.0
                init_seen = len(_mon_clicks)
                while time.time() < init_deadline:
                    try:
                        self._raise_if_stopped()
                    except Exception:
                        break
                    self._sleep(0.05)
                    if len(_mon_clicks) > init_seen:
                        _, ux, uy = _mon_clicks[-1]
                        init_seen = len(_mon_clicks)
                        # v1.5.17 — reject stray clicks (focus-recovery,
                        # tab strip, etc.).  Only accept clicks plausibly
                        # on the D button row.
                        if not self._is_manual_click_in_d_region(
                            ux, uy, base_x, base_y
                        ):
                            self.logger.info(
                                f"      [D-CLICK] Ignored stray click at ({ux},{uy}) "
                                f"— outside D-row region (base=({base_x},{base_y}))."
                            )
                            continue
                        self._sleep(0.5)
                        result = self._copy_terminal_text()
                        if result.strip() and looks_like_fs_tax_breakdown(result):
                            lx, ly = ux - base_x, uy - base_y
                            self.logger.info(
                                f"      [D-CLICK] Manual click at ({ux},{uy}) "
                                f"[x_off={lx}, y_off={ly}] — learned."
                            )
                            _record_success(lx, ly, "manual")
                            return result

            for x_off, y_off in offsets:
                click_x = base_x + x_off
                click_y = base_y + y_off
                self.logger.debug(
                    f"      [D-CLICK] Trying ({click_x}, {click_y}) [x={x_off}, y={y_off}]"
                )

                pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
                post_click_t = time.time()
                pyautogui.click()
                result = self._wait_for_response(
                    text_before,
                    timeout=constants.COMMAND_WAIT_LONG + 0.5,
                    min_wait=constants.COMMAND_WAIT_SHORT,
                    stability_checks=1,
                )
                result = self._wait_for_stable_screen(
                    initial_text=result, max_polls=4, interval=0.25
                )

                if result.strip() != text_before.strip():
                    # v1.5.18 — reverted the FS-{N} ADT tightening that
                    # v1.5.17 added for auto-success.  In real runs the
                    # tightening rejected legitimate Option 2/3 manual
                    # clicks (the post-click screen for an Option-N detail
                    # may render the FS-N marker in a format the tighter
                    # check missed, e.g. without the exact `FS-{N} ADT`
                    # string).  Result: when the user manually clicked D
                    # for Option 2/3, the click was *recognised* by the
                    # screen-changed check, but `_post_click_screen_matches
                    # _option` rejected it, the code sent `I` to reset,
                    # and the fan-out kept going — wiping the user's
                    # successful click.  Manual-click region validation
                    # below still guards against stray clicks.
                    if looks_like_fs_tax_breakdown(result):
                        # Was this a manual click? Any click recorded >100 ms
                        # after post_click_t is from the user, not pyautogui.
                        # Iterate from newest to oldest so we look at the
                        # *most recent* user click, not the first stray one.
                        user_click = None
                        for click in reversed(_mon_clicks):
                            if click[0] <= post_click_t + 0.1:
                                break
                            _, ux, uy = click
                            if self._is_manual_click_in_d_region(
                                ux, uy, base_x, base_y
                            ):
                                user_click = click
                                break
                        if user_click:
                            _, ux, uy = user_click
                            lx, ly = ux - base_x, uy - base_y
                            self.logger.info(
                                f"      [D-CLICK] Manual click at ({ux},{uy}) "
                                f"[x_off={lx}, y_off={ly}] — learned."
                            )
                            _record_success(lx, ly, "manual")
                        else:
                            self.logger.info(
                                f"      [D-CLICK] Tax breakdown at offset=({x_off},{y_off})"
                            )
                            _record_success(x_off, y_off, "auto")
                        return result
                    else:
                        upper = result.upper()
                        looks_like_pricing_screen = (
                            "PRICING OPTION" in upper
                            and "TOTAL AMOUNT" in upper
                            and ("BOOK" in upper or "+TQ" in upper)
                        )
                        if looks_like_pricing_screen:
                            self.logger.debug(
                                "      [D-CLICK] Screen changed but still looks like pricing options. "
                                "Trying the next offset without hard reset..."
                            )
                            text_before = result
                            pyautogui.press(
                                "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                            )
                            time.sleep(constants.ESCAPE_CLEAR_DELAY)
                            continue
                        # Something unexpected opened (e.g., clicking the
                        # serial-number column opened a flight-detail screen).
                        # Escape is cheaper and safer than "I": it closes
                        # popups, booking screens, and detail views without
                        # sending a GDS command that might mis-parse.
                        self.logger.debug(
                            "      [D-CLICK] Unexpected screen (not breakdown, not pricing). "
                            f"First 120 chars: {result[:120]!r} — dismissing with Escape."
                        )
                        pyautogui.press(
                            "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                        )
                        time.sleep(constants.ESCAPE_CLEAR_DELAY)
                        text_before = self._copy_terminal_text()
                        if "PRICING OPTION" in text_before.upper():
                            # Escape recovered the FS screen — continue the fan-out.
                            self.logger.debug(
                                "      [D-CLICK] Escape recovered FS screen; continuing fan-out."
                            )
                            continue
                        # Escape didn't recover — try "I" as a last resort.
                        self.logger.debug(
                            "      [D-CLICK] Escape did not recover FS screen; sending 'I'."
                        )
                        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
                        pyautogui.press("enter")
                        text_before = self._wait_for_response(
                            text_before,
                            timeout=constants.COMMAND_WAIT_FS,
                            min_wait=constants.COMMAND_WAIT_SHORT,
                            stability_checks=1,
                        )
                        text_before = self._wait_for_stable_screen(
                            initial_text=text_before, max_polls=3, interval=0.25
                        )
                        if "PRICING OPTION" not in text_before.upper():
                            self.logger.warning(
                                "      [D-CLICK] Could not recover FS display. Aborting."
                            )
                            return ""

            # Auto-invalidate a stale saved offset.  If we got here, every
            # auto-click attempt failed.  Only clear the saved offset when
            # base_y was within the visible terminal rect (on-screen failure
            # = the offset is genuinely wrong).  When base_y was off-screen,
            # the failure is because every click landed outside the window —
            # not because the saved offset itself is bad — so preserve it for
            # the next on-screen D-click.
            try:
                _rect_for_clear = self._get_terminal_rect()
                _base_y_in_rect = (
                    _rect_for_clear.top <= base_y <= _rect_for_clear.bottom
                )
            except Exception:
                _base_y_in_rect = True  # assume on-screen if rect unreadable

            if (saved_offset is not None or saved_char_x_offset is not None) and _base_y_in_rect:
                stale = saved_char_x_offset if saved_char_x_offset is not None else saved_offset
                self._cal = _calibration_mod.clear_d_click_offset(self._cal)
                _calibration_mod.save_calibration(self._cal)
                self.logger.warning(
                    f"      [D-CLICK] Saved offset {stale} did not produce "
                    f"a tax breakdown after fan-out; cleared from calibration."
                )
            elif saved_offset is not None or saved_char_x_offset is not None:
                self.logger.warning(
                    "      [D-CLICK] Fan-out failed but base_y is off-screen — "
                    "preserving saved offset (failure was off-screen, not a bad offset)."
                )

            # Fan-out exhausted — monitor is already running; just wait for the
            # user to click D manually (up to 15 seconds).
            self.logger.warning(
                "      [D-CLICK] Auto-click exhausted. Click the D button manually "
                "within 15 seconds — position will be learned for this PC."
            )
            deadline = time.time() + 15.0
            seen_clicks = len(_mon_clicks)
            while time.time() < deadline:
                try:
                    self._raise_if_stopped()
                except Exception:
                    break
                self._sleep(0.05)
                if len(_mon_clicks) > seen_clicks:
                    _, ux, uy = _mon_clicks[-1]
                    seen_clicks = len(_mon_clicks)
                    # v1.5.17 — same region guard as the initial 5s window.
                    # Stray clicks during the 15s wait (focus recovery,
                    # tab clicks, etc.) must not be attributed as D-learn
                    # events.
                    if not self._is_manual_click_in_d_region(
                        ux, uy, base_x, base_y
                    ):
                        self.logger.info(
                            f"      [D-CLICK] Ignored stray click at ({ux},{uy}) "
                            f"during 15s manual fallback — outside D-row region."
                        )
                        continue
                    self._sleep(0.5)
                    result = self._copy_terminal_text()
                    if result.strip() and looks_like_fs_tax_breakdown(result):
                        lx, ly = ux - base_x, uy - base_y
                        self.logger.info(
                            f"      [D-CLICK] Manual click succeeded at ({ux},{uy}) "
                            f"[x_off={lx}, y_off={ly}] — saved to calibration."
                        )
                        _record_success(lx, ly, "manual")
                        return result

            self.logger.warning(
                "      [D-CLICK] Could not expand tax details after all attempts."
            )
            return self._copy_terminal_text()

        finally:
            _mon_stop.set()
            _mon_thread.join(timeout=0.5)

    def click_currency_link(self, fd_text: str) -> str:
        """
        Click the 'BDT CURRENCY FARES EXISTS' hyperlink by directly targeting
        the LEFT portion of the terminal where the text actually renders.

        Previous approaches that FAILED:
        - char_idx math: placed click at x=747 (right side), text is on the left
        - Tab+Enter: cleared the screen but didn't activate the hyperlink

        This approach: find the line, click at multiple LEFT-side x_ratios (0.05-0.35)
        to reliably hit the actual green hyperlink text.
        """


        if not self.focus():
            return None

        self.logger.info(
            "      [CURRENCY] Clicking redirect link on LEFT side of terminal..."
        )

        # Clear any selection
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        time.sleep(constants.ESCAPE_CLEAR_DELAY)

        # Find which line has the text
        lines = fd_text.split("\n")
        target_line_idx = None
        for idx, line in enumerate(lines):
            if _RE_CURRENCY_FARES.search(line):
                target_line_idx = idx
                break

        if target_line_idx is None:
            self.logger.error(
                "      [CURRENCY] Could not find 'CURRENCY FARES EXISTS' line in text"
            )
            return None

        rect = self._get_terminal_rect()
        content_top = rect.top + self._content_top_padding
        click_y = int(content_top + (target_line_idx + 0.5) * self._line_height)

        self.logger.info(
            f"      [CURRENCY] Target: line {target_line_idx}, y={click_y}, "
            f"terminal rect: L={rect.left} R={rect.right} (width={rect.width()})"
        )

        # Wait for terminal to finish rendering before clicking
        stable_text = self._wait_for_stable_screen(initial_text=fd_text)

        # Phase B: anchor X to the actual char position of the link text.
        # Fall back to ratio fan-out when char detection fails.
        target_line_text = lines[target_line_idx]
        link_col = self._find_link_char_column(target_line_text, _RE_CURRENCY_FARES)
        if link_col is not None:
            base_x, _ = self._text_line_to_pixel(fd_text, target_line_idx, char_idx=link_col)
            x_positions = [base_x, base_x - 20, base_x + 20, base_x - 40, base_x + 40]
            self.logger.info(
                f"      [CURRENCY] Link at col {link_col} -> base_x={base_x}"
            )
        else:
            x_positions = [
                int(rect.left + rect.width() * r)
                for r in [0.15, 0.10, 0.20, 0.25, 0.05, 0.30, 0.35]
            ]
            self.logger.debug("      [CURRENCY] Char col not found — using ratio fallback")

        y_offsets = [0, -self._line_height // 2, self._line_height // 2]

        text_before = fd_text
        for y_off in y_offsets:
            for click_x in x_positions:
                actual_y = click_y + y_off
                self.logger.debug(
                    f"      [CURRENCY] Trying x={click_x}, y_off={y_off} -> ({click_x}, {actual_y})"
                )

                pyautogui.moveTo(
                    click_x, actual_y, duration=constants.MOUSE_MOVE_DURATION
                )
                pyautogui.click()
                time.sleep(constants.SCREEN_REFRESH_WAIT)

                result = self._copy_terminal_text()

                # Check if we accidentally triggered a dropdown
                if self._has_dropdown_activated(result):
                    self.logger.debug(
                        "      [CURRENCY] Dropdown detected - capturing text before closing..."
                    )
                    # IMPORTANT: Capture the dropdown text (may contain fare basis details)
                    dropdown_text = result
                    # Close the dropdown
                    pyautogui.press(
                        "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                    )
                    time.sleep(constants.ESCAPE_CLEAR_DELAY)
                    # Return the captured dropdown text instead of discarding it
                    self.logger.info(
                        f"      [CURRENCY] Dropdown text captured ({len(dropdown_text)} chars)"
                    )
                    return dropdown_text

                # Check if screen changed AND redirect is gone
                if result and not self._has_currency_redirect(result):
                    self.logger.info(
                        f"      [CURRENCY] Click succeeded at x={click_x}, y_off={y_off}"
                    )
                    # Phase C: record Y offset delta for self-correction
                    if y_off != 0:
                        self._cal = _calibration_mod.record_click_delta(self._cal, y_off)
                        self._line_height = self._cal["line_height"]
                        _calibration_mod.save_calibration(self._cal)

                    # Poll until fare data fully loads (adaptive, not fixed sleep)
                    if len(result.strip()) <= 100:
                        self.logger.debug(
                            f"      [CURRENCY] Only {len(result.strip())} chars, polling..."
                        )
                        result = self._wait_for_response(
                            result,
                            timeout=constants.COMMAND_WAIT_FS * 3,
                            min_wait=0.1,
                            poll_interval=0.1,
                            stability_checks=1,
                        )
                    self.logger.info(
                        f"      [CURRENCY] Fare data loaded ({len(result.strip())} chars)"
                    )

                    self.logger.info(
                        f"      [CURRENCY] Returning with {len(result.strip())} chars"
                    )
                    return result

                # Screen didn't change meaningfully, try next position
                self.logger.debug(
                    f"      [CURRENCY] No change at x={click_x}, y_off={y_off}"
                )

            # After trying all x_ratios for this y_offset, log progress
            if y_off != y_offsets[-1]:
                self.logger.debug(
                    f"      [CURRENCY] y_off={y_off} exhausted, trying next Y offset..."
                )

        # All positions failed " log diagnostic info for remote debugging
        self.logger.warning("      [CURRENCY] All click positions failed")
        self.logger.warning(
            f"      [CURRENCY] DEBUG first 200 chars of screen: {repr(stable_text[:200])}"
        )
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        return None

    def click_more_prompt_link(self, terminal_text: str) -> bool:
        """
        Navigate to the next page of Flights/Fares results.

        Primary path: Alt+M keyboard shortcut (Smartpoint built-in).
        Fallback: pixel-coordinate click fan-out for cases where the
        shortcut is not intercepted (e.g., focus lost to another widget).
        """

        if not self.focus():
            return False

        # Verify a "More" prompt actually exists before doing anything.
        clean = (terminal_text or "").rstrip("\r\n")
        lines = clean.split("\n") if clean else []
        has_prompt = any(_RE_MORE_PROMPT.search(ln) for ln in lines)
        if not has_prompt:
            return False

        # Clear any active selection / dropdown before sending the shortcut.
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        time.sleep(constants.ESCAPE_CLEAR_DELAY)

        # ── Primary: Alt+M ────────────────────────────────────────────────
        self.logger.debug("      [CLICK] Trying Alt+M shortcut for More...")
        pyautogui.hotkey("alt", "m")
        time.sleep(constants.COMMAND_WAIT_LONG)
        result = self._copy_terminal_text()
        if result.strip() and result.strip() != terminal_text.strip():
            self.logger.info("      [CLICK] Alt+M succeeded — next page loaded.")
            return True

        self.logger.debug(
            "      [CLICK] Alt+M did not change the screen; falling back to click."
        )

        # ── Fallback: coordinate-based click ─────────────────────────────
        rect = self._get_terminal_rect()
        total_lines_capacity = max(1, (rect.height() - 10) // self._line_height)

        def _find_prompt(text: str):
            c = (text or "").rstrip("\r\n")
            ls = c.split("\n") if c else []
            for i in range(len(ls) - 1, -1, -1):
                if _RE_MORE_PROMPT.search(ls[i]):
                    return c, ls, i
            return None

        def _line_base(c: str, ls: list[str], idx: int):
            col = self._find_link_char_column(ls[idx], _RE_MORE_PROMPT)
            if col is not None:
                bx, by = self._text_line_to_pixel(c, idx, char_idx=col)
            else:
                bx, by = self._text_line_to_pixel(c, idx, x_ratio=MORE_LINK_X_RATIO)
            return (bx, by) if rect.top <= by <= rect.bottom else None

        def _bottom_base(c: str, ls: list[str], idx: int):
            from_bottom = len(ls) - 1 - idx
            if from_bottom >= total_lines_capacity:
                return None
            col = self._find_link_char_column(ls[idx], _RE_MORE_PROMPT)
            if col is not None:
                bx, _ = self._text_line_to_pixel(c, idx, char_idx=col)
            else:
                bx, _ = self._text_line_to_pixel(c, idx, x_ratio=MORE_LINK_X_RATIO)
            by = int(
                rect.bottom - BOTTOM_MARGIN - (from_bottom + 0.5) * self._line_height
            )
            return (bx, by) if rect.top <= by <= rect.bottom else None

        candidates: list[tuple] = []
        seen: set = set()

        def _add(base, tb: str, label: str):
            if not base:
                return
            bx, by = base
            key = (int(bx), int(by), label)
            if key not in seen:
                seen.add(key)
                candidates.append((bx, by, tb, label))

        target = _find_prompt(terminal_text)
        if target:
            ct, ls, li = target
            _add(_line_base(ct, ls, li), terminal_text, "visible")
            _add(_bottom_base(ct, ls, li), terminal_text, "bottom")

        if len(lines) > total_lines_capacity and not candidates:
            self.logger.debug(
                "      [CLICK] More prompt may be off-screen; scrolling and re-reading layout..."
            )
            pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
            time.sleep(constants.ESCAPE_CLEAR_DELAY)
            safe_x, safe_y = self._get_terminal_focus_point()
            self._safe_focus_click(safe_x, safe_y)
            time.sleep(constants.COPY_DELAY)
            pyautogui.press(
                "pagedown", presses=4, interval=constants.KEYBOARD_INTERVAL
            )
            time.sleep(constants.PAGEDOWN_SCROLL_DELAY)
            scrolled_text = self._copy_terminal_text()
            if self._has_dropdown_activated(scrolled_text):
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)
                scrolled_text = self._copy_terminal_text()
            st = _find_prompt(scrolled_text)
            if st:
                sc, sl, si = st
                _add(_line_base(sc, sl, si), scrolled_text, "scrolled-visible")
                _add(_bottom_base(sc, sl, si), scrolled_text, "scrolled-bottom")

        if not candidates:
            self.logger.warning(
                "      [CLICK] Found More prompt text, but no visible click target was in bounds."
            )
            return False

        offsets = [
            (0, 0), (0, -10), (0, 10), (-5, 0), (5, 0),
            (0, -20), (0, 20), (-5, -10), (5, -10), (-5, 10), (5, 10),
            (0, -30), (0, 30),
        ]

        for base_x, base_y, text_before, label in candidates:
            for x_off, y_off in offsets:
                pyautogui.moveTo(
                    base_x + x_off, base_y + y_off,
                    duration=constants.MOUSE_MOVE_DURATION,
                )
                pyautogui.click()
                time.sleep(constants.COMMAND_WAIT_LONG)
                result = self._copy_terminal_text()
                if self._has_dropdown_activated(result):
                    pyautogui.press(
                        "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                    )
                    time.sleep(constants.ESCAPE_CLEAR_DELAY)
                    continue
                if result.strip() != text_before.strip():
                    self.logger.info(
                        f"      [CLICK] 'More' link clicked successfully via {label} target."
                    )
                    return True

        self.logger.warning(
            "      [CLICK] Exhausted all offset attempts to click 'More' link."
        )
        return False

    def recalibrate(self) -> dict:
        """Reset calibration to DPI-auto values and reload into this instance."""
        self._cal = _calibration_mod.reset_calibration()
        self._line_height = self._cal["line_height"]
        self._content_top_padding = self._cal.get("content_top_padding", CONTENT_TOP_PADDING)
        self.logger.info(
            f"[CAL] Recalibrated: line_height={self._line_height}, source={self._cal.get('source')}"
        )
        return self._cal

    def return_to_tax_list(self, country_code: str):
        """Re-send FTAX-{CC} to return to the tax type list page."""
        if not self.focus():
            return
        list_cmd = f"FTAX-{country_code}"
        self.logger.debug(f"      Returning to tax list: {list_cmd}")
        pyautogui.typewrite(list_cmd, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        time.sleep(constants.COMMAND_WAIT_FS)

    def _has_end_signal(self, text: str) -> bool:
        """Check if the terminal text contains the END signal in its last lines."""
        if not text:
            return False
        lines = [line.strip().upper() for line in text.splitlines() if line.strip()]
        # Check the last 20 non-empty lines for a standalone "END"
        check_lines = lines[-20:] if len(lines) >= 20 else lines
        for line in check_lines:
            if line == END_SIGNAL:
                return True
        return False

    def _has_more_prompt(self, text: str) -> bool:
        """Check if the terminal shows a 'More Fares' or 'More Flights' prompt."""
        if not text:
            return False
        if self._has_end_signal(text):
            return False
        lines = [line.strip().upper() for line in text.splitlines() if line.strip()]
        check_lines = lines[-8:] if len(lines) >= 8 else lines
        for line in check_lines:
            if "MORE FARES" in line or "MORE FLIGHTS" in line:
                return True
        return False

    def _has_currency_redirect(self, text: str):
        """
        Check if the text contains a standalone 'XXX CURRENCY FARES EXISTS' redirect link.

        This method differentiates between:
        1. Clickable redirect link: "BDT CURRENCY FARES EXISTS" appears WITHOUT fare data
        2. Informational text: "BDT CURRENCY FARES EXISTS" appears WITH fare data already showing

        Returns the currency code (e.g., 'BDT') if a CLICKABLE redirect is found, or None.
        """
        if not text:
            return None



        # First check if the currency redirect message exists at all
        match = _RE_CURRENCY_CODE_FARES.search(text.upper())
        if not match:
            return None

        currency_code = match.group(1)
        self.logger.debug(
            f"      [CURRENCY] Found '{currency_code} CURRENCY FARES EXISTS' message"
        )

        # Now check if fare data is already present - if so, this is informational text, not a clickable link
        # Check for actual fare lines with pattern: optional spaces, optional 'O', digit(s), spaces,
        # optional minus, 2-char airline code, spaces, fare amount, etc.
        fare_lines_found = 0
        for line in text.split("\n"):
            # If we find an actual fare line, the currency message is informational, not a redirect
            if _RE_FARE_LINE.match(line):
                fare_lines_found += 1
                if fare_lines_found <= 2:  # Log first 2 fare lines found
                    self.logger.debug(
                        f"      [CURRENCY] Found fare line: {line.strip()[:60]}"
                    )

        if fare_lines_found > 0:
            self.logger.debug(
                f"      [CURRENCY] Total {fare_lines_found} fare lines found - NOT clicking (informational text)"
            )
            return None

        # Also check for "More Fares" or "More" which indicates fares are present
        if _RE_MORE_FARES.search(text):
            self.logger.debug(
                f"      [CURRENCY] Found 'More Fares' link - NOT clicking (fares present)"
            )
            return None

        # If we get here, the currency redirect message exists WITHOUT fare data
        # This means it's a clickable redirect link
        self.logger.debug(
            f"      [CURRENCY] No fare data found - this is a CLICKABLE redirect link"
        )
        return currency_code

    def _has_invalid(self, text: str) -> bool:
        """Check if the last few lines contain 'INVALID' (MD returned no data)."""
        if not text:
            return False
        lines = text.strip().splitlines()
        check_lines = lines[-5:] if len(lines) >= 5 else lines
        for line in check_lines:
            stripped = line.strip().upper()
            if stripped == INVALID_SIGNAL:
                return True
        return False

    def _has_dropdown_activated(self, text: str) -> bool:
        """
        Check if a dropdown menu was accidentally activated (e.g., MAXIMUM STAY, MINIMUM STAY).

        When clicking on the wrong spot, dropdowns like "/12M" or "M" can expand and show
        options like "MAXIMUM STAY", "MINIMUM STAY", etc. This method detects those.

        BUG-3 fix: Only checks the last 10 lines (dropdown content is always at
        the bottom) and requires at least 2 keyword matches to avoid false positives
        from words like "PERMITTED" or "TICKETING" that appear in normal fare rules.

        Returns True if a dropdown is detected, False otherwise.
        """
        if not text:
            return False

        # Only check the last 10 lines — dropdown content appears at click point/bottom
        lines = text.strip().splitlines()
        check_region = "\n".join(lines[-10:]).upper()

        # Keywords that ONLY appear in dropdown menus, not in normal fare displays
        dropdown_keywords = [
            "MAXIMUM STAY",
            "MINIMUM STAY",
            "MAX STAY",
            "MIN STAY",
            "ADVANCE PURCHASE",
            "TRAVEL COMPLETE",
            "BLACKOUT DATES",
        ]

        # Require at least 2 keyword matches to avoid false positives
        matches = sum(1 for kw in dropdown_keywords if kw in check_region)
        return matches >= 2
