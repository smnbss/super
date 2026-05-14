// tests/test_catalog.mjs — Tests for catalog module
import { strict as assert } from 'assert';
import { isInstalled, installedClis, computeYoloSettingsUpdate } from '../lib/catalog.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Catalog Module Tests');
console.log('═'.repeat(50));

test('isInstalled detects claude', () => {
  // Should be installed on this machine
  assert.strictEqual(isInstalled('claude'), true);
});

test('isInstalled returns false for nonexistent CLI', () => {
  assert.strictEqual(isInstalled('nonexistent-cli-xyz'), false);
});

test('installedClis returns array of strings', () => {
  const clis = installedClis();
  assert.ok(Array.isArray(clis));
  assert.ok(clis.length > 0, 'Should have at least one CLI installed');
  assert.ok(clis.includes('claude'), 'Should include claude');
});

test('installedClis only returns valid CLI names', () => {
  const valid = ['claude', 'gemini', 'codex'];
  const clis = installedClis();
  for (const cli of clis) {
    assert.ok(valid.includes(cli), `Unexpected CLI: ${cli}`);
  }
});

// ─── computeYoloSettingsUpdate ───────────────────────────────────────────
console.log('\ncomputeYoloSettingsUpdate');
console.log('═'.repeat(50));

test('yolo on, no existing file → set', () => {
  const r = computeYoloSettingsUpdate({}, true, false);
  assert.strictEqual(r.action, 'set');
  assert.strictEqual(r.settings.permissions.defaultMode, 'bypassPermissions');
});

test('yolo on, empty existing settings → set', () => {
  const r = computeYoloSettingsUpdate({}, true, true);
  assert.strictEqual(r.action, 'set');
  assert.strictEqual(r.settings.permissions.defaultMode, 'bypassPermissions');
});

test('yolo on, preserves other top-level keys', () => {
  const existing = { env: { FOO: 'bar' }, mcpServers: { x: { url: 'y' } } };
  const r = computeYoloSettingsUpdate(existing, true, true);
  assert.strictEqual(r.action, 'set');
  assert.deepStrictEqual(r.settings.env, { FOO: 'bar' });
  assert.deepStrictEqual(r.settings.mcpServers, { x: { url: 'y' } });
  assert.strictEqual(r.settings.permissions.defaultMode, 'bypassPermissions');
});

test('yolo on, preserves other permissions keys (allow/deny/ask)', () => {
  const existing = { permissions: { allow: ['Bash(git *)'], deny: [], ask: [] } };
  const r = computeYoloSettingsUpdate(existing, true, true);
  assert.strictEqual(r.action, 'set');
  assert.deepStrictEqual(r.settings.permissions.allow, ['Bash(git *)']);
  assert.deepStrictEqual(r.settings.permissions.deny, []);
  assert.strictEqual(r.settings.permissions.defaultMode, 'bypassPermissions');
});

test('yolo on, already set → skip', () => {
  const existing = { permissions: { defaultMode: 'bypassPermissions' } };
  const r = computeYoloSettingsUpdate(existing, true, true);
  assert.strictEqual(r.action, 'skip');
  assert.match(r.message, /already set/);
});

test('yolo on, manual override (acceptEdits) → skip (do not clobber)', () => {
  const existing = { permissions: { defaultMode: 'acceptEdits' } };
  const r = computeYoloSettingsUpdate(existing, true, true);
  assert.strictEqual(r.action, 'skip');
  assert.match(r.message, /manual override/);
  // Original value untouched
  assert.strictEqual(r.settings.permissions.defaultMode, 'acceptEdits');
});

test('yolo off, no file → skip', () => {
  const r = computeYoloSettingsUpdate({}, false, false);
  assert.strictEqual(r.action, 'skip');
});

test('yolo off, file exists but key absent → skip', () => {
  const existing = { env: { FOO: 'bar' } };
  const r = computeYoloSettingsUpdate(existing, false, true);
  assert.strictEqual(r.action, 'skip');
});

test('yolo off, key was set by super → remove', () => {
  const existing = { permissions: { defaultMode: 'bypassPermissions' } };
  const r = computeYoloSettingsUpdate(existing, false, true);
  assert.strictEqual(r.action, 'remove');
  assert.strictEqual(r.settings.permissions, undefined, 'empty permissions object cleaned up');
});

test('yolo off, key set + sibling permissions → remove key only, keep siblings', () => {
  const existing = { permissions: { defaultMode: 'bypassPermissions', allow: ['Bash(git *)'] } };
  const r = computeYoloSettingsUpdate(existing, false, true);
  assert.strictEqual(r.action, 'remove');
  assert.strictEqual(r.settings.permissions.defaultMode, undefined);
  assert.deepStrictEqual(r.settings.permissions.allow, ['Bash(git *)']);
});

test('yolo off, manual override (acceptEdits) → skip (not super-managed)', () => {
  const existing = { permissions: { defaultMode: 'acceptEdits' } };
  const r = computeYoloSettingsUpdate(existing, false, true);
  assert.strictEqual(r.action, 'skip');
  // Original untouched
  assert.strictEqual(r.settings.permissions.defaultMode, 'acceptEdits');
});

test('does not mutate the input object', () => {
  const existing = { permissions: { allow: ['x'] } };
  const before = JSON.stringify(existing);
  computeYoloSettingsUpdate(existing, true, true);
  assert.strictEqual(JSON.stringify(existing), before);
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
