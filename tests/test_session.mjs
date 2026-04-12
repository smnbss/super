// tests/test_session.mjs — Tests for session module
import { strict as assert } from 'assert';
import { existsSync, mkdirSync, rmSync, readFileSync } from 'fs';
import { join } from 'path';
import { sessionNew, sessionResume, sessionList, sessionAppendTurn, sessionGetSummary, sessionCleanupOld, sessionClearInjections, sessionFile } from '../lib/session.mjs';
import { findRoot } from '../lib/config.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Session Module Tests');
console.log('═'.repeat(50));

test('sessionNew creates a session file', () => {
  const path = sessionNew('test-session');
  assert.ok(existsSync(path), `File should exist: ${path}`);
  const content = readFileSync(path, 'utf8');
  assert.ok(content.includes('# Super Session: test-session'));
  assert.ok(content.includes('**Project:**'));
  assert.ok(content.includes('**Started:**'));
});

test('sessionFile returns the active session', () => {
  const active = sessionFile();
  assert.ok(active, 'Should have an active session after sessionNew');
  assert.ok(existsSync(active));
});

test('sessionResume marks session as resumed', () => {
  const path = sessionNew('resume-test');
  const resumed = sessionResume(path);
  assert.strictEqual(resumed, path);
  const content = readFileSync(path, 'utf8');
  assert.ok(content.includes('Resumed'));
});

test('sessionResume throws for nonexistent file', () => {
  assert.throws(() => sessionResume('/tmp/nonexistent-session.md'), /not found/i);
});

test('sessionList returns array of sessions', () => {
  const sessions = sessionList();
  assert.ok(Array.isArray(sessions));
  assert.ok(sessions.length >= 2, 'Should have at least the 2 test sessions');
});

test('sessionList items have required fields', () => {
  const sessions = sessionList();
  const s = sessions[0];
  assert.ok(s.filepath);
  assert.ok(s.filename);
  assert.ok(s.title);
  assert.ok(typeof s.turns === 'number');
  assert.ok(typeof s.isActive === 'boolean');
});

test('sessionAppendTurn writes user turn', () => {
  const path = sessionNew('turn-test');
  sessionAppendTurn('claude', 'user', 'Hello world');
  const content = readFileSync(path, 'utf8');
  assert.ok(content.includes('👤 User'));
  assert.ok(content.includes('Hello world'));
  assert.ok(content.includes('🟠'));
});

test('sessionAppendTurn writes assistant turn', () => {
  sessionAppendTurn('gemini', 'assistant', 'Hi there');
  const path = sessionFile();
  const content = readFileSync(path, 'utf8');
  assert.ok(content.includes('🤖 Assistant'));
  assert.ok(content.includes('Hi there'));
  assert.ok(content.includes('🔵'));
});

test('sessionAppendTurn writes session_start', () => {
  sessionAppendTurn('codex', 'session_start', '');
  const path = sessionFile();
  const content = readFileSync(path, 'utf8');
  assert.ok(content.includes('🚀 Started'));
  assert.ok(content.includes('🟢'));
});

test('sessionGetSummary returns content', () => {
  const summary = sessionGetSummary(10);
  assert.ok(summary.length > 0);
  assert.ok(typeof summary === 'string');
});

test('sessionClearInjections does not crash', () => {
  sessionClearInjections(); // Should not throw
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
