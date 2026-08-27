// tests/test_jungle_up_gcp.mjs — brain-work-on-gcp CLI
import { strict as assert } from 'assert';
import { execFileSync, spawnSync } from 'child_process';
import { mkdtempSync, writeFileSync, chmodSync, readFileSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const SKILL = join(process.env.HOME, '.super/skills/brain-work-on-gcp');
const CLI = join(SKILL, 'jungle_up_gcp.sh');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

// Build a directory of fake executables. Each logs "name arg1 arg2..." to calls.log.
function fakeBin(names, { exitCode = 0, stdout = '' } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'fakebin-'));
  const log = join(dir, 'calls.log');
  for (const n of names) {
    const p = join(dir, n);
    writeFileSync(p, `#!/usr/bin/env bash\nprintf '%s' "${n}" >> "${log}"\nfor a in "$@"; do printf ' %s' "$a" >> "${log}"; done\nprintf '\\n' >> "${log}"\nprintf '%s' ${JSON.stringify(stdout)}\nexit ${exitCode}\n`);
    chmodSync(p, 0o755);
  }
  writeFileSync(log, '');
  return { dir, log, calls: () => readFileSync(log, 'utf8').trim().split('\n').filter(Boolean) };
}

// Run the CLI with a fake PATH prefix.
function runCli(args, { binDir = null, env = {} } = {}) {
  const PATH = binDir ? `${binDir}:${process.env.PATH}` : process.env.PATH;
  return spawnSync('bash', [CLI, ...args], {
    encoding: 'utf8',
    env: { ...process.env, ...env, PATH },
  });
}

// Source the script in library mode and evaluate one expression.
function callFn(expr, { binDir = null, env = {} } = {}) {
  const PATH = binDir ? `${binDir}:${process.env.PATH}` : process.env.PATH;
  return spawnSync('bash', ['-c', `JUNGLE_UP_GCP_LIB=1 source "${CLI}"; ${expr}`], {
    encoding: 'utf8',
    env: { ...process.env, ...env, PATH },
  });
}

console.log('brain-work-on-gcp');
console.log('═'.repeat(50));

// ── Task 1: skeleton ────────────────────────────────────────────────────────
test('script exists and is valid bash', () => {
  assert.ok(existsSync(CLI), `missing ${CLI}`);
  execFileSync('bash', ['-n', CLI]);
});

test('no arguments prints usage and exits 0', () => {
  const r = runCli([]);
  assert.equal(r.status, 0);
  assert.match(r.stdout, /golden build/);
  assert.match(r.stdout, /session create/);
});

test('unknown verb exits 2', () => {
  const r = runCli(['banana']);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /unknown/i);
});

test('library mode defines functions without dispatching', () => {
  const r = callFn('echo "loaded:$(type -t slugify)"');
  assert.equal(r.status, 0);
  assert.match(r.stdout, /loaded:function/);
  assert.doesNotMatch(r.stdout, /golden build/);
});

test('slugify lowercases and replaces invalid characters', () => {
  const r = callFn('slugify "API_Partner Cost/Approval"');
  assert.equal(r.stdout.trim(), 'api-partner-cost-approval');
});

test('instance_name prefixes, joins and truncates to 63', () => {
  const r = callFn('instance_name "api-partner" "cost-approval"');
  assert.equal(r.stdout.trim(), 'jungle-api-partner-cost-approval');
  const long = callFn(`instance_name "${'a'.repeat(40)}" "${'b'.repeat(40)}"`);
  assert.equal(long.stdout.trim().length, 63);
  assert.match(long.stdout.trim(), /^[a-z]/);
});

test('run honours DRY_RUN and prints instead of executing', () => {
  const fake = fakeBin(['gcloud']);
  const r = callFn('DRY_RUN=1 run gcloud compute instances list', { binDir: fake.dir });
  assert.match(r.stdout, /DRY-RUN: gcloud compute instances list/);
  assert.equal(fake.calls().length, 0, 'gcloud must not be invoked under DRY_RUN');
});

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
