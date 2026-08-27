// tests/test_jungle_up_gcp.mjs — brain-work-on-gcp CLI
import { strict as assert } from 'assert';
import { execFileSync, spawnSync } from 'child_process';
import { mkdtempSync, writeFileSync, chmodSync, readFileSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const SKILL = join(process.env.HOME, '.super/skills/brain-work-on-google-cloud');
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

// ── Task 2: IP detection and firewall ───────────────────────────────────────
test('detect_public_ip returns the first valid address', () => {
  const fake = fakeBin(['curl'], { stdout: '203.0.113.7' });
  const r = callFn('detect_public_ip', { binDir: fake.dir });
  assert.equal(r.status, 0);
  assert.equal(r.stdout.trim(), '203.0.113.7');
});

test('detect_public_ip rejects non-address output and fails', () => {
  const fake = fakeBin(['curl'], { stdout: '<html>captive portal</html>' });
  const r = callFn('detect_public_ip', { binDir: fake.dir });
  assert.equal(r.status, 1);
  assert.equal(r.stdout.trim(), '');
});

test('detect_public_ip tries every service before failing', () => {
  const fake = fakeBin(['curl'], { stdout: '', exitCode: 1 });
  callFn('detect_public_ip', { binDir: fake.dir });
  assert.equal(fake.calls().length, 3, 'expected three fallback services');
});

test('ensure_firewall_rule creates the rule when describe fails', () => {
  const fake = fakeBin(['gcloud'], { exitCode: 1 });
  const r = callFn('PROJECT_ID=p ensure_firewall_rule 203.0.113.7/32', { binDir: fake.dir });
  const create = fake.calls().find(c => c.includes('firewall-rules create'));
  assert.ok(create, `expected a create call, got: ${fake.calls().join(' | ')}`);
  assert.match(create, /--allow=tcp:22,80,443/);
  assert.match(create, /--source-ranges=203\.0\.113\.7\/32/);
  assert.match(create, /--target-tags=jungle-session/);
});

test('ensure_firewall_rule updates the rule when describe succeeds', () => {
  const fake = fakeBin(['gcloud'], { exitCode: 0 });
  callFn('PROJECT_ID=p ensure_firewall_rule 198.51.100.9/32', { binDir: fake.dir });
  const calls = fake.calls();
  assert.ok(calls.some(c => c.includes('firewall-rules update')), 'expected an update call');
  assert.ok(!calls.some(c => c.includes('firewall-rules create')), 'must not create');
});

test('resolve_source_cidr aborts rather than opening the firewall to the world', () => {
  const fake = fakeBin(['curl'], { stdout: '', exitCode: 1 });
  const r = callFn('resolve_source_cidr', { binDir: fake.dir });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /cannot detect/i);
});

test('no code path ever emits 0.0.0.0/0', () => {
  const src = readFileSync(CLI, 'utf8');
  assert.ok(!src.includes('0.0.0.0/0'), 'found an open-world CIDR in the script');
});

// ── Task 3: instance creation, SSH wait, wrappers ───────────────────────────
// SOURCE_IP is passed so these never reach the network for IP detection.
const OFFLINE = { SOURCE_IP: '203.0.113.7/32' };

test('vm_create builds a fresh instance with the spec defaults', () => {
  const fake = fakeBin(['gcloud']);
  const r = callFn('DRY_RUN=1 PROJECT_ID=p vm_create jungle-golden',
    { binDir: fake.dir, env: OFFLINE });
  assert.match(r.stdout, /instances create jungle-golden/);
  assert.match(r.stdout, /--machine-type=e2-standard-8/);
  assert.match(r.stdout, /--boot-disk-size=200GB/);
  assert.match(r.stdout, /--image-family=ubuntu-2404-lts-amd64/);
  assert.match(r.stdout, /--image-project=ubuntu-os-cloud/);
  assert.match(r.stdout, /--tags=jungle-session/);
});

test('vm_create from an image uses source-machine-image and no image-family', () => {
  const fake = fakeBin(['gcloud']);
  const r = callFn('DRY_RUN=1 PROJECT_ID=p vm_create jungle-x --from-image jungle-golden-20260827',
    { binDir: fake.dir, env: OFFLINE });
  assert.match(r.stdout, /--source-machine-image=jungle-golden-20260827/);
  assert.doesNotMatch(r.stdout, /--image-family/);
});

test('vm_ssh routes through gcloud compute ssh', () => {
  const fake = fakeBin(['gcloud']);
  callFn('PROJECT_ID=p ZONE=z vm_ssh jungle-x "docker info"', { binDir: fake.dir, env: OFFLINE });
  const call = fake.calls().find(c => c.includes('compute ssh'));
  assert.ok(call, `expected a compute ssh call, got: ${fake.calls().join(' | ')}`);
  assert.match(call, /jungle-x/);
  assert.match(call, /--command docker info/);
});

test('vm_wait_ssh gives up after the timeout rather than looping forever', () => {
  const fake = fakeBin(['gcloud'], { exitCode: 1 });
  const r = callFn('PROJECT_ID=p ZONE=z SSH_WAIT_TRIES=3 SSH_WAIT_SLEEP=0 vm_wait_ssh jungle-x',
    { binDir: fake.dir, env: OFFLINE });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /did not become reachable/i);
  assert.equal(fake.calls().length, 3);
});

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
