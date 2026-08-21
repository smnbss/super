// tests/test_claude_skills_shadow.mjs — Verifies how ensureClaudeSkillsDirectory
// (via installPhaseInstall) treats each possible state of .claude/skills/<name>:
//
//   correct symlink  → left alone
//   dangling symlink → re-pointed
//   redundant real dir shadowing .agents/skills → repaired into a symlink
//   DIVERGED real dir                            → left in place, warned about
//
// The shadowing case is the regression under test: a real directory used to be
// counted as "existing" and reported as success, so the two paths silently
// stopped being one store and .agents/skills went stale unnoticed.

import { strict as assert } from 'assert';
import { existsSync, mkdirSync, rmSync, writeFileSync, readFileSync, lstatSync, symlinkSync, readlinkSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

const tmp = join(tmpdir(), `super-skills-shadow-${process.pid}-${Date.now()}`);
mkdirSync(join(tmp, '.super'), { recursive: true });
process.env.SUPER_PROJECT_DIR = tmp;

const home = join(tmp, 'home');
mkdirSync(join(home, '.super'), { recursive: true });
process.env.HOME = home;

const { installPhaseInstall } = await import('../lib/catalog.mjs');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}\n    ${e.stack?.split('\n').slice(1, 3).join('\n    ')}`); failed++; }
}

console.log('.claude/skills shadowing tests');
console.log('═'.repeat(50));

writeFileSync(join(tmp, '.super', 'super.config.yaml'),
  ['system: []', 'clis: []', 'skills: []', 'plugins: []', 'mcps: []', ''].join('\n'));

const agents = join(tmp, '.agents', 'skills');
const claude = join(tmp, '.claude', 'skills');

function skill(name, body) {
  mkdirSync(join(agents, name), { recursive: true });
  writeFileSync(join(agents, name, 'SKILL.md'), body);
}

// Four skills, one per state.
skill('plain', 'canonical plain\n');
skill('dangling', 'canonical dangling\n');
skill('redundant', 'canonical redundant\n');
skill('diverged', 'canonical diverged\n');

mkdirSync(claude, { recursive: true });

// dangling: symlink whose target does not exist
symlinkSync(join('..', '..', '.agents', 'skills', 'gone-away'), join(claude, 'dangling'));

// redundant: real dir with byte-identical content (plus cruft that must be ignored)
mkdirSync(join(claude, 'redundant', '__pycache__'), { recursive: true });
writeFileSync(join(claude, 'redundant', 'SKILL.md'), 'canonical redundant\n');
writeFileSync(join(claude, 'redundant', '__pycache__', 'x.pyc'), 'cache');

// diverged: real dir carrying content that exists nowhere else
mkdirSync(join(claude, 'diverged'), { recursive: true });
writeFileSync(join(claude, 'diverged', 'SKILL.md'), 'LOCAL EDIT worth keeping\n');

installPhaseInstall(['claude'], { debugMode: false });

test('a skill with no .claude entry gets a symlink', () => {
  assert.ok(lstatSync(join(claude, 'plain')).isSymbolicLink(), 'plain should be a symlink');
  assert.equal(readFileSync(join(claude, 'plain', 'SKILL.md'), 'utf8'), 'canonical plain\n');
});

test('a dangling symlink is re-pointed at .agents/skills', () => {
  assert.ok(lstatSync(join(claude, 'dangling')).isSymbolicLink(), 'dangling should still be a symlink');
  assert.equal(readlinkSync(join(claude, 'dangling')), join('..', '..', '.agents', 'skills', 'dangling'));
  assert.equal(readFileSync(join(claude, 'dangling', 'SKILL.md'), 'utf8'), 'canonical dangling\n');
});

test('a redundant shadowing real dir is repaired into a symlink', () => {
  const st = lstatSync(join(claude, 'redundant'));
  assert.ok(st.isSymbolicLink(), 'redundant should have been converted to a symlink');
  assert.equal(readlinkSync(join(claude, 'redundant')), join('..', '..', '.agents', 'skills', 'redundant'));
});

test('a DIVERGED shadowing real dir is left untouched', () => {
  const st = lstatSync(join(claude, 'diverged'));
  assert.ok(!st.isSymbolicLink(), 'diverged must NOT be converted');
  assert.equal(readFileSync(join(claude, 'diverged', 'SKILL.md'), 'utf8'), 'LOCAL EDIT worth keeping\n',
    'diverged content must survive');
});

test('writing through .claude reaches .agents (one store, not two)', () => {
  writeFileSync(join(claude, 'redundant', 'SKILL.md'), 'written via .claude\n');
  assert.equal(readFileSync(join(agents, 'redundant', 'SKILL.md'), 'utf8'), 'written via .claude\n',
    'the whole point: a symlink means one store');
});

test('re-running is idempotent', () => {
  installPhaseInstall(['claude'], { debugMode: false });
  assert.ok(lstatSync(join(claude, 'redundant')).isSymbolicLink());
  assert.ok(lstatSync(join(claude, 'plain')).isSymbolicLink());
  assert.ok(!lstatSync(join(claude, 'diverged')).isSymbolicLink());
});

rmSync(tmp, { recursive: true, force: true });

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
