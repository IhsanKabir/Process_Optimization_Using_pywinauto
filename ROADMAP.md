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

## Current session — shipped items (not deferred)

These are done and live on `main` so the next reader knows not to re-open them:

- Standalone Currency Rate report (`--currency-report` CLI flag, GUI radio option,
  seed archive, USD change tracker with red-date suffix).
- Removed the legacy "Exchange Rates (FZS)" sheet from the main fare workbook.
- CLI ETA text output (`[ETA ~Xm Ys] ... done/total`) every 5 items when tqdm cannot
  render a bar (frozen exe, redirected stdout, etc.).
- Windows global ESC listener for CLI runs — ESC anywhere on the system aborts the
  run via the shared `stop_event`, matching the GUI's behavior.

---

## Housekeeping

When an item here moves from "deferred" to "in progress," move it into the active
todo list for that session. When it ships, delete it from this file (not into a
"done" log — that belongs in `git log`).
