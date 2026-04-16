"""
clipboard_util.py - Windows clipboard helpers with retry-safe reads/writes.

Uses pywin32's clipboard API first because it is more robust than raw ctypes
for normal desktop use, while keeping a low-level fallback for environments
where pywin32 is unavailable.
"""

import ctypes
import time

try:
    import win32clipboard
except Exception:
    win32clipboard = None

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _open_clipboard(retries: int = 5, delay: float = 0.05) -> bool:
    """Try to open the Windows clipboard with retries."""
    for _ in range(retries):
        if win32clipboard is not None:
            try:
                win32clipboard.OpenClipboard()
                return True
            except Exception:
                time.sleep(delay)
                continue
        if _user32.OpenClipboard(0):
            return True
        time.sleep(delay)
    return False


def _close_clipboard():
    """Close the clipboard, ignoring secondary close errors."""
    try:
        if win32clipboard is not None:
            win32clipboard.CloseClipboard()
            return
    except Exception:
        pass
    try:
        _user32.CloseClipboard()
    except Exception:
        pass


def clipboard_paste() -> str:
    """Read Unicode text from the Windows clipboard.

    Returns empty string on failure (clipboard locked, empty, or non-text).
    """
    if not _open_clipboard():
        return ""
    try:
        if win32clipboard is not None:
            try:
                data = win32clipboard.GetClipboardData(CF_UNICODETEXT)
                return str(data) if data else ""
            except Exception:
                return ""

        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        _kernel32.GlobalLock.restype = ctypes.c_wchar_p
        text = _kernel32.GlobalLock(handle)
        result = str(text) if text else ""
        _kernel32.GlobalUnlock(handle)
        return result
    finally:
        _close_clipboard()


def clipboard_clear():
    """Clear the Windows clipboard."""
    if not _open_clipboard():
        return
    try:
        if win32clipboard is not None:
            try:
                win32clipboard.EmptyClipboard()
                return
            except Exception:
                pass
        _user32.EmptyClipboard()
    finally:
        _close_clipboard()


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
        if win32clipboard is not None:
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(str(text), CF_UNICODETEXT)
                return
            except Exception:
                pass

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
        _close_clipboard()
