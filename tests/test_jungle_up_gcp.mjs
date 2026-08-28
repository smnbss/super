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
    writeFileSync(p, `#!/usr/bin/env bash\nprintf '%s' "${n}" >> "${log}"\nfor a in "$@"; do printf ' %s' "$a" >> "${log}"; done\nprintf '\\n' >> "${log}"\nprintf '%b' ${JSON.stringify(stdout)}\nexit ${exitCode}\n`);
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
  assert.match(create, /--allow=tcp:22,tcp:80,tcp:443/);
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

// ── Task 4: VM bootstrap and the AR credential helper ───────────────────────
const BOOTSTRAP = join(SKILL, 'files/vm-bootstrap.sh');
const CREDHELPER = join(SKILL, 'files/docker-credential-gcloudadc');

test('vm-bootstrap.sh is valid bash', () => {
  assert.ok(existsSync(BOOTSTRAP), `missing ${BOOTSTRAP}`);
  execFileSync('bash', ['-n', BOOTSTRAP]);
});

test('vm-bootstrap installs exactly the measured dependency set', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8');
  for (const want of ['docker-ce', 'git', 'curl', 'nodejs', 'corepack', 'google-cloud-sdk']) {
    assert.ok(s.includes(want), `bootstrap must install ${want}`);
  }
});

test('vm-bootstrap installs none of the tooling this design dropped', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8').toLowerCase();
  // claude-code and tmux are NOT in this list. Work must continue while the
  // operator's laptop is closed, so the agent runs on the VM under tmux.
  for (const banned of ['ollama', 'chromium', '@openai/codex',
                        '@google/gemini-cli', 'ubuntu-desktop', 'xrdp', 'super install']) {
    assert.ok(!s.includes(banned.toLowerCase()), `must not install ${banned}`);
  }
});

test('vm-bootstrap installs the detached-agent tooling', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8');
  assert.match(s, /@anthropic-ai\/claude-code/, 'the agent runs on the VM');
  assert.match(s, /tmux/, 'the agent must survive the SSH connection closing');
});

test('vm-bootstrap enables docker under systemd rather than backgrounding dockerd', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8');
  assert.match(s, /systemctl enable --now docker/);
  assert.ok(!/^\s*dockerd\b.*&\s*$/m.test(s), 'must not background dockerd');
});

// Measured against the real jungle on 2026-08-27: its root package.json declares
// no packageManager and no engines, so the root installs with npm, not pnpm.
test('vm-bootstrap installs jungle root deps with npm, not pnpm', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8');
  assert.match(s, /npm install/, 'the jungle root has no packageManager field');
  assert.ok(!/corepack prepare pnpm@latest/.test(s),
    'pnpm@latest triggers MINIMUM_RELEASE_AGE_VIOLATION');
});

// corepack's default pnpm 11 crashes on Node 20 with ERR_UNKNOWN_BUILTIN_MODULE.
test('vm-bootstrap installs Node 22, not Node 20', () => {
  const s = readFileSync(BOOTSTRAP, 'utf8');
  assert.match(s, /setup_22\.x/);
  assert.ok(!s.includes('setup_20.x'), 'Node 20 is too old for corepack pnpm 11');
});

test('credential helper exists and reads the ADC', () => {
  assert.ok(existsSync(CREDHELPER), `missing ${CREDHELPER}`);
  const s = readFileSync(CREDHELPER, 'utf8');
  assert.match(s, /application_default_credentials\.json/);
  assert.match(s, /oauth2\.googleapis\.com\/token/);
});

// ── Task 5: credentials ─────────────────────────────────────────────────────
test('inject_credentials copies all four credential paths', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z CRED_ADC=/tmp/adc CRED_NPMRC=/tmp/npmrc ' +
                   'CRED_COMPOSER=/tmp/auth SKIP_CRED_CHECK=1 inject_credentials jungle-x');
  for (const p2 of ['application_default_credentials\\.json', '\\.npmrc', 'auth\\.json', 'config\\.json']) {
    assert.match(r.stdout, new RegExp(p2), `must handle ${p2}`);
  }
});

test('inject_credentials fails with actionable guidance when the ADC is missing', () => {
  const r = callFn('CRED_ADC=/nope/adc.json inject_credentials jungle-x');
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /application-default login/);
});

test('scrub_credentials deletes the four paths on the VM', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z scrub_credentials jungle-x');
  assert.match(r.stdout, /rm -f/);
  assert.match(r.stdout, /application_default_credentials\.json/);
  assert.match(r.stdout, /\.npmrc/);
  assert.match(r.stdout, /auth\.json/);
});

// ⚠️ This test protects the operator's laptop. Do not weaken it.
test('the skill NEVER revokes application-default credentials', () => {
  const files = ['jungle_up_gcp.sh', 'files/vm-bootstrap.sh', 'SKILL.md']
    .map(f => join(SKILL, f)).filter(existsSync);
  assert.ok(files.length > 0, 'expected at least one file to scan');
  for (const f of files) {
    const offending = readFileSync(f, 'utf8').split('\n').filter(l =>
      /application-default\s+revoke/.test(l) && !/never|not |do not|forbid/i.test(l));
    assert.equal(offending.length, 0, `${f} contains a live revoke: ${offending.join(' | ')}`);
  }
});

// ── Task 6: golden build ────────────────────────────────────────────────────
const GOLDEN_ENV = { SOURCE_IP: '203.0.113.7/32', SKIP_CRED_CHECK: '1' };

test('golden build runs its phases in the required order', () => {
  const r = runCli(['golden', 'build', '--dry-run', '--project', 'p'], { env: GOLDEN_ENV });
  const out = r.stdout;
  const at = (re) => out.search(re);
  assert.ok(at(/instances create jungle-golden/) >= 0, `creates the instance; got:\n${out}`);
  assert.ok(at(/repo\.init\.sh/) > at(/instances create jungle-golden/), 'clones after create');
  assert.ok(at(/staging-images\.update\.sh/) > at(/repo\.init\.sh/), 'images after clone');
  assert.ok(at(/database\.restore\.sh/) > at(/staging-images\.update\.sh/), 'restore after images');
  assert.ok(at(/rm -f .*application_default_credentials/) > at(/database\.restore\.sh/),
    'scrubs after the restore');
  assert.ok(at(/machine-images create/) > at(/rm -f .*application_default_credentials/),
    'captures the image only after the scrub');
});

test('golden build stops the instance before capturing the image', () => {
  const r = runCli(['golden', 'build', '--dry-run', '--project', 'p'], { env: GOLDEN_ENV });
  assert.ok(r.stdout.search(/instances stop jungle-golden/) < r.stdout.search(/machine-images create/),
    'stop must precede capture');
});

test('golden build runs hosts.init.sh on the VM and never locally', () => {
  const r = runCli(['golden', 'build', '--dry-run', '--project', 'p'], { env: GOLDEN_ENV });
  const line = r.stdout.split('\n').find(l => l.includes('hosts.init.sh'));
  assert.ok(line, 'expected hosts.init.sh');
  assert.match(line, /vm_ssh|compute ssh/, 'hosts.init.sh must run over SSH on the VM');
});

test('parse_common_flags rejects an unknown option instead of ignoring it', () => {
  const r = runCli(['golden', 'build', '--wat'], { env: GOLDEN_ENV });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /unknown option/);
});

// ── Task 7: session state and session create ────────────────────────────────
test('state_write then state_read round-trips a value', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  const r = callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a ip=203.0.113.5; ` +
                   `WORKSPACE_ROOT=${ws} state_read s1 ip`);
  assert.equal(r.stdout.trim(), '203.0.113.5');
});

test('state file lands in the session workspace', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a`);
  assert.ok(existsSync(join(ws, 's1/.jungle-vm.json')), 'expected <ws>/<session>/.jungle-vm.json');
});

test('session create refuses when no golden image exists', () => {
  const fake = fakeBin(['gcloud'], { stdout: '' });
  const r = runCli(['session', 'create', 'api-partner', 'cost-approval', '--project', 'p'],
    { binDir: fake.dir, env: { SOURCE_IP: '203.0.113.7/32' } });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /golden build/, 'the error must name the fix');
});

test('session create derives the instance name from repo and session', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  const r = runCli(['session', 'create', 'api-partner', 'cost-approval', '--dry-run', '--project', 'p'],
    { env: { GOLDEN_IMAGE_OVERRIDE: 'jungle-golden-20260827', SOURCE_IP: '203.0.113.7/32',
             SKIP_CRED_CHECK: '1', WORKSPACE_ROOT: ws } });
  assert.match(r.stdout, /instances create jungle-api-partner-cost-approval/);
  assert.match(r.stdout, /--source-machine-image=jungle-golden-20260827/);
});

test('session create pulls before branching', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  const r = runCli(['session', 'create', 'api-partner', 'cost-approval', '--dry-run', '--project', 'p'],
    { env: { GOLDEN_IMAGE_OVERRIDE: 'jungle-golden-20260827', SOURCE_IP: '203.0.113.7/32',
             SKIP_CRED_CHECK: '1', WORKSPACE_ROOT: ws } });
  assert.ok(r.stdout.search(/git pull/) < r.stdout.search(/git switch -c cost-approval/),
    'pull must precede the branch');
});

test('session create warns when the golden image is older than 7 days', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  const r = runCli(['session', 'create', 'api-partner', 'x', '--dry-run', '--project', 'p'],
    { env: { GOLDEN_IMAGE_OVERRIDE: 'jungle-golden-20200101', SOURCE_IP: '203.0.113.7/32',
             SKIP_CRED_CHECK: '1', WORKSPACE_ROOT: ws } });
  assert.match(r.stderr, /older than 7 days/i);
});

// ── Task 8: mount verbs, preflight, Chrome ──────────────────────────────────
// PATH must still resolve bash itself, so use the system dirs. Neither carries
// sshfs — brew installs it under /opt/homebrew/bin.
const CLEAN_PATH = '/usr/bin:/bin';

test('mount preflight fails with install guidance when sshfs is absent', () => {
  const r = spawnSync('bash', ['-c', `JUNGLE_UP_GCP_LIB=1 source "${CLI}"; mount_preflight`],
    { encoding: 'utf8', env: { ...process.env, PATH: CLEAN_PATH } });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /macos-fuse-t\/homebrew-cask\/fuse-t/);
});

// The skill must not install a contested-licence dependency behind the user's back.
test('mount preflight states the licence conflict and names the fallback', () => {
  const r = spawnSync('bash', ['-c', `JUNGLE_UP_GCP_LIB=1 source "${CLI}"; mount_preflight`],
    { encoding: 'utf8', env: { ...process.env, PATH: CLEAN_PATH } });
  assert.match(r.stderr, /licen[cs]e/i);
  assert.match(r.stderr, /mutagen/i, 'must name the MIT fallback');
});

test('session mount uses the reconnect options and the GCE key', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a ip=203.0.113.5 mount=/tmp/m-s1`);
  const fake = fakeBin(['sshfs']);
  const r = callFn(`WORKSPACE_ROOT=${ws} DRY_RUN=1 cmd_session_mount s1`, { binDir: fake.dir });
  assert.match(r.stdout, /reconnect/);
  assert.match(r.stdout, /ServerAliveInterval=15/);
  assert.match(r.stdout, /google_compute_engine/);
});

test('chrome_command isolates the profile and maps the wildcard host', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a ip=203.0.113.5`);
  const r = callFn(`WORKSPACE_ROOT=${ws} chrome_command s1`);
  assert.match(r.stdout, /--user-data-dir=/);
  assert.match(r.stdout, /--host-resolver-rules="MAP \*\.weroad\.wr 203\.0\.113\.5"/);
  assert.match(r.stdout, /--no-first-run/);
});

// ── Task 8b: GitHub auth on the VM (repos.sh uses git@github.com SSH URLs) ──
test('inject_credentials rewrites git@github.com to token HTTPS', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z SKIP_CRED_CHECK=1 GITHUB_TOKEN=ghp_test ' +
                   'inject_credentials jungle-x');
  assert.match(r.stdout, /insteadOf/, 'the VM has no GitHub SSH key; repos.sh uses git@ URLs');
  assert.match(r.stdout, /git-credentials/);
});

test('the GitHub token never appears in a dry-run transcript', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z SKIP_CRED_CHECK=1 GITHUB_TOKEN=ghp_SECRET123 ' +
                   'inject_credentials jungle-x');
  assert.ok(!r.stdout.includes('ghp_SECRET123'), 'a token must never be echoed');
  assert.ok(!r.stderr.includes('ghp_SECRET123'), 'a token must never be echoed');
});

test('scrub removes the git credential files too', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z scrub_credentials jungle-x');
  assert.match(r.stdout, /git-credentials/, 'the token lands in ~/.git-credentials');
  assert.match(r.stdout, /gitconfig/, 'the insteadOf rewrite lands in ~/.gitconfig');
});

// ── Task 9: stack derivation, bring-up, render check ────────────────────────
test('derive_services asks compose and never hardcodes a service list', () => {
  const src = readFileSync(CLI, 'utf8');
  assert.match(src, /compose\.yaml config --services/);
  assert.ok(!src.includes('laravel.api-partner.weroad.wr'),
    'service names must be derived, not hardcoded');
});

test('stack_up starts the reverse proxy, then infra, then the services', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z stack_up jungle-x api-partner ' +
                   '"api-partner.weroad.wr laravel.api-partner.weroad.wr"');
  const at = (re) => r.stdout.search(re);
  assert.ok(at(/reverseproxy-expose\.yaml/) >= 0, `got:\n${r.stdout}`);
  assert.ok(at(/postgresql\.weroad\.wr/) > at(/reverseproxy-expose\.yaml/));
  assert.ok(at(/laravel\.api-partner\.weroad\.wr/) > at(/postgresql\.weroad\.wr/));
});

test('stack_up passes --no-deps so sibling APIs are not started', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z stack_up jungle-x api-partner "api-partner.weroad.wr"');
  assert.match(r.stdout, /--no-deps/);
});

// Measured on a real GCE Ubuntu 24.04 VM, 2026-08-27: /proc/net/if_inet6 IS
// present, php-fpm bound without the override, and the stack served 200. DVO-419
// does not apply here. The probe stays so an IPv6-less host still works.
test('the IPv4 php-fpm pool is mounted only when the VM lacks IPv6', () => {
  const src = readFileSync(CLI, 'utf8');
  assert.match(src, /proc\/net\/if_inet6/, 'must probe rather than assume');
  const conf = join(SKILL, 'files/zz-apko.conf');
  assert.ok(existsSync(conf));
  assert.match(readFileSync(conf, 'utf8'), /listen = 0\.0\.0\.0:9000/);
});

test('verify_render rejects a 200 with an empty body', () => {
  const fake = fakeBin(['gcloud'], { stdout: '200 12' });
  const r = callFn('PROJECT_ID=p ZONE=z verify_render jungle-x partner.weroad.wr',
    { binDir: fake.dir });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /empty shell/i);
});

test('verify_render accepts a real body', () => {
  const fake = fakeBin(['gcloud'], { stdout: '200 45210' });
  const r = callFn('PROJECT_ID=p ZONE=z verify_render jungle-x partner.weroad.wr',
    { binDir: fake.dir });
  assert.equal(r.status, 0);
});

// ── Task 10: list, stop, rm and the two gates ───────────────────────────────
test('session rm REFUSES to delete when the branch is unpushed', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a repo=api-partner branch=s1 mount=/tmp/m-x`);
  const fake = fakeBin(['gcloud'], { exitCode: 1 });
  const r = callFn(`WORKSPACE_ROOT=${ws} PROJECT_ID=p ZONE=z cmd_session_rm s1`, { binDir: fake.dir });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /not pushed/i);
  assert.ok(!fake.calls().some(c => c.includes('instances delete')), 'must not delete the VM');
});

test('session rm unmounts and scrubs before it deletes', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a repo=api-partner branch=s1 mount=/tmp/m-x`);
  const r = callFn(`WORKSPACE_ROOT=${ws} DRY_RUN=1 PROJECT_ID=p ZONE=z BRANCH_PUSHED=1 cmd_session_rm s1`);
  const at = (re) => r.stdout.search(re);
  assert.ok(at(/rm -f .*application_default_credentials/) < at(/instances delete/),
    'scrub must precede delete');
  assert.ok(at(/instances delete/) >= 0);
});

test('session list surfaces cost, because forgotten VMs are the real risk', () => {
  const fake = fakeBin(['gcloud'], { stdout: 'jungle-a RUNNING 2026-08-27T08:00:00Z\n' });
  const r = callFn('PROJECT_ID=p ZONE=z cmd_session_list', { binDir: fake.dir });
  assert.match(r.stdout, /EUR/);
});

test('the agent starts detached under tmux, so it survives a closed laptop', () => {
  const ws = mkdtempSync(join(tmpdir(), 'ws-'));
  callFn(`WORKSPACE_ROOT=${ws} state_write s1 vm=jungle-a repo=api-partner branch=s1`);
  const r = callFn(`WORKSPACE_ROOT=${ws} DRY_RUN=1 PROJECT_ID=p ZONE=z cmd_agent_start s1 "fix the thing"`);
  assert.match(r.stdout, /tmux new-session -d/, 'must be detached');
  assert.match(r.stdout, /claude /);
});

// ── Task 11: SKILL.md ───────────────────────────────────────────────────────
test('SKILL.md has frontmatter with name and description', () => {
  const p2 = join(SKILL, 'SKILL.md');
  assert.ok(existsSync(p2), `missing ${p2}`);
  const t = readFileSync(p2, 'utf8');
  assert.match(t, /^---\n[\s\S]*?name: brain-work-on-google-cloud\n[\s\S]*?\n---/);
  assert.match(t, /description: /);
});

test('SKILL.md records the decisions a future reader must not re-litigate', () => {
  const t = readFileSync(join(SKILL, 'SKILL.md'), 'utf8');
  assert.match(t, /setup_gcp\.sh/, 'why it duplicates setup_gcp.sh');
  assert.match(t, /NEVER|never/, 'the never-revoke rule');
  assert.match(t, /licen[cs]e/i, 'the Fuse-T licence position');
  assert.match(t, /brain-work-on/, 'the duplicated Linear conventions');
  assert.match(t, /laptop is closed/, 'why the agent runs on the VM');
});

test('SKILL.md carries the measured findings, not predictions', () => {
  const t = readFileSync(join(SKILL, 'SKILL.md'), 'utf8');
  for (const fact of ['tcp:22,tcp:80,tcp:443', '127.0.0.1:80', 'git@github.com:',
                      'packageManager', 'ERR_UNKNOWN_BUILTIN_MODULE',
                      'dlt-pipelines', 'IPv6', 'caches the php-fpm upstream']) {
    assert.ok(t.includes(fact), `SKILL.md must record: ${fact}`);
  }
});

test('SKILL.md uses no semicolons in prose', () => {
  const t = readFileSync(join(SKILL, 'SKILL.md'), 'utf8');
  let inFence = false;
  const offenders = [];
  for (const line of t.split('\n')) {
    if (line.trim().startsWith('```')) { inFence = !inFence; continue; }
    if (!inFence && !line.includes('`') && !line.startsWith('    ') && line.includes(';')) {
      offenders.push(line.trim());
    }
  }
  assert.equal(offenders.length, 0, `semicolons in prose: ${offenders.slice(0,3).join(' | ')}`);
});

// Regression: wait_for_fpm ignored DRY_RUN and looped 60 x 10s inside the
// stack_up test, turning a unit test into a ten-minute hang.
test('every wait loop honours DRY_RUN', () => {
  const src = readFileSync(CLI, 'utf8');
  for (const fn of ['wait_for_fpm', 'wait_for_databases']) {
    const body = src.slice(src.indexOf(`${fn}()`), src.indexOf(`${fn}()`) + 600);
    assert.match(body, /DRY_RUN/, `${fn} must short-circuit under DRY_RUN`);
  }
});

// ── Agent auth: Claude models, not LiteLLM ──────────────────────────────────
test('the skill never routes the agent through LiteLLM', () => {
  for (const f of ['jungle_up_gcp.sh', 'SKILL.md']) {
    const t = readFileSync(join(SKILL, f), 'utf8');
    const live = t.split('\n').filter(l =>
      /LITELLM|ANTHROPIC_BASE_URL/.test(l) && !/removed|not go through|never|Do not/i.test(l));
    assert.equal(live.length, 0, `${f} still routes through LiteLLM: ${live.join(' | ')}`);
  }
});

test('inject_agent_auth writes an OAuth token when one is set', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z CLAUDE_CODE_OAUTH_TOKEN=tok inject_agent_auth jungle-x');
  assert.match(r.stdout, /claude-env/);
  assert.ok(!r.stdout.includes('tok'), 'the token must never be echoed');
});

test('inject_agent_auth falls back to ANTHROPIC_API_KEY', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z ANTHROPIC_API_KEY=k inject_agent_auth jungle-x');
  assert.match(r.stdout, /claude-env/);
});

test('inject_agent_auth names setup-token when no credential exists', () => {
  const r = callFn('DRY_RUN=1 PROJECT_ID=p ZONE=z CLAUDE_CODE_OAUTH_TOKEN= ANTHROPIC_API_KEY= inject_agent_auth jungle-x');
  assert.match(r.stderr, /setup-token/);
});

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
