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
    # Timing
    FOCUS_DELAY,
    CLICK_DELAY,
    KEYBOARD_INTERVAL,
    COPY_DELAY,
    ESCAPE_CLEAR_DELAY,
    MOUSE_MOVE_DURATION,
    PAGEDOWN_SCROLL_DELAY,
    COMMAND_WAIT_SHORT,
    COMMAND_WAIT_MEDIUM,
    COMMAND_WAIT_LONG,
    COMMAND_WAIT_FS,
    COMMAND_WAIT_FTAX,
    SCREEN_REFRESH_WAIT,
    LOGIN_COMMAND_WAIT,
    LOGIN_USERNAME_WAIT,
    LOGIN_COMPLETION_WAIT,
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
)

class SmartpointAutomation:
    def __init__(self, window_title=DEFAULT_WINDOW_TITLE):
        """Initialize the Smartpoint automation class."""
        self.window_title = window_title
        self.app = None
        self.window = None
        self.connected = False
        self.logged_in = False
        self.logger = logging.getLogger('travelport.automation')
        self._cached_terminal_rect = None  # Cache for SmartRichTextBox rect
        
        # Ensure PyAutoGUI fail-safe is enabled. 
        # User can slam mouse to any corner of the screen to throw FailSafeException and abort.
        pyautogui.FAILSAFE = True

    def connect(self) -> bool:
        """Connect to the running instance of Smartpoint."""
        self.logger.info(f"  Attempting to connect to '{self.window_title}' using UIA backend...")
        try:
            # Connect via Desktop UIA backend - the actual terminal UI is visible here
            desktop = Desktop(backend="uia")
            
            # Use best_match just in case there are hidden whitespace characters
            self.window = desktop.window(best_match=self.window_title)
            
            # Verify the window exists and is visible
            if self.window.exists():
                self.connected = True
                self.logger.info(f"  Successfully connected to Smartpoint ({self.window.window_text()}).")
                return True
            else:
                self.logger.info(f"  [ERROR] Window '{self.window_title}' not found.")
                return False
                
        except Exception as e:
            self.logger.info(f"  [ERROR] Failed to connect to Smartpoint: {e}")
            return False

    def focus(self) -> bool:
        """Bring the Smartpoint window to the foreground forcefully."""
        if not self.connected or not self.window:
            return False
            
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
            time.sleep(FOCUS_DELAY)  # Brief wait for window to come forward
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
                self.logger.debug(f"      [RECT] Terminal pane: L={best_rect.left} T={best_rect.top} "
                                f"R={best_rect.right} B={best_rect.bottom}")
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
            pyautogui.typewrite(sign_on_cmd, interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FS) # Wait for username prompt

            # 2. Enter Username
            self.logger.info("Entering username...")
            pyautogui.typewrite(username, interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_LONG) # Wait for password prompt

            # 3. Enter Password
            self.logger.info("Entering password...")
            pyautogui.typewrite(password, interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')

            # Wait for login to complete
            self.logger.info("Waiting for login to complete...")
            time.sleep(LOGIN_COMPLETION_WAIT)

            # Check for success by reading terminal text
            terminal_text = self._copy_terminal_text()
            if "RESTRICTED" in terminal_text.upper() or "SIGN-ON" in terminal_text.upper() or "WELCOME" in terminal_text.upper():
                 self.logger.info("Login successful.")
                 self.logged_in = True
                 return True
            else:
                 self.logger.warning("Login might have failed. Please check the terminal.")
                 self.logger.debug(f"Terminal output: {terminal_text[:100]}...")
                 return False

        except Exception as e:
            self.logger.error(f"Login automation failed: {e}")
            return False

    def clear_screen(self):
        """Clear the terminal screen or input buffer by sending 'I'"""
        # Ensure focus first
        self.focus()
        
        # Sending 'I' completely refreshes the Travelport Smartpoint terminal
        print("  [DEBUG] Refreshing terminal with 'I' command...")
        pyautogui.typewrite("I", interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_LONG)  # Wait for refresh to complete

    def refresh_terminal(self):
        """Alias for clear_screen for compatibility."""
        self.clear_screen()

    def _copy_terminal_text(self) -> str:
        """Helper to copy text from the terminal via clipboard using mouse automation."""
        pyperclip.copy("")
        
        # Ensure focus hasn't been lost
        self.focus()
        
        if not self.window:
            return ""
            
        # Get window coordinates — click in a SAFE area (top-left)
        try:
            rect = self.window.rectangle()
            safe_x = rect.left + SAFE_CLICK_X_OFFSET   # Far left — no interactive links here
            safe_y = rect.top + SAFE_CLICK_Y_OFFSET    # Near top — above any FS result content
        except Exception:
            safe_x = SAFE_CLICK_X_OFFSET
            safe_y = SAFE_CLICK_Y_OFFSET
        
        # Click to focus the terminal area (safe position)
        pyautogui.click(x=safe_x, y=safe_y)
        time.sleep(CLICK_DELAY)
        
        # Select all + copy
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(CLICK_DELAY)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(COPY_DELAY)
        
        text = pyperclip.paste()
        
        # Click once to deselect
        pyautogui.press('escape')
            
        return text
        
    def show_completion_signal(self):
        """Show a clear completion signal in the terminal (no popup)."""
        self.logger.debug("\n" + "="*50)
        self.logger.debug("      🚀 TRAVELPORT AUTOMATION TASK COMPLETE 🚀")
        self.logger.debug("="*50 + "\n")

    def run_command(self, command: str, max_pages: int = MAX_PAGES_FARE) -> str:
        """
        Execute a complete command in Smartpoint, handling pagination if necessary.
        
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
        pyautogui.typewrite("I", interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_LONG)
        
        # Send the actual command
        pyautogui.typewrite(command, interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        
        # Wait for the terminal to respond
        time.sleep(COMMAND_WAIT_SHORT)
        
        # Capture initial response
        initial_text = self._copy_terminal_text()
        
        # If terminal returned INVALID immediately, stop — no point retrying
        if self._has_invalid(initial_text):
            self.logger.warning(f"    [!] Command returned INVALID immediately: {command}")
            return initial_text
        
        # Check for "CURRENCY FARES EXISTS" (e.g., "BDT CURRENCY FARES EXISTS")
        # This means no fares in the requested currency; we must CLICK the link
        # (typed commands like FD*BDT do not work for this redirect)
        currency_match = self._has_currency_redirect(initial_text)
        if currency_match:
            self.logger.debug(f"      [DEBUG] '{currency_match} CURRENCY FARES EXISTS' detected. Clicking link...")
            clicked_text = self.click_currency_link(initial_text)
            if clicked_text and clicked_text.strip() != initial_text.strip():
                initial_text = clicked_text
                self.logger.debug(f"      [DEBUG] Currency link clicked. Re-captured {len(initial_text)} chars.")
            else:
                self.logger.warning(f"      [WARNING] Currency link click did not change screen.")
        
        current_page = 1
        previous_md_text = initial_text
        
        # Pagination loop: ACCUMULATE all pages into full_text
        # Critical: use += not = so page 1 fares aren't lost when MD scrolls to page 2
        all_pages = [initial_text]
        while current_page < max_pages:
            # Capture what's currently on screen
            screen_text = self._copy_terminal_text()
            
            # Check if END is present anywhere in the captured text
            if self._has_end_signal(screen_text):
                self.logger.debug("      [DEBUG] 'END' signal detected. Pagination complete.")
                all_pages.append(screen_text)
                break
            
            # Attempt to click "«More Flights / Fares»"
            if self.click_more_prompt_link(screen_text):
                self.logger.debug(f"      Page {current_page}: Clicked 'More' link.")
                md_response = self._copy_terminal_text()
            else:
                # Fallback to standard MD just in case the link isn't explicitly printed
                self.logger.debug(f"      Page {current_page}: No 'More' link found. Sending MD...")
                pyautogui.typewrite("MD", interval=KEYBOARD_INTERVAL)
                pyautogui.press('enter')
                time.sleep(COMMAND_WAIT_MEDIUM)  # Wait for MD response
                md_response = self._copy_terminal_text()
            
            # Check if MD/click returned "INVALID" (no more data)
            if self._has_invalid(md_response):
                self.logger.debug("      [DEBUG] MD returned 'INVALID'. No more data to paginate.")
                break  # Don't add INVALID page to results
            
            # Detect stuck screen: same text as previous MD
            if md_response.strip() == previous_md_text.strip():
                self.logger.debug("      [DEBUG] Same text as previous page. Stopping pagination.")
                break
            previous_md_text = md_response
            
            # After MD/click, Smartpoint may show ANOTHER "«More Fares»" or "«More Flights»" prompt
            # that requires pressing Enter to clear BEFORE the actual data displays.
            if self._has_more_prompt(md_response):
                self.logger.debug("      [DEBUG] '«More Fares/Flights»' prompt detected. Pressing Enter...")
                pyautogui.press('enter')
                time.sleep(COMMAND_WAIT_FS)
                md_response = self._copy_terminal_text()
            
            all_pages.append(md_response)
            current_page += 1
        
        if current_page >= max_pages and max_pages > 1:
            self.logger.debug(f"      [WARNING] Reached max_pages ({max_pages}). Stopping.")
        
        # Join all pages — use separator so parser can handle overlapping headers
        full_text = "\n--- PAGE BREAK ---\n".join(all_pages)
        
        # Check for unsaleable fares
        # If UNSALEABLE_FARES_KEYWORD appears, we send the FU* command
        # which drops down the unsaleable fares inline (with O-prefixed line numbers)
        if UNSALEABLE_FARES_KEYWORD in full_text.upper():
            self.logger.debug("      [DEBUG] 'UNSALEABLE FARES' detected. Sending FU* command...")
            pyautogui.typewrite("FU*", interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_LONG)  # Wait for unsaleable fares to load
            # Re-capture and paginate through unsaleable fares if needed
            fu_pages = [self._copy_terminal_text()]
            fu_page = 1
            while fu_page < MAX_PAGES_UNSALEABLE:  # Unsaleable fares rarely exceed a few pages
                if self._has_end_signal(fu_pages[-1]):
                    break
                pyautogui.typewrite("MD", interval=KEYBOARD_INTERVAL)
                pyautogui.press('enter')
                time.sleep(COMMAND_WAIT_MEDIUM)
                fu_response = self._copy_terminal_text()
                if self._has_invalid(fu_response) or fu_response.strip() == fu_pages[-1].strip():
                    break
                fu_pages.append(fu_response)
                fu_page += 1
            
            # CRITICAL FIX: Append the unsaleable text instead of overwriting the full data array!
            full_text += "\n--- UNSALEABLE FARES BREAK ---\n" + "\n--- PAGE BREAK ---\n".join(fu_pages)
            self.logger.debug(f"      [DEBUG] Unsaleable fares captured ({len(fu_pages)} pages appended).")
        return full_text
    
    def run_ftax_command(self, country_code: str, tax_code: str, tax_index: int = 1, max_pages: int = MAX_PAGES_TAX) -> str:
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
        pyautogui.typewrite(direct_cmd, interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_FTAX)
        
        first_page = self._copy_terminal_text()
        
        # If direct command returned INVALID, fall back to Tab navigation
        if self._has_invalid(first_page):
            self.logger.debug(f"      Direct command returned INVALID. Falling back to Tab navigation (index {tax_index})...")
            # Re-send the list command to get back to the tax list
            list_cmd = f"FTAX-{country_code}"
            pyautogui.typewrite(list_cmd, interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FTAX)
            
            # Tab to the correct link
            for _ in range(tax_index):
                pyautogui.press('tab', interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FTAX)
            first_page = self._copy_terminal_text()
            
            if self._has_invalid(first_page):
                self.logger.warning(f"      Tab navigation also returned INVALID for {tax_code}.")
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
            if 'TAX RATE' in previous_text.upper():
                seen_tax_rate = True
                
            # Check if we reached EXEMPTIONS (which always follows TAX RATE)
            # Only trigger this AFTER we have seen the TAX RATE block, as EXEMPTIONS
            # can also appear on page 1 before the rates!
            if seen_tax_rate and ('EXEMPTIONS:' in previous_text.upper() or 'EXEMPTION:' in previous_text.upper()):
                self.logger.debug("      'EXEMPTIONS:' section reached after TAX RATE. Rates are fully captured. Stopping.")
                break
            
            # Send MD
            self.logger.debug(f"      Page {current_page}: Sending MD...")
            pyautogui.typewrite("MD", interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FS)
            
            page_text = self._copy_terminal_text()
            
            # Check if MD returned INVALID
            if self._has_invalid(page_text):
                self.logger.debug("      MD returned 'INVALID'. End of pagination.")
                break
            
            # Check if we're stuck (same content as previous page)
            if page_text.strip() == previous_text.strip():
                # Retry once with a longer wait before declaring stuck
                self.logger.debug("      Same text detected. Waiting 2s and retrying...")
                time.sleep(COMMAND_WAIT_LONG)
                page_text = self._copy_terminal_text()
                if page_text.strip() == previous_text.strip():
                    self.logger.debug("      Stuck: same content after retry. Stopping.")
                    break
            
            # Handle «More Fares/Flights» prompt
            if self._has_more_prompt(page_text):
                pyautogui.press('enter')
                time.sleep(COMMAND_WAIT_FS)
                page_text = self._copy_terminal_text()
            
            all_pages_text.append(page_text)
            previous_text = page_text
            current_page += 1
        
        if current_page > max_pages:
            self.logger.warning(f"      Reached max_pages ({max_pages}). Stopping.")
        
        # Combine all pages into one block of text
        # Each page may have overlapping header lines; we join with a separator
        combined = "\n--- PAGE BREAK ---\n".join(all_pages_text)
        self.logger.debug(f"      Accumulated {len(all_pages_text)} pages, {len(combined)} total chars.")
        
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
        
        pyautogui.typewrite(command, interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_FS)  # Wait for FS results to load
        
        return self._copy_terminal_text()
    
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
        
        pyautogui.typewrite(fq_cmd, interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_FS)  # Wait for fare quote to load
        
        result = self._copy_terminal_text()
        
        # If FQ* returned INVALID, this option might not support it
        if self._has_invalid(result):
            self.logger.warning(f"      FQ*{option_number} returned INVALID. Trying FQP*{option_number}...")
            # Fallback: try FQP* (pricing-specific variant)
            pyautogui.typewrite(f"FQP*{option_number}", interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FS)
            result = self._copy_terminal_text()
        
        # Paginate if needed (fare quotes can span multiple pages)
        page = 1
        while page < 5:
            if self._has_end_signal(result):
                break
            if self._has_invalid(result):
                break
            pyautogui.typewrite("MD", interval=KEYBOARD_INTERVAL)
            pyautogui.press('enter')
            time.sleep(COMMAND_WAIT_FS)
            md_result = self._copy_terminal_text()
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
        pyautogui.press('escape')
        time.sleep(CLICK_DELAY)
        
        for _ in range(tabs_to_press):
            pyautogui.press('tab', interval=KEYBOARD_INTERVAL)
            
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_LONG)  # Wait for the inline tax breakdown to expand
        return self._copy_terminal_text()

    def _text_line_to_pixel(self, text: str, target_line_idx: int, 
                             char_idx: int = None, x_ratio: float = 0.5):
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
            # Use the actual line length to determine column count
            # (the terminal column count changes when window is resized)
            lines = text.split('\n')
            if target_line_idx < len(lines):
                line_len = max(len(lines[target_line_idx]), 1)
                # Position D as a proportion of the line length
                x_ratio_from_char = char_idx / line_len
                pixel_x = int(rect.left + rect.width() * x_ratio_from_char)
            else:
                pixel_x = int(rect.left + rect.width() * x_ratio)
        else:
            pixel_x = int(rect.left + rect.width() * x_ratio)
        
        return (pixel_x, pixel_y)
    
    def click_element_by_text_position(self, text: str, search_pattern: str,
                                        x_ratio: float = 0.5, occurrence: int = 0,
                                        y_offsets: list = None, use_2d_offsets: bool = False) -> str:
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
                (0, -9), (0, 9),           # Vertical only
                (-10, 0), (10, 0),         # Horizontal only
                (0, -18), (0, 18),         # More vertical
                (-10, -9), (10, -9),       # Diagonal combinations
                (-10, 9), (10, 9),
                (-20, 0), (20, 0),         # More horizontal
            ]
        else:
            # Legacy: vertical offsets only
            if y_offsets is None:
                y_offsets = [0, -9, 9, -18, 18]
            offsets = [(0, y) for y in y_offsets]

        # Clear any text selection first
        pyautogui.press('escape', presses=2, interval=KEYBOARD_INTERVAL)
        time.sleep(ESCAPE_CLEAR_DELAY)

        # Find matching lines
        lines = text.split('\n')
        matching_lines = []
        for idx, line in enumerate(lines):
            if re.search(search_pattern, line, re.IGNORECASE):
                matching_lines.append(idx)

        if not matching_lines:
            self.logger.error(f"      [CLICK] Pattern '{search_pattern}' not found in {len(lines)} lines")
            return ""

        if occurrence >= len(matching_lines) or (occurrence < 0 and abs(occurrence) > len(matching_lines)):
            self.logger.error(f"      [CLICK] Only {len(matching_lines)} matches, need #{occurrence}")
            return ""

        target_line = matching_lines[occurrence]
        base_x, base_y = self._text_line_to_pixel(text, target_line, x_ratio=x_ratio)

        self.logger.info(f"      [CLICK] Line {target_line} -> ({base_x}, {base_y})")

        text_before = text
        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(f"      [CLICK] Trying ({click_x}, {click_y}) [offset=({x_off},{y_off})]")

            pyautogui.moveTo(click_x, click_y, duration=MOUSE_MOVE_DURATION)
            pyautogui.click()
            time.sleep(COMMAND_WAIT_SHORT)

            result = self._copy_terminal_text()

            # Check if we accidentally activated a dropdown
            if self._has_dropdown_activated(result):
                self.logger.debug("      [CLICK] Dropdown detected, closing with Escape and retrying...")
                pyautogui.press('escape', presses=2, interval=KEYBOARD_INTERVAL)
                time.sleep(ESCAPE_CLEAR_DELAY)
                continue

            if result.strip() != text_before.strip():
                self.logger.info(f"      [CLICK] ✓ Screen changed at offset=({x_off},{y_off})")
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
        
        lines = fs_text.split('\n')
        
        # Strategy: Find lines containing «BOOK» or +TQ — these markers are
        # always on the same line as the D button. Using "D  R" is unreliable
        # because the clipboard sometimes splits D and R across lines.
        d_button_lines = []
        for idx, line in enumerate(lines):
            if '+TQ' in line or '«BOOK»' in line or '\xabBOOK\xbb' in line:
                d_button_lines.append(idx)
        
        self.logger.info(f"      [D-CLICK] Found {len(d_button_lines)} BOOK/+TQ lines: {d_button_lines}")
        
        if not d_button_lines:
            # Fallback: search for lines near PRICING OPTION headers
            self.logger.warning("      [D-CLICK] No 'D  R' pattern found. Trying PRICING OPTION fallback...")
            option_headers = []
            for idx, line in enumerate(lines):
                if re.search(r'PRICING\s+OPTION\s+\d+', line, re.IGNORECASE):
                    option_headers.append(idx)
            
            if option_index < len(option_headers):
                target_line = option_headers[option_index] + 4
            else:
                self.logger.error(f"      [D-CLICK] Cannot locate D button for option {option_index}")
                return ""
        else:
            if option_index >= len(d_button_lines):
                self.logger.error(f"      [D-CLICK] Only {len(d_button_lines)} D buttons, need index {option_index}")
                return ""
            
            target_line = d_button_lines[option_index]
        
        # Use empirically measured x_ratio for D button position.
        # Clipboard char positions don't map 1:1 to pixels (measured 0.907 vs actual 0.856).
        # The D button is consistently at ~85.5% of terminal width.
        D_X_RATIO = D_BUTTON_X_RATIO
        base_x, base_y = self._text_line_to_pixel(fs_text, target_line, x_ratio=D_X_RATIO)
        
        self.logger.info(f"      [D-CLICK] Option {option_index+1}: line {target_line}, "
                        f"click at ({base_x}, {base_y})")
        
        # Clear selection
        pyautogui.press('escape', presses=2, interval=KEYBOARD_INTERVAL)
        time.sleep(ESCAPE_CLEAR_DELAY)
        
        # Try clicking with combined X and Y offsets for tolerance
        text_before = fs_text
        offsets = [
            (0, 0), (-15, 0), (15, 0),     # Same line, shift X
            (0, -9), (0, 9),                 # One line up/down, same X
            (-15, -9), (15, -9),             # One line up, shift X
            (-15, 9), (15, 9),               # One line down, shift X
        ]
        
        for x_off, y_off in offsets:
            click_x = base_x + x_off
            click_y = base_y + y_off
            self.logger.debug(f"      [D-CLICK] Trying ({click_x}, {click_y}) [x={x_off}, y={y_off}]")

            pyautogui.moveTo(click_x, click_y, duration=MOUSE_MOVE_DURATION)
            pyautogui.click()
            time.sleep(COMMAND_WAIT_SHORT)
            
            result = self._copy_terminal_text()
            
            if result.strip() != text_before.strip():
                upper = result.upper()
                # D expansion shows: FARE COMPONENT BASIS, tax codes (YQ, BD, etc.), EQU, etc.
                if any(kw in upper for kw in ["EQU", "TAXES", "TAX", "YQ", "FARE COMPONENT", "BASIS"]):
                    self.logger.info(f"      [D-CLICK] ✓ Tax breakdown at offset=({x_off},{y_off})")
                    return result
                else:
                    self.logger.debug(f"      [D-CLICK] Screen changed but no tax/fare data. Sending 'I' to reset...")
                    pyautogui.typewrite("I", interval=KEYBOARD_INTERVAL)
                    pyautogui.press('enter')
                    time.sleep(COMMAND_WAIT_FS)
                    text_before = self._copy_terminal_text()
                    if "PRICING OPTION" not in text_before.upper():
                        self.logger.warning(f"      [D-CLICK] Could not recover FS display. Aborting.")
                        return ""
        
        self.logger.warning(f"      [D-CLICK] Could not expand tax details after all attempts.")
        return self._copy_terminal_text()
    
    def click_currency_link(self, fd_text: str) -> str:
        """
        Click the 'BDT CURRENCY FARES EXISTS' hyperlink.
        The link spans the full text, so we click in the middle.

        Uses 2D offset tolerance to prevent accidental clicks on adjacent
        elements like the "Fare" section header.
        """
        result = self.click_element_by_text_position(
            text=fd_text,
            search_pattern=r'CURRENCY\s+FARES?\s+EXISTS?',
            x_ratio=CURRENCY_LINK_X_RATIO,  # Click center of the text
            occurrence=0,
            use_2d_offsets=True  # Use 2D offsets for better tolerance
        )

        # Validate the click succeeded by checking for expected currency data
        if result and not self._has_currency_redirect(result):
            # Successfully clicked and navigated away from the redirect message
            self.logger.info("      [CLICK] ✓ Currency link clicked successfully, fare data loaded")
            return result
        else:
            # Click may have failed, warn but return result anyway
            self.logger.warning("      [CLICK] Currency link click may have failed - still seeing redirect message")
            return result
    
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
        clean_text = terminal_text.rstrip('\r\n')
        lines = clean_text.split('\n')
        
        # Search from bottom up
        for i in range(len(lines)-1, -1, -1):
            line = lines[i]
            match = re.search(r'(MORE\s+(?:FARES|FLIGHTS|OPTIONS))', line, re.IGNORECASE)

            if match:
                pyautogui.press('escape', presses=2, interval=KEYBOARD_INTERVAL)
                time.sleep(ESCAPE_CLEAR_DELAY)

                # IMPORTANT: Scroll down if the text is overflowing
                if len(lines) > total_lines_capacity:
                    self.logger.debug("      [CLICK] Scrolling terminal to bottom before clicking...")
                    pyautogui.click(rect.left + rect.width()//2, rect.top + rect.height()//2)
                    time.sleep(COPY_DELAY)
                    pyautogui.press('pagedown', presses=4, interval=KEYBOARD_INTERVAL)
                    time.sleep(PAGEDOWN_SCROLL_DELAY)
                    
                    # Target isolated calculation from the visual bottom
                    # Empirical Test: Smartpoint's bottom frame padding sits exactly at 0px.
                    # The text renders completely flush against the lowest border of the active text area.
                    # BOTTOM_MARGIN is imported from constants
                    lines_from_bottom = len(lines) - 1 - i
                    base_y = int(rect.bottom - BOTTOM_MARGIN - (lines_from_bottom + 0.5) * LINE_HEIGHT)
                    
                    # Offset X by ~32px (0.04 of 800) to perfectly center on the 'M' core, avoiding airline codes!
                    base_x, _ = self._text_line_to_pixel(clean_text, i, x_ratio=MORE_LINK_X_RATIO)
                else:
                    base_x, base_y = self._text_line_to_pixel(clean_text, i, x_ratio=MORE_LINK_X_RATIO)

                # Start Retry/Tolerance Logic
                # Use 2D offsets to handle both horizontal and vertical positioning errors
                # This prevents accidental clicks on adjacent elements like "/12M" or "M" dropdowns
                offsets = [
                    (0, 0),
                    (0, -10), (0, 10),          # Vertical only
                    (-5, 0), (5, 0),            # Horizontal only (small shifts)
                    (0, -20), (0, 20),          # More vertical
                    (-5, -10), (5, -10),        # Diagonal combinations
                    (-5, 10), (5, 10),
                    (0, -30), (0, 30)           # Even more vertical
                ]
                text_before = terminal_text

                for x_off, y_off in offsets:
                    click_x = base_x + x_off
                    click_y = base_y + y_off
                    self.logger.debug(f"      [CLICK] Trying 'More' link at ({click_x}, {click_y}) [offset=({x_off},{y_off})]")

                    pyautogui.moveTo(click_x, click_y, duration=MOUSE_MOVE_DURATION)
                    pyautogui.click()
                    time.sleep(COMMAND_WAIT_LONG)

                    result = self._copy_terminal_text()

                    # Check if we accidentally activated a dropdown (MAXIMUM STAY, etc.)
                    if self._has_dropdown_activated(result):
                        self.logger.debug("      [CLICK] Dropdown detected, closing with Escape and retrying...")
                        pyautogui.press('escape', presses=2, interval=KEYBOARD_INTERVAL)
                        time.sleep(ESCAPE_CLEAR_DELAY)
                        continue

                    if result.strip() != text_before.strip():
                        self.logger.info("      [CLICK] ✓ 'More' link clicked successfully!")
                        return True

                self.logger.warning("      [CLICK] Exhausted all offset attempts to click 'More' link.")
                return False
                
        return False
    
    def return_to_tax_list(self, country_code: str):
        """Re-send FTAX-{CC} to return to the tax type list page."""
        if not self.focus():
            return
        list_cmd = f"FTAX-{country_code}"
        self.logger.debug(f"      Returning to tax list: {list_cmd}")
        pyautogui.typewrite(list_cmd, interval=KEYBOARD_INTERVAL)
        pyautogui.press('enter')
        time.sleep(COMMAND_WAIT_FS)
    
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
        Check if the text contains a 'XXX CURRENCY FARES EXISTS' message.

        Returns the currency code (e.g., 'BDT') if found, or None.
        """
        if not text:
            return None
        import re
        match = re.search(r'([A-Z]{3})\s+CURRENCY\s+FARES?\s+EXISTS?', text.upper())
        if match:
            return match.group(1)
        return None
    
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
            'MAXIMUM STAY',
            'MINIMUM STAY',
            'MAX STAY',
            'MIN STAY',
            'ADVANCE PURCHASE',
            'TRAVEL COMPLETE',
            'PERMITTED',
            'NOT PERMITTED',
            'TICKETING',
            'BLACKOUT DATES'
        ]

        # Check if any dropdown keywords appear (these typically shouldn't be in fare lists)
        for keyword in dropdown_keywords:
            if keyword in upper_text:
                return True

        return False