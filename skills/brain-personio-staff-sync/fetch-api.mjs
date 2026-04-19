#!/usr/bin/env node
/**
 * Fetch all Personio employee pages using the captured API credentials
 * Requires: PERSONIO_XSRF_TOKEN and PERSONIO_SESSION_COOKIE environment variables
 */

import { writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const API_URL = 'https://weroad.app.personio.com/people-list/bff/data';

// Get credentials from environment
const XSRF_TOKEN = process.env.PERSONIO_XSRF_TOKEN;
const SESSION_COOKIE = process.env.PERSONIO_SESSION_COOKIE;

if (!XSRF_TOKEN || !SESSION_COOKIE) {
  console.error('Error: Required environment variables not set');
  console.error('Please set:');
  console.error('  PERSONIO_XSRF_TOKEN - Your ATHENA-XSRF-TOKEN cookie value');
  console.error('  PERSONIO_SESSION_COOKIE - Your ATHENA_SESSION cookie value');
  console.error('');
  console.error('To get these:');
  console.error('  1. Open Chrome DevTools on Personio');
  console.error('  2. Go to Network tab');
  console.error('  3. Find a request to /api/ or /people-list/');
  console.error('  4. Copy the ATHENA-XSRF-TOKEN and ATHENA_SESSION cookie values');
  process.exit(1);
}

// Headers from captured request
const headers = {
  'accept': 'application/json, text/plain, */*',
  'accept-language': 'en-US,en;q=0.9',
  'content-type': 'application/json',
  'origin': 'https://weroad.app.personio.com',
  'referer': 'https://weroad.app.personio.com/',
  'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
  'sec-ch-ua-mobile': '?0',
  'sec-ch-ua-platform': '"macOS"',
  'sec-fetch-dest': 'empty',
  'sec-fetch-mode': 'cors',
  'sec-fetch-site': 'same-origin',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
  'x-athena-xsrf-token': XSRF_TOKEN,
  'cookie': `ATHENA_SESSION=${SESSION_COOKIE}; ATHENA-XSRF-TOKEN=${XSRF_TOKEN}`
};

// Base request body
const baseBody = {
  "referenceKey": "12293228-current-view-dd2bef3d",
  "name": "Current view",
  "employeeId": 12293228,
  "columns": ["first_name", "last_name", "email", "position", "status", "hire_date", "contract_end_date", "team_id", "fix_salary", "office_id", "department_id", "supervisor_id", "dynamic_4700709"],
  "filters": [{"id": "status", "value": {"condition": "contains", "value": ["active"]}}],
  "sorting": {"id": "last_name", "desc": false},
  "type": "eo.saved-view.people-list-current-view",
  "id": 23126441,
  "source": "people-list",
  "pagination": {"pageIndex": 1, "pageSize": 25}
};

async function fetchPage(pageIndex) {
  const body = { ...baseBody, pagination: { pageIndex, pageSize: 25 } };

  try {
    const response = await fetch(API_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error(`Error fetching page ${pageIndex}:`, error.message);
    return null;
  }
}

async function main() {
  const allEmployees = [];
  let totalPages = 8; // 195 / 25 = 7.8, round up to 8

  console.log('Fetching all Personio employee pages...\n');

  for (let page = 1; page <= totalPages; page++) {
    console.log(`Fetching page ${page}/${totalPages}...`);
    const data = await fetchPage(page);

    if (data?.success && data?.data?.items) {
      const employees = data.data.items;
      allEmployees.push(...employees);
      console.log(`  ✓ Got ${employees.length} employees (total: ${allEmployees.length})`);

      // Update total pages from first response if available
      if (page === 1 && data.data.paginator?.total) {
        const calculatedPages = Math.ceil(data.data.paginator.total / 25);
        console.log(`  Total employees expected: ${data.data.paginator.total}`);
        totalPages = calculatedPages;
      }
    } else {
      console.log(`  ✗ Failed to get data`);
    }

    // Small delay between requests
    if (page < totalPages) {
      await new Promise(r => setTimeout(r, 300));
    }
  }

  console.log(`\n✅ Total employees fetched: ${allEmployees.length}`);

  // Save combined data
  const output = {
    timestamp: new Date().toISOString(),
    count: allEmployees.length,
    employees: allEmployees
  };

  const outputPath = join(tmpdir(), 'personio-all-employees.json');
  writeFileSync(outputPath, JSON.stringify(output, null, 2));
  console.log(`\n💾 Saved to ${outputPath}`);
}

main().catch(console.error);
