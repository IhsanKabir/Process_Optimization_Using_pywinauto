"""
smartpoint_automation.py - Travelport Smartpoint UI Automation

Controls the Travelport Smartpoint terminal using pywinauto.
Connects to the application, sends commands via keyboard, captures output via clipboard,
and handles MD (More Data) pagination automatically.
"""

import time
import logging
import pyperclip
from pywinauto import Desktop

import pyautogui

import ctypes

import constants
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
    TERMINAL_AUTOMATION_ID,
    # Data validation
    FS_EXPANSION_KEYWORDS,
    # Focus tracking
    FOCUS_CACHE_SECONDS,
)


class SmartpointAutomation:
    def __init__(self, window_title=DEFAULT_WINDOW_TITLE):
        """Initialize the Smartpoint automation class."""
        self.window_title = window_title
        self.app = None
        self.window = None
        self.connected = False
        self.logged_in = False
        self.logger = logging.getLogger("travelport.automation")
        self._cached_terminal_rect = None  # Cache for SmartRichTextBox rect
        self._last_focus_time = 0.0  # Timestamp of last successful focus()
        self._last_terminal_text = ""  # Cache for deduplicating reads

        # Ensure PyAutoGUI fail-safe is enabled.
        # User can slam mouse to any corner of the screen to throw FailSafeException and abort.
        pyautogui.FAILSAFE = True

    def connect(self) -> bool:
        """Connect to the running instance of Smartpoint."""
        self.logger.info(
            f"  Attempting to connect to '{self.window_title}' using UIA backend..."
        )
        try:
            # Connect via Desktop UIA backend - the actual terminal UI is visible here
            desktop = Desktop(backend="uia")

            # Use best_match just in case there are hidden whitespace characters
            self.window = desktop.window(best_match=self.window_title)

            # Verify the window exists and is visible
            if self.window.exists():
                self.connected = True
                self.logger.info(
                    f"  Successfully connected to Smartpoint ({self.window.window_text()})."
                )
                return True
            else:
                self.logger.info(f"  [ERROR] Window '{self.window_title}' not found.")
                return False

        except Exception as e:
            self.logger.info(f"  [ERROR] Failed to connect to Smartpoint: {e}")
            return False

    def focus(self, force: bool = False) -> bool:
        """Bring the Smartpoint window to the foreground forcefully.

        Uses focus caching: skips the expensive Win32 calls if focus was
        set recently (within FOCUS_CACHE_SECONDS). Pass force=True to
        bypass the cache.
        """
        if not self.connected or not self.window:
            return False

        # Skip if focus was set recently (saves ~150ms per call)
        now = time.time()
        if not force and (now - self._last_focus_time) < FOCUS_CACHE_SECONDS:
            return True

        try:
            # Get the raw Windows handle manually
            hwnd = self.window.wrapper_object().handle
            if hwnd:
                user32 = ctypes.windll.user32
                # SW_RESTORE = 9
                user32.ShowWindow(hwnd, 9)
                # Force foreground
                user32.SetForegroundWindow(hwnd)

            self.window.set_focus()
            time.sleep(constants.FOCUS_DELAY)  # Brief wait for window to come forward
            self._last_focus_time = time.time()
            return True
        except Exception as e:
            self.logger.info(f"  [ERROR] Could not focus Smartpoint window: {e}")
            return False

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
            # 1. Initiate Sign-On
            sign_on_cmd = f"SON/Z{pcc}" if pcc else "SON/Z"
            self.logger.info(f"Sending sign-on command: {sign_on_cmd}")
            pyautogui.typewrite(sign_on_cmd, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            time.sleep(constants.COMMAND_WAIT_FS)  # Wait for username prompt

            # 2. Enter Username
            self.logger.info("Entering username...")
            pyautogui.typewrite(username, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            time.sleep(constants.COMMAND_WAIT_LONG)  # Wait for password prompt

            # 3. Enter Password
            self.logger.info("Entering password...")
            pyautogui.typewrite(password, interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")

            # Wait for login to complete
            self.logger.info("Waiting for login to complete...")
            time.sleep(constants.LOGIN_COMPLETION_WAIT)

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

        except Exception as e:
            self.logger.error(f"Login automation failed: {e}")
            return False

    def clear_screen(self):
        """Clear the terminal screen or input buffer by sending 'I'"""
        # Ensure focus first
        self.focus(force=True)

        # Sending 'I' completely refreshes the Travelport Smartpoint terminal
        print("  [DEBUG] Refreshing terminal with 'I' command...")
        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        time.sleep(constants.COMMAND_WAIT_LONG)  # Wait for refresh to complete

    def refresh_terminal(self):
        """Alias for clear_screen for compatibility."""
        self.clear_screen()

    def _copy_terminal_text(self) -> str:
        """Helper to copy text from the terminal via clipboard using mouse automation."""
        pyperclip.copy("")

        # Ensure focus hasn't been lost (cached — nearly free if recent)
        self.focus()

        if not self.window:
            return ""

        # Get window coordinates — click in a SAFE area (top-left)
        try:
            rect = self.window.rectangle()
            safe_x = (
                rect.left + SAFE_CLICK_X_OFFSET
            )  # Far left — no interactive links here
            safe_y = (
                rect.top + SAFE_CLICK_Y_OFFSET
            )  # Near top — above any FS result content
        except Exception:
            safe_x = SAFE_CLICK_X_OFFSET
            safe_y = SAFE_CLICK_Y_OFFSET

        # Click to focus the terminal area (safe position)
        pyautogui.click(x=safe_x, y=safe_y)
        time.sleep(constants.CLICK_DELAY)

        # Select all + copy
        pyautogui.hotkey("ctrl", "a")
        time.sleep(constants.CLICK_DELAY)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(constants.COPY_DELAY)

        text = pyperclip.paste()

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
            time.sleep(min_wait)

        deadline = time.time() + timeout
        current = None
        stable_count = 0

        while time.time() < deadline:
            time.sleep(poll_interval)
            new_text = self._copy_terminal_text()

            # First check: has screen changed from original?
            if new_text.strip() != text_before.strip():
                # Screen has changed - now verify it's stable
                if current is not None and new_text.strip() == current.strip():
                    stable_count += 1
                    if stable_count >= stability_checks:
                        # Screen has changed and is now stable
                        return new_text
                else:
                    # Screen is still changing
                    stable_count = 0
                    current = new_text

        # Final read after timeout
        return self._copy_terminal_text()

    def _wait_for_stable_screen(self, max_polls: int = 3, interval: float = 0.3) -> str:
        """
        Wait until the terminal screen content stabilizes (stops changing).

        Polls the clipboard multiple times and returns when two consecutive
        reads produce identical content. Prevents clicking while data is
        still rendering.

        Returns the stable terminal text.
        """
        prev = self._copy_terminal_text()
        for _ in range(max_polls):
            time.sleep(interval)
            curr = self._copy_terminal_text()
            if curr.strip() == prev.strip():
                return curr
            prev = curr
        return prev

    def show_completion_signal(self):
        """Show a clear completion signal in the terminal (no popup)."""
        self.logger.debug("\n" + "=" * 50)
        self.logger.debug("      🚀 TRAVELPORT AUTOMATION TASK COMPLETE 🚀")
        self.logger.debug("=" * 50 + "\n")

    def run_command(self, command: str, max_pages: int = MAX_PAGES_FARE) -> str:
        """
        Execute a complete command in Smartpoint, handling pagination if necessary.

        SPEED-OPTIMIZED: Uses adaptive polling instead of fixed sleeps,
        eliminates redundant terminal reads, and uses cached focus.

        Smartpoint pagination flow:
          1. Run command → first page of fares appears
          2. Check for "CURRENCY FARES EXISTS" → re-run in alternate currency
          3. If no "END" at the bottom → type MD + Enter
          4. If MD returns "INVALID" → stop (no more data)
          5. A "«More Fares»" prompt may appear → press Enter again
          6. Remaining data loads; repeat until "END" is found
          7. Check for UNSALEABLE_FARES_KEYWORD → send FU*
          8. Ctrl+A, Ctrl+C to capture the full text

        Returns the full combined text output from all pages.
        """
        if not self.focus():
            self.logger.debug("  [ERROR] Cannot run command, window not focused.")
            return ""

        self.logger.debug(f"    Running: {command}")

        # Send 'I' first to clear any previous terminal state cleanly
        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        time.sleep(constants.COMMAND_WAIT_LONG)

        # Capture state BEFORE sending command (for adaptive polling)
        text_before_cmd = self._copy_terminal_text()

        # Send the actual command
        pyautogui.typewrite(command, interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")

        # SPEED: Adaptive polling — exits as soon as screen changes
        initial_text = self._wait_for_response(
            text_before_cmd, timeout=constants.COMMAND_WAIT_FS
        )

        # If terminal returned INVALID immediately, stop — no point retrying
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
                    f"      [CURRENCY] ✓ Clicked {currency_match} redirect, screen updated ({len(initial_text)} chars)"
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
            # SPEED: Reuse screen_text from previous iteration instead of re-reading

            # Check if END is present anywhere in the captured text
            if self._has_end_signal(screen_text):
                self.logger.debug(
                    "      [DEBUG] 'END' signal detected. Pagination complete."
                )
                all_pages.append(screen_text)
                break

            # Attempt to click "«More Flights / Fares»"
            if self.click_more_prompt_link(screen_text):
                self.logger.debug(f"      Page {current_page}: Clicked 'More' link.")
                md_response = self._copy_terminal_text()
            else:
                # Fallback to standard MD — use adaptive polling
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

            # After MD/click, Smartpoint may show ANOTHER "«More Fares»" or "«More Flights»" prompt
            # that requires pressing Enter to clear BEFORE the actual data displays.
            if self._has_more_prompt(md_response):
                self.logger.debug(
                    "      [DEBUG] '«More Fares/Flights»' prompt detected. Pressing Enter..."
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

        # Join all pages — use separator so parser can handle overlapping headers
        full_text = "\n--- PAGE BREAK ---\n".join(all_pages)

        # Check for unsaleable fares
        if UNSALEABLE_FARES_KEYWORD in full_text.upper():
            self.logger.debug(
                "      [DEBUG] 'UNSALEABLE FARES' detected. Sending FU* command..."
            )
            fu_text_before = self._copy_terminal_text()
            pyautogui.typewrite("FU*", interval=constants.KEYBOARD_INTERVAL)
            pyautogui.press("enter")
            # SPEED: Adaptive polling
            fu_first = self._wait_for_response(
                fu_text_before, timeout=constants.COMMAND_WAIT_LONG + 0.5
            )
            fu_pages = [fu_first]
            fu_page = 1
            while fu_page < MAX_PAGES_UNSALEABLE:
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
        import re

        if not self.focus():
            return "", page_text

        target_line_idx = None
        target_char_idx = None
        fare_basis = str(fare.get("fare_basis", "")).upper()
        airline = str(fare.get("airline", "")).upper()
        line_number = fare.get("line")
        amount_pattern = rf"{fare.get('fare', 0):.2f}(?:R)?"

        for index, line in enumerate(page_text.split("\n")):
            if fare_basis not in line.upper() or airline not in line.upper():
                continue

            if line_number is not None and not re.search(
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
        offsets = [
            (0, 0),
            (10, 0),
            (-10, 0),
            (0, -9),
            (0, 9),
            (15, 0),
            (-15, 0),
            (10, -9),
            (10, 9),
            (-10, -9),
            (-10, 9),
        ]

        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(
                f"      [PENALTY] Trying fare click at ({click_x}, {click_y}) [offset=({x_off},{y_off})]"
            )

            pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
            pyautogui.click()
            time.sleep(constants.COMMAND_WAIT_SHORT)

            result = self._copy_terminal_text()
            upper_result = result.upper()
            if "16. PENALTIES" in upper_result or (
                "PENALTIES" in upper_result
                and ("CHANGES" in upper_result or "CANCELLATIONS" in upper_result)
            ):
                popup_text = result
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)
                return popup_text, self._copy_terminal_text()

            if result.strip() != text_before.strip():
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)
                text_before = self._copy_terminal_text()

        self.logger.warning(
            f"      [PENALTY] No Rule 16 popup captured for {fare_basis}"
        )
        return "", self._copy_terminal_text()

    def _extract_penalties_from_visible_page(
        self, page_text: str, seen_fares: set[tuple]
    ) -> tuple[list[dict], str]:
        """Extract penalty popup text for each visible fare line on the current page."""
        from parser import parse_fare_display

        parsed = parse_fare_display(page_text)
        visible_fares = sorted(parsed.get("fares", []), key=lambda item: item["line"])
        extracted = []
        current_page_text = page_text

        for fare in visible_fares:
            fare_key = (
                fare.get("fare_basis"),
                fare.get("rbd"),
                fare.get("is_rt"),
                fare.get("fare"),
            )
            if fare_key in seen_fares:
                continue

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

        self.logger.debug(f"    Running penalty extraction: {command}")

        pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
        pyautogui.press("enter")
        time.sleep(constants.COMMAND_WAIT_LONG)

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
            page_records, screen_text = self._extract_penalties_from_visible_page(
                screen_text, seen_fares
            )
            penalty_records.extend(page_records)

            if self._has_end_signal(screen_text):
                break

            if self.click_more_prompt_link(screen_text):
                md_response = self._copy_terminal_text()
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
                time.sleep(0.3)  # Brief pause before retry
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

            # Handle «More Fares/Flights» prompt
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

        # Fixed line height for Smartpoint terminal font
        # Empirically measured: probe y=237, terminal top=82, D on line 7
        # 82 + 5 + 7.5*20 = 237 → LINE_HEIGHT=20, padding=5
        # LINE_HEIGHT is imported from constants

        # Content starts ~5px below the terminal pane top edge
        content_top = rect.top + CONTENT_TOP_PADDING

        # Y: center of the target line
        pixel_y = int(content_top + (target_line_idx + 0.5) * LINE_HEIGHT)

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
        import re

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
                    f"      [CLICK] ✓ Dropdown text captured ({len(dropdown_text)} chars)"
                )
                return dropdown_text

            if result.strip() != text_before.strip():
                self.logger.info(
                    f"      [CLICK] ✓ Screen changed at offset=({x_off},{y_off})"
                )
                return result

        self.logger.warning(f"      [CLICK] All offsets tried, screen unchanged.")
        return self._copy_terminal_text()

    def click_d_button(self, option_index: int, fs_text: str) -> str:
        """
        Click the 'D' (Details) button for a specific Pricing Option in FS results.

        Finds the D button by looking for lines containing the "D  R" pattern
        (which appears on the «BOOK» +TQ line of each Pricing Option), then
        calculates the exact pixel position from the character column.
        """
        import re

        if not self.focus():
            return ""

        lines = fs_text.split("\n")

        # Strategy: Find lines containing «BOOK» or +TQ — these markers are
        # always on the same line as the D button. Using "D  R" is unreliable
        # because the clipboard sometimes splits D and R across lines.
        d_button_lines = []
        for idx, line in enumerate(lines):
            if "+TQ" in line or "«BOOK»" in line or "\xabBOOK\xbb" in line:
                d_button_lines.append(idx)

        self.logger.info(
            f"      [D-CLICK] Found {len(d_button_lines)} BOOK/+TQ lines: {d_button_lines}"
        )

        if not d_button_lines:
            # Fallback: search for lines near PRICING OPTION headers
            self.logger.warning(
                "      [D-CLICK] No 'D  R' pattern found. Trying PRICING OPTION fallback..."
            )
            option_headers = []
            for idx, line in enumerate(lines):
                if re.search(r"PRICING\s+OPTION\s+\d+", line, re.IGNORECASE):
                    option_headers.append(idx)

            if option_index < len(option_headers):
                target_line = option_headers[option_index] + 4
            else:
                self.logger.error(
                    f"      [D-CLICK] Cannot locate D button for option {option_index}"
                )
                return ""
        else:
            if option_index >= len(d_button_lines):
                self.logger.error(
                    f"      [D-CLICK] Only {len(d_button_lines)} D buttons, need index {option_index}"
                )
                return ""

            target_line = d_button_lines[option_index]

        # Use empirically measured x_ratio for D button position.
        # Clipboard char positions don't map 1:1 to pixels (measured 0.907 vs actual 0.856).
        # The D button is consistently at ~85.5% of terminal width.
        D_X_RATIO = D_BUTTON_X_RATIO
        base_x, base_y = self._text_line_to_pixel(
            fs_text, target_line, x_ratio=D_X_RATIO
        )

        self.logger.info(
            f"      [D-CLICK] Option {option_index+1}: line {target_line}, "
            f"click at ({base_x}, {base_y})"
        )

        # Clear selection
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        time.sleep(constants.ESCAPE_CLEAR_DELAY)

        # Try clicking with combined X and Y offsets for tolerance
        text_before = fs_text
        offsets = [
            (0, 0),
            (-15, 0),
            (15, 0),  # Same line, shift X
            (0, -9),
            (0, 9),  # One line up/down, same X
            (-15, -9),
            (15, -9),  # One line up, shift X
            (-15, 9),
            (15, 9),  # One line down, shift X
        ]

        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(
                f"      [D-CLICK] Trying ({click_x}, {click_y}) [x={x_off}, y={y_off}]"
            )

            pyautogui.moveTo(click_x, click_y, duration=constants.MOUSE_MOVE_DURATION)
            pyautogui.click()
            time.sleep(constants.COMMAND_WAIT_SHORT)

            result = self._copy_terminal_text()

            if result.strip() != text_before.strip():
                upper = result.upper()
                # D expansion shows: FARE COMPONENT BASIS, tax codes (YQ, BD, etc.), EQU, etc.
                if any(
                    kw in upper
                    for kw in ["EQU", "TAXES", "TAX", "YQ", "FARE COMPONENT", "BASIS"]
                ):
                    self.logger.info(
                        f"      [D-CLICK] ✓ Tax breakdown at offset=({x_off},{y_off})"
                    )
                    return result
                else:
                    self.logger.debug(
                        f"      [D-CLICK] Screen changed but no tax/fare data. Sending 'I' to reset..."
                    )
                    pyautogui.typewrite("I", interval=constants.KEYBOARD_INTERVAL)
                    pyautogui.press("enter")
                    time.sleep(constants.COMMAND_WAIT_FS)
                    text_before = self._copy_terminal_text()
                    if "PRICING OPTION" not in text_before.upper():
                        self.logger.warning(
                            f"      [D-CLICK] Could not recover FS display. Aborting."
                        )
                        return ""

        self.logger.warning(
            f"      [D-CLICK] Could not expand tax details after all attempts."
        )
        return self._copy_terminal_text()

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
        import re

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
            if re.search(r"CURRENCY\s+FARES?\s+EXISTS?", line, re.IGNORECASE):
                target_line_idx = idx
                break

        if target_line_idx is None:
            self.logger.error(
                "      [CURRENCY] Could not find 'CURRENCY FARES EXISTS' line in text"
            )
            return None

        rect = self._get_terminal_rect()
        content_top = rect.top + CONTENT_TOP_PADDING
        click_y = int(content_top + (target_line_idx + 0.5) * LINE_HEIGHT)

        self.logger.info(
            f"      [CURRENCY] Target: line {target_line_idx}, y={click_y}, "
            f"terminal rect: L={rect.left} R={rect.right} (width={rect.width()})"
        )

        # Wait for terminal to finish rendering before clicking
        stable_text = self._wait_for_stable_screen()

        # Click at multiple X positions on the LEFT side of the terminal
        # The text "BDT  CURRENCY  FARES  EXISTS" occupies roughly 5%-40% of terminal width
        # Also try Y offsets (±10px) in case LINE_HEIGHT varies on different displays
        x_ratios = [0.15, 0.10, 0.20, 0.25, 0.05, 0.30, 0.35]
        y_offsets = [0, -10, 10]

        text_before = fd_text
        for y_off in y_offsets:
            for x_ratio in x_ratios:
                click_x = int(rect.left + rect.width() * x_ratio)
                actual_y = click_y + y_off
                self.logger.debug(
                    f"      [CURRENCY] Trying x={x_ratio:.2f}, y_off={y_off} -> ({click_x}, {actual_y})"
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
                        f"      [CURRENCY] ✓ Dropdown text captured ({len(dropdown_text)} chars)"
                    )
                    return dropdown_text

                # Check if screen changed AND redirect is gone
                if result and not self._has_currency_redirect(result):
                    self.logger.info(
                        f"      [CURRENCY] ✓ Click succeeded at x={x_ratio:.2f}, y_off={y_off}"
                    )

                    # Poll for fare data to fully load
                    for wait_round in range(5):
                        if len(result.strip()) > 100:
                            self.logger.info(
                                f"      [CURRENCY] ✓ Fare data loaded ({len(result.strip())} chars)"
                            )
                            return result
                        self.logger.debug(
                            f"      [CURRENCY] Only {len(result.strip())} chars, waiting (round {wait_round + 1}/5)..."
                        )
                        time.sleep(constants.COMMAND_WAIT_FS)
                        result = self._copy_terminal_text()

                    self.logger.info(
                        f"      [CURRENCY] Returning with {len(result.strip())} chars"
                    )
                    return result

                # Screen didn't change meaningfully, try next position
                self.logger.debug(
                    f"      [CURRENCY] No change at x={x_ratio:.2f}, y_off={y_off}"
                )

            # After trying all x_ratios for this y_offset, log progress
            if y_off != y_offsets[-1]:
                self.logger.debug(
                    f"      [CURRENCY] y_off={y_off} exhausted, trying next Y offset..."
                )

        # All positions failed — log diagnostic info for remote debugging
        self.logger.warning("      [CURRENCY] All click positions failed")
        self.logger.warning(
            f"      [CURRENCY] DEBUG — first 200 chars of screen: {repr(stable_text[:200])}"
        )
        pyautogui.press("escape", presses=2, interval=constants.KEYBOARD_INTERVAL)
        return None

    def click_more_prompt_link(self, terminal_text: str) -> bool:
        """
        Dynamically finds and clicks '«More Flights»' by anchoring to the screen bottom.
        Leaves top-down math isolated for other buttons.
        """
        import re

        if not self.focus():
            return False

        rect = self._get_terminal_rect()
        total_lines_capacity = (rect.height() - 10) // LINE_HEIGHT

        # KEY FIX: Scrub trailing empty phantom lines so counting from the bottom is exact!
        clean_text = terminal_text.rstrip("\r\n")
        lines = clean_text.split("\n")

        # Search from bottom up
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            match = re.search(
                r"(MORE\s+(?:FARES|FLIGHTS|OPTIONS))", line, re.IGNORECASE
            )

            if match:
                pyautogui.press(
                    "escape", presses=2, interval=constants.KEYBOARD_INTERVAL
                )
                time.sleep(constants.ESCAPE_CLEAR_DELAY)

                # IMPORTANT: Scroll down if the text is overflowing
                if len(lines) > total_lines_capacity:
                    self.logger.debug(
                        "      [CLICK] Scrolling terminal to bottom before clicking..."
                    )
                    pyautogui.click(
                        rect.left + rect.width() // 2, rect.top + rect.height() // 2
                    )
                    time.sleep(constants.COPY_DELAY)
                    pyautogui.press(
                        "pagedown", presses=4, interval=constants.KEYBOARD_INTERVAL
                    )
                    time.sleep(constants.PAGEDOWN_SCROLL_DELAY)

                    # Target isolated calculation from the visual bottom
                    # Empirical Test: Smartpoint's bottom frame padding sits exactly at 0px.
                    # The text renders completely flush against the lowest border of the active text area.
                    # BOTTOM_MARGIN is imported from constants
                    lines_from_bottom = len(lines) - 1 - i
                    base_y = int(
                        rect.bottom
                        - BOTTOM_MARGIN
                        - (lines_from_bottom + 0.5) * LINE_HEIGHT
                    )

                    # Offset X by ~32px (0.04 of 800) to perfectly center on the 'M' core, avoiding airline codes!
                    base_x, _ = self._text_line_to_pixel(
                        clean_text, i, x_ratio=MORE_LINK_X_RATIO
                    )
                else:
                    base_x, base_y = self._text_line_to_pixel(
                        clean_text, i, x_ratio=MORE_LINK_X_RATIO
                    )

                # Start Retry/Tolerance Logic
                # Use 2D offsets to handle both horizontal and vertical positioning errors
                # This prevents accidental clicks on adjacent elements like "/12M" or "M" dropdowns
                offsets = [
                    (0, 0),
                    (0, -10),
                    (0, 10),  # Vertical only
                    (-5, 0),
                    (5, 0),  # Horizontal only (small shifts)
                    (0, -20),
                    (0, 20),  # More vertical
                    (-5, -10),
                    (5, -10),  # Diagonal combinations
                    (-5, 10),
                    (5, 10),
                    (0, -30),
                    (0, 30),  # Even more vertical
                ]
                text_before = terminal_text

                for x_off, y_off in offsets:
                    click_x = base_x + x_off
                    click_y = base_y + y_off
                    self.logger.debug(
                        f"      [CLICK] Trying 'More' link at ({click_x}, {click_y}) [offset=({x_off},{y_off})]"
                    )

                    pyautogui.moveTo(
                        click_x, click_y, duration=constants.MOUSE_MOVE_DURATION
                    )
                    pyautogui.click()
                    time.sleep(constants.COMMAND_WAIT_LONG)

                    result = self._copy_terminal_text()

                    # Check if we accidentally activated a dropdown (MAXIMUM STAY, etc.)
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
                        # Even though we got a dropdown, we should still check if we got the More link
                        # For now, let's continue trying since dropdown means we didn't hit More link
                        continue

                    if result.strip() != text_before.strip():
                        self.logger.info(
                            "      [CLICK] ✓ 'More' link clicked successfully!"
                        )
                        return True

                self.logger.warning(
                    "      [CLICK] Exhausted all offset attempts to click 'More' link."
                )
                return False

        return False

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
        lines = text.strip().splitlines()
        # Check the last 10 lines for a standalone "END"
        check_lines = lines[-10:] if len(lines) >= 10 else lines
        for line in check_lines:
            stripped = line.strip().upper()
            if stripped == END_SIGNAL:
                return True
        return False

    def _has_more_prompt(self, text: str) -> bool:
        """Check if the terminal shows a '«More Fares»' or '«More Flights»' prompt."""
        if not text:
            return False
        lines = text.strip().splitlines()
        check_lines = lines[-5:] if len(lines) >= 5 else lines
        for line in check_lines:
            upper = line.strip().upper()
            if "MORE FARES" in upper or "MORE FLIGHTS" in upper:
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

        import re

        # First check if the currency redirect message exists at all
        match = re.search(r"([A-Z]{3})\s+CURRENCY\s+FARES?\s+EXISTS?", text.upper())
        if not match:
            return None

        currency_code = match.group(1)
        self.logger.debug(
            f"      [CURRENCY] Found '{currency_code} CURRENCY FARES EXISTS' message"
        )

        # Now check if fare data is already present - if so, this is informational text, not a clickable link
        # Check for actual fare lines with pattern: optional spaces, optional 'O', digit(s), spaces,
        # optional minus, 2-char airline code, spaces, fare amount, etc.
        fare_pattern = r"^\s*O?\d+\s+-?[A-Z0-9]{2}\s+\d+\.?\d*R?\s+\S+\s+[A-Z]\s+"

        fare_lines_found = 0
        for line in text.split("\n"):
            # If we find an actual fare line, the currency message is informational, not a redirect
            if re.match(fare_pattern, line):
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

        # Also check for "More Fares" or "«More" which indicates fares are present
        if re.search(r"«More|More\s+Fares", text, re.IGNORECASE):
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

        Returns True if a dropdown is detected, False otherwise.
        """
        if not text:
            return False

        upper_text = text.upper()

        # Common dropdown keywords that indicate an accidental menu activation
        dropdown_keywords = [
            "MAXIMUM STAY",
            "MINIMUM STAY",
            "MAX STAY",
            "MIN STAY",
            "ADVANCE PURCHASE",
            "TRAVEL COMPLETE",
            "PERMITTED",
            "NOT PERMITTED",
            "TICKETING",
            "BLACKOUT DATES",
        ]

        # Check if any dropdown keywords appear (these typically shouldn't be in fare lists)
        for keyword in dropdown_keywords:
            if keyword in upper_text:
                return True

        return False
