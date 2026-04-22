# Travelport Automation — Roadmap

Tracks work that is agreed on but deliberately deferred to future sessions. Items here are
**not** speculative wish-lists — each one has been discussed, scoped, and pushed out on
purpose so the current release can ship.

---

## Deferred — Feedback, Accounts, and Tiers

### 1. Fix the feedback channel (configured but broken)

**Status:** Deferred. Infrastructure exists, endpoint/base URL not wired.

**What's broken:** The GUI Feedback dialog sends submissions to an upstream endpoint
controlled by the `TRAVELPORT_AGENT_API_BASE` environment variable. That variable has no
sensible default, so feedback silently fails in field installs.

**Required work:**
- Pick the production base URL (or a hosted collector) and set it as the default
  when the env var is unset.
- Confirm the upstream actually persists submissions (DB / sheet / issue tracker).
- Add a user-visible toast / dialog state for delivery failure instead of logging only.
- Add a simple retry queue so a submission made while offline is retried on next launch.

**Why deferred:** Needs an infra decision (where submissions land) that we haven't made
yet. Can ship independently of the scraper work.

---

### 2. Login / user identity

**Status:** Deferred. No user identity layer today.

**What's missing:** Every install is anonymous. We cannot attribute feedback, usage
stats, or pricing-tier entitlements to a specific user.

**Required work:**
- Decide the auth provider (self-hosted, Auth0-equivalent, or GitHub/Google OAuth).
- Add a first-run sign-in flow in the GUI with token refresh on subsequent launches.
- Persist the token in an OS-appropriate secure store (Credential Manager on Windows).
- Pass the user id with feedback submissions and usage telemetry.
- CLI: allow `--user-token` or a cached token file so headless runs can still identify.

**Why deferred:** Depends on (1) picking the auth provider and (2) standing up a
backend to validate tokens. Non-trivial scope; not blocking the GDS automation work.

---

### 3. Pricing tiers + free tier

**Status:** Deferred. No commercial layer today.

**What's planned:**
- **Free tier:** Some limit (e.g., N routes per day or N currency pulls per day) to let
  new users evaluate the tool.
- **Paid tiers:** Higher quotas, priority support, possibly access to premium sheets
  (penalties, tax reports) that heavy users value most.

**Required work (builds on #2):**
- Quota enforcement (per-day counters tied to the user id from #2).
- A billing integration (Stripe / local gateway).
- Server-side entitlement check on each run so tampering with a local flag does not
  unlock paid features.
- GUI surface: show current plan, quota remaining, and an upgrade link.

**Why deferred:** Makes no sense without #2 (identity) and without a backend. Also
requires a business/pricing decision that's outside the code.

---
### 4. Click reliability across PCs and screen sizes

**Status:** ✅ Shipped.

**Root cause:** `LINE_HEIGHT=20` and `D_BUTTON_X_RATIO=0.855` were hardcoded absolute values measured on one machine. On a bigger screen / different DPI the terminal renders at a larger line height — by line 7 the click Y was already ~28px off, outside the ±9px fan-out. Affected D button, More Fares/Flights, BDT Fare Exists, and Penalty clicks.

**What was shipped:**

Phase A — Calibration infrastructure (`calibration.py`)

- Reads Windows system DPI at startup.  **Correction (post-test):** DPI scaling was removed from `compute_line_height` — the 20 px baseline was already measured in physical pixels (exe manifest sets `PerMonitorV2`), so scaling it by DPI double-counted. The empirical baseline of 20 px is correct across DPI scales; Phase C delta learning handles any per-machine deviation.
- Also added `SetProcessDpiAwareness(2)` at the top of `gui.py` and `main.py` (before any window creation) so source-level runs match the compiled-exe manifest.  Removed a stale late call to `SetProcessDpiAwareness(1)` that fired after `tk.Tk()` (too late to have any effect).
- Persists to `%APPDATA%\TravelportAuto\calibration.json`; loaded by `SmartpointAutomation.__init__` into `self._line_height` and `self._content_top_padding`.
- All 5 `LINE_HEIGHT` calculation sites in `smartpoint_automation.py` now use the calibrated value.
- **Recalibrate button** added to the GUI bottom bar — resets to baseline and confirms the new line height.

Phase B — Landmark-anchored clicks (no more hardcoded ratios)
- `_find_d_char_column`: finds the rightmost standalone `D` in the right 30% of the `+TQ`/`BOOK` line; passes `char_idx` to `_text_line_to_pixel`. Falls back to `D_BUTTON_X_RATIO` only if char detection fails.
- `_find_link_char_column`: reusable helper for any regex-matched link; used for BDT Fare Exists and More Fares — both now click at the actual text character column.

Phase C — Self-correcting delta accumulation
- `record_click_delta` in `calibration.py`: rolling 50-entry history of Y offsets used on successful retries. When the average drifts > 0.5px, nudges `line_height` by ±1px and marks source as `"learned"`. Saved to JSON on every successful non-zero-offset click (D button and More Fares sites).

**History:**
- D clicks worked on dev machine; failed on larger screen — clicked close but not on target. See screenshot: `d OPTION CLICK.png`.
- Post-ship: DPI-scaling overcorrected (25 px at 125% DPI) causing clicks to land ~2 lines below. Fixed by removing DPI scaling — baseline 20 px physical is correct on all tested machines.

**Current unpushed review (2026-04-20):**
- `smartpoint_automation.py:2235` still logs `x_ratio` after the retry loop was refactored to iterate `x_positions`. If the first BDT Currency Fare click misses, that debug line raises `NameError`, aborting the retry fan-out and making the roadmap-4 fix appear flaky on harder machines.
- The newer fail-safe hardening also exposed a bounds-assumption bug in `_get_terminal_focus_point`: the clamp uses `rect.right` / `rect.bottom` directly even when the fallback rect path only guaranteed `left` / `top` plus derived width/height. In the current local full-suite run this shows up as 4 regressions in `tests/test_smartpoint_automation.py`.
- The separate FTAX global-airport search changes are not the main blocker for roadmap 4. They pass in the repo `.venv`; the remaining follow-up there is packaging discipline so `airportsdata` stays installed and bundled in the exe.

**Solution options considered:**
1. Surgical patch
   - Replace the stale `x_ratio` reference with the actual clicked X coordinate.
   - Normalize fallback rect bounds once inside `_get_terminal_focus_point` before clamping.
   - Update the clipboard-focus tests to match the intentional `_safe_focus_click` path.
   - Lowest risk and the fastest way to restore confidence in the roadmap-4 changes.
2. Broader hardening refactor
   - Extract a shared rect-normalization helper and a single focus-click abstraction.
   - Add dedicated regression tests for "first click misses, retry succeeds" and for rects missing `right`/`bottom`.
   - Cleaner long term, but wider change surface than needed for the current blocker.

**Recommended updated plan:**
- Take the surgical patch first; do not expand roadmap-4 behavior again until the current automation suite is green.
- Fix the stale variable in `click_currency_link` and re-run the BDT Currency Fare retry path.
- Make `_get_terminal_focus_point` clamp from normalized bounds (`left/top/right/bottom`) rather than raw rect attributes.
- Update/add focused tests for:
  - currency-link retry after an initial miss;
  - fallback rects that lack `right`/`bottom`;
  - the `_safe_focus_click` path introduced by the fail-safe fix.
- Re-run `.venv\Scripts\python.exe -m pytest -q -o addopts=''` and keep the suite green before packaging.
- Smoke-test the packaged exe on at least two display setups (100% and 125% DPI, different resolutions) before pushing.

**Live follow-up (2026-04-20 11:47):**
- `fs_debug.log` confirms the pricing row text is stable and still renders `D  R` at the far right of the `BOOK/+TQ` line, so the parser is not losing the landmark.
- The runtime log still shows the first D click opening a repriced `PRICING OPTIONS` screen instead of the tax breakdown, which matches the live symptom that the click can land on `R` even when the detected `D` column is correct.
- The current follow-up patch now chooses the more conservative of the ratio-based X and the character-based X (with a larger left bias derived from terminal character width), and it keeps probing the next offsets when Smartpoint returns to another pricing screen instead of aborting after the first miss.

**Next live verification:**
- Re-run the same case and inspect the fresh `run_*.log` for the new `using x=...` D-click line and multiple offset attempts.
- If the screen still reprices instead of opening the tax breakdown, tune the left bias from the logged `char_x`, `ratio_x`, and `using x` values rather than changing the line-height calibration again.

---

### 5. FTAX extraction crash — PyAutoGUI fail-safe

**Status:** ✅ Shipped.

**Root cause:** `_copy_terminal_text` called `pyautogui.click(x=safe_x, y=safe_y)` for terminal focus. When the Smartpoint window was positioned near the physical top-left corner of a monitor (common on multi-monitor setups), `_get_terminal_focus_point` returned coords near `(0, 0)` — pyautogui's fail-safe fired and crashed the entire run.

**What was shipped:**

Part A — Clamped focus point in `_get_terminal_focus_point`
- Result is now clamped to at least 5px inside the terminal rect bounds on all sides. Logs a debug message whenever clamping was needed.

Part B — `_safe_focus_click` helper (eliminates fail-safe path)
- All three focus-only clicks in `_copy_terminal_text` replaced with `self._safe_focus_click(x, y)`, which uses `_pw_mouse.click` (pywinauto / Win32 SendInput) directly — no pyautogui, no fail-safe check.

Part C — One-shot retry on `FailSafeException`
- The entire focus+copy block in `_copy_terminal_text` is wrapped in `try/except`. If a `FailSafeException` still reaches it, it logs a warning, re-fetches the rect, retries once via `_safe_focus_click`, and returns `""` on second failure instead of crashing the run.

**History:**

```text
pyautogui.FailSafeException: PyAutoGUI fail-safe triggered from mouse moving to a corner of the screen.
  File "smartpoint_automation.py", line 1459, in run_ftax_command
  File "smartpoint_automation.py", line 790, in _wait_for_response
  File "smartpoint_automation.py", line 675, in _copy_terminal_text
```

---

## Current session — shipped items (not deferred)

These are done and live on `main` so the next reader knows not to re-open them:

- Standalone Currency Rate report (`--currency-report` CLI flag, GUI radio option,
  seed archive, USD change tracker with red-date suffix).
- Removed the legacy "Exchange Rates (FZS)" sheet from the main fare workbook.
- CLI ETA text output (`[ETA ~Xm Ys] ... done/total`) every 5 items when tqdm cannot
  render a bar (frozen exe, redirected stdout, etc.).
- Windows global ESC listener for CLI runs — ESC anywhere on the system aborts the
  run via the shared `stop_event`, matching the GUI's behavior.
- **Future Tax UI rename:** "Taxes" radio button relabelled "Future Tax"; internal
  mode value kept as `"tax"` for backwards compatibility.
- **Hide irrelevant checkboxes in Future Tax mode:** "Fares Only" and "Taxes Only"
  checkboxes are hidden (not just disabled) when mode is `"tax"` — they have no
  meaning for FTAX and cluttered the panel.
- **Future Tax airport filter:** The Route field is relabelled "Airport:" in FTAX mode.
  Hint text updated to accept any of: airport code, airport name, country code/name,
  or a route (origin is extracted). e.g. `DAC`, `Dhaka`, `BD`, `DAC-MCT`.
- **Ternary precedence bug in `_build_args`:** `x or None if cond else None` was
  silently always evaluating `x or None` regardless of `cond`. Fixed by extracting
  `is_tax`, `primary_filter`, and `airline_filter` variables with explicit ternaries.
  Root symptom: every Future Tax run started with SG/Singapore (first key in config).
- **Click reliability (#4) and FTAX fail-safe crash (#5):** See detailed write-ups in
  the Deferred section above (both marked ✅ Shipped).
- **DPI-scaling post-ship fix:** `calibration.py`'s `compute_line_height` was scaling
  the 20 px baseline by DPI ratio, overcorrecting to 25 px at 125% DPI and causing
  D-button clicks to land ~2 lines below target. Reverted to fixed 20 px baseline —
  the exe manifest already sets `PerMonitorV2`, so the baseline is in physical pixels
  and correct across scales. Also moved `SetProcessDpiAwareness(2)` to the very top
  of `gui.py` and `main.py` (before any window creation) for source-level runs.
- **Scroll-to-find-More-Fares dropdown crash:** `click_more_prompt_link` was focusing
  the terminal for the pre-scroll refocus with `pyautogui.click(rect_center)`. The
  center of the terminal is always an interactive fare row, so it opened the
  `MAXIMUM STAY` / `MINIMUM STAY` dropdown and the subsequent `PageDown` scrolled
  the dropdown instead of the terminal, leaving the run stuck. Affected DAC-DOH QR,
  WY, and MCT routes. Replaced with a defensive `ESC ESC` → `_safe_focus_click(
  _get_terminal_focus_point())` (safe corner ~50 px, 30 px inside the rect) →
  `PageDown`, plus a post-scroll `_has_dropdown_activated` check with ESC recovery.
  See `smartpoint_automation.py:2427-2471`.
- **FS two-window date fallback:** replaced the single `MAX_FS_DATE_STEPS=32` cap
  (which only tried 2 offsets — 30 and 32 days out) with a two-window schedule:
  7 consecutive days starting at `FS_DATE_OFFSET_START=30` (≈1 month), then 7 more
  starting at `FS_DATE_FALLBACK_OFFSET=90` (≈3 months). `FS_DATE_STEP=1` for
  consecutive days, `FS_DATE_WINDOW_DAYS=7`. Rescues airlines whose first-month
  inventory has dried up or who only fly seasonally. See `constants.py:195-208`,
  `main.py:2450-2467`. Tests: `tests/test_fs_date_schedule.py`.
- **FZS precision preservation:** `fzs_parser.parse_fzs_output` was `round(..., 4)`-ing
  the extracted rate, so `1 QAR EQUALS 33.760812 BDT` became `33.7608` downstream.
  The currency report's cell format is already `"0.000000"` (6 decimals), so the
  rounding was purely lossy. Removed the `round` on both forward and inverse
  directions. Tests: `tests/test_fzs_parser.py` (4 tests pinning the precision
  contract).
- **India K3 origin-sensitive tax correction:** `tax_rt` for round-trip gross fares
  was naïvely summing outbound + inbound FS taxes. For routes like DAC-CCU-DAC
  this over-counted by K3 (~421 BDT) because the isolated inbound one-way scrape
  (CCU→DAC) bills K3 as if it were a standalone India-origin journey — it isn't
  when folded into an RT that starts in DAC. New helper module
  `origin_sensitive_taxes.py` exposes `compute_rt_tax_total(outbound_origin,
  outbound_fs_taxes, inbound_fs_taxes)` which strips `tax_breakdown["K3"]` from
  both legs when the outbound origin isn't an Indian IATA airport (determined via
  `airportsdata.load("IATA")` filtered by `country == "IN"`, cached with
  `lru_cache`). Extensible via `ORIGIN_SENSITIVE_TAX_CODES = {"K3": "IN"}` if
  other origin-sensitive codes surface. Wired in at `excel_report.py:1818-1832`.
  Tests: `tests/test_origin_sensitive_taxes.py` (14 tests including parametrized
  India airports, case insensitivity, empty/None legs, malformed breakdown).
  Known unknown: domestic India RTs like DEL-BOM-DEL — both scrapes have K3 and
  the current logic keeps both. Needs confirmation from a real scrape whether
  Indian domestic RTs legitimately pay K3 twice.

---

## Housekeeping

When an item here moves from "deferred" to "in progress," move it into the active
todo list for that session. When it ships, delete it from this file (not into a
"done" log — that belongs in `git log`).
