// lib/validators.mjs — Project validators (lint/typecheck)
// Replaces validators.sh

import { execSync } from 'child_process';
import { configGet } from './config.mjs';

export function runLint() {
  const cmd = configGet('project.lintCommand');
  if (!cmd) return true;
  console.log('\n🔍 Running lint...');
  try { execSync(cmd, { stdio: 'inherit' }); console.log('✓ Lint passed'); return true; }
  catch { console.log('✗ Lint failed'); return false; }
}

export function runTypecheck() {
  const cmd = configGet('project.typeCheckCommand');
  if (!cmd) return true;
  console.log('\n🔍 Running type check...');
  try { execSync(cmd, { stdio: 'inherit' }); console.log('✓ Type check passed'); return true; }
  catch { console.log('✗ Type check failed'); return false; }
}

export function runValidators() {
  return runLint() && runTypecheck();
}
