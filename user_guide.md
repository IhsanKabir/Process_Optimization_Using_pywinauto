# TravelportAuto — User Guide

**Version:** v1.3.0 · **Last updated:** 2026-04-12

---

## Table of Contents

1. What this tool does
2. Prerequisites
3. Installation
4. Folder structure
5. Configuration — config.json
6. Running the tool
   - Double-click (recommended)
   - Command Prompt — all flags
7. Extraction modes
   - Fare mode (default)
   - Tax mode
   - Penalty mode
   - Quick-paste mode
8. Filters and limits
9. Speed profiles
10. Checkpoints and resume
11. Change detection and comparisons
12. Understanding the Excel report
13. Output folder structure
14. Troubleshooting

---

## 1. What this tool does

TravelportAuto drives your open **Travelport Smartpoint** terminal automatically — it types commands, reads the screen output via clipboard capture, parses fare/tax/penalty data, and generates formatted **Excel reports**.

Every time it runs it also compares the new data against the **previous run**, so you immediately see what changed (new fares, price increases, sold-out routes, removed fares) highlighted in colour.

Results are saved locally as Excel files and JSON snapshots. If configured, data is also pushed to a live dashboard via BigQuery.

---

## 2. Prerequisites

| Requirement | Details |
|-------------|---------|
| **Windows 10 or 11** | 64-bit, recommended resolution ≥ 1920 × 1080 |
| **Travelport Smartpoint** | Must be installed, open, and fully signed-in before you run the tool |
| **Active GDS session** | You must be at a live terminal prompt — not a login screen |
| **Stable internet** | Required for BigQuery push (optional feature) |

> **Important:** Do not move your mouse or type while the tool is running. It controls the screen. If you accidentally move the mouse to any corner of the screen the tool will stop (this is a safety feature — see [Checkpoints](#10-checkpoints-and-resume) on how to resume).

---

## 3. Installation

1. Download **TravelportAuto.exe** from the Downloads page.
2. Copy it to a permanent folder, for example `C:\TravelportAuto\` or your Desktop.
3. That is all — no installer, no extra files needed.

On first run the tool automatically downloads `commands.txt` (the default route list) next to the exe. You can then open and edit that file to customise your routes.

> **Configuration is managed centrally.** Airline names, airport codes, and all other settings are loaded automatically from the server each time the tool runs — there is nothing to configure. If you need a new airline or route added, use the **Feedback** button inside the tool.

---

## 4. Folder structure

After the first run your folder will look like this:

```text
TravelportAuto/
├── TravelportAuto.exe       Main application
├── commands.txt             Your route commands — edit this to add/remove routes
├── data/
│   ├── reports/             Excel output files
│   │   └── fare_report_YYYY-MM-DD_HHMM.xlsx
│   ├── archive/             JSON snapshots (used for change detection)
│   │   ├── fare/
│   │   └── tax/
│   ├── checkpoints/         Auto-saved progress files (for resume)
│   └── logs/                Application log files (for troubleshooting)
```

---

## 5. Customising your route list — commands.txt

`commands.txt` is created automatically next to the exe on first run. Open it with Notepad to add or remove routes.

Each line is one GDS Fare Display command:

```text
FDDACMCT/BG      ← Fare Display: DAC → MCT, airline BG
FDDACCGK/BG
FDDACCGK/BS
```

To skip a route temporarily, add `#` at the start of the line:

```text
# FDDACMCT/BG   ← this line is ignored
```

> **Need a new airline or airport added?** Use the **Feedback** button in the tool to send a request. The admin will update the central configuration — your tool will pick it up automatically on the next run.

---

## 6. Running the tool

### 6.1 Double-click (recommended)

Simply **double-click** `TravelportAuto.exe`.

- Smartpoint must already be open and signed in.
- The tool will run all commands in `commands.txt` automatically.
- A window shows live progress — each route updates as it completes.
- When done, click **Open Report** to open the Excel file.

### 6.2 Command Prompt — all flags

Open Command Prompt (`cmd`) in the TravelportAuto folder, then run:

```bat
TravelportAuto.exe [flags]
```

**Full flag reference:**

| Flag | Example | Description |
|------|---------|-------------|
| `--auto` | | Extract live from Smartpoint (same as double-click) |
| `--tax` | | Run tax extraction (FTAX) instead of fares |
| `--penalty` | | Run Rule 16 penalty extraction |
| `--quick-paste` | | Manual mode: paste GDS output yourself |
| `--route ROUTE` | `--route DAC-MCT` | Only run commands for this route (both directions) |
| `--one-direction` | | With `--route`, match only the exact direction typed |
| `--airline CODE` | `--airline BG` or `--airline BG,BS` | Only run commands for these airline(s) |
| `--limit N` | `--limit 5` | Stop after N commands (useful for testing) |
| `--only-fd` | | Skip YQ/tax extraction, only get base fares (faster) |
| `--only-yq` | | Skip base fares, only extract YQ surcharges and exchange rates |
| `--speed PROFILE` | `--speed fast` or `--speed safe` | Speed profile (see section 9 below) |
| `--checkpoint` | | Save progress after each command so you can resume if interrupted |
| `--resume PATH` | `--resume data\checkpoints\checkpoint_2026-04-12_1025.json` | Resume from a saved checkpoint |
| `--compare-snapshot DATE` | `--compare-snapshot 2026-04-08` | Compare against a specific past snapshot by date |
| `--compare-snapshot DATETIME` | `--compare-snapshot 2026-04-08_1805` | Compare against a specific past snapshot by date and time |
| `--no-changes` | | Skip change detection entirely (faster, no Changes Summary sheet) |
| `--no-validation` | | Disable sanity checks (use only if a route has unusual data) |
| `--output PATH` | `--output C:\Reports\today.xlsx` | Save Excel to a custom location |
| `--config PATH` | `--config custom_config.json` | Use a different config file |

---

## 7. Extraction modes

### 7.1 Fare mode (default)

Runs every command in `commands.txt`. For each route:
1. Opens the **FD** (Fare Display) screen — reads all RBD fares with base fare, taxes, total.
2. Opens the **FS** (Fare Summary) screen — reads YQ/YR/Q surcharges and full tax breakdown in BDT.

Output: **fare_report_YYYY-MM-DD_HHMM.xlsx**

```bat
TravelportAuto.exe --auto
```

### 7.2 Tax mode (`--tax`)

Runs FTAX commands for every airport listed under `tax_airports` in `config.json`. Extracts current, upcoming, and expired tax rates with effective dates.

Output: **tax_report_YYYY-MM-DD_HHMM.xlsx**

```bat
TravelportAuto.exe --auto --tax
```

To run only the first 3 airports (for testing):
```bat
TravelportAuto.exe --auto --tax --limit 3
```

### 7.3 Penalty mode (`--penalty`)

Extracts Rule 16 change/cancellation penalties for each fare basis code found during the fare run. **This takes significantly longer** — run it separately after a fare run.

```bat
TravelportAuto.exe --auto --penalty
```

### 7.4 Quick-paste mode (`--quick-paste`)

For manually reviewing a single screen. Copy the terminal output to your clipboard, then run:

```bat
TravelportAuto.exe --quick-paste
```

The tool will parse what is on your clipboard without touching Smartpoint.

---

## 8. Filters and limits

You can combine filters:

```bash
# Only Biman fares to Muscat, both directions
TravelportAuto.exe --auto --route DAC-MCT --airline BG

# Only outbound DAC→MCT for BG
TravelportAuto.exe --auto --route DAC-MCT --one-direction --airline BG

# First 10 commands only (quick test run)
TravelportAuto.exe --auto --limit 10

# Skip YQ extraction for a faster run
TravelportAuto.exe --auto --only-fd
```bat

---

## 9. Speed profiles

The tool has two timing profiles for screen interaction:

| Profile | Flag | Use when |
|---------|------|---------|
| **Normal** | *(default)* | Stable machine, good network |
| **Fast** | `--speed fast` | Powerful machine, ~50% faster, may miss screens on slow connections |
| **Safe** | `--speed safe` | Older/slower machine, or if the tool occasionally misses data |

Example:
```
TravelportAuto.exe --auto --speed safe
```bat

---

## 10. Checkpoints and resume

For long runs (50+ commands), use `--checkpoint` to save progress after every command:

```
TravelportAuto.exe --auto --checkpoint
```bat

If the run is interrupted (e.g. fail-safe triggered, machine sleep, crash), resume from where it stopped:

```
TravelportAuto.exe --resume data\checkpoints\checkpoint_2026-04-12_1025.json
```bat

The tool will skip already-completed commands and continue from the last saved point. The checkpoint file is saved in `data/checkpoints/` and the filename includes the date and time the run started.

> **Tip:** If you see `PyAutoGUI fail-safe triggered` in the console, this means the mouse was moved to a screen corner. The run stops but data up to that point is safe. Resume with `--resume`.

---

## 11. Change detection and comparisons

### Default behaviour

Every time the tool runs, it **automatically compares the new data against the previous run's snapshot** saved in `data/archive/`. Changed fares appear highlighted in the Excel report:

| Colour | Meaning |
|--------|---------|
| 🔴 Red text on pink | Fare **increased** |
| 🟢 Green text on light green | Fare **decreased** |
| 🟡 Yellow background | **New** fare (did not exist before) |
| ⬜ Grey, italic | **Sold out** (was available before) |

The Changes Summary sheet lists every change with old and new values side by side.

### Comparing against a specific past date

To compare today's run against a snapshot from a specific date:

```bash
# Compare against the snapshot saved on 8 April 2026
TravelportAuto.exe --auto --compare-snapshot 2026-04-08

# Compare against a specific time on that date (if multiple runs that day)
TravelportAuto.exe --auto --compare-snapshot 2026-04-08_1805
```

This is useful when you want to see changes over a longer period — for example, comparing today's fares against last week's.

### Skipping change detection

If you just want a clean report with no comparison:

```bat
TravelportAuto.exe --auto --no-changes
```

---

## 12. Understanding the Excel report

The fare report contains the following sheets (tabs):

### Tab 1 — Side-by-Side Comparison
The main view. Routes are grouped by international destination. All domestic origin airports (DAC, CGP, ZYL, etc.) and airlines appear side-by-side for each route. Each cell shows the total fare. Changed cells are colour-coded (see section 11 — Change detection and comparisons).

### Tab 2 — Individual Tables
Per-airline, per-route tables showing:
- RBD and fare basis code
- Base fare (OW and RT)
- With YQ added (OW and RT)
- Gross total (OW and RT)
- Charges summary: `YQ:246 YR:0 Q:0`
- Tax breakdown: `BD:500 UT:300 ...`

### Tab 3 — YQ-YR-Q Charges *(new in v1.3.0)*
Dedicated sheet showing **only** the YQ, YR and Q surcharge codes extracted from the FS command output, grouped by route and airline. Useful for comparing these charges across routes without the full tax detail.

Columns per airline/route block:
| Charge | Amount (BDT) |
|--------|-------------|
| YQ | 246.00 |
| YR | 0.00 |
| Q | 0.00 |
| **Total Charges** | **246.00** |

### Tab 4 — Tax Breakdowns
Full tax breakdown per route and airline. Shows every individual tax code (BD, UT, IN, E7, etc.) with amounts in BDT, plus YQ/YR/Q charges and the grand total.

Includes exchange rate and base currency for each route.

### Tab 5 — Currency Conversion
Lists the current exchange rates used during this run (e.g. 1 USD = 122.71 BDT). Useful for auditing conversions.

### Tab 6 — Changes Summary *(only present if changes were detected)*
A flat list of every fare change detected compared to the previous run. Columns: Route, RBD, Change Type, Old OW, New OW, Old RT, New RT, % Change.

---

## 13. Output folder structure

After a run, check the `data/` folder:

```text
data/
├── reports/
│   └── fare_report_2026-04-12_1430.xlsx     ← Open this
├── archive/
│   ├── fare/
│   │   └── BG_DAC-MCT_2026-04-12_1430.json  ← Snapshot for future comparison
│   └── tax/
│       └── SIN_2026-04-12_1430.json
├── checkpoints/
│   └── checkpoint_2026-04-12_1430.json      ← For resume if interrupted
└── logs/
    └── travelport_auto_2026-04-12.log        ← Detailed run log
```

---

## 14. Troubleshooting

### Tool does nothing / exits immediately
- Make sure Smartpoint is **open and fully signed in** before starting the tool.
- Check `data/logs/` for the error message.

### "PyAutoGUI fail-safe triggered"
The mouse was accidentally moved to a screen corner. Your data up to that point is saved.
- Resume: `TravelportAuto.exe --resume data\checkpoints\checkpoint_2026-04-12_HHMM.json`
- Use `--checkpoint` flag on every long run as a precaution.

### Some fares are missing / 0 values
- Try `--speed safe` — the screen may have been moving too fast for the timing.
- Check `data/logs/` for `[WARNING]` lines showing which commands had issues.

### Excel file won't open
- Check `data/reports/` — the file may have a lock if the tool is still running.
- If the tool crashed, the file may be incomplete. Re-run the tool.

### YQ/Tax data shows 0 for some routes
- The FS (Fare Summary) screen may have timed out. Run with `--speed safe`.
- Or run `--only-yq` after the main run to re-extract just the tax data.

### Change detection always shows everything as "New"
- This is normal on the **very first run** — there is no previous snapshot to compare against.
- After the first run, a snapshot is saved and future runs will show real changes.
- To compare against a specific past date: `--compare-snapshot 2026-04-08`

### Data looks wrong or garbled
- Check that your Smartpoint session language is set to English.
- Make sure the screen resolution is at least 1920 × 1080.
- Do not have other windows overlapping Smartpoint during the run.

---

*For further help, send the log file from `data/logs/` to your support contact.*
