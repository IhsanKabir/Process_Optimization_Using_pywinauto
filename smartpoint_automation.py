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
from ctypes import wintypes

class SmartpointAutomation:
    def __init__(self, window_title="Application Window 1"):
        """Initialize the Smartpoint automation class."""
        self.window_title = window_title
        self.app = None
        self.window = None
        self.connected = False
        self.logged_in = False
        self.logger = logging.getLogger('travelport.automation')
        
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
            time.sleep(1.0) # Allow plenty of time for window to come forward
            return True
        except Exception as e:
            self.logger.info(f"  [ERROR] Could not focus Smartpoint window: {e}")
            return False

    def login(self, username: str, password: str, pcc: str | None = None) -> bool:
        """
        Automate the Smartpoint login process.
        Assumes the terminal is ready to accept the sign-on command.
        Command format: SON/Z{PCC}[enter]{USERNAME}[enter]{PASSWORD}[enter]
        """
        if self.logged_in:
            print("  [DEBUG] Already logged in, skipping login sequence.")
            return True
            
        if not self.focus():
            print("  [ERROR] Cannot login, window not focused.")
            return False
            
        print("  [DEBUG] Starting login sequence...")
        self.clear_screen()
        
        try:
            # 1. Initiate Sign-On
            sign_on_cmd = f"SON/Z{pcc}" if pcc else "SON/Z"
            print(f"    Sending sign-on command: {sign_on_cmd}")
            pyautogui.typewrite(sign_on_cmd, interval=0.05)
            pyautogui.press('enter')
            time.sleep(1.5) # Wait for username prompt
            
            # 2. Enter Username
            print("    Entering username...")
            pyautogui.typewrite(username, interval=0.05)
            pyautogui.press('enter')
            time.sleep(1.0) # Wait for password prompt
            
            # 3. Enter Password
            print("    Entering password...")
            pyautogui.typewrite(password, interval=0.05)
            pyautogui.press('enter')
            
            # Wait for login to complete
            print("    Waiting for login to complete...")
            time.sleep(4.0)
            
            # Check for success by reading terminal text
            terminal_text = self._copy_terminal_text()
            if "RESTRICTED" in terminal_text.upper() or "SIGN-ON" in terminal_text.upper() or "WELCOME" in terminal_text.upper():
                 print("  [SUCCESS] Login successful.")
                 self.logged_in = True
                 return True
            else:
                 print("  [WARNING] Login might have failed. Please check the terminal.")
                 print(f"  [DEBUG] Terminal output: {terminal_text[:100]}...")
                 return False
                 
        except Exception as e:
            print(f"  [ERROR] Login automation failed: {e}")
            return False

    def clear_screen(self):
        """Clear the terminal screen or input buffer by sending 'I'"""
        # Ensure focus first
        self.focus()
        
        # Sending 'I' completely refreshes the Travelport Smartpoint terminal
        print("  [DEBUG] Refreshing terminal with 'I' command...")
        pyautogui.typewrite("I", interval=0.05)
        pyautogui.press('enter')
        time.sleep(2.0) # Wait for refresh to complete

    def refresh_terminal(self):
        """Alias for clear_screen for compatibility."""
        self.clear_screen()

    def _copy_terminal_text(self) -> str:
        """Helper to copy text from the terminal via clipboard using mouse automation."""
        pyperclip.copy("")
        time.sleep(0.3)
        
        # Ensure focus hasn't been lost
        self.focus()
        
        if not self.window:
            return ""
            
        # Get window coordinates — click in the terminal body area
        try:
            rect = self.window.rectangle()
            center_x = rect.left + (rect.width() // 2)
            # Click in the middle vertically (the terminal text area)
            center_y = rect.top + (rect.height() // 2)
        except Exception:
            screen_width, screen_height = pyautogui.size()
            center_x = screen_width // 2
            center_y = screen_height // 2
        
        # Click to focus the terminal area
        pyautogui.click(x=center_x, y=center_y, duration=0.2)
        time.sleep(0.3)
        
        # Select all + copy
        pyautogui.hotkey('ctrl', 'a', interval=0.1)
        time.sleep(0.8)
        pyautogui.hotkey('ctrl', 'c', interval=0.1)
        time.sleep(1.0)
        
        text = pyperclip.paste()
        self.logger.debug(f"      [DEBUG] Extracted {len(text)} characters from clipboard")
        
        # Click once to deselect
        pyautogui.press('escape')
        time.sleep(0.2)
            
        return text
        
    def show_completion_signal(self):
        """Show a clear completion signal in the terminal (no popup)."""
        self.logger.debug("\n" + "="*50)
        self.logger.debug("      🚀 TRAVELPORT AUTOMATION TASK COMPLETE 🚀")
        self.logger.debug("="*50 + "\n")

    def run_command(self, command: str, max_pages: int = 10) -> str:
        """
        Execute a complete command in Smartpoint, handling pagination if necessary.
        
        Smartpoint pagination flow:
          1. Run command → first page of fares appears
          2. Check for "CURRENCY FARES EXISTS" → re-run in alternate currency
          3. If no "END" at the bottom → type MD + Enter
          4. If MD returns "INVALID" → stop (no more data)
          5. A "«More Fares»" prompt may appear → press Enter again
          6. Remaining data loads; repeat until "END" is found
          7. Check for "UNSALEABLE FARES MAY EXIST" → send FU*
          8. Ctrl+A, Ctrl+C to capture the full text
        
        Returns the full combined text output from all pages.
        """
        if not self.focus():
            self.logger.debug("  [ERROR] Cannot run command, window not focused.")
            return ""

        self.logger.debug(f"    Running: {command}")
        
        # Send the initial command using PyAutoGUI
        pyautogui.typewrite(command, interval=0.05)
        pyautogui.press('enter')
        
        # Wait for the terminal to respond
        time.sleep(4.0) 
        
        # Capture initial response
        initial_text = self._copy_terminal_text()
        
        # Check for "CURRENCY FARES EXISTS" (e.g., "BDT CURRENCY FARES EXISTS")
        # This means no fares in the requested currency; we need to switch
        currency_match = self._has_currency_redirect(initial_text)
        if currency_match:
            self.logger.debug(f"      [DEBUG] '{currency_match} CURRENCY FARES EXISTS' detected. Switching currency...")
            # Type FD*{CURRENCY} to redisplay in the alternate currency
            redirect_cmd = f"FD*{currency_match}"
            pyautogui.typewrite(redirect_cmd, interval=0.05)
            pyautogui.press('enter')
            time.sleep(4.0)
        
        current_page = 1
        previous_md_text = initial_text
        
        # Pagination loop: keep sending MD until END appears
        full_text = initial_text
        while current_page < max_pages:
            # Capture what's currently on screen
            screen_text = self._copy_terminal_text()
            
            # Check if END is present anywhere in the captured text
            if self._has_end_signal(screen_text):
                self.logger.debug("      [DEBUG] 'END' signal detected. Pagination complete.")
                break
            
            # No END found — we need to paginate with MD
            self.logger.debug(f"      Page {current_page}: No 'END' found. Sending MD...")
            pyautogui.typewrite("MD", interval=0.05)
            pyautogui.press('enter')
            time.sleep(3.0)  # Wait for MD response
            
            # Check if MD returned "INVALID" (no more data to paginate)
            md_response = self._copy_terminal_text()
            
            if self._has_invalid(md_response):
                self.logger.debug("      [DEBUG] MD returned 'INVALID'. No more data to paginate.")
                break
            
            # Detect stuck screen: same text as previous MD
            if md_response.strip() == previous_md_text.strip():
                self.logger.debug("      [DEBUG] Same text as previous page. Stopping pagination.")
                break
            previous_md_text = md_response
                
            full_text = md_response
            
            # After MD, Smartpoint may show "«More Fares»" or "«More Flights»" prompt
            # We need to check and press Enter to confirm
            if self._has_more_prompt(md_response):
                self.logger.debug("      [DEBUG] '«More Fares/Flights»' prompt detected. Pressing Enter...")
                pyautogui.press('enter')
                time.sleep(3.0)  # Wait for remaining data to load
                full_text = self._copy_terminal_text()
            
            current_page += 1
        
        if current_page >= max_pages and max_pages > 1:
            self.logger.debug(f"      [WARNING] Reached max_pages ({max_pages}). Stopping.")
        
        # Final capture — now the full data (including paginated results) should be on screen
        # Note: We rely on `full_text` being updated during pagination. If `max_pages=1`, it's just `initial_text`.
        if self._has_invalid(self._copy_terminal_text()) and not self._has_invalid(initial_text):
            # If the screen is currently INVALID but our initial response wasn't, 
            # we likely paged too far. Let's return the last valid text.
            pass
        else:
            full_text = self._copy_terminal_text()
        
        # Check for unsaleable fares
        # If "UNSALEABLE FARES MAY EXIST" appears, we send the FU* command
        # which drops down the unsaleable fares inline (with O-prefixed line numbers)
        if "UNSALEABLE FARES MAY EXIST" in full_text.upper():
            self.logger.debug("      [DEBUG] 'UNSALEABLE FARES' detected. Sending FU* command...")
            pyautogui.typewrite("FU*", interval=0.05)
            pyautogui.press('enter')
            time.sleep(4.0)  # Wait for unsaleable fares to load
            
            # Re-capture and paginate through unsaleable fares if needed
            full_text = self._copy_terminal_text()
            fu_page = 1
            while fu_page < 5:  # Unsaleable fares rarely exceed a few pages
                if self._has_end_signal(full_text):
                    break
                pyautogui.typewrite("MD", interval=0.05)
                pyautogui.press('enter')
                time.sleep(3.0)
                fu_response = self._copy_terminal_text()
                if self._has_invalid(fu_response) or fu_response.strip() == full_text.strip():
                    break
                full_text = fu_response
                fu_page += 1
            self.logger.debug("      [DEBUG] Unsaleable fares captured.")
        return full_text
    
    def run_ftax_command(self, country_code: str, tax_code: str, tax_index: int = 1, max_pages: int = 50) -> str:
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
        pyautogui.typewrite(direct_cmd, interval=0.05)
        pyautogui.press('enter')
        time.sleep(4.0)
        
        first_page = self._copy_terminal_text()
        
        # If direct command returned INVALID, fall back to Tab navigation
        if self._has_invalid(first_page):
            self.logger.debug(f"      Direct command returned INVALID. Falling back to Tab navigation (index {tax_index})...")
            # Re-send the list command to get back to the tax list
            list_cmd = f"FTAX-{country_code}"
            pyautogui.typewrite(list_cmd, interval=0.05)
            pyautogui.press('enter')
            time.sleep(4.0)
            
            # Tab to the correct link
            for _ in range(tax_index):
                pyautogui.press('tab', interval=0.1)
            pyautogui.press('enter')
            time.sleep(4.0)
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
            pyautogui.typewrite("MD", interval=0.05)
            pyautogui.press('enter')
            time.sleep(3.0)
            
            page_text = self._copy_terminal_text()
            
            # Check if MD returned INVALID
            if self._has_invalid(page_text):
                self.logger.debug("      MD returned 'INVALID'. End of pagination.")
                break
            
            # Check if we're stuck (same content as previous page)
            if page_text.strip() == previous_text.strip():
                # Retry once with a longer wait before declaring stuck
                self.logger.debug("      Same text detected. Waiting 2s and retrying...")
                time.sleep(2.0)
                page_text = self._copy_terminal_text()
                if page_text.strip() == previous_text.strip():
                    self.logger.debug("      Stuck: same content after retry. Stopping.")
                    break
            
            # Handle «More Fares/Flights» prompt
            if self._has_more_prompt(page_text):
                pyautogui.press('enter')
                time.sleep(3.0)
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
    
    def return_to_tax_list(self, country_code: str):
        """Re-send FTAX-{CC} to return to the tax type list page."""
        if not self.focus():
            return
        list_cmd = f"FTAX-{country_code}"
        self.logger.debug(f"      Returning to tax list: {list_cmd}")
        pyautogui.typewrite(list_cmd, interval=0.05)
        pyautogui.press('enter')
        time.sleep(4.0)
    
    def _has_end_signal(self, text: str) -> bool:
        """Check if the terminal text contains the END signal in its last lines."""
        if not text:
            return False
        lines = text.strip().splitlines()
        # Check the last 10 lines for a standalone "END" 
        check_lines = lines[-10:] if len(lines) >= 10 else lines
        for line in check_lines:
            stripped = line.strip().upper()
            if stripped == "END":
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
            if stripped == "INVALID":
                return True
        return False