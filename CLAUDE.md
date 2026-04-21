# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Windows-only desktop automation for the Travelport Smartpoint GDS terminal. It drives Smartpoint via pywinauto + pyautogui, scrapes terminal pages through the clipboard, parses the output with dense regex, and emits Excel reports. Ships as a PyInstaller exe (`TravelportAuto`) and also runs directly from Python.

Most debugging and live testing has to happen on a Windows machine with an authenticated Smartpoint session — there is no headless mode for the UI-driving paths.

## Common commands

Tests (from repo root, on Windows with `.venv` created):

```powershell
.\run_tests.ps1                                         # full suite (uses pytest.ini: -v --cov)
.\run_tests.ps1 tests/test_parser.py -v                 # one file
.\run_tests.ps1 -q -o addopts=''                        # skip coverage, faster
.\.venv\Scripts\python.exe -m pytest -x -q              # direct, fail-fast
```

Run from source (Windows only, Smartpoint must be open and focused once when prompted):

```powershell
python main.py --auto                                   # fare extraction
python main.py --auto --tax --airport SYD               # FTAX for one airport
python main.py --auto --penalty                         # Rule 16 penalty extraction
python main.py --auto --route DAC-MCT --limit 5         # filtered + capped
python main.py                                          # manual mode: process data/raw/*.txt
python gui.py                                           # Tk GUI entry
```

Build the exe (PowerShell script handles venv + PyInstaller):

```powershell
.\build_app.ps1
```

Lint / type / security (CI runs these, see `.github/workflows/test.yml`):

```powershell
flake8 .
black --check .
mypy *.py
bandit -r .
```

## High-level architecture

Single pipeline: **drive terminal → scrape clipboard → parse → report**. Entry points wire these phases together; each phase has a dedicated module.

### Orchestration

- `main.py` — CLI entry point and the per-run orchestrator for every mode (fares, tax, penalty, currency, quick-paste). Parses args, loads+validates config, routes to the correct scraper/parser/reporter. Very large (~2900 lines); new behavior is usually added as a helper near existing modes rather than a new top-level block.
- `gui.py` — Tk GUI that builds an `argparse.Namespace` in `_build_args` and hands off to `main.main(prebuilt_args=...)`. The GUI is just an args-builder plus a live log pane; no business logic lives here.
- Both entry points call `ctypes.windll.shcore.SetProcessDpiAwareness(2)` at module-top (before any window creation). Both calls run when gui.py imports main.py; the second one raises and is swallowed by `try/except` — intentional.

### Terminal driver

- `smartpoint_automation.py` — `SmartpointAutomation` class. All window attach, keystroke sending, clipboard scrape, pagination detection, and click-at-pixel logic lives here. Anything that moves the mouse or reads the clipboard should go through this class.
- Terminal output is read by clicking a **safe focus point** inside the terminal rect, then sending `Ctrl+A/Ctrl+C` via pywinauto (not pyautogui) and pasting. pyautogui's mouse fail-safe used to crash runs when the window touched a screen corner; all focus-only clicks now use `_safe_focus_click` (pywinauto `_pw_mouse.click`) and `_get_terminal_focus_point` clamps the click 5 px inside the rect.
- Three landmark helpers locate clickable glyphs on the terminal rather than trusting hardcoded x-ratios: `_find_d_char_column` (the `D` details button), `_find_link_char_column` (for `CURRENCY FARES EXISTS` and `MORE FARES/FLIGHTS/OPTIONS`). Ratio constants in `constants.py` are fallbacks.

### Calibration

- `calibration.py` — per-machine display calibration persisted to `%APPDATA%\TravelportAuto\calibration.json`. `SmartpointAutomation.__init__` loads it into `self._line_height` and `self._content_top_padding`; every pixel calculation uses those instance fields, not the raw `LINE_HEIGHT` constant.
- **Do not re-introduce DPI-scaling of `line_height`.** The 20 px baseline is already in physical pixels (exe manifest sets PerMonitorV2). Scaling by DPI double-counts and was reverted — see ROADMAP.md item 4 for the history. Phase C delta learning in `record_click_delta` handles per-machine drift by nudging line-height ±1 px after 5+ non-zero successful offsets.

### Parsers

- `parser.py` — fare-display (`FD`) output.
- `tax_parser.py` — FTAX tax rules (`FTAX-{CC}/{CODE}`). Most complex parser; pages through 20+ screens of irrelevant legal text looking for `TAX RATE:` blocks.
- `tax_breakdown_parser.py` — FS tax breakdown (the per-option detail screen opened by clicking `D`).
- `fzs_parser.py` — fare-basis details (FZS).
- `penalty_parser.py` — Rule 16 penalty extraction.
- Each parser is regex-heavy and accepts the raw scraped text. Parsers don't touch the UI; they're pure functions over strings.

### Reports

- `excel_report.py` — fare reports.
- `tax_report.py`, `penalty_report.py`, `currency_report.py` — mode-specific Excel layouts.
- `change_detector.py` — diff against the prior archived snapshot; drives color-coding in the report.
- `checkpoint_manager.py` — resume partially-completed runs after a crash or ESC.

### Config, validation, credentials

- `config.json` (gitignored) + `config_schema.json` (JSON Schema) loaded through `config_manager.py`. `APP_ENV=dev|prod` picks `config.{env}.json`.
- `validators.py` — every user-facing string (airline, route, airport, limit) goes through a `validate_*` call before being used in commands. `validate_airport_code` is what the new global-airport-directory resolver relies on.
- `credential_manager.py` — Smartpoint login via env vars (`SMARTPOINT_USERNAME`, `SMARTPOINT_PASSWORD`, `SMARTPOINT_PCC`) or `.env`. Never hardcoded.

### Tax airport resolution

- `_build_searchable_tax_airports` (main.py) is the single source of truth for "which airports can `--tax --airport X` accept". It merges three layers:
  1. Global IATA directory from the `airportsdata` package (marked `_source=global`).
  2. `airport_country_codes` from config.
  3. `tax_airports` from config (marked `_source=config`, wins on duplicates).
- `_resolve_tax_airport_query` matches by code, country code, country name, or airport/city-name substring. Ambiguous matches raise `ValidationError` with the candidate list. When the search pool includes the global directory, the "not found" and "matches multiple" messages say "airports" instead of "configured tax airports" — `_has_global_tax_airport_search` flips the phrasing.

## Packaging gotcha

The exe is built from `TravelportAuto.spec`. When you add a new runtime dependency:

- Pure-Python packages auto-bundle if imported at module top.
- Data-bearing packages (like `airportsdata`, which ships JSON under its package dir) need **both** a `hiddenimports=[..., 'airportsdata']` entry **and** `collect_data_files('airportsdata')` in `datas`. Without the data files, `airportsdata.load("IATA")` returns empty at runtime and every global-airport lookup silently fails in the exe while passing in the venv.

## Knowledge graph

`.cursorrules` and `AGENTS.md` document a `code-review-graph` MCP toolchain (`detect_changes`, `get_review_context`, `query_graph`, `get_impact_radius`, etc.). When those tools are available, prefer them over Grep/Glob for structural questions (callers, dependents, test coverage). Fall back to Grep/Read when they aren't.

## Workflow notes

- `ROADMAP.md` is the live log of what's shipped, deferred, and in-flight. Read the "Current session — shipped items" section before starting anything — it's the fastest way to see what already happened.
- Debug artifacts land in repo root on purpose (`error.log`, `fs_debug.log`, `run_*.log`, `tmp*/` working dirs). They're gitignored; leave them for the user to inspect.
- Tests that drive the UI class (`tests/test_smartpoint_automation.py`) monkeypatch `spa.pyautogui`, `spa.pyperclip`, `_safe_focus_click`, `_get_terminal_rect`, `_text_line_to_pixel`, `_wait_for_response`, `_wait_for_stable_screen`. New tests should follow the same pattern rather than trying to instantiate real pywinauto.
- Git on this checkout is configured such that working-tree files are CRLF while blobs are LF. Plain `git diff HEAD` therefore reports the entire file as changed for most files. Use `git diff --ignore-cr-at-eol HEAD` when reviewing uncommitted changes or the signal is lost in noise.
