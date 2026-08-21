// tests/test_resync_cwd.mjs — bin/resync-vendored-skills must not depend on cwd,
// and must never exit 0 having verified nothing.
//
// The original discovered the brain via a bare `$PWD/.claude/skills` test, so
// running it from anywhere else — $SUPER_HOME, or any SUBDIRECTORY of the brain —
// silently checked one fewer copy and still printed "0 copy(ies) checked · 0
// drifted" and exited 0. That is indistinguishable from "everything is in sync",
// which is the whole failure mode: a clean all-clear that verified nothing.

import { strict as assert } from 'assert';
import { mkdirSync, writeFileSync, rmSync, copyFileSync, chmodSync, symlinkSync, readFileSync } from 'fs';
import { join, dirname } from 'path';
import { tmpdir } from 'os';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';

const REAL_SCRIPT = join(dirname(fileURLToPath(import.meta.url)), '..', 'bin', 'resync-vendored-skills');

const tmp = join(tmpdir(), `super-resync-cwd-${process.pid}-${Date.now()}`);
const fakeSuper = join(tmp, 'super');
const fakeHome = join(tmp, 'home');
const brain = join(tmp, 'brain');

// A canonical super install: the script plus one built-in skill.
mkdirSync(join(fakeSuper, 'bin'), { recursive: true });
mkdirSync(join(fakeSuper, 'skills', 'demo'), { recursive: true });
copyFileSync(REAL_SCRIPT, join(fakeSuper, 'bin', 'resync-vendored-skills'));
chmodSync(join(fakeSuper, 'bin', 'resync-vendored-skills'), 0o755);
writeFileSync(join(fakeSuper, 'skills', 'demo', 'SKILL.md'), 'CANONICAL v2\n');

// A brain checkout: .super marker, the .agents store (drifted), and the
// .claude view symlinked into it — the real layout.
mkdirSync(join(brain, '.super'), { recursive: true });
mkdirSync(join(brain, '.agents', 'skills', 'demo'), { recursive: true });
mkdirSync(join(brain, '.claude', 'skills'), { recursive: true });
mkdirSync(join(brain, 'memory', 'L2'), { recursive: true });
writeFileSync(join(brain, '.agents', 'skills', 'demo', 'SKILL.md'), 'STALE v1\n');
symlinkSync(join('..', '..', '.agents', 'skills', 'demo'), join(brain, '.claude', 'skills', 'demo'));

// An empty $HOME so the script's user-scope candidates don't exist and the test
// is isolated from the real machine.
mkdirSync(fakeHome, { recursive: true });

const script = join(fakeSuper, 'bin', 'resync-vendored-skills');

function run(cwd, args = [], extraEnv = {}) {
  const env = { ...process.env, HOME: fakeHome, SUPER_HOME: fakeSuper, ...extraEnv };
  delete env.BRAIN_ROOT; delete env.SUPER_PROJECT_DIR;
  Object.assign(env, extraEnv);
  try {
    const stdout = execFileSync(script, args, { cwd, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    return { code: 0, out: stdout };
  } catch (e) {
    return { code: e.status ?? -1, out: `${e.stdout || ''}${e.stderr || ''}` };
  }
}
const checkedCount = (out) => Number((out.match(/resync: (\d+) copy\(ies\) checked/) || [])[1] ?? -1);

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('resync-vendored-skills cwd-independence tests');
console.log('═'.repeat(50));

test('from the brain root: finds the copies and reports drift', () => {
  const r = run(brain, ['--check']);
  assert.ok(checkedCount(r.out) >= 1, `expected >=1 copy checked, got:\n${r.out}`);
  assert.equal(r.code, 1, '--check must exit 1 on drift');
});

test('from a SUBDIRECTORY of the brain: same result (walks up)', () => {
  const r = run(join(brain, 'memory', 'L2'), ['--check']);
  assert.ok(checkedCount(r.out) >= 1, `subdirectory must still find the brain:\n${r.out}`);
  assert.equal(r.code, 1);
});

test('from $SUPER_HOME: refuses to pass having checked nothing', () => {
  const r = run(fakeSuper, ['--check']);
  assert.equal(checkedCount(r.out), 0, 'no brain is reachable from there');
  assert.equal(r.code, 1, 'MUST NOT exit 0 after verifying nothing');
  assert.match(r.out, /FAILED — no distribution copy was checked/);
  assert.match(r.out, /No brain checkout found/);
});

test('BRAIN_ROOT overrides cwd entirely', () => {
  const r = run(fakeSuper, ['--check'], { BRAIN_ROOT: brain });
  assert.ok(checkedCount(r.out) >= 1, `BRAIN_ROOT must be honoured:\n${r.out}`);
});

test('SUPER_PROJECT_DIR works too (same override super honours)', () => {
  const r = run(fakeSuper, ['--check'], { SUPER_PROJECT_DIR: brain });
  assert.ok(checkedCount(r.out) >= 1, `SUPER_PROJECT_DIR must be honoured:\n${r.out}`);
});

test('the walk never mistakes $HOME for a brain', () => {
  // Give $HOME both markers — the shape that made the first version of this fix
  // report "Brain found at /Users/basso".
  mkdirSync(join(fakeHome, '.super'), { recursive: true });
  mkdirSync(join(fakeHome, '.agents', 'skills'), { recursive: true });
  const r = run(fakeHome, ['--check']);
  assert.equal(checkedCount(r.out), 0, '$HOME must never be accepted as the brain');
  assert.equal(r.code, 1);
});

test('fix mode actually resyncs, and writes through to the shared store', () => {
  const r = run(brain, []);
  assert.equal(r.code, 0, `fix run should succeed:\n${r.out}`);
  // .claude/skills/demo is a symlink into .agents/skills/demo, so one store.
  assert.equal(readFileSync(join(brain, '.agents', 'skills', 'demo', 'SKILL.md'), 'utf8'), 'CANONICAL v2\n');
  assert.equal(readFileSync(join(brain, '.claude', 'skills', 'demo', 'SKILL.md'), 'utf8'), 'CANONICAL v2\n');
});

test('a clean tree then reports in sync and exits 0', () => {
  const r = run(brain, ['--check']);
  assert.equal(r.code, 0, `clean tree must exit 0:\n${r.out}`);
  assert.ok(checkedCount(r.out) >= 1);
});

rmSync(tmp, { recursive: true, force: true });

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
