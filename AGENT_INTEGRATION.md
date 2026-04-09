# Travelport Agent Integration Guide

This project is best deployed as a local Windows agent that talks to your
existing website/backend API.

The website remains the place where users log in, create jobs, review history,
download reports, and where you can stop or block misuse.

The desktop EXE remains responsible for the local Smartpoint automation.

## Recommended Concepts

Add these three concepts to your existing website/backend:

- `devices`
- `jobs`
- `job_results`

These map cleanly to how the local Travelport automation actually works.

## 1. Devices

Represents one installed desktop agent on one Windows machine.

Suggested fields:

```text
id
user_id
device_name
device_token
status                online/offline/blocked
last_seen_at
app_version
hostname
os_version
smartpoint_version
notes
```

Use this to:

- pair the EXE to a signed-in website user
- see which machines are active
- block one user/device if needed

## 2. Jobs

Represents one requested automation run from the website.

Suggested fields:

```text
id
user_id
device_id
job_type              fare/tax/penalty
status                queued/running/stop_requested/completed/failed/cancelled
route_filter
airline_filter
options_json
created_at
started_at
completed_at
requested_by
stop_requested_at
failure_reason
```

Typical payload examples:

```json
{
  "job_type": "fare",
  "route_filter": "DAC-MCT",
  "airline_filter": "BG",
  "options": {
    "auto": true,
    "include_ftax": false
  }
}
```

```json
{
  "job_type": "penalty",
  "route_filter": "DAC-MCT",
  "airline_filter": "BG",
  "options": {
    "auto": true,
    "one_direction": false
  }
}
```

## 3. Job Results

Represents the output produced by one completed job.

Suggested fields:

```text
id
job_id
report_file_url
log_file_url
summary_json
records_uploaded
warnings_count
created_at
```

This can also reference detailed parsed rows already stored centrally in your
backend database.

## Userwise Stop / Misuse Control

This belongs in the website/backend, not only in the EXE.

Recommended controls:

- `devices.status = blocked`
- `jobs.status = stop_requested`
- per-user daily or hourly job limits
- per-user allowed device count

Recommended flow:

1. Website admin marks a user/device as blocked.
2. Agent heartbeat sees that device is blocked and refuses new jobs.
3. If a job is already running, backend sets `stop_requested`.
4. Agent checks the stop flag between commands and exits safely.

## Should the EXE still generate reports/logs locally?

Yes.

It should do both:

- generate local reports/logs for the end user on their machine
- upload report/log artifacts to your website/backend

Current local output behavior already supports this pattern:

- reports go into `data/reports`
- logs go into `data/logs`

In a frozen EXE build, those paths resolve relative to the executable
directory.

## Where to Add Config

Use two separate config layers:

### Core automation config

Keep using:

- `config.json`
- `commands.txt`

These control parsing/reporting/business behavior.

### Agent/website integration config

Use:

- `agent_config.json`

Template provided:

- `agent_config.json.example`

Suggested fields:

- `api_base_url`
- `device_id`
- `device_token`
- `poll_interval_seconds`
- `heartbeat_interval_seconds`
- `upload_reports`
- `upload_logs`
- `keep_local_reports`
- `keep_local_logs`
- `stop_check_interval_seconds`

For production, prefer environment variables over hardcoding secrets in the
file.

## API Endpoints To Add To Your Existing Website

Suggested minimum endpoints:

```text
POST   /api/travelport-agent/register
POST   /api/travelport-agent/pair
GET    /api/travelport-agent/jobs/next
POST   /api/travelport-agent/jobs/{id}/heartbeat
POST   /api/travelport-agent/jobs/{id}/complete
POST   /api/travelport-agent/jobs/{id}/fail
POST   /api/travelport-agent/jobs/{id}/upload-report
POST   /api/travelport-agent/jobs/{id}/upload-log
POST   /api/travelport-agent/jobs/{id}/stop-ack
```

Website-side user endpoints:

```text
POST   /api/travelport/jobs
GET    /api/travelport/jobs
GET    /api/travelport/jobs/{id}
POST   /api/travelport/jobs/{id}/stop
GET    /api/travelport/devices
POST   /api/travelport/devices/{id}/block
POST   /api/travelport/devices/{id}/unblock
```

## EXE Name

The packaging script now standardizes on:

```text
TravelportAgent.exe
```

If you currently see two executables in `dist`, that is because there are two
older PyInstaller spec names in the repo. The new build script uses only one
standard name going forward.

## Production Rule

Do not let the EXE connect directly to your central production database.

Use your website/backend API instead.

That gives you:

- safer credential handling
- per-user authorization
- easier abuse control
- simpler audit logs
- better separation between desktop automation and hosted data
