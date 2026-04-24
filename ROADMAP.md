# Travelport Automation — Roadmap

Tracks work that is agreed on but deliberately deferred to future sessions. Items here are
**not** speculative wish-lists — each one has been discussed, scoped, and pushed out on
purpose so the current release can ship.

---

## Deferred — Feedback, Accounts, and Tiers

> **Ground truth (2026-04-23 live-infra discovery):** Earlier revisions of this plan
> asked "which collector?" and "which identity provider?" Both are already answered by
> shipped infrastructure this file hadn't caught up to. Read this block first; every
> item below depends on it.

### Infrastructure that actually exists (verified 2026-04-23)

**Two repos, three deploys:**

| Repo / branch | Deploys to | Notes |
|---|---|---|
| `IhsanKabir/Process_Optimization_Using_pywinauto` (this repo) → `main` | GitHub Releases (`TravelportAuto.exe`) | Desktop build via `build_app.ps1`. Latest live: `1.4.0` (2026-04-13). |
| `IhsanKabir/Aviation-Inventory-Pricing-Intelligence-Using-CatBoost-LightGBM-MLP` → `master` | **Cloud Run API + Vercel web** | Live backend + web UI. This is the only branch that ships. |
| Same repo → `main` | **Nothing. Orphaned.** | Force-push target of `.github/workflows/mirror-aviation-web.yml` in this repo. Has no runnable app; deploy workflows only trigger on `master`. |

**Live URLs (verified by curl 2026-04-23):**

- Web: `https://aviation-inventory-pricing-intellig.vercel.app` — `deploy-web-vercel.yml` on push to public repo's `master`
- API: `https://aero-pulse-api-591603094460.asia-south1.run.app` — `deploy-api-cloud-run.yml` on push to public repo's `master`. Service: `aero-pulse-api`, region `asia-south1`, GCP project `aeropulseintelligence`, dataset `aviation_intel`. Last successful deploy 2026-04-13T12:24Z.

**OpenAPI endpoints already live (from `/openapi.json` on 2026-04-23):**

- `/health`
- `/gds/*` — `changes`, `changes/summary`, `fares`, `fares/history`, `runs`, `runs/latest`, `taxes`, `taxes/{airport_code}`
- `/api/v1/meta/airlines`, `/api/v1/meta/routes`
- `/api/v1/reporting/*` — 13 endpoints covering current-snapshot, change-dashboard, change-events, forecasting, penalties, taxes, route-monitor-matrix, export.xlsx, cycles, etc.
- `/api/v1/user-auth/login`, `/register`, `/me`, `/oauth-login`, `/logout`
- `/api/v1/access-requests`, `/api/v1/access-requests/{request_id}`

### What's actually broken

1. **Mirror-to-deploy pipeline is disconnected.** [`.github/workflows/mirror-aviation-web.yml`](.github/workflows/mirror-aviation-web.yml) force-pushes the `aviation_web_integration/**` subtree from this repo's `main` → public repo's `main`. But **nothing deploys from `main`** on the public repo. Verified:
    - [`aviation_web_integration/apps/api/app/routers/travelport_feedback.py`](aviation_web_integration/apps/api/app/routers/travelport_feedback.py) + [`repositories/travelport_feedback.py`](aviation_web_integration/apps/api/app/repositories/travelport_feedback.py) exist on `main` but **not on `master`**.
    - [`aviation_web_integration/apps/api/main_patch.py`](aviation_web_integration/apps/api/main_patch.py) says "add these two lines to `apps/api/app/main.py`" — they are **not** in `master`'s `main.py` (verified: only `gds_router` is registered there).
    - `POST https://aero-pulse-api-.../travelport-agent/feedback` → **404** (verified by curl).
    - Same pattern for web: `aviation_web_integration/apps/web/app/downloads/page.tsx` exists on `main` but the live site deploys its own `apps/web/app/downloads/page.tsx` from `master`. Mirrored edits never reach users.
2. **No `DEFAULT_API_BASE_URL`.** [feedback_client.py:69-74](feedback_client.py#L69-L74) raises `FeedbackSubmissionError("Feedback delivery is not configured on this machine yet...")` when empty. [agent_config.py:54-60](agent_config.py#L54-L60) resolves from env → JSON → `""`. Every field install without the env var set fails loudly on the first feedback submit.
3. **Desktop client doesn't use the existing auth endpoints.** [feedback_client.py](feedback_client.py) sends `Authorization: Bearer <device_token>` only. No sign-in flow, no keyring, no use of `/api/v1/user-auth/login`. Feedback rows cannot be attributed to a real user.

### Decisions already made by deployed code (do not re-debate)

- **Collector:** FastAPI + BigQuery on Cloud Run. Live. C1 (GitHub/Linear proxy) from earlier revisions is off the table — choosing it means abandoning a live service + mirror + web app.
- **Identity backend:** `/api/v1/user-auth/*` on the deployed API. The old "Option A paste-token / B Google OAuth / C Keycloak" decision is obsolete — the server already does email/password + Google OAuth. Desktop work is client integration, not provider choice.
- **Storage:** BigQuery (`aeropulseintelligence:aviation_intel`). Not Postgres. Swapping would be a rewrite; don't.

**What still needs a product decision (and only this):** whether paid tiers ship now
or are deferred pending demand evidence. See Item 3.

---

### 1. Fix the feedback channel (unblocked — no Step 0 pending)

**Status:** Deferred — ready to code. ~3–4 focused days.

**Goal:** `POST https://aero-pulse-api-591603094460.asia-south1.run.app/travelport-agent/feedback` returns 2xx for a valid payload from a fresh desktop install with zero env vars set, and logs survive offline submission.

**Step 1.0 — Pick mirror-vs-master strategy (5-minute decision, record here):**

- **(a) Stop mirroring `apps/**`.** Remove that path-filter from `mirror-aviation-web.yml` (or delete the workflow). All future web/API changes land as PRs directly against the public repo's `master`. **Recommended** — the mirror does nothing useful today and causes confusion.
- (b) Retarget mirror to open a PR against `master` on every push (replaces current force-push-to-`main`). Heavier.
- (c) Keep mirror as docs-only; rename `aviation_web_integration/` → `docs/aviation_web_reference/` so nobody assumes it deploys.

**Work:**

| Step | Where | Change | Verify |
|---|---|---|---|
| 1.1 | Public repo `master` — PR | Copy `apps/api/app/routers/travelport_feedback.py` and `apps/api/app/repositories/travelport_feedback.py` from this repo's `aviation_web_integration/` (contents are the same on `main`). Append to `apps/api/app/main.py`: `from app.routers import travelport_feedback as travelport_feedback_router` + `app.include_router(travelport_feedback_router.router, prefix="/travelport-agent", tags=["Travelport Feedback"])`. | `deploy-api-cloud-run.yml` runs on merge; `curl -X POST .../travelport-agent/feedback -d '{"subject":"x","message":"y","category":"general"}'` returns 2xx. `GET /openapi.json` shows `/travelport-agent/feedback` in `paths`. |
| 1.2 | Public repo `master` — BigQuery schema | Confirm the `travelport_feedback` table exists in `aeropulseintelligence:aviation_intel`. If not, add `CREATE TABLE` SQL under the existing `sql/` directory and run it. Repository code at [repositories/travelport_feedback.py](aviation_web_integration/apps/api/app/repositories/travelport_feedback.py) tells you the expected columns. | `bq ls aeropulseintelligence:aviation_intel` lists it; manual POST inserts a row. |
| 1.3 | This repo — [agent_config.py:25-42](agent_config.py#L25-L42) | Add module-level `DEFAULT_API_BASE_URL = "https://aero-pulse-api-591603094460.asia-south1.run.app/travelport-agent"`. In `load_agent_config`, fall back to it when env + JSON resolve to empty. Keep env/JSON overrides working (needed for dev). | `AgentConfig().api_base_url` on a fresh machine with no env/JSON equals the default. |
| 1.4 | This repo — [feedback_client.py:69-74](feedback_client.py#L69-L74) | Drop the "not configured on this machine" guard once the default exists. | Existing tests still pass; manual GUI submit from a machine with no env var succeeds. |
| 1.5 | This repo — [feedback_client.py](feedback_client.py) | Classify failures: `URLError` / `timeout` → queue for retry; `HTTPError 4xx` → reject without retry, surface server message; `HTTPError 5xx` → queue + warn. Current retry loop treats all failures alike. | Unit tests cover each branch. |
| 1.6 | This repo — new `feedback_queue.py` | JSON queue at `%APPDATA%\TravelportAuto\feedback_queue.json`. On URLError/5xx, append payload. Flush on app startup and after every successful submit. Cap 50 entries; drop oldest. | Round-trip test; malformed JSON does not crash startup; cap enforced. |
| 1.7 | This repo — [gui.py:1929-1939](gui.py#L1929-L1939) | On URLError, swap "Send" button for "Saved — will retry on next launch" then close. On 4xx, keep existing inline server-message display. | Manual GUI verification with backend reachable / unreachable / returning 400. |
| 1.8 | This repo — [feedback_client.py:22](feedback_client.py#L22) + [gui.py](gui.py) (the caller that builds `context`) | PII scrub for `context` dict before POST. Deny-list: absolute file paths, env var dumps, any key whose name contains pass / pwd / token / secret / key (case-insensitive), and Smartpoint credential patterns. Enumerate exactly what GUI puts in `context` today and pin in a test. | Test asserts the allowed `context` keys for each category and that denied values become `[REDACTED]`. |
| 1.9 | Public repo `master` — router | Rate limit (slowapi, 10/min/IP) OR require valid `device_token` on POST. Currently the endpoint will be open on first deploy; one hostile script fills BigQuery. | Integration test: 11th anonymous request within a minute returns 429. |
| 1.10 | Public repo `master` — observability | One Cloud Logging-based alert policy: "feedback endpoint 5xx rate > 1%/5min → email". | Alert fires on a forced-500 smoke test. |
| 1.11 | Tests — this repo | Default base URL resolution (env set / JSON set / both empty); queue append on URLError; drop on 4xx; queue drain on startup; queue survives malformed JSON; PII scrubber pins `context` keys. | `pytest` green; coverage includes new files. |

**Why deferred:** No external blocker once 1.0 is written down.

---

### 2. Login / user identity (unblocked — provider decision already made by deployed server)

**Status:** Deferred — ready to code once Item 1 ships (so feedback submissions already carry the user header).

**What changed:** The old plan asked "Option A paste-token, Option B Google OAuth, or Option C Keycloak?" Moot. The deployed API already exposes email/password (`/register`, `/login`, `/me`, `/logout`) and Google OAuth (`/oauth-login`). There's also `/api/v1/access-requests`, implying a web-side approval workflow already exists.

**Goal:** Desktop GUI uses the same account the user uses on the web. Every desktop network call that can be attributed carries `Authorization: Bearer <user_token>`.

**Open question for whoever picks this up (5-minute check):** Does `POST /api/v1/user-auth/login` return a bearer token in the body, or set a session cookie? Read `apps/api/app/routers/user_auth.py` (or wherever) on the public repo's `master` branch to confirm the contract. This decides whether desktop stores a long-lived JWT in keyring or manages a cookie jar. Both work, but they shape the client code differently.

**Work (assumes bearer token; adapt 2.1/2.5 if it's cookies):**

| Step | Where | Change |
|---|---|---|
| 2.1 | This repo — new `auth_manager.py` | Wrap `keyring`. Functions: `save_token(token: str)`, `get_token() -> str \| None`, `clear_token()`. Service name: `"TravelportAuto"`, username: `"user_token"`. |
| 2.2 | This repo — [TravelportAuto.spec](TravelportAuto.spec) | Add `'keyring.backends.Windows'` and `'win32ctypes.pywin32.pywintypes'` to `hiddenimports`. **Packaging risk verified:** without these, `keyring` silently uses in-memory backend in the exe and tokens do not persist across runs. |
| 2.3 | This repo — [gui.py](gui.py) | First-run dialog: email + password fields, button → `POST /api/v1/user-auth/login`. On success, save token to keyring. On 401, show server message. Show current user (from `/me`) in status bar. Menu: "Sign out" clears keyring. |
| 2.4 | This repo — [gui.py](gui.py) | "Sign in with Google" button → open browser to `/api/v1/user-auth/oauth-login`, poll or receive redirect for token. Can be deferred to a follow-up if email/password suffices for beta. |
| 2.5 | This repo — [main.py](main.py) CLI | `--user-token` flag > keyring > `TRAVELPORT_USER_TOKEN` env var. Exit 2 with clear message if still missing for commands that need auth. Commands that don't need auth (e.g. local parse-only) keep working anonymous. |
| 2.6 | This repo — [feedback_client.py](feedback_client.py) | Prefer user token over device token when keyring has one. `Authorization: Bearer <user_token>`. Keep `device_id` in payload for telemetry continuity. |
| 2.7 | Public repo `master` | Confirm a "revoke token" admin action exists (CLI or dashboard) so leaked tokens can be killed. Tokens should carry `jti` and be revocable server-side. If missing, add it. |
| 2.8 | Tests — this repo | `auth_manager` roundtrip (mock `keyring`); CLI `--user-token` precedence; GUI login error-paths (401, 5xx, network); feedback falls back to device token when keyring empty; revoked-token returns 401. |

**Why deferred:** Ships after Item 1 so feedback submissions already carry user headers the day auth lands. No external blocker.

---

### 3. Pricing tiers + free tier

**Status:** Deferred — **still blocked on demand validation**. Unchanged.

**Top-level challenge:** Is there evidence of willingness-to-pay? If not, piggy-back usage fields onto the Item 1 feedback payload (routes/day, FTAX airports/day, penalty runs/day), let it run a quarter, then decide tiers with real data. Everything below assumes demand is validated.

**What's planned (if validated):**

- **Free tier:** Some limit (e.g., N routes per day or N currency pulls per day).
- **Paid tiers:** Higher quotas, priority support, possibly premium sheets (penalties, tax reports).

**Auth provider is no longer a blocker** — `/api/v1/user-auth/*` is the identity layer. What still blocks:

- Free-tier cap: "N routes/day"? "N FTAX airports/day"? "Fares only; no penalty/tax sheets"?
- Paid mechanism: flat subscription, metered, or **license keys**?
- Quota boundary: soft-warn + upgrade prompt, or hard-block **new runs only** (never abort in-flight — see risk)?

**Work (license-key path recommended for a 1–100 user niche):**

| Step | Where | Change |
|---|---|---|
| 3.1 | Public repo `master` | `licenses` table (BigQuery or whichever relational store `user-auth` already uses — check first). Columns: `user_id`, `plan`, `valid_until`, `device_limit`, `status`. |
| 3.2 | Public repo `master` | `GET /api/v1/entitlements` — returns signed JWT (`{plan, quotas, exp=24h}`). Desktop caches until `exp`. |
| 3.3 | Public repo `master` | `POST /api/v1/usage` — batched counter uploads from desktop. |
| 3.4 | This repo — new `entitlement_client.py` | Cache signed JWT. Verify signature locally (public key bundled in exe); no network on hot path. Refresh when `exp - now < 1h`. |
| 3.5 | This repo — [main.py](main.py) orchestrator | Before each **run** (not each op): `can_start_run(expected_metric_count)`. **Do not abort mid-run** — partial Excel files corrupt workflow. |
| 3.6 | This repo — [gui.py](gui.py) | Status bar "Pro · 37 / 50 routes today". Menu "Enter license key" / "Upgrade plan" opens browser. |
| 3.7 | Public repo | Anti-tamper: signed JWT with server private key; client verifies with public key. Server returns 429 on exhaustion. |
| 3.8 | Tests | Signed JWT verify/reject; cached entitlement survives offline up to `exp`; block-new-run-on-exhaustion (not mid-run); batch usage upload retries. |

**Risks that shaped this plan (unchanged):**

- **Hard-block mid-run corrupts Excel output.** 3.5 gates at run-start only.
- **Per-op revalidation fails on flaky networks.** Signed JWT with 24h offline grace avoids the churn.
- **Stripe is ~2 sprints of webhooks/idempotency/tax.** License keys skip all of that; fit the 1–100 user niche.

**Why deferred:** Product decision (demand evidence) outside the code.

---

### Recommended sequence (revised 2026-04-23 after live-infra discovery)

**Step 0 (now one question, not three):** Is paid-tier demand validated?

- **Not validated** → Items 1 + 2 only this quarter. Skip Item 3. Piggy-back usage fields on the Item 1 feedback payload to gather data passively.
- **Validated** → Items 1 + 2 + 3, sequentially.

**Sprint 1 (~3–4 days):** Item 1. Pick mirror strategy (1.0), land router on public `master`, add `DEFAULT_API_BASE_URL`, PII scrub, offline queue, rate limit, alert.

**Sprint 2 (~3–4 days):** Item 2. Desktop auth against `/api/v1/user-auth/*`. Feedback header switches from `device_token` to user token.

**Sprint 3 (only if demand validated):** Item 3 skeleton — entitlements endpoint, usage batching, run-start gating. No Stripe.

**Parallel-safe quick win:** Item 6 (auto-generated downloads page) can ship any time. It doesn't touch the desktop exe.

---

### 6. Auto-generate downloads page from GitHub Releases

**Status:** Deferred — unblocked quick win. No external dependencies. Ships independently of Items 1–3.

**What's broken:** The live downloads page at `https://aviation-inventory-pricing-intellig.vercel.app/downloads` is served from the public repo's `master` branch at `apps/web/app/downloads/page.tsx`. It contains a hardcoded `RELEASES: Release[]` array (12 entries as of 2026-04-13, last manual update v1.3.8). GitHub Releases on the desktop repo `IhsanKabir/Process_Optimization_Using_pywinauto` already has newer tags (`1.3.9`, `1.4.0`) — the page is stale within hours of every release.

**Hard prerequisite:** Edit on the **public repo's `master` branch**, not this repo's `aviation_web_integration/`. The mirror pipeline is orphaned (see Ground truth block) — edits to the subtree copy do not reach the live site.

**Options:**

- **(a) Server-side fetch at build/revalidate time (recommended).** Convert `downloads/page.tsx` to an async server component. Fetch `https://api.github.com/repos/IhsanKabir/Process_Optimization_Using_pywinauto/releases?per_page=30` with `{ next: { revalidate: 3600 } }`. ISR refreshes hourly; Vercel's edge cache absorbs traffic; no GitHub token needed (60 req/hr/IP anonymous is ample). ~30 lines of code, no workflow plumbing.
- (b) GitHub Action triggered by `release` event on this repo, opens a PR against public repo's `master` rewriting the `RELEASES` array. Heavier infra, no runtime benefit.

**Edge cases to handle:**

- Release with no `.exe` asset → `exe_url: null` (the existing `Release` type already allows this).
- Filter out `draft: true`; optionally filter `prerelease: true`.
- Derive `label: "Latest"` from the first non-prerelease, non-draft entry.
- Fall back to the hardcoded `RELEASES` array if the fetch throws (network issue during build).

**Why deferred:** Not on the prior roadmap because the prior roadmap didn't know the mirror was orphaned. Small, clean, and visible to users — good next-idle-hour task.

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

- **Item 2 (login / user identity — steps 2.1–2.3, 2.5–2.6, 2.8):**
  - New `auth_manager.py`: wraps `keyring` library (Windows Credential Locker in exe,
    system default in dev). Functions: `save_token`, `get_token`, `clear_token`,
    `is_signed_in`. Service name `"TravelportAuto"` / username `"session_token"` are
    stable — changing them would log out all users.
  - `TravelportAuto.spec` — added `keyring`, `keyring.backends.Windows`,
    `win32ctypes`, `win32ctypes.pywin32.pywintypes` to `hiddenimports` so the Windows
    Credential Locker backend is bundled in the exe and tokens persist across runs.
  - `AUTH_API_ROOT` constant added to `agent_config.py` pointing at the live Cloud Run
    API root (used by GUI for `/api/v1/user-auth/*` calls).
  - GUI changes:
    - "Sign In" button in the bottom bar; replaces with "Account ▾" when signed in.
    - Clicking "Account ▾" pops a menu showing the email and a "Sign out" option.
    - Login dialog: email + password fields, `<Return>` to submit, inline error display.
    - On successful login the session token is stored in keyring; the user email is
      shown as `● email` in the right side of the bottom bar.
    - On sign-out: keyring cleared, label hidden, button reset to "Sign In".
    - Startup: 1.5 s after launch, a background thread reads the stored token and calls
      `GET /api/v1/user-auth/me` to confirm it's still valid. If valid, the user label
      appears silently with no dialog.
  - `main.py` — `--user-token` CLI flag for headless runs that need an authenticated
    identity. Precedence: `--user-token` > keyring > `TRAVELPORT_USER_TOKEN` env var.
  - `feedback_client.py` — `submit_feedback` now accepts an optional
    `user_session_token` kwarg and a new `_resolve_session_token()` helper. When a
    user session is available (explicit arg > keyring > env var), feedback is sent with
    `X-User-Session: <token>`; device token falls back to `Authorization: Bearer` only
    when no user session exists. `device_id` stays in the payload regardless.
  - 14 new tests across `test_auth_manager.py` and `test_feedback_auth.py` covering
    keyring roundtrip, clear/is_signed_in, constant stability, and all token-precedence
    branches (explicit > keyring > env > device). 258 total tests passing.

- **Item 1 (feedback channel, desktop side — steps 1.3–1.8, 1.11):**
  - `DEFAULT_API_BASE_URL` baked into `agent_config.py` so fresh installs with no env/JSON
    automatically target the live Cloud Run API. Env/JSON overrides still respected.
  - "Feedback delivery is not configured" guard removed from `feedback_client.py`.
  - Failure classification: `URLError`/`TimeoutError`/`OSError` → `FeedbackQueuedForRetry`;
    `HTTPError 5xx` → `FeedbackQueuedForRetry`; `HTTPError 4xx` → `FeedbackSubmissionError`
    (rejected without retry, server message surfaced to user).
  - New `feedback_queue.py`: JSON offline queue at `%APPDATA%\TravelportAuto\feedback_queue.json`.
    Cap 50 entries (oldest dropped); `drain_feedback_queue` helper flushes on success.
  - GUI: `FeedbackQueuedForRetry` closes the dialog and shows "Saved for Later" instead of
    leaving the submit button re-enabled and showing an error.
  - GUI startup: `_drain_feedback_queue_async` fires 3 seconds after launch in a background
    thread, flushing any queued payloads from previous offline sessions.
  - PII scrubber (`_scrub_context`): redacts any context key matching `pass|pwd|token|secret|key|auth|cred`
    and any string value containing an absolute file path before POST.
  - 29 new tests across `test_feedback_client.py` and `test_feedback_queue.py` covering
    all failure branches, PII scrubbing, default URL resolution, and queue lifecycle.

- **Item 1 (feedback channel, public repo — step 1.1):**
  - `apps/api/app/routers/travelport_feedback.py` and
    `apps/api/app/repositories/travelport_feedback.py` copied from the orphaned
    `aviation_web_integration/` subtree to the airline_scraper_full_clone's live `master`
    branch files.
  - Router registered in `apps/api/app/main.py` with `prefix="/travelport-agent"`.
  - `POST /travelport-agent/feedback` and `GET /travelport-agent/feedback` now exist on master.
    Next step: merge to master and let `deploy-api-cloud-run.yml` build it into the live API.

- **Item 6 (downloads page):**
  - `apps/web/app/downloads/page.tsx` converted from a static hardcoded array to an async
    Next.js server component. Fetches
    `https://api.github.com/repos/IhsanKabir/Process_Optimization_Using_pywinauto/releases`
    with `{ next: { revalidate: 3600 } }` (ISR, hourly refresh). Falls back to
    `FALLBACK_RELEASES` if the GitHub API is unavailable at build/revalidate time.
    Filters out drafts; pre-releases kept in the table but can be excluded by adjusting
    the filter. First non-draft entry automatically labelled "Latest".

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
