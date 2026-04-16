// tests/test_ui.mjs — Tests for UI module
import { strict as assert } from 'assert';
import * as ui from '../lib/ui.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('UI Module Tests');
console.log('═'.repeat(50));

test('colors.primary wraps text', () => {
  const result = ui.colors.primary('hello');
  assert.ok(result.includes('hello'));
});

test('colors.bold wraps text', () => {
  const result = ui.colors.bold('hello');
  assert.ok(result.includes('hello'));
});

test('icons object has required keys', () => {
  assert.ok(ui.icons.ok);
  assert.ok(ui.icons.error);
  assert.ok(ui.icons.warning);
  assert.ok(ui.icons.bridge);
  assert.ok(ui.icons.active);
});

test('cliIcons has all 3 CLIs', () => {
  assert.ok(ui.cliIcons.claude);
  assert.ok(ui.cliIcons.gemini);
  assert.ok(ui.cliIcons.codex);
});

test('cliLabels has all 3 CLIs', () => {
  assert.strictEqual(ui.cliLabels.claude, 'Claude Code');
  assert.strictEqual(ui.cliLabels.gemini, 'Gemini CLI');
  assert.strictEqual(ui.cliLabels.codex, 'Codex CLI');
});

test('cliIcon returns correct icons', () => {
  assert.strictEqual(ui.cliIcon('claude'), '🟠');
  assert.strictEqual(ui.cliIcon('gemini'), '🔵');
  assert.strictEqual(ui.cliIcon('CLAUDE'), '🟠'); // case insensitive
  assert.strictEqual(ui.cliIcon('unknown'), '⚪');
  assert.strictEqual(ui.cliIcon(null), '⚪');
});

test('humanSize formats correctly', () => {
  assert.strictEqual(ui.humanSize(500), '500B');
  assert.strictEqual(ui.humanSize(2048), '2KB');
  assert.strictEqual(ui.humanSize(1572864), '2MB');
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
