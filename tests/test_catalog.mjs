// tests/test_catalog.mjs — Tests for catalog module
import { strict as assert } from 'assert';
import { isInstalled, installedClis } from '../lib/catalog.mjs';

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
  const valid = ['claude', 'gemini', 'codex', 'kimi'];
  const clis = installedClis();
  for (const cli of clis) {
    assert.ok(valid.includes(cli), `Unexpected CLI: ${cli}`);
  }
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
