"""
gui.py - TravelportAuto GUI launcher

Single-window tkinter interface. Entry point for PyInstaller build.
Replaces the console window entirely.

Run directly:   python gui.py
Built exe:      TravelportAuto.exe  (console=False in spec)
"""

import argparse
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


# ── Thread-safe logging bridge ───────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    """Sends log records into a queue so the GUI thread can render them."""
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


class _StdoutRedirect:
    """Redirect print() calls to the log queue."""
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str):
        text = text.rstrip()
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass


# ── Main GUI ─────────────────────────────────────────────────────────────────

class TravelportGUI:
    VERSION = "v1.3.0"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"TravelportAuto  {self.VERSION}")
        self.root.geometry("900x640")
        self.root.minsize(720, 520)

        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self._run_thread: threading.Thread | None = None
        self._last_report: str | None = None
        self._total_cmds = 0
        self._done_cmds = 0

        self._apply_theme()
        self._build_ui()
        self._setup_logging()
        self._poll()

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        style = ttk.Style(self.root)
        # Use Windows native theme if available
        available = style.theme_names()
        for t in ("vista", "xpnative", "winnative", "clam"):
            if t in available:
                style.theme_use(t)
                break
        self.root.configure(bg="#f2f2f2")

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Title bar
        bar = tk.Frame(self.root, bg="#0f3758", pady=9)
        bar.pack(fill="x")
        tk.Label(bar, text="  TravelportAuto", bg="#0f3758", fg="white",
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        tk.Label(bar, text=f"{self.VERSION}  ", bg="#0f3758", fg="#78b4d4",
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Label(bar, text="Travelport Smartpoint Automation Tool  ",
                 bg="#0f3758", fg="#6a8fa8",
                 font=("Segoe UI", 9)).pack(side="right")

        # Body
        body = tk.Frame(self.root, bg="#f2f2f2")
        body.pack(fill="both", expand=True, padx=10, pady=8)

        # Left panel (fixed width)
        left = tk.Frame(body, bg="#f2f2f2", width=230)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        self._build_left(left)

        # Right panel (log)
        right = tk.Frame(body, bg="#f2f2f2")
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        # Bottom bar
        self._build_bottom()

    def _section_label(self, parent, text):
        tk.Label(parent, text=text.upper(), bg="#f2f2f2", fg="#0f3758",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(10, 1))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 4))

    def _build_left(self, parent):
        # ── Mode
        self._section_label(parent, "Mode")
        self.mode_var = tk.StringVar(value="fare")
        for label, val in [("Fare Extraction", "fare"),
                            ("Tax (FTAX)", "tax"),
                            ("Penalties (Rule 16)", "penalty")]:
            ttk.Radiobutton(parent, text=label,
                            variable=self.mode_var, value=val).pack(anchor="w")

        # ── Speed
        self._section_label(parent, "Speed")
        self.speed_var = tk.StringVar(value="normal")
        for label, val in [("Normal (default)", "normal"),
                            ("Fast (~50% faster)", "fast"),
                            ("Safe (slower machines)", "safe")]:
            ttk.Radiobutton(parent, text=label,
                            variable=self.speed_var, value=val).pack(anchor="w")

        # ── Filters
        self._section_label(parent, "Filters")
        tk.Label(parent, text="Route:", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.route_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.route_var).pack(fill="x")
        tk.Label(parent, text="e.g. DAC-MCT  (blank = all)",
                 bg="#f2f2f2", fg="#888",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")

        tk.Label(parent, text="Airline:", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        self.airline_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.airline_var).pack(fill="x")
        tk.Label(parent, text="e.g. BG  or  BG,BS  (blank = all)",
                 bg="#f2f2f2", fg="#888",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")

        tk.Label(parent, text="Limit (0 = run all):", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        self.limit_var = tk.StringVar(value="0")
        ttk.Entry(parent, textvariable=self.limit_var, width=8).pack(anchor="w")

        # ── Options
        self._section_label(parent, "Options")
        self.checkpoint_var = tk.BooleanVar(value=False)
        self.no_changes_var = tk.BooleanVar(value=False)
        self.only_fd_var    = tk.BooleanVar(value=False)
        self.only_yq_var    = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Checkpoint / Resume",
                        variable=self.checkpoint_var).pack(anchor="w")
        ttk.Checkbutton(parent, text="Skip change detection",
                        variable=self.no_changes_var).pack(anchor="w")
        ttk.Checkbutton(parent, text="Only FD  (skip YQ/tax)",
                        variable=self.only_fd_var).pack(anchor="w")
        ttk.Checkbutton(parent, text="Only YQ  (skip base fares)",
                        variable=self.only_yq_var).pack(anchor="w")

        # ── Output
        self._section_label(parent, "Output Path")
        tk.Label(parent, text="Optional — leave blank for auto",
                 bg="#f2f2f2", fg="#888",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")
        row = tk.Frame(parent, bg="#f2f2f2")
        row.pack(fill="x")
        self.output_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.output_var).pack(side="left",
                                                          fill="x", expand=True)
        ttk.Button(row, text="…", width=3,
                   command=self._browse_output).pack(side="left", padx=(2, 0))

    def _build_right(self, parent):
        # Status row
        status_row = tk.Frame(parent, bg="#f2f2f2")
        status_row.pack(fill="x", pady=(0, 3))
        self.status_label = tk.Label(status_row, text="Ready",
                                     bg="#f2f2f2", fg="#555",
                                     font=("Segoe UI", 9))
        self.status_label.pack(side="left")
        self.cmd_counter = tk.Label(status_row, text="",
                                    bg="#f2f2f2", fg="#0f3758",
                                    font=("Segoe UI", 9, "bold"))
        self.cmd_counter.pack(side="right")

        # Progress bar
        self.progress = ttk.Progressbar(parent, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 5))

        # Log label
        tk.Label(parent, text="LOG OUTPUT", bg="#f2f2f2", fg="#0f3758",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")

        # Log text area — dark terminal style
        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            relief="flat",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

        # Colour tags
        self.log_text.tag_config("ERROR",   foreground="#f44747")
        self.log_text.tag_config("WARNING", foreground="#ffcc02")
        self.log_text.tag_config("SUCCESS", foreground="#4ec9b0")
        self.log_text.tag_config("INFO",    foreground="#d4d4d4")
        self.log_text.tag_config("DIM",     foreground="#6a9153")

    def _build_bottom(self):
        bar = tk.Frame(self.root, bg="#dde3e8", pady=8)
        bar.pack(fill="x", side="bottom")

        self.start_btn = ttk.Button(bar, text="▶   Start",
                                    command=self._start, width=14)
        self.start_btn.pack(side="left", padx=(12, 4))

        self.stop_btn = ttk.Button(bar, text="■   Stop",
                                   command=self._stop, width=14,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        self.open_btn = ttk.Button(bar, text="📂  Open Report",
                                   command=self._open_report, width=16,
                                   state="disabled")
        self.open_btn.pack(side="left", padx=4)

        self.result_label = tk.Label(bar, text="",
                                     bg="#dde3e8", fg="#333",
                                     font=("Segoe UI", 8),
                                     anchor="e")
        self.result_label.pack(side="right", padx=12)

    # ── Logging / stdout capture ─────────────────────────────────────────────

    def _setup_logging(self):
        handler = _QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
        # Capture print() calls too
        sys.stdout = _StdoutRedirect(self.log_queue)

    def _poll(self):
        """Drain queue every 80 ms, update widgets on the main thread."""
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_done(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _append_log(self, text: str):
        self.log_text.configure(state="normal")

        # Pick colour tag
        tl = text.lower()
        if "error" in tl or "failed" in tl or "✗" in text:
            tag = "ERROR"
        elif "warning" in tl:
            tag = "WARNING"
        elif "✓" in text or "complete" in tl or "saved:" in tl or "success" in tl:
            tag = "SUCCESS"
        elif text.startswith("#") or text.startswith("  #"):
            tag = "DIM"
        else:
            tag = "INFO"

        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        # Extract progress from  [45/85]  patterns
        m = re.search(r"\[(\d+)/(\d+)\]", text)
        if m:
            self._done_cmds = int(m.group(1))
            self._total_cmds = int(m.group(2))
            self.cmd_counter.config(
                text=f"{self._done_cmds} / {self._total_cmds} commands"
            )

    # ── Button handlers ──────────────────────────────────────────────────────

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="Save report as…",
        )
        if path:
            self.output_var.set(path)

    def _start(self):
        if self._run_thread and self._run_thread.is_alive():
            return

        self.stop_event.clear()
        self._last_report = None
        self._done_cmds = 0
        self._total_cmds = 0

        # Clear log
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        args = self._build_args()

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.result_label.configure(text="")
        self.cmd_counter.configure(text="")
        self.status_label.configure(text="Running…", fg="#0f3758")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        self._run_thread = threading.Thread(
            target=self._worker, args=(args,), daemon=True
        )
        self._run_thread.start()

    def _stop(self):
        self.stop_event.set()
        self.status_label.configure(text="Stopping after current command…", fg="#b73632")
        self.stop_btn.configure(state="disabled")

    def _open_report(self):
        if self._last_report and os.path.exists(self._last_report):
            os.startfile(self._last_report)
        else:
            messagebox.showinfo("No Report", "Report file not found.")

    # ── Args builder ─────────────────────────────────────────────────────────

    def _build_args(self) -> argparse.Namespace:
        mode = self.mode_var.get()
        speed = self.speed_var.get()
        try:
            limit = int(self.limit_var.get().strip() or "0")
        except ValueError:
            limit = 0

        return argparse.Namespace(
            auto=True,
            tax=(mode == "tax"),
            penalty=(mode == "penalty"),
            quick_paste=False,
            route=self.route_var.get().strip() or None,
            one_direction=False,
            airline=self.airline_var.get().strip() or None,
            limit=limit,
            only_fd=self.only_fd_var.get(),
            only_yq=self.only_yq_var.get(),
            only_currency=False,
            include_ftax=False,
            speed=speed if speed != "normal" else None,
            checkpoint=self.checkpoint_var.get(),
            resume=None,
            compare_snapshot=None,
            no_changes=self.no_changes_var.get(),
            no_validation=False,
            output=self.output_var.get().strip() or None,
            config=None,   # main.py will use DEFAULT_CONFIG
        )

    # ── Worker thread ────────────────────────────────────────────────────────

    def _worker(self, args: argparse.Namespace):
        result_path = None
        try:
            import main as _main
            result_path = _main.run_with_args(args, stop_event=self.stop_event)
        except SystemExit:
            pass
        except Exception as exc:
            logging.getLogger().error(f"Unhandled error: {exc}", exc_info=True)
        finally:
            self.log_queue.put(("done", result_path))

    # ── Completion (called on main thread via queue) ─────────────────────────

    def _on_done(self, result_path: str | None):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

        if result_path and os.path.exists(result_path):
            self._last_report = result_path
            self.open_btn.configure(state="normal")
            self.status_label.configure(text="Done", fg="#1d8a63")
            self.result_label.configure(
                text=f"✓  {os.path.basename(result_path)}"
            )
            self._append_log(f"\n✓ Report saved: {result_path}")
        elif self.stop_event.is_set():
            self.status_label.configure(text="Stopped by user", fg="#b73632")
        else:
            self.status_label.configure(text="Finished (no report generated)", fg="#555")


# ── Entry point ──────────────────────────────────────────────────────────────

def launch():
    root = tk.Tk()
    # Crisp rendering on HiDPI Windows screens
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    TravelportGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
