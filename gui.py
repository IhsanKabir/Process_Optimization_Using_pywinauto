"""
gui.py - TravelportAuto GUI

User-friendly window. No raw log by default - shows a live route
checklist with plain-language status icons. Technical log is available
via a hidden "Show technical log" toggle for troubleshooting.

Entry point for PyInstaller build (console=False in spec).
Run directly:  python gui.py
"""

# Must be called before any window is created so pyautogui and UIAutomation
# both use physical pixel coordinates on DPI-scaled displays.
try:
    import ctypes as _ctypes
    _ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import argparse
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, scrolledtext, ttk

# â”€â”€ Thread-safe log bridge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


class _StdoutRedirect:
    def __init__(self, q: queue.Queue):
        self.q = q
        self.encoding = "utf-8"

    def write(self, text: str):
        text = text.rstrip()
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass

    def isatty(self):
        return False

    def writable(self):
        return True


ESC_HOLD_TO_STOP_SECONDS = 0.8


def _escape_hold_state(
    is_pressed: bool,
    now: float,
    pressed_since: float | None,
    hold_seconds: float = ESC_HOLD_TO_STOP_SECONDS,
) -> tuple[float | None, bool]:
    """Track whether ESC has been held long enough to request a stop."""
    if not is_pressed:
        return None, False
    if pressed_since is None:
        return now, False
    return pressed_since, (now - pressed_since) >= hold_seconds


# â”€â”€ Tooltip helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class _Tooltip:
    """Lightweight tkinter tooltip - shows a small label on hover."""

    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=self.text,
            justify="left",
            bg="#ffffe0",
            fg="#333",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 8),
            padx=6,
            pady=3,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _runtime_dir() -> str:
    """Return the folder that should hold user-visible runtime files."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Preferences and updater state live next to the exe (or script in dev mode)
_SCRIPT_DIR = _runtime_dir()
_PREFS_FILE = os.path.join(_SCRIPT_DIR, "preferences.json")
_UPDATE_STATE_FILE = os.path.join(_SCRIPT_DIR, "_tpa_update_state.txt")
_UPDATE_LOG_FILE = os.path.join(_SCRIPT_DIR, "_tpa_update.log")
_PENDING_UPDATE_EXE = os.path.join(_SCRIPT_DIR, "TravelportAuto_update.exe")


def _load_prefs() -> dict:
    """Load saved preferences from disk. Returns empty dict on any error."""
    try:
        with open(_PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_prefs(data: dict):
    """Persist preferences to disk. Silently ignores errors."""
    try:
        with open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _read_update_state() -> dict | None:
    """Read the updater status marker written by the batch updater."""
    try:
        with open(_UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return None

    if not raw:
        return None

    parts = raw.split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return {
        "status": parts[0].strip().lower(),
        "version": parts[1].strip(),
        "message": parts[2].strip(),
    }


def _write_update_state(status: str, version: str = "", message: str = ""):
    """Persist updater status for the next app launch."""
    try:
        with open(_UPDATE_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(f"{status}|{version}|{message}".strip())
    except Exception:
        pass


def _clear_update_state():
    """Remove stale updater status markers once they are no longer needed."""
    try:
        os.remove(_UPDATE_STATE_FILE)
    except OSError:
        pass


def _build_update_notice(
    current_version: str, state: dict | None, pending_exe_path: str | None = None
) -> dict | None:
    """Build a startup notice when an update did not fully replace the exe."""
    if not state:
        return None

    status = str(state.get("status") or "").lower()
    target_version = str(state.get("version") or "").strip()
    message = str(state.get("message") or "").strip()

    if target_version and _parse_version(current_version) >= _parse_version(
        target_version
    ):
        return None

    if status not in {"pending", "failed", "installed"}:
        return None

    parts = []
    if target_version:
        parts.append(
            f"TravelportAuto {target_version} was downloaded, but this app is still running {current_version}."
        )
    else:
        parts.append(
            f"An update was downloaded, but this app is still running {current_version}."
        )

    if message:
        parts.append(message)

    pending_exe = pending_exe_path or _PENDING_UPDATE_EXE
    if os.path.exists(pending_exe):
        parts.append(f"Downloaded file: {pending_exe}")

    if os.path.exists(_UPDATE_LOG_FILE):
        parts.append(f"Updater log: {_UPDATE_LOG_FILE}")

    parts.append(
        "Close TravelportAuto, replace TravelportAuto.exe manually with the downloaded file, then reopen the app."
    )

    return {
        "title": "Update Needs Manual Replace",
        "message": "\n\n".join(parts),
    }


def _parse_cmd(cmd_str: str):
    """'FDDACMCT/BG'  ->  ('BG', 'DAC â†’ MCT')"""
    m = re.match(r"FD([A-Z]{3})([A-Z]{3})/([A-Z0-9]+)", cmd_str.upper())
    if m:
        origin, dest, airline = m.group(1), m.group(2), m.group(3)
        return airline, f"{origin} â†’ {dest}"
    return cmd_str, ""


def _format_eta_seconds(seconds: float) -> str:
    """Return a compact human-friendly ETA string."""
    total_seconds = max(0, int(round(seconds)))
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _estimate_remaining_seconds(
    elapsed_seconds: float, completed: int, total: int
) -> int | None:
    """Estimate remaining runtime from average completed-command duration."""
    if total <= 0:
        return None
    if completed >= total:
        return 0
    if completed <= 0 or elapsed_seconds <= 0:
        return None

    average_seconds = elapsed_seconds / completed
    remaining = average_seconds * max(0, total - completed)
    return max(1, int(round(remaining)))


# â”€â”€ Update checker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

GITHUB_RELEASES_API = (
    "https://api.github.com/repos/IhsanKabir/"
    "Process_Optimization_Using_pywinauto/releases/latest"
)


def _parse_version(tag: str) -> tuple:
    """'v1.3.0' â†’ (1, 3, 0)  - returns (0,) on failure."""
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except Exception:
        return (0,)


def _pick_release_exe_url(assets: list[dict]) -> str | None:
    """Choose the primary desktop exe from a GitHub release asset list."""
    preferred_names = {"travelportauto.exe"}
    fallback_url = None

    for asset in assets:
        name = str(asset.get("name") or "").strip()
        url = str(asset.get("browser_download_url") or "").strip()
        lower_name = name.lower()
        if not lower_name.endswith(".exe") or not url:
            continue
        if lower_name in preferred_names:
            return url
        if lower_name.endswith("_update.exe"):
            continue
        if fallback_url is None:
            fallback_url = url

    return fallback_url


def _pick_release_zip_url(assets: list[dict]) -> str | None:
    """Choose a .zip asset from a release. v1.5.x ships as a folder zip
    instead of a single exe; the in-app one-click update flow can't swap a
    folder safely, so we fall back to opening the release page."""
    for asset in assets:
        name = str(asset.get("name") or "").strip().lower()
        url = str(asset.get("browser_download_url") or "").strip()
        if name.endswith(".zip") and url:
            return url
    return None


def _build_updater_script(
    current_exe: str, new_exe: str, state_file: str, log_file: str, target_version: str
) -> str:
    """Generate the batch script that swaps in the downloaded exe."""
    clean_version = (target_version or "").replace("|", "/").strip()
    if not clean_version:
        clean_version = "unknown"

    return (
        "@echo off\n"
        "setlocal EnableExtensions EnableDelayedExpansion\n"
        f'set "SRC={new_exe}"\n'
        f'set "DST={current_exe}"\n'
        f'set "STATE={state_file}"\n'
        f'set "LOG={log_file}"\n'
        f'set "TARGET_VERSION={clean_version}"\n'
        '> "%LOG%" echo Starting TravelportAuto updater for %TARGET_VERSION%\n'
        "timeout /t 5 /nobreak > nul\n"
        "set RETRIES=8\n"
        ":retry\n"
        'if not exist "%SRC%" (\n'
        '  > "%STATE%" echo failed^|%TARGET_VERSION%^|Downloaded update file is missing.\n'
        "  goto launch\n"
        ")\n"
        'copy /y "%SRC%" "%DST%" >> "%LOG%" 2>&1\n'
        "if errorlevel 1 (\n"
        "  set /a RETRIES-=1\n"
        '  >> "%LOG%" echo Copy failed. Retries left=!RETRIES!\n'
        "  if !RETRIES! LEQ 0 (\n"
        '    > "%STATE%" echo failed^|%TARGET_VERSION%^|Windows could not replace TravelportAuto.exe automatically. The downloaded update is still saved as TravelportAuto_update.exe.\n'
        "    goto launch\n"
        "  )\n"
        "  timeout /t 2 /nobreak > nul\n"
        "  goto retry\n"
        ")\n"
        'del /f /q "%SRC%" >> "%LOG%" 2>&1\n'
        'for /d %%i in ("%~dp0_MEI*") do rd /s /q "%%i" 2>nul\n'
        'for /d %%i in ("%TEMP%\\_MEI*") do rd /s /q "%%i" 2>nul\n'
        '> "%STATE%" echo installed^|%TARGET_VERSION%^|Update installed successfully.\n'
        ":launch\n"
        'start "" "%DST%"\n'
        'del "%~f0"\n'
        "endlocal\n"
        "exit /b\n"
    )


def _build_folder_updater_script(
    current_exe: str, staging_folder: str, state_file: str, log_file: str, target_version: str
) -> str:
    """Generate the batch script that xcopy's an extracted update folder over the install dir."""
    clean_version = (target_version or "").replace("|", "/").strip() or "unknown"
    folder = os.path.dirname(current_exe)
    return (
        "@echo off\n"
        "setlocal EnableExtensions EnableDelayedExpansion\n"
        f'set "SRC={staging_folder}"\n'
        f'set "DST={folder}"\n'
        f'set "EXE={current_exe}"\n'
        f'set "STATE={state_file}"\n'
        f'set "LOG={log_file}"\n'
        f'set "TARGET_VERSION={clean_version}"\n'
        '> "%LOG%" echo Starting folder updater for %TARGET_VERSION%\n'
        "timeout /t 5 /nobreak > nul\n"
        'if not exist "%SRC%" (\n'
        '  > "%STATE%" echo failed^|%TARGET_VERSION%^|Staging folder not found.\n'
        "  goto launch\n"
        ")\n"
        # Back up user-customisable files before xcopy overwrites them with zip defaults.
        'if exist "%DST%\\preferences.json" copy /y "%DST%\\preferences.json" "%DST%\\preferences.json.bak" >nul 2>&1\n'
        'if exist "%DST%\\commands.txt" copy /y "%DST%\\commands.txt" "%DST%\\commands.txt.bak" >nul 2>&1\n'
        # agent_config.json backup: restore only if the new zip didn't include one.
        'if exist "%DST%\\agent_config.json" copy /y "%DST%\\agent_config.json" "%DST%\\agent_config.json.bak" >nul 2>&1\n'
        'xcopy /s /y /e "%SRC%\\*" "%DST%\\" >> "%LOG%" 2>&1\n'
        "if errorlevel 1 (\n"
        '  >> "%LOG%" echo xcopy failed; retrying after 3s...\n'
        "  timeout /t 3 /nobreak > nul\n"
        '  xcopy /s /y /e "%SRC%\\*" "%DST%\\" >> "%LOG%" 2>&1\n'
        ")\n"
        "if errorlevel 1 (\n"
        '  if exist "%DST%\\preferences.json.bak" copy /y "%DST%\\preferences.json.bak" "%DST%\\preferences.json" >nul 2>&1\n'
        '  if exist "%DST%\\commands.txt.bak" copy /y "%DST%\\commands.txt.bak" "%DST%\\commands.txt" >nul 2>&1\n'
        '  if exist "%DST%\\agent_config.json.bak" copy /y "%DST%\\agent_config.json.bak" "%DST%\\agent_config.json" >nul 2>&1\n'
        '  > "%STATE%" echo failed^|%TARGET_VERSION%^|Could not copy update files. Staging folder: %SRC%\n'
        "  goto launch\n"
        ")\n"
        # Restore user files that xcopy may have overwritten with zip defaults.
        'if exist "%DST%\\preferences.json.bak" (\n'
        '  copy /y "%DST%\\preferences.json.bak" "%DST%\\preferences.json" >nul 2>&1\n'
        '  del /f /q "%DST%\\preferences.json.bak"\n'
        ")\n"
        'if exist "%DST%\\commands.txt.bak" (\n'
        '  copy /y "%DST%\\commands.txt.bak" "%DST%\\commands.txt" >nul 2>&1\n'
        '  del /f /q "%DST%\\commands.txt.bak"\n'
        ")\n"
        # Restore agent_config.json only if the new zip didn't supply one.
        'if exist "%DST%\\agent_config.json.bak" (\n'
        '  if not exist "%DST%\\agent_config.json" copy /y "%DST%\\agent_config.json.bak" "%DST%\\agent_config.json" >nul 2>&1\n'
        '  del /f /q "%DST%\\agent_config.json.bak"\n'
        ")\n"
        'rd /s /q "%SRC%" 2>nul\n'
        '> "%STATE%" echo installed^|%TARGET_VERSION%^|Update installed successfully.\n'
        ":launch\n"
        'start "" "%EXE%"\n'
        'del "%~f0"\n'
        "endlocal\n"
        "exit /b\n"
    )


def _check_for_update(current_version: str) -> dict | None:
    """Return release dict if a newer version is available, else None."""
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": "TravelportAuto-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = data.get("tag_name", "")
        if _parse_version(latest_tag) > _parse_version(current_version):
            assets = data.get("assets", [])
            exe_url = _pick_release_exe_url(assets)
            zip_url = _pick_release_zip_url(assets) if not exe_url else None
            return {
                "version": latest_tag,
                "notes": data.get("body", ""),
                "exe_url": exe_url,
                "zip_url": zip_url,
                "release_url": data.get("html_url", ""),
            }
    except Exception:
        pass
    return None


# â”€â”€ Main GUI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TravelportGUI:
    VERSION = "v1.5.28"

    # Step labels shown in the step indicator
    STEPS = ["Setup", "Connect", "Extracting", "Report"]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"TravelportAuto  {self.VERSION}")
        self.root.geometry("1180x680")
        self.root.minsize(1060, 620)

        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self._run_thread: threading.Thread | None = None
        self._last_report: str | None = None
        self._stop_overlay: tk.Toplevel | None = None
        self._global_esc_active = False
        self._update_info: dict | None = None
        self._feedback_dialog: tk.Toplevel | None = None
        self._feedback_thread: threading.Thread | None = None
        self._feedback_submit_btn = None
        self._feedback_status_var = tk.StringVar(value="")
        self._feedback_category_var = tk.StringVar(value="bug")
        self._feedback_subject_var = tk.StringVar()
        self._feedback_message_text = None
        self._login_dialog: tk.Toplevel | None = None
        self._login_submit_btn = None
        self._google_btn = None
        self._login_status_label = None
        self._login_status_var = tk.StringVar(value="")
        self._user_info: dict | None = None
        self._overlay_eta_var = tk.StringVar(value="")
        self._row_states: dict[str, str] = {}
        self._completed_routes = 0
        self._run_started_at: float | None = None
        # v1.5.17 - ETA stabilization.  Lock per-unit duration at each
        # completion event; between events, count down from the locked
        # estimate.  Without this, mid-route the ETA *increased* because
        # `elapsed / completed` grew while `completed` stayed constant.
        self._eta_per_unit_seconds: float | None = None
        self._eta_locked_at_elapsed: float = 0.0
        self._eta_locked_at_completed: int = 0

        # Route checklist state
        self._current_row: str | None = None  # treeview iid of the running row
        self._done = 0
        self._total = 0
        self._current_step = 0
        self._log_visible = False

        self._apply_theme()
        self._build_ui()
        self._load_preferences()
        self._setup_logging()
        self._show_post_update_notice()
        self.root.bind_all("<Escape>", lambda *_: self._stop())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()
        self.root.after(3000, self._drain_feedback_queue_async)
        self.root.after(1500, self._check_auth_startup)
        # Check for updates silently in the background
        threading.Thread(target=self._bg_update_check, daemon=True).start()

    def _load_preferences(self):
        """Restore user settings from previous session."""
        prefs = _load_prefs()
        if not prefs:
            return
        for var_name, key in [
            ("mode_var", "mode"),
            ("speed_var", "speed"),
            ("route_var", "route"),
            ("airline_var", "airline"),
            ("limit_var", "limit"),
        ]:
            val = prefs.get(key)
            if val is not None:
                getattr(self, var_name).set(val)
        for var_name, key in [
            ("checkpoint_var", "checkpoint"),
            ("no_changes_var", "no_changes"),
            ("only_fd_var", "only_fd"),
            ("only_yq_var", "only_yq"),
        ]:
            val = prefs.get(key)
            if val is not None:
                getattr(self, var_name).set(val)

    def _save_preferences(self):
        """Persist current UI settings to disk."""
        _save_prefs({
            "mode": self.mode_var.get(),
            "speed": self.speed_var.get(),
            "route": self.route_var.get(),
            "airline": self.airline_var.get(),
            "limit": self.limit_var.get(),
            "checkpoint": self.checkpoint_var.get(),
            "no_changes": self.no_changes_var.get(),
            "only_fd": self.only_fd_var.get(),
            "only_yq": self.only_yq_var.get(),
        })

    def _on_close(self):
        """Handle window close: save prefs, then destroy."""
        self._save_preferences()
        self.root.destroy()

    # â”€â”€ Theme â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _apply_theme(self):
        style = ttk.Style(self.root)
        for t in ("vista", "xpnative", "winnative", "clam"):
            if t in style.theme_names():
                style.theme_use(t)
                break
        self.root.configure(bg="#f2f2f2")

        # Treeview row tag colours
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    # â”€â”€ UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_ui(self):
        # Title bar
        bar = tk.Frame(self.root, bg="#0f3758", pady=9)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="  TravelportAuto",
            bg="#0f3758",
            fg="white",
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")
        tk.Label(
            bar,
            text=f"  {self.VERSION}  ",
            bg="#0f3758",
            fg="#78b4d4",
            font=("Segoe UI", 10),
        ).pack(side="left")
        tk.Label(
            bar,
            text="Developed by Ihsan Kabir  ",
            bg="#0f3758",
            fg="#5a7f9a",
            font=("Segoe UI", 9),
        ).pack(side="right")
        # Update badge - hidden until a newer version is detected
        self._update_btn = tk.Button(
            bar,
            text="",
            bg="#e8a500",
            fg="#1a1a1a",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._show_update_dialog,
            padx=8,
            pady=2,
        )
        # Not packed yet - shown only when update is available

        # Body
        body = tk.Frame(self.root, bg="#f2f2f2")
        body.pack(fill="both", expand=True, padx=10, pady=8)

        # Scrollable left panel - wraps the controls in a Canvas so taller content
        # (e.g. Currency mode with Previous Rates + Output Path) stays reachable.
        left_container = tk.Frame(body, bg="#f2f2f2", width=290)
        left_container.pack(side="left", fill="y", padx=(0, 10))
        left_container.pack_propagate(False)

        left_canvas = tk.Canvas(
            left_container, bg="#f2f2f2", highlightthickness=0, borderwidth=0
        )
        left_scrollbar = ttk.Scrollbar(
            left_container, orient="vertical", command=left_canvas.yview
        )
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_scrollbar.pack(side="right", fill="y")

        left = tk.Frame(left_canvas, bg="#f2f2f2")
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_canvas_configure(event):
            # Keep inner frame width in sync with the canvas viewport.
            left_canvas.itemconfigure(left_window, width=event.width)

        def _on_left_inner_configure(_event):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _on_left_mousewheel(event):
            left_canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_left_wheel(_event):
            left_canvas.bind_all("<MouseWheel>", _on_left_mousewheel)

        def _unbind_left_wheel(_event):
            left_canvas.unbind_all("<MouseWheel>")

        left_canvas.bind("<Configure>", _on_left_canvas_configure)
        left.bind("<Configure>", _on_left_inner_configure)
        left_canvas.bind("<Enter>", _bind_left_wheel)
        left_canvas.bind("<Leave>", _unbind_left_wheel)

        self._build_left(left)

        right = tk.Frame(body, bg="#f2f2f2")
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        self._build_bottom()

    # â”€â”€ Left panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _section(self, parent, text):
        tk.Label(
            parent,
            text=text.upper(),
            bg="#f2f2f2",
            fg="#0f3758",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(10, 1))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 5))

    def _build_left(self, parent):
        self._left_parent = parent

        # â”€â”€ Group 1: What to Extract â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_extract = tk.Frame(parent, bg="#f2f2f2")
        self._section(g_extract, "What to Extract")
        self.mode_var = tk.StringVar(value="fare")
        for label, val in [
            ("Fares", "fare"),
            ("Baggage Allowance", "baggage"),
            ("Future Tax", "tax"),
            ("Penalties", "penalty"),
            ("Currency Rate", "currency"),
            ("Manual (paste GDS output)", "quickpaste"),
        ]:
            ttk.Radiobutton(
                g_extract, text=label, variable=self.mode_var, value=val
            ).pack(anchor="w", pady=1)
        tk.Label(
            g_extract,
            text="Manual: copy terminal output first,\nthen press Start",
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
            justify="left",
        ).pack(anchor="w")
        self.mode_var.trace_add("write", self._on_mode_change)

        # â”€â”€ Group 2: Speed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_speed = tk.Frame(parent, bg="#f2f2f2")
        self._section(g_speed, "Speed")
        self.speed_var = tk.StringVar(value="normal")
        for label, val in [
            ("Normal", "normal"),
            ("Fast", "fast"),
            ("Reliable (slower)", "safe"),
        ]:
            ttk.Radiobutton(
                g_speed, text=label, variable=self.speed_var, value=val
            ).pack(anchor="w", pady=1)

        # â”€â”€ Group 3: Filters (hidden in Currency) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_filters = tk.Frame(parent, bg="#f2f2f2")
        self._section(g_filters, "Filters")
        self._primary_filter_label_var = tk.StringVar(value="Route:")
        self._primary_filter_help_var = tk.StringVar(
            value="e.g. DAC-MCT or DAC-MCT,DAC-BKK  (blank = all)"
        )
        self._airline_help_var = tk.StringVar(
            value="e.g. BG or BG,BS,EK  (blank = all)"
        )
        tk.Label(
            g_filters,
            textvariable=self._primary_filter_label_var,
            bg="#f2f2f2",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        self.route_var = tk.StringVar()
        ttk.Entry(g_filters, textvariable=self.route_var).pack(fill="x")
        tk.Label(
            g_filters,
            textvariable=self._primary_filter_help_var,
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        ).pack(anchor="w")

        self._airline_label = tk.Label(
            g_filters, text="Airline:", bg="#f2f2f2", font=("Segoe UI", 9)
        )
        self._airline_label.pack(anchor="w", pady=(5, 0))
        self.airline_var = tk.StringVar()
        self._airline_entry = ttk.Entry(g_filters, textvariable=self.airline_var)
        self._airline_entry.pack(fill="x")
        self._airline_hint_label = tk.Label(
            g_filters,
            textvariable=self._airline_help_var,
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        )
        self._airline_hint_label.pack(anchor="w")

        tk.Label(
            g_filters, text="Limit (0 = run all):", bg="#f2f2f2", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(5, 0))
        self.limit_var = tk.StringVar(value="0")
        ttk.Entry(g_filters, textvariable=self.limit_var, width=8).pack(anchor="w")

        # â”€â”€ Group 4a: Options - core (always) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_options_core = tk.Frame(parent, bg="#f2f2f2")
        self._section(g_options_core, "Options")
        self.checkpoint_var = tk.BooleanVar(value=True)
        self.no_changes_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            g_options_core,
            text="Save progress (resume on interrupt)",
            variable=self.checkpoint_var,
        ).pack(anchor="w", pady=1)
        ttk.Checkbutton(
            g_options_core, text="Skip change report", variable=self.no_changes_var
        ).pack(anchor="w", pady=1)

        # â”€â”€ Group 4b: Options - only-flags (Fares mode only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_only_flags = tk.Frame(parent, bg="#f2f2f2")
        self.only_fd_var = tk.BooleanVar(value=False)
        self.only_yq_var = tk.BooleanVar(value=False)
        self.baggage_inline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            g_only_flags, text="Fares only (skip taxes)", variable=self.only_fd_var
        ).pack(anchor="w", pady=1)
        ttk.Checkbutton(
            g_only_flags, text="Taxes only (skip fares)", variable=self.only_yq_var
        ).pack(anchor="w", pady=1)
        ttk.Checkbutton(
            g_only_flags,
            text="Include baggage (BOOK+FQC)",
            variable=self.baggage_inline_var,
        ).pack(anchor="w", pady=1)

        # â”€â”€ Group 5: Compare against (hidden in Currency / Manual) â”€â”€â”€â”€â”€â”€

        # ── Group 4c: Baggage file (Fares + Baggage modes) ─────────────────
        g_baggage_file = tk.Frame(parent, bg="#f2f2f2")
        tk.Label(
            g_baggage_file,
            text="Baggage file (optional):",
            bg="#f2f2f2",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(6, 0))
        self.baggage_file_var = tk.StringVar()
        bag_row = tk.Frame(g_baggage_file, bg="#f2f2f2")
        bag_row.pack(fill="x")
        ttk.Entry(bag_row, textvariable=self.baggage_file_var).pack(
            side="left", fill="x", expand=True
        )
        self._baggage_browse_btn = ttk.Button(
            bag_row, text="Browse", width=7, command=self._browse_baggage_file
        )
        self._baggage_browse_btn.pack(side="left", padx=(4, 0))
        tk.Label(
            g_baggage_file,
            text="Leave blank to extract live  |  browse for saved baggage JSON",
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        ).pack(anchor="w")

        g_compare = tk.Frame(parent, bg="#f2f2f2")
        tk.Label(
            g_compare, text="Compare against:", bg="#f2f2f2", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(6, 0))
        self.compare_var = tk.StringVar()
        compare_row = tk.Frame(g_compare, bg="#f2f2f2")
        compare_row.pack(fill="x")
        ttk.Entry(compare_row, textvariable=self.compare_var).pack(
            side="left", fill="x", expand=True
        )
        self._compare_browse_btn = ttk.Button(
            compare_row, text="Browse", width=7, command=self._browse_compare_file
        )
        self._compare_browse_btn.pack(side="left", padx=(4, 0))
        tk.Label(
            g_compare,
            text="blank = previous run  |  date or browse for snapshot file",
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        ).pack(anchor="w")

        # â”€â”€ Group 6: Previous Rates (Currency mode only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_prev_rates = tk.Frame(parent, bg="#f2f2f2")
        tk.Label(
            g_prev_rates,
            text="Previous Rates File:",
            bg="#f2f2f2",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(6, 0))
        self._prev_rates_path = None
        self._prev_rates_date = None
        self._prev_rates_var = tk.StringVar(value="")
        prev_row = tk.Frame(g_prev_rates, bg="#f2f2f2")
        prev_row.pack(fill="x")
        ttk.Entry(prev_row, textvariable=self._prev_rates_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        self._prev_rates_browse_btn = ttk.Button(
            prev_row, text="Browse", width=7, command=self._browse_prev_rates
        )
        self._prev_rates_browse_btn.pack(side="left", padx=(4, 0))
        tk.Label(
            g_prev_rates,
            text="Optional - sets the Previous Date column (Currency Rate only).",
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        ).pack(anchor="w")

        # â”€â”€ Group 7: Output Path (always) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        g_output = tk.Frame(parent, bg="#f2f2f2")
        self._section(g_output, "Output Path")
        tk.Label(
            g_output,
            text="Leave blank - saved automatically",
            bg="#f2f2f2",
            fg="#999",
            font=("Segoe UI", 7, "italic"),
        ).pack(anchor="w")
        out_row = tk.Frame(g_output, bg="#f2f2f2")
        out_row.pack(fill="x")
        self.output_var = tk.StringVar()
        ttk.Entry(out_row, textvariable=self.output_var).pack(
            side="left", fill="x", expand=True
        )
        self._output_browse_btn = ttk.Button(
            out_row, text="...", width=3, command=self._browse
        )
        self._output_browse_btn.pack(side="left", padx=(2, 0))

        # Ordered list drives mode-aware show/hide.
        self._left_sections = [
            (g_extract, lambda m: True),
            (g_speed, lambda m: True),
            (g_filters, lambda m: m not in {"currency", "baggage"}),
            (g_options_core, lambda m: m != "baggage"),
            (g_only_flags, lambda m: m == "fare"),
            (g_baggage_file, lambda m: m in {"fare", "baggage"}),
            (g_compare, lambda m: m in {"fare", "tax", "penalty"}),
            (g_prev_rates, lambda m: m == "currency"),
            (g_output, lambda m: True),
        ]

        # Tooltips (B.7) - attached after buttons exist.
        _Tooltip(
            self._compare_browse_btn,
            "Browse for a JSON / CSV / XLSX snapshot to diff against.",
        )
        _Tooltip(
            self._prev_rates_browse_btn,
            "Browse for JSON / CSV / XLSX from a prior currency run.",
        )
        _Tooltip(
            self._baggage_browse_btn,
            "Browse for a saved baggage JSON from a prior baggage-only run.",
        )
        _Tooltip(
            self._output_browse_btn,
            "Leave empty to auto-name under data/reports/.",
        )

        self._apply_mode_visibility()

    # â”€â”€ Right panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_right(self, parent):
        # Step indicator
        step_frame = tk.Frame(parent, bg="#f2f2f2")
        step_frame.pack(fill="x", pady=(0, 8))

        self._step_labels: list[tk.Label] = []
        for i, name in enumerate(self.STEPS):
            lbl = tk.Label(
                step_frame, text=name, bg="#f2f2f2", font=("Segoe UI", 9), fg="#aaa"
            )
            lbl.pack(side="left")
            self._step_labels.append(lbl)
            if i < len(self.STEPS) - 1:
                tk.Label(
                    step_frame,
                    text="  ->  ",
                    bg="#f2f2f2",
                    fg="#ccc",
                    font=("Segoe UI", 9),
                ).pack(side="left")

        # Progress bar + counter
        prog_row = tk.Frame(parent, bg="#f2f2f2")
        prog_row.pack(fill="x", pady=(0, 4))
        self.progress = ttk.Progressbar(prog_row, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.counter_label = tk.Label(
            prog_row,
            text="",
            bg="#f2f2f2",
            fg="#0f3758",
            font=("Segoe UI", 9, "bold"),
            width=28,
            anchor="e",
        )
        self.counter_label.pack(side="left", padx=(6, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(2, 6))

        # Route checklist (Treeview)
        tree_frame = tk.Frame(parent, bg="#f2f2f2")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("status", "airline", "route"),
            show="headings",
            selectmode="none",
        )
        self.tree.heading("status", text="")
        self.tree.heading("airline", text="Airline")
        self.tree.heading("route", text="Route")
        self.tree.column("status", width=36, stretch=False, anchor="center")
        self.tree.column("airline", width=110, stretch=False)
        self.tree.column("route", width=200, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # Row colour tags
        self.tree.tag_configure("pending", foreground="#aaa")
        self.tree.tag_configure(
            "running", foreground="#0f6ec4", font=("Segoe UI", 10, "bold")
        )
        self.tree.tag_configure("done", foreground="#1d8a63")
        self.tree.tag_configure("failed", foreground="#b73632")

        # Collapsible technical log
        self._build_log_toggle(parent)

    def _build_log_toggle(self, parent):
        toggle_row = tk.Frame(parent, bg="#f2f2f2")
        toggle_row.pack(fill="x", pady=(6, 0))

        self._toggle_btn = tk.Button(
            toggle_row,
            text="Show technical log",
            bg="#f2f2f2",
            fg="#777",
            font=("Segoe UI", 8),
            relief="flat",
            cursor="hand2",
            command=self._toggle_log,
            anchor="w",
        )
        self._toggle_btn.pack(side="left")

        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            font=("Consolas", 8),
            bg="#1e1e1e",
            fg="#d4d4d4",
            relief="flat",
            state="disabled",
            height=0,
        )
        self.log_text.pack(fill="x")
        self.log_text.tag_config("ERROR", foreground="#f44747")
        self.log_text.tag_config("WARNING", foreground="#ffcc02")
        self.log_text.tag_config("SUCCESS", foreground="#4ec9b0")

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        self.log_text.configure(height=8 if self._log_visible else 0)
        self._toggle_btn.configure(
            text=(
                "â–¼  Hide technical log"
                if self._log_visible
                else "Show technical log"
            )
        )

    # â”€â”€ Bottom bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_bottom(self):
        bar = tk.Frame(self.root, bg="#dde3e8", pady=8)
        bar.pack(fill="x", side="bottom")

        self.start_btn = ttk.Button(
            bar, text="Start", command=self._start, width=14
        )
        self.start_btn.pack(side="left", padx=(12, 4))

        self.stop_btn = ttk.Button(
            bar, text="Stop", command=self._stop, width=14, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=4)

        self.open_btn = ttk.Button(
            bar,
            text="Open Report",
            command=self._open_report,
            width=16,
            state="disabled",
        )
        self.open_btn.pack(side="left", padx=4)

        self.feedback_btn = ttk.Button(
            bar, text="Feedback", command=self._open_feedback_dialog, width=14
        )
        self.feedback_btn.pack(side="left", padx=4)

        self.account_btn = ttk.Button(
            bar, text="Sign In", command=self._on_account_btn, width=12
        )
        self.account_btn.pack(side="left", padx=4)

        self.recalibrate_btn = ttk.Button(
            bar, text="Recalibrate", command=self._recalibrate_display, width=15
        )
        self.recalibrate_btn.pack(side="left", padx=4)
        _Tooltip(
            self.recalibrate_btn,
            "Reset click calibration for this display.\n"
            "Run this after changing screen resolution or DPI scaling.",
        )

        self.reset_dclick_btn = ttk.Button(
            bar,
            text="Reset D-click",
            command=self._reset_d_click_calibration,
            width=16,
        )
        self.reset_dclick_btn.pack(side="left", padx=4)
        _Tooltip(
            self.reset_dclick_btn,
            "Drop the saved D-click offset for this PC.\n"
            "The next D-click will pause for 5 seconds - click the\n"
            "D button on the FS screen during that window so the new\n"
            "position is learned. Use this if D-click keeps landing\n"
            "on the wrong glyph (e.g. BOOK instead of D).",
        )

        self.time_calc_btn = ttk.Button(
            bar, text="Time Calc", command=self._open_time_calculator, width=12
        )
        self.time_calc_btn.pack(side="left", padx=4)
        _Tooltip(
            self.time_calc_btn,
            "Calculate local arrival time from origin/destination\n"
            "UTC offsets, departure time, and flight duration.",
        )

        self._user_label = tk.Label(
            bar, text="", bg="#dde3e8", fg="#357a38", font=("Segoe UI", 9)
        )
        self._user_label.pack(side="right", padx=8)

        self.status_label = tk.Label(
            bar, text="Ready", bg="#dde3e8", fg="#555", font=("Segoe UI", 9)
        )
        self.status_label.pack(side="right", padx=12)

    # â”€â”€ Logging setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _setup_logging(self):
        handler = _QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

        # main.py logs to the "travelport" named logger and adds its own
        # StreamHandler to it.  Without this, each message propagates to the
        # root QueueHandler AND fires the StreamHandler â†’ stdout â†’ queue,
        # producing duplicate lines.  Turning off propagation means the named
        # logger's own handlers run; the root QueueHandler catches everything
        # else (e.g. third-party library logs).
        travelport_logger = logging.getLogger("travelport")
        travelport_logger.propagate = False
        travelport_logger.addHandler(handler)

        stream = _StdoutRedirect(self.log_queue)
        sys.stdout = stream
        sys.stderr = stream

    def _drain_feedback_queue_async(self):
        """Drain the offline feedback queue in a background thread at startup."""
        def _worker():
            try:
                import urllib.request

                from agent_config import load_agent_config
                from feedback_queue import drain_feedback_queue

                agent = load_agent_config()

                def _raw_submit(payload):
                    body = __import__("json").dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        f"{agent.api_base_url.rstrip('/')}/feedback",
                        data=body,
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    if agent.device_token:
                        req.add_header("Authorization", f"Bearer {agent.device_token}")
                    urllib.request.urlopen(req, timeout=15)

                drain_feedback_queue(_raw_submit)
            except Exception:
                pass  # Drain is best-effort; never surface errors at startup

        threading.Thread(target=_worker, daemon=True).start()

    def _show_post_update_notice(self):
        notice = _build_update_notice(self.VERSION, _read_update_state())
        if notice:
            self.root.after(
                250,
                lambda: messagebox.showwarning(
                    notice["title"],
                    notice["message"],
                ),
            )
        elif _read_update_state():
            _clear_update_state()

    # â”€â”€ Queue polling (main thread) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _poll(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._handle_log(payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "feedback_done":
                    self._on_feedback_done(payload)
                elif kind == "auth_done":
                    self._on_auth_done(payload)
                elif kind == "auth_status":
                    if self._login_status_label:
                        self._login_status_label.configure(fg="#2980b9")
                    self._login_status_var.set(payload)
                elif kind == "update_available":
                    self._on_update_available(payload)
                elif kind == "update_restart":
                    self._on_update_restart()
                elif kind == "update_open_browser":
                    import webbrowser

                    webbrowser.open(payload)
        except queue.Empty:
            pass
        self._refresh_eta()
        self.root.after(150, self._poll)

    # â”€â”€ Log parsing â†’ UI updates â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _handle_log(self, text: str):
        """Parse a log line and update the step indicator + route checklist."""
        tl = text.lower()

        # â”€â”€ Step detection â”€â”€
        if re.search(r"\[1/4\].*load|loading config", tl):
            self._set_step(1)
        elif re.search(r"connecting to smart|\[2/4\].*auto", tl):
            self._set_step(2)
        elif re.search(r"\[4/4\].*generat|generating excel", tl):
            self._set_step(4)

        # â”€â”€ Route command line:  [45/85] FDDACMCT/BG â”€â”€
        m_cmd = re.search(r"\[(\d+)/(\d+)\]\s+(FD[A-Z0-9]+/[A-Z0-9]+)", text)
        # â”€â”€ Currency progress:  [3/17] OMR -> BDT: 320.64   (success)
        # â”€â”€ Currency failure:   [3/17] Could not parse rate for OMR
        m_fzs = re.search(
            r"\[(\d+)/(\d+)\]\s+(?:[A-Z]{3}\s*->\s*[A-Z]{3}|Could not parse)",
            text,
        )
        # â”€â”€ FZS pre-scan banner sets the total up-front so ETA has a denominator
        # even before the first currency completes.
        m_fzs_total = re.search(
            r"Extracting FZS rates for (\d+) currencies", text
        )
        # â”€â”€ Tax progress: [N/M] Airport: KUL (Kuala Lumpur) -> FTAX-MY
        # Each line marks the START of a new airport, so by the time we see
        # line N, exactly N-1 airports are completed.  Without this the ETA
        # overlay stays stuck on "calculating..." for the whole tax run.
        m_tax = re.search(
            r"\[(\d+)/(\d+)\]\s+Airport:\s+[A-Z]{3}", text
        )
        if m_cmd:
            idx = int(m_cmd.group(1))
            total = int(m_cmd.group(2))
            cmd = m_cmd.group(3)
            self._done = idx
            self._total = total
            self._set_step(3)
            self._add_route_row(cmd, idx)
            self._update_counter()

        elif m_fzs:
            idx = int(m_fzs.group(1))
            total = int(m_fzs.group(2))
            self._done = idx
            self._total = total
            self._completed_routes = idx
            self._capture_eta_progress_tick()
            self._set_step(3)

            # Insert a row per currency so the tree fills up with ticks.
            m_succ = re.search(
                r"\[\d+/\d+\]\s+([A-Z]{3})\s*->\s*[A-Z]{3}:\s*([\d.]+)", text
            )
            m_fail = re.search(
                r"\[\d+/\d+\]\s+Could not parse rate for ([A-Z]{3})", text
            )
            if m_succ:
                self._add_currency_row(idx, m_succ.group(1), m_succ.group(2), "done")
            elif m_fail:
                self._add_currency_row(idx, m_fail.group(1), "-", "failed")

            self._update_counter()
            self._refresh_eta()

        elif m_fzs_total:
            total = int(m_fzs_total.group(1))
            if total > 0:
                self._total = total
                self._set_step(3)
                self._update_counter()

        elif m_tax:
            idx = int(m_tax.group(1))
            total = int(m_tax.group(2))
            self._done = idx
            self._total = total
            # Seeing airport N's start means N-1 are completed (the previous
            # ones).  Don't go negative when N=1.
            self._completed_routes = max(0, idx - 1)
            self._capture_eta_progress_tick()
            self._set_step(3)
            self._update_counter()
            self._refresh_eta()

        # â”€â”€ Route succeeded â”€â”€
        elif re.search(
            r"âœ“.*fare data|âœ“.*tax.*complet|âœ“.*completed|fare data captured", tl
        ):
            self._mark_row("done")

        # â”€â”€ Route failed â”€â”€
        elif re.search(r"failed after|âœ— failed|âœ—.*failed", tl):
            self._mark_row("failed")

        # â”€â”€ Append to hidden technical log â”€â”€
        self._append_raw(text)

    def _set_step(self, n: int):
        if n <= self._current_step:
            return
        self._current_step = n
        for i, lbl in enumerate(self._step_labels):
            step_num = i + 1
            if step_num < n:
                lbl.configure(
                    text=f"[x] {self.STEPS[i]}", fg="#1d8a63", font=("Segoe UI", 9)
                )
            elif step_num == n:
                lbl.configure(
                    text=self.STEPS[i], fg="#0f3758", font=("Segoe UI", 9, "bold")
                )
            else:
                lbl.configure(text=self.STEPS[i], fg="#aaa", font=("Segoe UI", 9))

    def _add_route_row(self, cmd_str: str, idx: int):
        airline, route = _parse_cmd(cmd_str)
        iid = f"row_{idx}"
        # If already exists (e.g. resume), just update it
        if self.tree.exists(iid):
            self.tree.item(iid, values=("âŸ³", airline, route), tags=("running",))
        else:
            self.tree.insert(
                "", "end", iid=iid, values=("âŸ³", airline, route), tags=("running",)
            )
        self._row_states[iid] = "running"
        self.tree.see(iid)
        self._current_row = iid

    def _add_currency_row(self, idx: int, code: str, rate_str: str, state: str):
        """Insert (or update) a currency row and mark it done/failed in one step.

        Currency runs emit one log line per currency when the rate is finalised, so
        each line is a completed event - no separate "running â†’ done" transition.
        """
        iid = f"row_{idx}"
        icon = "âœ“" if state == "done" else "âœ—"
        detail = (
            f"\u2192 BDT: {rate_str}" if state == "done" else "failed to parse"
        )
        values = (icon, code, detail)
        if self.tree.exists(iid):
            self.tree.item(iid, values=values, tags=(state,))
        else:
            self.tree.insert("", "end", iid=iid, values=values, tags=(state,))
        self._row_states[iid] = state
        self.tree.see(iid)
        self._current_row = iid

    def _mark_row(self, state: str):
        if not self._current_row or not self.tree.exists(self._current_row):
            return
        icon = "âœ“" if state == "done" else "âœ—"
        previous_state = self._row_states.get(self._current_row)
        vals = self.tree.item(self._current_row, "values")
        self.tree.item(
            self._current_row, values=(icon, vals[1], vals[2]), tags=(state,)
        )
        self._row_states[self._current_row] = state
        if previous_state not in {"done", "failed"} and state in {"done", "failed"}:
            self._completed_routes += 1
            self._capture_eta_progress_tick()
            self._refresh_eta()
        self._update_counter()

    def _update_counter(self):
        if not self._total:
            self.counter_label.configure(text="")
            return
        pct = int(self._done / self._total * 100)
        done = sum(1 for s in self._row_states.values() if s == "done")
        failed = sum(1 for s in self._row_states.values() if s == "failed")
        running = sum(1 for s in self._row_states.values() if s == "running")
        self.counter_label.configure(
            text=(
                f"\u2713 {done}  \u2717 {failed}  \u27f3 {running}   "
                f"({self._done}/{self._total})"
            )
        )
        self.progress.configure(mode="determinate", value=pct)

    def _capture_eta_progress_tick(self) -> None:
        """v1.5.17 - call whenever _completed_routes changes.  Locks the
        per-unit time estimate at this completion event so _refresh_eta
        can compute a smoothly-counting-down ETA between events instead
        of an increasing one (the old `elapsed/completed` recompute drifted
        upward whenever a single route was taking a long time)."""
        if not self._run_started_at or self._completed_routes <= 0:
            return
        elapsed = time.monotonic() - self._run_started_at
        self._eta_per_unit_seconds = elapsed / max(1, self._completed_routes)
        self._eta_locked_at_elapsed = elapsed
        self._eta_locked_at_completed = self._completed_routes

    def _refresh_eta(self):
        if self.stop_event.is_set():
            self._overlay_eta_var.set("ETA: stopping...")
            return

        if (
            not self._run_started_at
            or not self._run_thread
            or not self._run_thread.is_alive()
        ):
            self._overlay_eta_var.set("")
            return

        if self._total <= 0:
            self._overlay_eta_var.set("ETA: waiting for route count...")
            return

        if self._completed_routes <= 0 or self._eta_per_unit_seconds is None:
            self._overlay_eta_var.set("ETA: calculating after first route...")
            return

        # Use the per-unit duration captured at the last completion tick.
        # Between ticks, time elapses but the estimate is stable; subtract
        # time-since-tick so the displayed ETA counts down smoothly until
        # the next route finishes.
        units_remaining = max(0, self._total - self._completed_routes)
        estimated_remaining_at_lock = (
            self._eta_per_unit_seconds * units_remaining
        )
        elapsed_since_lock = (
            time.monotonic() - self._run_started_at - self._eta_locked_at_elapsed
        )
        remaining_seconds = max(
            0, int(round(estimated_remaining_at_lock - elapsed_since_lock))
        )

        if units_remaining == 0:
            self._overlay_eta_var.set("ETA: finishing current step...")
        elif remaining_seconds <= 0:
            self._overlay_eta_var.set("ETA: finishing current step...")
        else:
            self._overlay_eta_var.set(
                f"ETA: about {_format_eta_seconds(remaining_seconds)} left"
            )

    def _append_raw(self, text: str):
        self.log_text.configure(state="normal")
        tl = text.lower()
        tag = "INFO"
        if "error" in tl or "failed" in tl:
            tag = "ERROR"
        elif "warning" in tl:
            tag = "WARNING"
        elif "âœ“" in text or "success" in tl:
            tag = "SUCCESS"
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # â”€â”€ Mode change handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _on_mode_change(self, *_):
        if self.mode_var.get() == "quickpaste":
            self.no_changes_var.set(True)
        self._apply_mode_visibility()

    def _apply_mode_visibility(self):
        """Show/hide left-panel groups based on current mode; rename tree headings."""
        mode = self.mode_var.get()
        for group, _pred in self._left_sections:
            group.pack_forget()
        for group, pred in self._left_sections:
            if pred(mode):
                group.pack(fill="x")
        self._update_filter_controls(mode)
        self._update_tree_headings(mode)

    def _update_filter_controls(self, mode: str):
        """Rename the shared filter field and disable airline input in tax mode."""
        if mode == "tax":
            self._primary_filter_label_var.set("Airport:")
            self._primary_filter_help_var.set(
                "Code, name, country or route (origin used), e.g. DAC, Dhaka, BD or DAC-MCT  (blank = all)"
            )
            self._airline_help_var.set("Ignored in Future Tax mode")
            self._airline_label.configure(fg="#999")
            self._airline_hint_label.configure(fg="#999")
            self._airline_entry.configure(state="disabled")
        else:
            self._primary_filter_label_var.set("Route:")
            self._primary_filter_help_var.set(
                "e.g. DAC-MCT or DAC-MCT,DAC-BKK  (blank = configured list)"
            )
            self._airline_help_var.set("e.g. BG or BG,BS,EK  (blank = all)")
            self._airline_label.configure(fg="#000")
            self._airline_hint_label.configure(fg="#999")
            self._airline_entry.configure(state="normal")

    def _update_tree_headings(self, mode: str):
        """Rename the tree's two visible columns to match the current mode."""
        if not hasattr(self, "tree"):
            return
        if mode == "currency":
            self.tree.heading("airline", text="Currency")
            self.tree.heading("route", text="Rate \u2192 BDT")
        elif mode == "tax":
            self.tree.heading("airline", text="Airline")
            self.tree.heading("route", text="Airport")
        elif mode == "baggage":
            self.tree.heading("airline", text="Airline")
            self.tree.heading("route", text="Route")
        else:  # fare, penalty, quickpaste
            self.tree.heading("airline", text="Airline")
            self.tree.heading("route", text="Route")

    # â”€â”€ Quick-paste wizard (GUI-native, step-by-step clipboard collection) â”€â”€â”€â”€

    def _run_quickpaste_wizard(self) -> dict | None:
        """Show step-by-step dialogs to collect GDS output from clipboard.

        Returns a dict with keys ``commands``, ``raw_texts``, ``raw_fs_texts``
        ready to be attached to the args namespace, or *None* if the user
        cancels at any point.
        """
        from tkinter import simpledialog, messagebox as _mb

        # Step 1 - ask for command string
        cmds_str = simpledialog.askstring(
            "Manual Paste - Step 1 of ...",
            "Enter one or more GDS commands, separated by commas:\n\n"
            "Example:  FDDACMCT/BG,  FDDACDOH/QR",
            parent=self.root,
        )
        if not cmds_str or not cmds_str.strip():
            return None

        # Parse commands (import from main without triggering full module init)
        try:
            from main import parse_command
        except Exception as exc:
            _mb.showerror("Error", f"Could not load parser: {exc}", parent=self.root)
            return None

        raw = [c.strip().upper() for c in cmds_str.split(",") if c.strip()]
        commands = [parse_command(c) for c in raw]
        commands = [c for c in commands if c]
        if not commands:
            _mb.showerror(
                "Invalid Commands",
                "No valid commands recognised.\n\n"
                "Commands must start with FD, e.g.  FDDACMCT/BG",
                parent=self.root,
            )
            return None

        total_steps = 1 + len(commands) * 2
        raw_texts: dict = {}
        raw_fs_texts: dict = {}

        for i, cmd in enumerate(commands):
            airline = cmd["airline"]
            route = cmd["route"]

            # FD step
            step = 2 + i * 2
            proceed = _mb.askokcancel(
                f"Manual Paste - Step {step}/{total_steps}",
                f"Command {i + 1}/{len(commands)}:  {airline}  {route}\n\n"
                "Switch to Travelport Smartpoint and copy the\n"
                "FD (Fare Display) output to your clipboard,\n"
                "then click OK.",
                parent=self.root,
            )
            if not proceed:
                return None

            try:
                from clipboard_util import clipboard_paste

                fd_text = clipboard_paste()
            except Exception:
                fd_text = ""

            # FS step
            step += 1
            proceed = _mb.askokcancel(
                f"Manual Paste - Step {step}/{total_steps}",
                f"Command {i + 1}/{len(commands)}:  {airline}  {route}\n\n"
                "Now copy the FS (Tax Summary) output to your clipboard,\n"
                "then click OK.\n\n"
                "(Click Cancel to skip tax data for this route.)",
                parent=self.root,
            )
            fs_text = ""
            if proceed:
                try:
                    fs_text = clipboard_paste()
                except Exception:
                    fs_text = ""

            file_key = f"{airline}_{route}"
            raw_texts[file_key] = fd_text
            raw_fs_texts[file_key] = fs_text

        return {
            "commands": commands,
            "raw_texts": raw_texts,
            "raw_fs_texts": raw_fs_texts,
        }

    # â”€â”€ Auto-update â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _bg_update_check(self):
        """Run in background thread; posts result to queue."""
        info = _check_for_update(self.VERSION)
        if info:
            self.log_queue.put(("update_available", info))

    def _on_update_available(self, info: dict):
        self._update_info = info
        self._update_btn.configure(text=f"  Update {info['version']}  ")
        self._update_btn.pack(side="right", padx=(0, 8))

    def _show_update_dialog(self):
        info = self._update_info
        if not info:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Update Available - {info['version']}")
        dlg.geometry("520x460")
        dlg.minsize(480, 420)
        dlg.resizable(True, True)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#f2f2f2")

        body = tk.Frame(dlg, bg="#f2f2f2", padx=20, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text=f"TravelportAuto {info['version']} is available",
            bg="#f2f2f2",
            fg="#0f3758",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text=f"You are on {self.VERSION}",
            bg="#f2f2f2",
            fg="#888",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 12))

        tk.Label(
            body, text="Release notes:", bg="#f2f2f2", font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")
        notes_box = scrolledtext.ScrolledText(
            body, wrap="word", font=("Segoe UI", 9), height=10, state="normal"
        )
        notes_box.insert("end", info.get("notes") or "(no release notes)")
        notes_box.configure(state="disabled")
        notes_box.pack(fill="both", expand=True, pady=(4, 12))

        progress_var = tk.StringVar(value="")
        tk.Label(
            body,
            textvariable=progress_var,
            bg="#f2f2f2",
            fg="#555",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 6))

        btn_row = tk.Frame(body, bg="#f2f2f2")
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="right")
        update_btn = ttk.Button(
            btn_row,
            text="Download & Update",
            command=lambda: self._start_update(info, dlg, progress_var, update_btn),
        )
        update_btn.pack(side="right", padx=(0, 6))

    def _start_update(self, info, dlg, progress_var, btn):
        if not info.get("exe_url") and not info.get("zip_url"):
            messagebox.showerror("Update Error", "No download link was found for this release.")
            return
        btn.configure(state="disabled")
        progress_var.set("Downloading...")
        if info.get("exe_url"):
            threading.Thread(
                target=self._download_and_replace,
                args=(info, dlg, progress_var),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._download_and_replace_zip,
                args=(info, dlg, progress_var),
                daemon=True,
            ).start()

    def _download_and_replace(self, info, dlg, progress_var):
        """Download new exe, verify SHA256 hash, write an updater batch, then restart."""
        try:
            # Work out paths
            if getattr(sys, "frozen", False):
                current_exe = sys.executable
            else:
                # Dev mode - just open the releases page
                self.log_queue.put(("update_open_browser", info.get("exe_url", "")))
                return

            folder = os.path.dirname(current_exe)
            new_exe = os.path.join(folder, "TravelportAuto_update.exe")
            download_exe = os.path.join(folder, "TravelportAuto_update.download")
            target_version = str(info.get("version") or "").strip()

            _write_update_state(
                "pending",
                target_version,
                "The updater downloaded a new exe and is trying to replace the running application.",
            )
            try:
                os.remove(_UPDATE_LOG_FILE)
            except OSError:
                pass
            try:
                os.remove(download_exe)
            except OSError:
                pass

            # Download with simple progress reporting
            def _reporthook(count, block_size, total):
                if total > 0:
                    pct = min(int(count * block_size * 100 / total), 100)
                    progress_var.set(f"Downloading... {pct}%")

            urllib.request.urlretrieve(info["exe_url"], download_exe, _reporthook)
            os.replace(download_exe, new_exe)

            # IMP-10: Verify SHA256 hash if found in release notes
            import hashlib, re as _re

            notes = info.get("notes", "") or ""
            hash_match = _re.search(
                r'(?:sha256|SHA256)[:\s]+([0-9a-fA-F]{64})', notes
            )
            if hash_match:
                expected_hash = hash_match.group(1).lower()
                progress_var.set("Verifying integrity...")
                sha256 = hashlib.sha256()
                with open(new_exe, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)
                actual_hash = sha256.hexdigest()
                if actual_hash != expected_hash:
                    os.remove(new_exe)
                    _write_update_state(
                        "failed",
                        target_version,
                        "Downloaded file failed SHA256 verification and was removed.",
                    )
                    progress_var.set(
                        f"Error: SHA256 mismatch!\n"
                        f"Expected: {expected_hash[:16]}...\n"
                        f"Got:      {actual_hash[:16]}..."
                    )
                    return

            progress_var.set("Installing...")

            # Write batch updater - runs after this process exits.
            # 5-second wait gives the old PyInstaller process time to fully
            # clean up its _MEI* temp folder before we start the new exe.
            # We also delete any leftover _MEI* dirs ourselves to avoid the
            # "Failed to load Python DLL" error on stale extractions.
            bat = os.path.join(folder, "_tpa_update.bat")
            with open(bat, "w", encoding="utf-8") as f:
                f.write(
                    _build_updater_script(
                        current_exe=current_exe,
                        new_exe=new_exe,
                        state_file=_UPDATE_STATE_FILE,
                        log_file=_UPDATE_LOG_FILE,
                        target_version=target_version,
                    )
                )

            import subprocess

            subprocess.Popen(
                ["cmd", "/c", bat],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            self.log_queue.put(("update_restart", None))

        except Exception as exc:
            _write_update_state(
                "failed",
                str(info.get("version") or "").strip(),
                f"Updater error: {exc}",
            )
            progress_var.set(f"Error: {exc}")

    def _download_and_replace_zip(self, info, dlg, progress_var):
        """Download update zip, extract it to a staging folder, then run a folder-swap batch."""
        import zipfile as _zipfile

        try:
            if not getattr(sys, "frozen", False):
                import webbrowser

                self.log_queue.put(("update_open_browser", info.get("release_url", "")))
                return

            target_version = str(info.get("version") or "").strip()
            appdata_dir = os.environ.get("APPDATA", os.path.dirname(sys.executable))
            tpa_appdata = os.path.join(appdata_dir, "TravelportAuto")
            os.makedirs(tpa_appdata, exist_ok=True)
            zip_path = os.path.join(tpa_appdata, "TravelportAuto_update.zip")
            staging_root = os.path.join(tpa_appdata, "_update_staging")

            shutil.rmtree(staging_root, ignore_errors=True)
            try:
                os.remove(zip_path)
            except OSError:
                pass

            _write_update_state("pending", target_version, "Downloading update zip...")
            try:
                os.remove(_UPDATE_LOG_FILE)
            except OSError:
                pass

            def _reporthook(count, block_size, total):
                if total > 0:
                    pct = min(int(count * block_size * 100 / total), 100)
                    progress_var.set(f"Downloading... {pct}%")

            urllib.request.urlretrieve(info["zip_url"], zip_path, _reporthook)
            progress_var.set("Extracting...")

            os.makedirs(staging_root, exist_ok=True)
            with _zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(staging_root)
            os.remove(zip_path)

            # Find the directory inside the staging area that contains TravelportAuto.exe.
            staging_app_folder = staging_root
            for dirpath, _dirs, files in os.walk(staging_root):
                if any(f.lower() == "travelportauto.exe" for f in files):
                    staging_app_folder = dirpath
                    break

            progress_var.set("Installing...")
            current_exe = sys.executable
            install_folder = os.path.dirname(current_exe)

            bat = os.path.join(install_folder, "_tpa_update.bat")
            with open(bat, "w", encoding="utf-8") as f:
                f.write(
                    _build_folder_updater_script(
                        current_exe=current_exe,
                        staging_folder=staging_app_folder,
                        state_file=_UPDATE_STATE_FILE,
                        log_file=_UPDATE_LOG_FILE,
                        target_version=target_version,
                    )
                )

            import subprocess

            subprocess.Popen(
                ["cmd", "/c", bat],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            self.log_queue.put(("update_restart", None))

        except Exception as exc:
            _write_update_state(
                "failed",
                str(info.get("version") or "").strip(),
                f"Updater error: {exc}",
            )
            progress_var.set(f"Error: {exc}")

    def _on_update_restart(self):
        self.root.destroy()

    # â”€â”€ Button actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _browse(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="Save report as...",
        )
        if path:
            self.output_var.set(path)

    def _start(self):
        if self._run_thread and self._run_thread.is_alive():
            return
        self.stop_event.clear()
        self._last_report = None
        self._run_started_at = time.monotonic()
        self._overlay_eta_var.set("ETA: calculating after first route...")
        self._row_states.clear()
        # Reset the ETA stabilizer for the new run.
        self._eta_per_unit_seconds = None
        self._eta_locked_at_elapsed = 0.0
        self._eta_locked_at_completed = 0
        self._completed_routes = 0
        self._done = 0
        self._total = 0
        self._current_row = None
        self._current_step = 0

        # Clear checklist
        for row in self.tree.get_children():
            self.tree.delete(row)
        # Reset step labels
        for lbl in self._step_labels:
            lbl.configure(fg="#aaa", font=("Segoe UI", 9))
        # Clear raw log
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        self.counter_label.configure(text="")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.status_label.configure(text="Starting...", fg="#0f3758")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        args = self._build_args()

        # For manual paste mode, collect clipboard data now (in the main thread)
        # before handing off to the worker, so we never touch sys.stdin.
        if args.quick_paste:
            qp_data = self._run_quickpaste_wizard()
            if qp_data is None:
                # User cancelled - restore buttons and bail out
                self._run_started_at = None
                self._overlay_eta_var.set("")
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                self.progress.stop()
                self.status_label.configure(text="Ready", fg="#555")
                return
            args._quick_paste_data = qp_data

        self._run_thread = threading.Thread(
            target=self._worker, args=(args,), daemon=True
        )
        self._run_thread.start()
        # In auto mode, minimize the main window and show a small always-on-top
        # stop overlay so pyautogui can reach Smartpoint, while ESC / Stop
        # remain accessible to the user.
        if args.auto:
            self.root.after(600, self._show_stop_overlay)

    def _stop(self):
        if not self._run_thread or not self._run_thread.is_alive():
            return
        self.stop_event.set()
        self._overlay_eta_var.set("ETA: stopping...")
        self._hide_stop_overlay()
        self.status_label.configure(text="Stopping...", fg="#b73632")
        self.stop_btn.configure(state="disabled")

    def _reset_d_click_calibration(self):
        """Drop the saved D-click offset so the next D-click runs the 5s
        manual-learning window.  Used when the saved offset is landing on
        the wrong glyph on this PC (e.g. BOOK instead of D)."""
        try:
            import calibration as _cal_mod

            cal = _cal_mod.load_calibration()
            current = _cal_mod.get_d_click_offset(cal)
            if current is None:
                messagebox.showinfo(
                    "Reset D-click calibration",
                    "No saved D-click offset to reset on this PC.\n\n"
                    "The next D-click will already use the 5-second manual "
                    "learning window.",
                )
                return
            cal = _cal_mod.clear_d_click_offset(cal)
            _cal_mod.save_calibration(cal)
            messagebox.showinfo(
                "Reset D-click calibration",
                f"Saved D-click offset {current} cleared.\n\n"
                "The next D-click will pause for 5 seconds - click the D "
                "button on the FS screen during that window and the new "
                "position will be learned and saved for this PC.",
            )
        except Exception as exc:
            messagebox.showerror(
                "Reset D-click calibration",
                f"Could not reset D-click calibration:\n\n{exc}",
            )

    def _browse_baggage_file(self):
        raw_dir = os.path.join("data", "raw")
        if not os.path.isdir(raw_dir):
            raw_dir = "."
        path = filedialog.askopenfilename(
            title="Select saved baggage JSON",
            initialdir=raw_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.baggage_file_var.set(path)

    def _browse_compare_file(self):
        archive_dir = os.path.join("data", "archive")
        if not os.path.isdir(archive_dir):
            archive_dir = "."
        path = filedialog.askopenfilename(
            title="Select snapshot file to compare against",
            initialdir=archive_dir,
            filetypes=[("JSON snapshots", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.compare_var.set(path)

    def _browse_prev_rates(self):
        from tkinter import simpledialog
        from datetime import date as _d, datetime as _dt, timedelta as _td

        path = filedialog.askopenfilename(
            title="Select previous rates file",
            filetypes=[
                ("Supported", "*.json *.csv *.xlsx *.xlsm"),
                ("JSON", "*.json"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xlsm"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        # Prefer the most recent archived snapshot date over calendar yesterday:
        # users typically import to match the latest prior run, not an arbitrary
        # "yesterday" that may have no data.
        default_date = (_d.today() - _td(days=1)).strftime("%Y-%m-%d")
        archive_dir = os.path.join("data", "archive", "currency")
        if os.path.isdir(archive_dir):
            dates: list[_d] = []
            for name in os.listdir(archive_dir):
                m = re.match(r"^rates_(\d{4}-\d{2}-\d{2})\.json$", name)
                if not m:
                    continue
                try:
                    dates.append(_dt.strptime(m.group(1), "%Y-%m-%d").date())
                except ValueError:
                    continue
            if dates:
                default_date = max(dates).strftime("%Y-%m-%d")
        date_str = simpledialog.askstring(
            "Effective date",
            "Which date does this file represent? (YYYY-MM-DD)",
            initialvalue=default_date,
            parent=self.root,
        )
        if not date_str:
            return
        self._prev_rates_path = path
        self._prev_rates_date = date_str.strip()
        self._prev_rates_var.set(
            f"{os.path.basename(path)}  ({self._prev_rates_date})"
        )

    def _open_report(self):
        if self._last_report and os.path.exists(self._last_report):
            os.startfile(self._last_report)
        else:
            messagebox.showinfo("No Report", "Report file not found.")

    def _recalibrate_display(self):
        """Reset click calibration to DPI-auto values for this display."""
        try:
            import calibration as _cal_mod
            data = _cal_mod.reset_calibration()
            lh = data["line_height"]
            dpi = data.get("dpi", "?")
            messagebox.showinfo(
                "Recalibrated",
                f"Click calibration reset.\n\nLine height: {lh} px  (DPI: {dpi})\n\n"
                "Restart the app for the new values to take effect on the next run.",
            )
        except Exception as exc:
            messagebox.showerror("Recalibrate Failed", str(exc))

    # â”€â”€ Account / login â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _refresh_user_label(self) -> None:
        if self._user_info:
            email = self._user_info.get("email", "")
            display = email or self._user_info.get("full_name", "Signed in")
            self._user_label.configure(text=f"â— {display}", fg="#357a38")
            self.account_btn.configure(text="Account")
        else:
            self._user_label.configure(text="")
            self.account_btn.configure(text="Sign In")

    def _on_account_btn(self) -> None:
        if self._user_info:
            menu = tk.Menu(self.root, tearoff=False)
            email = self._user_info.get("email", "")
            if email:
                menu.add_command(label=email, state="disabled")
                menu.add_separator()
            menu.add_command(label="Sign out", command=self._sign_out)
            try:
                x = self.account_btn.winfo_rootx()
                y = self.account_btn.winfo_rooty() + self.account_btn.winfo_height()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()
        else:
            self._open_login_dialog()

    def _sign_out(self) -> None:
        from auth_manager import clear_token
        clear_token()
        self._user_info = None
        self._refresh_user_label()

    def _check_auth_startup(self) -> None:
        """Background: read stored token; call /me to confirm it's still valid."""
        def _worker():
            try:
                from auth_manager import get_token
                token = get_token()
                if not token:
                    return
                from agent_config import AUTH_API_ROOT
                import json as _json
                import urllib.request as _req
                request = _req.Request(
                    f"{AUTH_API_ROOT}/api/v1/user-auth/me",
                    headers={"X-User-Session": token},
                )
                with _req.urlopen(request, timeout=10) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                user = data.get("user") or data
                self.log_queue.put(("auth_done", {"ok": True, "user": user}))
            except Exception:
                pass  # Silently ignore - user just stays unsigned in

        threading.Thread(target=_worker, daemon=True).start()

    def _open_login_dialog(self) -> None:
        if self._login_dialog and self._login_dialog.winfo_exists():
            self._login_dialog.lift()
            self._login_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Sign in to TravelportAuto")
        dialog.geometry("380x340")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self._close_login_dialog)
        self._login_dialog = dialog
        self._login_status_var.set("")

        body = tk.Frame(dialog, padx=24, pady=20)
        body.pack(fill="both", expand=True)

        # Primary: Google sign-in
        self._google_btn = ttk.Button(
            body, text="Sign in with Google", command=self._start_google_oauth
        )
        self._google_btn.pack(fill="x", pady=(0, 12))

        # Separator
        sep = tk.Frame(body)
        sep.pack(fill="x", pady=(0, 12))
        tk.Frame(sep, height=1, bg="#d0d0d0").pack(
            fill="x", side="left", expand=True, padx=(0, 8), pady=7
        )
        tk.Label(sep, text="or sign in with email", font=("Segoe UI", 8), fg="#808080").pack(side="left")
        tk.Frame(sep, height=1, bg="#d0d0d0").pack(
            fill="x", side="left", expand=True, padx=(8, 0), pady=7
        )

        # Secondary: email + password
        tk.Label(body, text="Email", anchor="w", font=("Segoe UI", 9)).pack(fill="x")
        self._login_email_var = tk.StringVar()
        ttk.Entry(body, textvariable=self._login_email_var).pack(fill="x", pady=(2, 10))

        tk.Label(body, text="Password", anchor="w", font=("Segoe UI", 9)).pack(fill="x")
        self._login_password_var = tk.StringVar()
        ttk.Entry(body, textvariable=self._login_password_var, show="â—").pack(fill="x", pady=(2, 8))

        self._login_status_label = tk.Label(
            body, textvariable=self._login_status_var,
            fg="#c0392b", wraplength=320, justify="left", font=("Segoe UI", 9)
        )
        self._login_status_label.pack(fill="x", pady=(0, 8))

        footer = tk.Frame(dialog, padx=24, pady=10)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancel", command=self._close_login_dialog).pack(side="left")
        self._login_submit_btn = ttk.Button(footer, text="Sign In", command=self._submit_login)
        self._login_submit_btn.pack(side="right")

        self._login_email_var.set("")
        self._login_password_var.set("")
        dialog.bind("<Return>", lambda *_: self._submit_login())

    def _close_login_dialog(self) -> None:
        if self._login_dialog and self._login_dialog.winfo_exists():
            self._login_dialog.grab_release()
            self._login_dialog.destroy()
        self._login_dialog = None
        self._login_submit_btn = None
        self._google_btn = None
        self._login_status_label = None
        self._login_status_var.set("")

    def _submit_login(self) -> None:
        if not hasattr(self, "_login_email_var"):
            return
        email = self._login_email_var.get().strip()
        password = self._login_password_var.get()
        if not email:
            self._login_status_var.set("Please enter your email address.")
            return
        if not password:
            self._login_status_var.set("Please enter your password.")
            return
        if self._login_submit_btn:
            self._login_submit_btn.configure(state="disabled")
        self._login_status_var.set("Signing in...")
        threading.Thread(
            target=self._login_worker,
            args=(email, password),
            daemon=True,
        ).start()

    def _login_worker(self, email: str, password: str) -> None:
        import json as _json
        import urllib.error as _ue
        import urllib.request as _req

        try:
            from agent_config import AUTH_API_ROOT
            body = _json.dumps({"email": email, "password": password}).encode("utf-8")
            request = _req.Request(
                f"{AUTH_API_ROOT}/api/v1/user-auth/login",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with _req.urlopen(request, timeout=15) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            token = data.get("session_token", "")
            user = data.get("user") or {}
            if not token:
                self.log_queue.put(("auth_done", {"ok": False, "error": "No session token in response."}))
                return
            from auth_manager import KeyringUnavailableError, save_token
            try:
                save_token(token)
            except KeyringUnavailableError as kr_exc:
                self.log_queue.put(("auth_done", {"ok": False, "error": str(kr_exc)}))
                return
            self.log_queue.put(("auth_done", {"ok": True, "user": user}))
        except _ue.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            try:
                msg = _json.loads(detail).get("detail", detail)
            except Exception:
                msg = detail[:200] or f"Error {exc.code}"
            self.log_queue.put(("auth_done", {"ok": False, "error": str(msg)}))
        except Exception as exc:
            self.log_queue.put(("auth_done", {"ok": False, "error": f"Could not connect: {exc}"}))

    def _on_auth_done(self, payload: dict) -> None:
        if payload.get("ok"):
            self._user_info = payload.get("user") or {}
            self._refresh_user_label()
            self._close_login_dialog()
        else:
            if self._login_submit_btn:
                self._login_submit_btn.configure(state="normal")
            if self._google_btn:
                self._google_btn.configure(state="normal")
            if self._login_status_label:
                self._login_status_label.configure(fg="#c0392b")
            self._login_status_var.set(payload.get("error", "Sign in failed."))

    def _start_google_oauth(self) -> None:
        from agent_config import GOOGLE_OAUTH_CLIENT_ID, AUTH_API_ROOT
        if self._google_btn:
            self._google_btn.configure(state="disabled")
        if self._login_submit_btn:
            self._login_submit_btn.configure(state="disabled")
        if self._login_status_label:
            self._login_status_label.configure(fg="#2980b9")
        self._login_status_var.set("Opening Google sign-in in your browser...")
        threading.Thread(
            target=self._google_oauth_worker,
            args=(GOOGLE_OAUTH_CLIENT_ID, AUTH_API_ROOT),
            daemon=True,
        ).start()

    def _google_oauth_worker(self, client_id: str, api_base_url: str) -> None:
        try:
            from google_oauth import GoogleOAuthError, run_google_oauth_flow
            self.log_queue.put(("auth_status", "Completing Google sign-in..."))
            result = run_google_oauth_flow(client_id, api_base_url)

            from auth_manager import KeyringUnavailableError, save_token
            try:
                save_token(result.session_token)
            except KeyringUnavailableError as exc:
                self.log_queue.put(("auth_done", {"ok": False, "error": str(exc)}))
                return

            self.log_queue.put(("auth_done", {"ok": True, "user": {
                "email": result.email,
                "full_name": result.name,
            }}))

        except Exception as exc:
            self.log_queue.put(("auth_done", {"ok": False, "error": str(exc)}))

    def _open_feedback_dialog(self):
        if self._feedback_dialog and self._feedback_dialog.winfo_exists():
            self._feedback_dialog.lift()
            self._feedback_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Send Feedback")
        dialog.geometry("520x460")
        dialog.minsize(460, 400)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#f2f2f2")
        dialog.protocol("WM_DELETE_WINDOW", self._close_feedback_dialog)
        self._feedback_dialog = dialog
        self._feedback_status_var.set("")
        self._feedback_subject_var.set("")
        self._feedback_category_var.set("bug")

        # Footer pinned to bottom of dialog so buttons are always visible
        footer = tk.Frame(dialog, bg="#f2f2f2", padx=12, pady=8)
        footer.pack(side="bottom", fill="x")

        tk.Label(
            footer,
            text="Delivered through the configured agent backend.",
            bg="#f2f2f2",
            fg="#666",
            font=("Segoe UI", 8),
        ).pack(side="left")

        ttk.Button(footer, text="Cancel", command=self._close_feedback_dialog).pack(
            side="right", padx=(6, 0)
        )
        self._feedback_submit_btn = ttk.Button(
            footer, text="Submit", command=self._submit_feedback
        )
        self._feedback_submit_btn.pack(side="right")

        body = tk.Frame(dialog, bg="#f2f2f2", padx=12, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Send Feedback To Admin",
            bg="#f2f2f2",
            fg="#0f3758",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text="Use this for bug reports, suggestions, or questions.",
            bg="#f2f2f2",
            fg="#666",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 4))

        reply_note = (
            "Replies will be sent to your registered email."
            if self._user_info
            else "Sign in so we can reply to your feedback."
        )
        tk.Label(
            body,
            text=reply_note,
            bg="#f2f2f2",
            fg="#2980b9",
            font=("Segoe UI", 8, "italic"),
        ).pack(anchor="w", pady=(0, 12))

        tk.Label(body, text="Type", bg="#f2f2f2", font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Combobox(
            body,
            textvariable=self._feedback_category_var,
            values=("bug", "suggestion", "question", "other"),
            state="readonly",
        ).pack(fill="x", pady=(0, 8))

        tk.Label(body, text="Subject", bg="#f2f2f2", font=("Segoe UI", 9)).pack(
            anchor="w"
        )
        ttk.Entry(body, textvariable=self._feedback_subject_var).pack(
            fill="x", pady=(0, 8)
        )

        tk.Label(body, text="Message", bg="#f2f2f2", font=("Segoe UI", 9)).pack(
            anchor="w"
        )
        self._feedback_message_text = scrolledtext.ScrolledText(
            body,
            wrap="word",
            font=("Segoe UI", 9),
            height=7,
        )
        self._feedback_message_text.pack(fill="both", expand=True, pady=(0, 6))

        tk.Label(
            body,
            textvariable=self._feedback_status_var,
            bg="#f2f2f2",
            fg="#b73632",
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        ).pack(fill="x")

        self._feedback_message_text.focus_set()

    def _close_feedback_dialog(self):
        if self._feedback_dialog and self._feedback_dialog.winfo_exists():
            self._feedback_dialog.grab_release()
            self._feedback_dialog.destroy()
        self._feedback_dialog = None
        self._feedback_submit_btn = None
        self._feedback_message_text = None
        self._feedback_status_var.set("")

    def _submit_feedback(self):
        if not self._feedback_message_text:
            return

        category = self._feedback_category_var.get().strip() or "bug"
        subject = self._feedback_subject_var.get().strip()
        message = self._feedback_message_text.get("1.0", "end").strip()

        if not subject:
            self._feedback_status_var.set("Please enter a short subject.")
            return
        if not message:
            self._feedback_status_var.set("Please enter your feedback message.")
            return

        if self._feedback_submit_btn:
            self._feedback_submit_btn.configure(state="disabled")
        self._feedback_status_var.set("Sending...")

        context = {
            "mode": self.mode_var.get(),
            "route_filter": self.route_var.get().strip(),
            "airline_filter": self.airline_var.get().strip(),
        }
        if self._user_info:
            context["user_email"] = self._user_info.get("email", "")

        self._feedback_thread = threading.Thread(
            target=self._feedback_worker,
            args=(category, subject, message, context),
            daemon=True,
        )
        self._feedback_thread.start()

    def _feedback_worker(
        self,
        category: str,
        subject: str,
        message: str,
        context: dict[str, str],
    ):
        try:
            from feedback_client import FeedbackQueuedForRetry, submit_feedback

            result = submit_feedback(
                category=category,
                subject=subject,
                message=message,
                app_version=self.VERSION,
                context=context,
            )
            self.log_queue.put(("feedback_done", {"ok": True, "result": result}))
        except FeedbackQueuedForRetry as exc:
            self.log_queue.put(("feedback_done", {"ok": False, "queued": True, "error": str(exc)}))
        except Exception as exc:
            self.log_queue.put(("feedback_done", {"ok": False, "queued": False, "error": str(exc)}))

    def _on_feedback_done(self, payload: dict):
        if payload.get("ok"):
            self._close_feedback_dialog()
            messagebox.showinfo(
                "Feedback Sent",
                "Your feedback was sent successfully.\n"
                "We'll review it and reply to your registered email if needed.",
            )
            return

        if payload.get("queued"):
            # Network or server error - feedback saved offline; close dialog
            self._close_feedback_dialog()
            messagebox.showinfo(
                "Saved for Later",
                "Could not reach the server right now.\n"
                "Your feedback has been saved and will be sent automatically on next launch.",
            )
            return

        if self._feedback_submit_btn:
            self._feedback_submit_btn.configure(state="normal")
        self._feedback_status_var.set(payload.get("error", "Could not send feedback."))

    # â”€â”€ Args builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


    def _open_time_calculator(self):
        """Popup dialog: compute local arrival time from two UTC offsets + duration."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Time Calculator")
        dlg.geometry("360x280")
        dlg.minsize(320, 260)
        dlg.resizable(True, True)
        dlg.grab_set()

        pad = {"padx": 10, "pady": 4}

        tk.Label(dlg, text="Origin UTC Offset (e.g. +6, -5)",
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", **pad)
        origin_tz = tk.StringVar(value="+6")
        ttk.Entry(dlg, textvariable=origin_tz, width=12).grid(row=0, column=1, sticky="w", **pad)

        tk.Label(dlg, text="Arrival UTC Offset (e.g. +3, -5)",
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", **pad)
        arrival_tz = tk.StringVar(value="+3")
        ttk.Entry(dlg, textvariable=arrival_tz, width=12).grid(row=1, column=1, sticky="w", **pad)

        tk.Label(dlg, text="Origin Local Departure (HH:MM)",
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", **pad)
        depart_time = tk.StringVar(value="")
        ttk.Entry(dlg, textvariable=depart_time, width=12).grid(row=2, column=1, sticky="w", **pad)

        tk.Label(dlg, text="Flight Duration (HH:MM)",
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", **pad)
        duration = tk.StringVar(value="")
        ttk.Entry(dlg, textvariable=duration, width=12).grid(row=3, column=1, sticky="w", **pad)

        ttk.Separator(dlg, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=8, padx=10
        )

        result_frame = tk.Frame(dlg, bg="#f0f4f8", relief="flat", bd=1)
        result_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

        tk.Label(result_frame, text="Arrival Time (destination local):",
                 bg="#f0f4f8", font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(6, 0))
        arrival_result = tk.StringVar(value="--:-- (+0 day)")
        tk.Label(result_frame, textvariable=arrival_result,
                 bg="#f0f4f8", fg="#0f3758", font=("Segoe UI", 14, "bold")).pack(
            anchor="w", padx=8, pady=(0, 6)
        )

        error_label = tk.Label(dlg, text="", fg="#c0392b", font=("Segoe UI", 8))
        error_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=10)

        def _parse_offset(s):
            s = s.strip().replace(" ", "")
            sign = 1
            if s.startswith("+"):
                s = s[1:]
            elif s.startswith("-"):
                sign = -1
                s = s[1:]
            if ":" in s:
                h, m = s.split(":", 1)
                return sign * (int(h) * 60 + int(m))
            return sign * int(s) * 60

        def _parse_hhmm(s):
            s = s.strip()
            if ":" in s:
                h, m = s.split(":", 1)
                return int(h) * 60 + int(m)
            if len(s) == 4 and s.isdigit():
                return int(s[:2]) * 60 + int(s[2:])
            raise ValueError(f"Cannot parse time: {s!r}")

        def _calculate(*_):
            error_label.config(text="")
            try:
                origin_off = _parse_offset(origin_tz.get())
                arr_off = _parse_offset(arrival_tz.get())
                dep_mins = _parse_hhmm(depart_time.get())
                dur_mins = _parse_hhmm(duration.get())
            except Exception as exc:
                error_label.config(text=f"Input error: {exc}")
                arrival_result.set("--:--")
                return
            utc_dep = dep_mins - origin_off
            utc_arr = utc_dep + dur_mins
            local_arr = utc_arr + arr_off
            day_offset = local_arr // (24 * 60)
            local_arr = local_arr % (24 * 60)
            h, m = divmod(local_arr, 60)
            day_str = "" if day_offset == 0 else f"  (+{day_offset}d)" if day_offset > 0 else f"  ({day_offset}d)"
            arrival_result.set(f"{h:02d}:{m:02d}{day_str}")

        for var in (origin_tz, arrival_tz, depart_time, duration):
            var.trace_add("write", _calculate)

        ttk.Button(dlg, text="Close", command=dlg.destroy, width=10).grid(
            row=7, column=1, sticky="e", padx=10, pady=8
        )
        dlg.columnconfigure(0, weight=1)

    def _build_args(self) -> argparse.Namespace:
        mode = self.mode_var.get()
        speed = self.speed_var.get()
        try:
            limit = int(self.limit_var.get().strip() or "0")
        except ValueError:
            limit = 0
        is_quickpaste = mode == "quickpaste"
        is_currency = mode == "currency"
        is_tax = mode == "tax"
        is_baggage = mode == "baggage"
        primary_filter = self.route_var.get().strip() or None
        airline_filter = self.airline_var.get().strip() or None
        return argparse.Namespace(
            auto=(not is_quickpaste),
            tax=is_tax,
            penalty=(mode == "penalty"),
            quick_paste=is_quickpaste,
            currency_report=is_currency,
            load_previous_rates=getattr(self, "_prev_rates_path", None) if is_currency else None,
            previous_date=getattr(self, "_prev_rates_date", None) if is_currency else None,
            route=None if (is_tax or is_baggage) else primary_filter,
            airport=primary_filter if is_tax else None,
            one_direction=False,
            airline=None if (is_tax or is_baggage) else airline_filter,
            limit=limit,
            only_fd=self.only_fd_var.get(),
            only_yq=self.only_yq_var.get(),
            only_currency=False,
            include_ftax=False,
            only_baggage=is_baggage,
            baggage=self.baggage_inline_var.get() if not is_baggage else False,
            baggage_file=self.baggage_file_var.get().strip() or None,
            speed=speed if speed != "normal" else None,
            checkpoint=self.checkpoint_var.get(),
            resume=None,
            compare_snapshot=self.compare_var.get().strip() or None,
            no_changes=self.no_changes_var.get(),
            no_validation=False,
            output=self.output_var.get().strip() or None,
            config=None,
        )

    # â”€â”€ Worker thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _worker(self, args: argparse.Namespace):
        result_path = None
        try:
            import main as _main

            result_path = _main.run_with_args(args, stop_event=self.stop_event)
        except SystemExit:
            pass
        except Exception as exc:
            logging.getLogger().error(f"Unexpected error: {exc}", exc_info=True)
        finally:
            self.log_queue.put(("done", result_path))

    # â”€â”€ Completion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _show_stop_overlay(self):
        """Small always-on-top overlay shown while automation is running.
        Keeps Stop / ESC accessible without blocking Smartpoint."""
        if self._stop_overlay and self._stop_overlay.winfo_exists():
            return
        ov = tk.Toplevel(self.root)
        ov.title("")
        ov.resizable(False, False)
        ov.attributes("-topmost", True)
        ov.configure(bg="#1e2a35")
        ov.protocol("WM_DELETE_WINDOW", lambda: None)  # prevent accidental close

        # Position bottom-right corner, well away from the Smartpoint terminal
        ov.update_idletasks()
        sw = ov.winfo_screenwidth()
        sh = ov.winfo_screenheight()
        ov.geometry(f"240x88+{sw - 260}+{sh - 144}")

        tk.Label(
            ov,
            text="TravelportAuto  - running",
            bg="#1e2a35",
            fg="#78b4d4",
            font=("Segoe UI", 8),
        ).pack(pady=(8, 2))
        tk.Label(
            ov,
            textvariable=self._overlay_eta_var,
            bg="#1e2a35",
            fg="#dbe9f4",
            font=("Segoe UI", 8, "bold"),
        ).pack(pady=(0, 6))
        tk.Button(
            ov,
            text="Stop  (hold ESC)",
            bg="#b73632",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            activebackground="#8b1f1d",
            activeforeground="white",
            command=self._stop,
            cursor="hand2",
        ).pack(fill="x", padx=10, pady=(0, 8))

        ov.bind_all("<Escape>", lambda *_: self._stop())
        self._stop_overlay = ov
        self.root.iconify()

        # Start global ESC key listener (works even when app doesn't have focus)
        self._start_global_esc_listener()

    def _start_global_esc_listener(self):
        """Poll for ESC key globally using Win32 GetAsyncKeyState."""
        self._global_esc_active = True

        def _poll_esc():
            import ctypes
            VK_ESCAPE = 0x1B
            get_key = ctypes.windll.user32.GetAsyncKeyState
            pressed_since = None
            while self._global_esc_active:
                pressed_since, should_stop = _escape_hold_state(
                    bool(get_key(VK_ESCAPE) & 0x8000),
                    time.monotonic(),
                    pressed_since,
                )
                if should_stop:
                    self.root.after(0, self._stop)
                    break
                time.sleep(0.1)

        self._esc_thread = threading.Thread(target=_poll_esc, daemon=True)
        self._esc_thread.start()

    def _stop_global_esc_listener(self):
        self._global_esc_active = False

    def _hide_stop_overlay(self):
        self._stop_global_esc_listener()
        if self._stop_overlay and self._stop_overlay.winfo_exists():
            self._stop_overlay.destroy()
        self._stop_overlay = None
        self.root.deiconify()
        self.root.lift()

    def _on_done(self, result_path: str | None):
        self._run_started_at = None
        self._overlay_eta_var.set("")
        self._hide_stop_overlay()
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_step(len(self.STEPS) + 1)  # +1 so last step shows [x] not bold

        if result_path and os.path.exists(result_path):
            self._last_report = result_path
            self.open_btn.configure(state="normal")
            is_partial = "_partial" in os.path.basename(result_path)
            if is_partial:
                self.status_label.configure(
                    text=f"âš  Partial report saved - {os.path.basename(result_path)}",
                    fg="#e67e22",
                )
            else:
                self.status_label.configure(
                    text=f"[x]  {os.path.basename(result_path)}", fg="#1d8a63"
                )
        elif self.stop_event.is_set():
            self.status_label.configure(text="Stopped - no data captured yet", fg="#b73632")
        else:
            self.status_label.configure(text="Finished", fg="#555")


# â”€â”€ Entry point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def launch():
    root = tk.Tk()
    try:
        TravelportGUI(root)
        root.mainloop()
    except Exception as e:
        import traceback

        messagebox.showerror(
            "TravelportAuto - Startup Error",
            f"An unexpected error occurred:\n\n{e}\n\n{traceback.format_exc()}",
        )


if __name__ == "__main__":
    launch()


