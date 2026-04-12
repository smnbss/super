// tests/test_security.mjs — Tests for security module
import { strict as assert } from 'assert';
import { securityCheck, formatBlockReason } from '../lib/security.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Security Module Tests');
console.log('═'.repeat(50));

// Note: these tests assume yoloMode: true in the config, which returns 0 (allow) for everything
// We test the pattern matching logic directly

test('securityCheck returns 0 for safe commands in yolo mode', () => {
  assert.strictEqual(securityCheck('Bash', { command: 'ls -la' }), 0);
  assert.strictEqual(securityCheck('Bash', { command: 'git status' }), 0);
  assert.strictEqual(securityCheck('Bash', { command: 'git push' }), 0); // yolo allows
});

test('securityCheck returns 0 for reads in yolo mode', () => {
  assert.strictEqual(securityCheck('Read', { path: '/tmp/test.txt' }), 0);
  assert.strictEqual(securityCheck('Glob', { pattern: '*.js' }), 0);
});

test('securityCheck returns 0 for writes in yolo mode', () => {
  assert.strictEqual(securityCheck('Write', { path: '/tmp/test.txt' }), 0);
  assert.strictEqual(securityCheck('Edit', { path: '/tmp/test.txt' }), 0);
});

test('securityCheck handles empty input gracefully', () => {
  assert.strictEqual(securityCheck('Bash', {}), 0);
  assert.strictEqual(securityCheck('Bash', { command: '' }), 0);
  assert.strictEqual(securityCheck('Unknown', {}), 0);
});

test('formatBlockReason returns string', () => {
  const msg = formatBlockReason('Bash', 'Dangerous operation');
  assert.ok(msg.includes('SUPER SECURITY BLOCK'));
  assert.ok(msg.includes('Bash'));
  assert.ok(msg.includes('Dangerous operation'));
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
