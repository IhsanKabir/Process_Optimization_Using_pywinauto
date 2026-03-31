# Environment Configuration Examples

This directory contains example configuration files for different environments.

## Configuration Files

- `config.json` - Default/Production configuration (not in version control)
- `config.dev.json.example` - Development environment template
- `config.test.json` - Test environment (used by CI/CD)

## Setup

1. Copy the appropriate example file:
   ```bash
   cp config.dev.json.example config.dev.json
   ```

2. Edit with your environment-specific values

3. Set the environment variable:
   ```bash
   # Windows PowerShell
   $env:APP_ENV="dev"

   # Windows CMD
   set APP_ENV=dev

   # Linux/Mac
   export APP_ENV=dev
   ```

4. The application will automatically load `config.dev.json` instead of `config.json`

## Environment Variables

- `APP_ENV` - Environment name (default, dev, prod, test)
- `SMARTPOINT_USERNAME` - Smartpoint login username
- `SMARTPOINT_PASSWORD` - Smartpoint login password
- `SMARTPOINT_PCC` - Pseudo City Code (optional)

## Configuration Schema

See `config_schema.json` for the JSON schema specification.

## Security Notes

- Never commit actual config files (config.json, config.dev.json) to version control
- Use .env files for sensitive credentials
- Example/template files are safe to commit
