# Personio Staff Sync Agent

Automates extraction of WeRoad's staff roster from Personio HR system.

## Quick Start

### Option 1: Browser Automation (recommended)

```bash
cd /path/to/brain-personio-staff-sync
npm run scrape
```

This will:
1. Open Chrome browser
2. Navigate to Personio login
3. Pause for you to login manually
4. Extract staff data
5. Save to `personio-scrape-debug.json`

### Option 2: Direct API (requires active session)

If you have a recent login session with valid cookies, set the required environment variables first:

```bash
export PERSONIO_XSRF_TOKEN="your-xsrf-token"
export PERSONIO_SESSION_COOKIE="your-session-cookie"
cd /path/to/brain-personio-staff-sync
node fetch-api.mjs
```

Then convert to TSV:
```bash
node /tmp/convert-to-tsv-full.mjs
```

## Why this exists

- No official Personio API credentials available for individual employees
- The `rootless-personio` CLI is broken (Personio changed auth)
- The MCP server requires admin API credentials
- This browser automation approach works with your existing login session

## Files

- `scrape-personio.mjs` - Main scraper script
- `fetch-api.mjs` - Direct API fetcher (requires env vars)
- `package.json` - Node dependencies
- `SKILL.md` - Agent definition for Claude Code

## Data output

- **TSV**: `personio-staff.tsv` - Full staff roster with all fields (written to current directory)
- **JSON**: `personio-scrape-debug.json` - Raw API response (debug)

### TSV Columns

| Column | Description |
|--------|-------------|
| ID | Personio employee ID |
| First Name | Employee first name |
| Last Name | Employee last name |
| Email | WeRoad email address |
| Position | Job title |
| Department | Organization department |
| Team | Team assignment |
| Office | Office location |
| Hire Date | Employment start date |
| Status | Active/Inactive |
| Supervisor | Direct manager |
| Contract End Date | End date for fixed-term contracts |
| Occupation Type | Permanent, Fixed Term, etc. |

## Alternative

For automated daily sync, WeRoad uses Personio's native Google Sheets integration. See `memory/L1/teams.md` for details.
