#!/usr/bin/env node
/**
 * Personio Staff Scraper
 * Opens Chrome, prompts for manual login, extracts staff roster, saves to TSV
 */

import { chromium } from '@playwright/test';
import { writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import readline from 'readline';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = process.cwd();

const PERSONIO_URL = 'https://weroad.app.personio.com/login';
const STAFF_URL = 'https://weroad.app.personio.com/staff';

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function ask(question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

function formatDateToPersonioStyle(dateStr) {
  if (!dateStr || typeof dateStr !== 'string') return '';
  try {
    const [day, month, year] = dateStr.split('.');
    if (!day || !month || !year) return dateStr;
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const monthIndex = parseInt(month, 10) - 1;
    const monthName = months[monthIndex] || month;
    return `${parseInt(day, 10)} ${monthName} ${year}`;
  } catch {
    return dateStr;
  }
}

function getContractEndDate(contractEndDate) {
  if (!contractEndDate) return '';
  if (typeof contractEndDate === 'object') {
    if (contractEndDate.has_access === false) return '';
    return contractEndDate.label || contractEndDate.value || '';
  }
  return String(contractEndDate);
}

function getOccupationType(dynamic) {
  if (!dynamic) return '';
  if (typeof dynamic === 'object') {
    if (dynamic.has_access === false) return '';
    return dynamic.label || dynamic.value || '';
  }
  return String(dynamic);
}

function escapeTsv(value) {
  if (value === null || value === undefined) return '';
  const str = String(value);
  // Escape tabs and newlines
  return str.replace(/\t/g, ' ').replace(/\n/g, ' ').replace(/\r/g, '');
}

function convertToTsv(employees) {
  // All fields from Personio API (salary excluded)
  const header = ['ID', 'First Name', 'Last Name', 'Email', 'Position', 'Department', 'Team', 'Office', 'Hire Date', 'Status', 'Supervisor', 'Contract End Date', 'Occupation Type'];
  const lines = [header.join('\t')];

  employees.forEach((emp) => {
    const row = [
      emp.id || '',
      escapeTsv(emp.first_name || emp.firstName || emp.firstname || ''),
      escapeTsv(emp.last_name || emp.lastName || emp.lastname || ''),
      escapeTsv(emp.email || ''),
      escapeTsv(emp.position || emp.jobTitle || emp.job_title || ''),
      escapeTsv(emp.department_id?.label || emp.department || emp.departmentName || emp.department_name || ''),
      escapeTsv(emp.team_id?.label || emp.team || emp.teamName || emp.team_name || ''),
      escapeTsv(emp.office_id?.label || emp.office || emp.officeName || emp.office_name || ''),
      escapeTsv(formatDateToPersonioStyle(emp.hire_date || emp.hireDate || emp.employment_start_date || emp.employmentDate)),
      escapeTsv(emp.status?.label || emp.status || 'Active'),
      escapeTsv(emp.supervisor_id?.label || emp.supervisor || emp.manager || emp.supervisorName || emp.supervisor_name || ''),
      escapeTsv(getContractEndDate(emp.contract_end_date || emp.contractEndDate)),
      escapeTsv(getOccupationType(emp.dynamic_4700709 || emp.occupationType))
    ];
    lines.push(row.join('\t'));
  });

  return lines.join('\n');
}

async function main() {
  console.log('🚀 Starting Personio Staff Sync...\n');

  // Launch browser with user profile (to keep session cookies)
  console.log('Opening Chrome...');
  const browser = await chromium.launch({
    headless: false,  // Show browser window
    slowMo: 50       // Slow down actions for visibility
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  });

  const page = await context.newPage();

  // Store API responses
  const apiResponses = [];

  // Listen for API responses
  page.on('response', async (response) => {
    const url = response.url();
    if (url.includes('/api/') && (url.includes('employee') || url.includes('staff'))) {
      try {
        const data = await response.json();
        apiResponses.push({ url: url.split('?')[0], data });
        console.log(`📡 Captured API: ${url.split('?')[0]}`);
      } catch (e) {
        // Not JSON, ignore
      }
    }
  });

  try {
    // Step 1: Navigate to login page
    console.log(`\n📍 Navigating to: ${PERSONIO_URL}`);
    await page.goto(PERSONIO_URL, { waitUntil: 'networkidle' });

    // Step 2: Wait for user to login
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('⏳ PLEASE LOGIN MANUALLY');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('1. Enter your email and password in the browser');
    console.log('2. Complete any 2FA if required');
    console.log('3. Once you see the Personio dashboard, press Enter here\n');

    await ask('Press Enter when logged in...');

    // Check if logged in
    const currentUrl = page.url();
    console.log(`\nCurrent URL: ${currentUrl}`);

    if (currentUrl.includes('/login')) {
      console.log('⚠️  Still on login page. Waiting...');
      await page.waitForTimeout(5000);
      if (page.url().includes('/login')) {
        throw new Error('Still on login page. Please login and try again.');
      }
    }

    // Step 3: Navigate to Staff page
    console.log(`\n📍 Navigating to Staff page: ${STAFF_URL}`);
    await page.goto(STAFF_URL, { waitUntil: 'networkidle' });

    // Wait for staff list to load
    console.log('⏳ Waiting for staff list to load...');
    await page.waitForTimeout(3000);

    // Step 4: Extract employee data
    console.log('\n🔍 Extracting employee data...');

    // Try to extract from page state first
    const employeesFromState = await page.evaluate(() => {
      // Try multiple locations where Personio might store employee data
      const initialState = window.__INITIAL_STATE__ || window.__DATA__ || window.REDUX_INITIAL_STATE || window.__PRELOADED_STATE__;
      if (initialState) {
        // Look for employees in various places
        const employees = initialState.employees ||
                         initialState.staff ||
                         initialState.entities?.employees ||
                         initialState.data?.employees ||
                         initialState.employeeList ||
                         initialState.people;
        if (employees) return employees;
      }
      return null;
    });

    console.log(`Found ${employeesFromState?.length || 0} employees from page state`);

    // Step 5: Also reload to capture API responses
    console.log('\n🔄 Reloading to capture API responses...');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    console.log(`Captured ${apiResponses.length} API responses`);

    // Extract employees from API responses
    let employees = [];

    // Try to find employee array in API responses
    for (const resp of apiResponses) {
      const data = resp.data;
      if (Array.isArray(data)) {
        employees = data;
        break;
      }
      // Check nested structures
      if (data.data && Array.isArray(data.data)) {
        employees = data.data;
        break;
      }
      if (data.employees && Array.isArray(data.employees)) {
        employees = data.employees;
        break;
      }
      if (data.items && Array.isArray(data.items)) {
        employees = data.items;
        break;
      }
    }

    // Use page state if API didn't return data
    if (employees.length === 0 && employeesFromState) {
      employees = Array.isArray(employeesFromState) ? employeesFromState : [employeesFromState];
    }

    console.log(`\n✅ Total employees extracted: ${employees.length}`);

    if (employees.length === 0) {
      console.log('\n⚠️  No employees found. Debug info:');
      console.log('- API responses:', apiResponses.map(r => r.url));
      console.log('- Page state:', employeesFromState ? 'found' : 'not found');
      throw new Error('No employee data extracted');
    }

    // Show sample
    console.log('\nSample employee:', JSON.stringify(employees[0], null, 2));

    // Step 6: Convert to TSV and save
    console.log('\n💾 Converting to TSV...');
    const tsv = convertToTsv(employees);
    const outputPath = join(OUTPUT_DIR, 'personio-staff.tsv');
    writeFileSync(outputPath, tsv);

    console.log(`✅ Saved ${employees.length} employees to: ${outputPath}`);

    // Also save debug JSON
    const debugPath = join(OUTPUT_DIR, 'personio-scrape-debug.json');
    writeFileSync(debugPath, JSON.stringify({
      timestamp: new Date().toISOString(),
      url: page.url(),
      count: employees.length,
      employees: employees.slice(0, 5), // First 5 for debugging
      apiResponses: apiResponses.map(r => ({ url: r.url, keys: Object.keys(r.data) }))
    }, null, 2));
    console.log(`🐛 Debug info saved to: ${debugPath}`);

    // Wait for user to review
    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('Review the data in the browser.');
    await ask('Press Enter to close the browser...');

  } catch (error) {
    console.error('\n❌ Error:', error.message);
    console.error(error.stack);
    await ask('\nPress Enter to close browser...');
  } finally {
    await browser.close();
    rl.close();
    console.log('\n👋 Browser closed.');
  }
}

main().catch(console.error);
