// tests/test_antigravity.mjs — Antigravity CLI (agy) support
import { strict as assert } from 'assert';
import { existsSync, readFileSync, accessSync, constants } from 'fs';
import { join, dirname, isAbsolute } from 'path';
import { fileURLToPath } from 'url';
import { mergeAgyHooks } from '../lib/catalog.mjs';

const HOME = join(dirname(fileURLToPath(import.meta.url)), '..');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Antigravity CLI (agy) Support Tests');
console.log('═'.repeat(50));

// ─── hooks.json.template ───────────────────────────────────────────────────
const templatePath = join(HOME, 'hooks', 'antigravity', 'hooks.json.template');

test('hooks.json.template exists', () => {
  assert.ok(existsSync(templatePath), 'template missing');
});

test('template resolves to valid named-hook JSON with expected events', () => {
  const raw = readFileSync(templatePath, 'utf8').replace(/\{\{SUPER_HOME\}\}/g, HOME);
  const data = JSON.parse(raw);
  // Top-level key is the named hook (agy shape), not a `hooks` wrapper.
  assert.ok(data.super, 'expected a "super" named hook');
  assert.ok(!data.hooks, 'must NOT use the claude/codex `hooks` wrapper shape');
  for (const ev of ['PreInvocation', 'PostInvocation', 'PostToolUse', 'Stop']) {
    assert.ok(Array.isArray(data.super[ev]), `missing event ${ev}`);
  }
});

test('every hook command is an ABSOLUTE path to an existing executable script', () => {
  const raw = readFileSync(templatePath, 'utf8').replace(/\{\{SUPER_HOME\}\}/g, HOME);
  const data = JSON.parse(raw);
  for (const events of Object.values(data)) {
    for (const defs of Object.values(events)) {
      for (const def of defs) {
        for (const h of def.hooks || []) {
          assert.ok(isAbsolute(h.command), `command not absolute: ${h.command}`);
          assert.ok(existsSync(h.command), `script missing: ${h.command}`);
          accessSync(h.command, constants.X_OK); // throws if not executable
          assert.ok(typeof h.timeout === 'number', 'timeout must be a number (seconds)');
        }
      }
    }
  }
});

test('unexpanded template still carries the {{SUPER_HOME}} placeholder', () => {
  const raw = readFileSync(templatePath, 'utf8');
  assert.ok(raw.includes('{{SUPER_HOME}}'), 'template should use {{SUPER_HOME}} placeholder');
});

// ─── mergeAgyHooks ───────────────────────────────────────────────────────────
console.log('\nmergeAgyHooks');

const sampleDef = (cmd) => [{ hooks: [{ type: 'command', command: cmd, timeout: 10 }] }];

test('merges into empty existing', () => {
  const out = mergeAgyHooks({}, { super: { Stop: sampleDef('/x/stop.sh') } });
  assert.deepStrictEqual(out.super.Stop, sampleDef('/x/stop.sh'));
});

test('is idempotent — re-merging the same data does not duplicate handlers', () => {
  const data = { super: { PostToolUse: sampleDef('/x/post.sh') } };
  let out = mergeAgyHooks({}, data);
  out = mergeAgyHooks(out, JSON.parse(JSON.stringify(data)));
  assert.strictEqual(out.super.PostToolUse.length, 1, 'handler duplicated on re-merge');
});

test('preserves a user-defined named hook alongside super', () => {
  const existing = { 'my-linter': { PreToolUse: sampleDef('/u/lint.sh') } };
  const out = mergeAgyHooks(existing, { super: { Stop: sampleDef('/x/stop.sh') } });
  assert.ok(out['my-linter'], 'user hook dropped');
  assert.ok(out.super, 'super hook not added');
});

test('adds a new event to an existing super hook without clobbering', () => {
  const existing = { super: { Stop: sampleDef('/x/stop.sh') } };
  const out = mergeAgyHooks(existing, { super: { PreInvocation: sampleDef('/x/pre.sh') } });
  assert.ok(out.super.Stop, 'existing event lost');
  assert.ok(out.super.PreInvocation, 'new event not added');
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
