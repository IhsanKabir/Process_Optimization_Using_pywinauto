"""
clipboard_util.py - Win32 Clipboard Access (No External Dependencies)

Replaces pyperclip with direct Win32 API calls to avoid:
  - Clipboard deadlocks when another app holds the clipboard lock
  - ctypes DLL initialization conflicts in PyInstaller builds

All functions retry on transient lock failures (up to 5 attempts).
"""

import ctypes
import ctypes.wintypes as wintypes
import time

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _open_clipboard(retries: int = 5, delay: float = 0.05) -> bool:
    """Try to open the Windows clipboard with retries."""
    for _ in range(retries):
        if _user32.OpenClipboard(0):
            return True
        time.sleep(delay)
    return False


def clipboard_paste() -> str:
    """Read Unicode text from the Windows clipboard.

    Returns empty string on failure (clipboard locked, empty, or non-text).
    """
    if not _open_clipboard():
        return ""
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        _kernel32.GlobalLock.restype = ctypes.c_wchar_p
        text = _kernel32.GlobalLock(handle)
        result = str(text) if text else ""
        _kernel32.GlobalUnlock(handle)
        return result
    finally:
        _user32.CloseClipboard()


def clipboard_clear():
    """Clear the Windows clipboard."""
    if not _open_clipboard():
        return
    try:
        _user32.EmptyClipboard()
    finally:
        _user32.CloseClipboard()


def clipboard_copy(text: str):
    """Write Unicode text to the Windows clipboard.

    If text is empty/None, just clears the clipboard.
    """
    if not text:
        clipboard_clear()
        return

    if not _open_clipboard():
        return
    try:
        _user32.EmptyClipboard()
        # Allocate global memory for the text (including null terminator)
        byte_count = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, byte_count)
        if not h_mem:
            return
        _kernel32.GlobalLock.restype = ctypes.c_void_p
        ptr = _kernel32.GlobalLock(h_mem)
        if ptr:
            ctypes.memmove(ptr, ctypes.create_unicode_buffer(text), byte_count)
            _kernel32.GlobalUnlock(h_mem)
            _user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        else:
            _kernel32.GlobalFree(h_mem)
    finally:
        _user32.CloseClipboard()
