---
name: brain-personio-staff-sync
description: Open Chrome, prompt user to login to Personio, scrape staff roster, and save to TSV.
---

# Personio Staff Sync

Syncs the WeRoad staff roster from Personio by opening a browser and scraping the data after manual login.

## Prerequisites

```bash
cd /path/to/brain-personio-staff-sync
npm install
npx playwright install chromium
```

## Usage

Run the scraper:

```bash
cd /path/to/brain-personio-staff-sync
npm run scrape
```

## What it does

1. **Opens Chrome** with a visible window
2. **Navigates** to `https://weroad.app.personio.com/login`
3. **Pauses** for you to login manually
4. **Navigates** to the Staff page
5. **Extracts** employee data from API responses
6. **Saves** to `src/personio/staff.tsv` (all 14 columns)
7. **Backups** raw data to `personio-scrape-debug.json`

## Manual data extraction (if automated fails)

If the script can't extract data automatically:

1. Use Chrome DevTools in the opened browser
2. Look for API calls to `/api/v1/company/employees` in the Network tab
3. Right-click → Copy → Copy response
4. Save to `employees.json`
5. Transform to TSV format matching `src/personio/staff.tsv`

## Output format

The TSV has these columns:
```
ID	First Name	Last Name	Email	Position	Department	Team	Office	Hire Date	Status	Supervisor	Contract End Date	Occupation Type
```

Note: Salary is excluded for privacy.

Full output is saved directly to `personio-staff.tsv` in the current directory.

## Known issues

- **Login required**: You must manually login each time (no stored credentials)
- **2FA**: If prompted for email verification, complete it in the browser
- **URL**: Use `weroad.app.personio.com` (not .de)
- **Session expiry**: Personio sessions expire, so you need to re-login periodically
- **Rate limiting**: Don't run this too frequently

## Alternative: Google Sheet sync

WeRoad has an official daily sync to a Google Sheet. Check with the People team for access:
- URL in `memory/L1/teams.md`
- Updated automatically by Personio native integration

---

## Implementation

The scraper is implemented in `scrape-personio.mjs` using Playwright.
