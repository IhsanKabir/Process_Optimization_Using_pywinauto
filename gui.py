"""
gui.py - TravelportAuto GUI

User-friendly window. No raw log by default — shows a live route
checklist with plain-language status icons. Technical log is available
via a hidden "Show technical log" toggle for troubleshooting.

Entry point for PyInstaller build (console=False in spec).
Run directly:  python gui.py
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


# ── Thread-safe log bridge ────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


class _StdoutRedirect:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str):
        text = text.rstrip()
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_cmd(cmd_str: str):
    """'FDDACMCT/BG'  →  ('BG', 'DAC → MCT')"""
    m = re.match(r"FD([A-Z]{3})([A-Z]{3})/([A-Z0-9]+)", cmd_str.upper())
    if m:
        origin, dest, airline = m.group(1), m.group(2), m.group(3)
        return airline, f"{origin} → {dest}"
    return cmd_str, ""


# ── Main GUI ──────────────────────────────────────────────────────────────────

class TravelportGUI:
    VERSION = "v1.3.0"

    # Step labels shown in the step indicator
    STEPS = ["Setup", "Connect", "Extracting", "Report"]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"TravelportAuto  {self.VERSION}")
        self.root.geometry("920x640")
        self.root.minsize(740, 520)

        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self._run_thread: threading.Thread | None = None
        self._last_report: str | None = None

        # Route checklist state
        self._current_row: str | None = None   # treeview iid of the running row
        self._done = 0
        self._total = 0
        self._current_step = 0
        self._log_visible = False

        self._apply_theme()
        self._build_ui()
        self._setup_logging()
        self.root.bind_all("<Escape>", lambda *_: self._stop())
        self._poll()

    # ── Theme ─────────────────────────────────────────────────────────────────

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

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Title bar
        bar = tk.Frame(self.root, bg="#0f3758", pady=9)
        bar.pack(fill="x")
        tk.Label(bar, text="  TravelportAuto", bg="#0f3758", fg="white",
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        tk.Label(bar, text=f"  {self.VERSION}  ", bg="#0f3758", fg="#78b4d4",
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Label(bar, text="Travelport Smartpoint Automation Tool  ",
                 bg="#0f3758", fg="#5a7f9a",
                 font=("Segoe UI", 9)).pack(side="right")

        # Body
        body = tk.Frame(self.root, bg="#f2f2f2")
        body.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(body, bg="#f2f2f2", width=235)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg="#f2f2f2")
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        self._build_bottom()

    # ── Left panel ────────────────────────────────────────────────────────────

    def _section(self, parent, text):
        tk.Label(parent, text=text.upper(), bg="#f2f2f2", fg="#0f3758",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(10, 1))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 5))

    def _build_left(self, parent):
        self._section(parent, "What to Extract")
        self.mode_var = tk.StringVar(value="fare")
        for label, val in [("Fares", "fare"),
                            ("Taxes", "tax"),
                            ("Penalties", "penalty"),
                            ("Manual (paste GDS output)", "quickpaste")]:
            ttk.Radiobutton(parent, text=label,
                            variable=self.mode_var, value=val).pack(anchor="w", pady=1)
        tk.Label(parent, text="Manual: copy terminal output first,\nthen press Start",
                 bg="#f2f2f2", fg="#999",
                 font=("Segoe UI", 7, "italic"), justify="left").pack(anchor="w")
        self.mode_var.trace_add("write", self._on_mode_change)

        self._section(parent, "Speed")
        self.speed_var = tk.StringVar(value="normal")
        for label, val in [("Normal", "normal"),
                            ("Fast", "fast"),
                            ("Reliable (slower)", "safe")]:
            ttk.Radiobutton(parent, text=label,
                            variable=self.speed_var, value=val).pack(anchor="w", pady=1)

        self._section(parent, "Filters")
        tk.Label(parent, text="Route:", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.route_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.route_var).pack(fill="x")
        tk.Label(parent, text="e.g. DAC-MCT or DAC-MCT,DAC-BKK  (blank = all)",
                 bg="#f2f2f2", fg="#999",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")

        tk.Label(parent, text="Airline:", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        self.airline_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.airline_var).pack(fill="x")
        tk.Label(parent, text="e.g. BG or BG,BS,EK  (blank = all)",
                 bg="#f2f2f2", fg="#999",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")

        tk.Label(parent, text="Limit (0 = run all):", bg="#f2f2f2",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        self.limit_var = tk.StringVar(value="0")
        ttk.Entry(parent, textvariable=self.limit_var, width=8).pack(anchor="w")

        self._section(parent, "Options")
        self.checkpoint_var = tk.BooleanVar(value=True)
        self.no_changes_var = tk.BooleanVar(value=False)
        self.only_fd_var    = tk.BooleanVar(value=False)
        self.only_yq_var    = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Save progress (resume if interrupted)",
                        variable=self.checkpoint_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Skip change report",
                        variable=self.no_changes_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Fares only (skip taxes)",
                        variable=self.only_fd_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Taxes only (skip fares)",
                        variable=self.only_yq_var).pack(anchor="w", pady=1)

        self._section(parent, "Output Path")
        tk.Label(parent, text="Leave blank — saved automatically",
                 bg="#f2f2f2", fg="#999",
                 font=("Segoe UI", 7, "italic")).pack(anchor="w")
        row = tk.Frame(parent, bg="#f2f2f2")
        row.pack(fill="x")
        self.output_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.output_var).pack(side="left",
                                                          fill="x", expand=True)
        ttk.Button(row, text="…", width=3,
                   command=self._browse).pack(side="left", padx=(2, 0))

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, parent):
        # Step indicator
        step_frame = tk.Frame(parent, bg="#f2f2f2")
        step_frame.pack(fill="x", pady=(0, 8))

        self._step_labels: list[tk.Label] = []
        for i, name in enumerate(self.STEPS):
            lbl = tk.Label(step_frame, text=name, bg="#f2f2f2",
                           font=("Segoe UI", 9), fg="#aaa")
            lbl.pack(side="left")
            self._step_labels.append(lbl)
            if i < len(self.STEPS) - 1:
                tk.Label(step_frame, text="  →  ", bg="#f2f2f2",
                         fg="#ccc", font=("Segoe UI", 9)).pack(side="left")

        # Progress bar + counter
        prog_row = tk.Frame(parent, bg="#f2f2f2")
        prog_row.pack(fill="x", pady=(0, 4))
        self.progress = ttk.Progressbar(prog_row, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.counter_label = tk.Label(prog_row, text="", bg="#f2f2f2",
                                      fg="#0f3758", font=("Segoe UI", 9, "bold"),
                                      width=14, anchor="e")
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
        self.tree.heading("status",  text="")
        self.tree.heading("airline", text="Airline")
        self.tree.heading("route",   text="Route")
        self.tree.column("status",  width=36,  stretch=False, anchor="center")
        self.tree.column("airline", width=110, stretch=False)
        self.tree.column("route",   width=200, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # Row colour tags
        self.tree.tag_configure("pending", foreground="#aaa")
        self.tree.tag_configure("running", foreground="#0f6ec4",
                                font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("done",    foreground="#1d8a63")
        self.tree.tag_configure("failed",  foreground="#b73632")

        # Collapsible technical log
        self._build_log_toggle(parent)

    def _build_log_toggle(self, parent):
        toggle_row = tk.Frame(parent, bg="#f2f2f2")
        toggle_row.pack(fill="x", pady=(6, 0))

        self._toggle_btn = tk.Button(
            toggle_row,
            text="▶  Show technical log",
            bg="#f2f2f2", fg="#777",
            font=("Segoe UI", 8),
            relief="flat", cursor="hand2",
            command=self._toggle_log,
            anchor="w",
        )
        self._toggle_btn.pack(side="left")

        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            font=("Consolas", 8),
            bg="#1e1e1e", fg="#d4d4d4",
            relief="flat",
            state="disabled",
            height=0,
        )
        self.log_text.pack(fill="x")
        self.log_text.tag_config("ERROR",   foreground="#f44747")
        self.log_text.tag_config("WARNING", foreground="#ffcc02")
        self.log_text.tag_config("SUCCESS", foreground="#4ec9b0")

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        self.log_text.configure(height=8 if self._log_visible else 0)
        self._toggle_btn.configure(
            text="▼  Hide technical log" if self._log_visible
                 else "▶  Show technical log"
        )

    # ── Bottom bar ────────────────────────────────────────────────────────────

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

        self.status_label = tk.Label(bar, text="Ready",
                                     bg="#dde3e8", fg="#555",
                                     font=("Segoe UI", 9))
        self.status_label.pack(side="right", padx=12)

    # ── Logging setup ─────────────────────────────────────────────────────────

    def _setup_logging(self):
        handler = _QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
        sys.stdout = _StdoutRedirect(self.log_queue)

    # ── Queue polling (main thread) ───────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._handle_log(payload)
                elif kind == "done":
                    self._on_done(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ── Log parsing → UI updates ──────────────────────────────────────────────

    def _handle_log(self, text: str):
        """Parse a log line and update the step indicator + route checklist."""
        tl = text.lower()

        # ── Step detection ──
        if re.search(r"\[1/4\].*load|loading config", tl):
            self._set_step(1)
        elif re.search(r"connecting to smart|\[2/4\].*auto", tl):
            self._set_step(2)
        elif re.search(r"\[4/4\].*generat|generating excel", tl):
            self._set_step(4)

        # ── Route command line:  [45/85] FDDACMCT/BG ──
        m_cmd = re.search(r"\[(\d+)/(\d+)\]\s+(FD[A-Z0-9]+/[A-Z0-9]+)", text)
        if m_cmd:
            idx   = int(m_cmd.group(1))
            total = int(m_cmd.group(2))
            cmd   = m_cmd.group(3)
            self._done  = idx
            self._total = total
            self._set_step(3)
            self._add_route_row(cmd, idx)
            self._update_counter()

        # ── Route succeeded ──
        elif re.search(r"✓.*fare data|✓.*tax.*complet|✓.*completed|fare data captured", tl):
            self._mark_row("done")

        # ── Route failed ──
        elif re.search(r"failed after|✗ failed|✗.*failed", tl):
            self._mark_row("failed")

        # ── Append to hidden technical log ──
        self._append_raw(text)

    def _set_step(self, n: int):
        if n <= self._current_step:
            return
        self._current_step = n
        for i, lbl in enumerate(self._step_labels):
            step_num = i + 1
            if step_num < n:
                lbl.configure(text=f"✓ {self.STEPS[i]}", fg="#1d8a63",
                              font=("Segoe UI", 9))
            elif step_num == n:
                lbl.configure(text=self.STEPS[i], fg="#0f3758",
                              font=("Segoe UI", 9, "bold"))
            else:
                lbl.configure(text=self.STEPS[i], fg="#aaa",
                              font=("Segoe UI", 9))

    def _add_route_row(self, cmd_str: str, idx: int):
        airline, route = _parse_cmd(cmd_str)
        iid = f"row_{idx}"
        # If already exists (e.g. resume), just update it
        if self.tree.exists(iid):
            self.tree.item(iid, values=("⟳", airline, route), tags=("running",))
        else:
            self.tree.insert("", "end", iid=iid,
                             values=("⟳", airline, route),
                             tags=("running",))
        self.tree.see(iid)
        self._current_row = iid

    def _mark_row(self, state: str):
        if not self._current_row or not self.tree.exists(self._current_row):
            return
        icon = "✓" if state == "done" else "✗"
        vals = self.tree.item(self._current_row, "values")
        self.tree.item(self._current_row,
                       values=(icon, vals[1], vals[2]),
                       tags=(state,))

    def _update_counter(self):
        if self._total:
            pct = int(self._done / self._total * 100)
            self.counter_label.configure(
                text=f"{self._done} / {self._total}"
            )
            self.progress.configure(mode="determinate", value=pct)

    def _append_raw(self, text: str):
        self.log_text.configure(state="normal")
        tl = text.lower()
        tag = "INFO"
        if "error" in tl or "failed" in tl:
            tag = "ERROR"
        elif "warning" in tl:
            tag = "WARNING"
        elif "✓" in text or "success" in tl:
            tag = "SUCCESS"
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ── Mode change handler ───────────────────────────────────────────────────

    def _on_mode_change(self, *_):
        if self.mode_var.get() == "quickpaste":
            self.no_changes_var.set(True)
        else:
            self.no_changes_var.set(False)

    # ── Button actions ────────────────────────────────────────────────────────

    def _browse(self):
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
        self.status_label.configure(text="Starting…", fg="#0f3758")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        args = self._build_args()
        self._run_thread = threading.Thread(
            target=self._worker, args=(args,), daemon=True
        )
        self._run_thread.start()

    def _stop(self):
        self.stop_event.set()
        self.status_label.configure(text="Stopping…", fg="#b73632")
        self.stop_btn.configure(state="disabled")

    def _open_report(self):
        if self._last_report and os.path.exists(self._last_report):
            os.startfile(self._last_report)
        else:
            messagebox.showinfo("No Report", "Report file not found.")

    # ── Args builder ──────────────────────────────────────────────────────────

    def _build_args(self) -> argparse.Namespace:
        mode = self.mode_var.get()
        speed = self.speed_var.get()
        try:
            limit = int(self.limit_var.get().strip() or "0")
        except ValueError:
            limit = 0
        is_quickpaste = (mode == "quickpaste")
        return argparse.Namespace(
            auto=(not is_quickpaste),
            tax=(mode == "tax"),
            penalty=(mode == "penalty"),
            quick_paste=is_quickpaste,
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
            config=None,
        )

    # ── Worker thread ─────────────────────────────────────────────────────────

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

    # ── Completion ────────────────────────────────────────────────────────────

    def _on_done(self, result_path: str | None):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_step(len(self.STEPS))

        if result_path and os.path.exists(result_path):
            self._last_report = result_path
            self.open_btn.configure(state="normal")
            self.status_label.configure(
                text=f"✓  {os.path.basename(result_path)}", fg="#1d8a63"
            )
        elif self.stop_event.is_set():
            self.status_label.configure(text="Stopped", fg="#b73632")
        else:
            self.status_label.configure(text="Finished", fg="#555")


# ── Entry point ───────────────────────────────────────────────────────────────

def launch():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    TravelportGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
