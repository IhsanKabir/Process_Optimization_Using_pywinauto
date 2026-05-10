# Security Policy

## Reporting a Vulnerability

If you find a security issue, please email **ihsankabir999@gmail.com** directly rather than opening a public issue.

Please include:
- Description of the issue
- Steps to reproduce
- Potential impact

I will respond within 7 days.

## Scope

This tool runs locally on Windows and drives an authenticated Smartpoint session. It does not transmit fare data externally. The optional feedback feature sends only user-submitted text (category, subject, message) plus basic device metadata (OS version, app version) to the project backend. Sensitive fields (passwords, tokens, file paths) are scrubbed before transmission.

## Credentials

All Smartpoint credentials (`SMARTPOINT_USERNAME`, `SMARTPOINT_PASSWORD`, `SMARTPOINT_PCC`) are loaded exclusively from environment variables or a `.env` file — never from source code. The `.env` file is gitignored and must never be committed.
