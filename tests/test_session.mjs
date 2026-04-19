// tests/test_session.mjs — Tests for session module
import { strict as assert } from 'assert';
import { existsSync, mkdirSync, rmSync, readFileSync, writeFileSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { sessionNew, sessionResume, sessionList, sessionAppendTurn, sessionGetSummary, sessionCleanupOld, sessionClearInjections, sessionInjectContext, sessionFile } from '../lib/session.mjs';
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

// ─── Cross-session context injection ─────────────────────────────────────────
// Regression: inject must write ONLY to <root>/.super/session-context.md and
// never touch CLAUDE.md / GEMINI.md / AGENTS.md at the project root.
(() => {
  const tmp = join(tmpdir(), `super-inject-${process.pid}-${Date.now()}`);
  mkdirSync(join(tmp, '.super', 'sessions'), { recursive: true });
  sessionNew('inject-fixture', tmp);

  test('sessionInjectContext writes to .super/session-context.md', () => {
    sessionInjectContext('claude', tmp);
    const ctx = join(tmp, '.super', 'session-context.md');
    assert.ok(existsSync(ctx), 'session-context.md should exist');
    const content = readFileSync(ctx, 'utf8');
    assert.ok(content.includes('<!-- super:session-context -->'));
    assert.ok(content.includes('<!-- /super:session-context -->'));
    assert.ok(content.includes('CLI: `claude`'));
    assert.ok(content.includes('SuperCLI Cross-Session Context'));
  });

  test('sessionInjectContext never writes to root CLAUDE/GEMINI/AGENTS files', () => {
    // Pre-seed with sentinels so we can detect any mutation.
    for (const f of ['CLAUDE.md', 'GEMINI.md', 'AGENTS.md']) {
      writeFileSync(join(tmp, f), `SENTINEL-${f}\n`);
    }
    sessionInjectContext('codex', tmp);
    for (const f of ['CLAUDE.md', 'GEMINI.md', 'AGENTS.md']) {
      assert.strictEqual(
        readFileSync(join(tmp, f), 'utf8'),
        `SENTINEL-${f}\n`,
        `${f} must not be touched by sessionInjectContext`,
      );
    }
  });

  test('sessionInjectContext overwrites (not appends) on repeat call', () => {
    sessionInjectContext('claude', tmp);
    const first = readFileSync(join(tmp, '.super', 'session-context.md'), 'utf8');
    sessionInjectContext('gemini', tmp);
    const second = readFileSync(join(tmp, '.super', 'session-context.md'), 'utf8');
    assert.ok(second.includes('CLI: `gemini`'));
    assert.ok(!second.includes('CLI: `claude`'), 'old CLI line should be gone');
    // Exactly one HEADER occurrence — no duplication.
    const occurrences = (second.match(/<!-- super:session-context -->/g) || []).length;
    assert.strictEqual(occurrences, 1);
    assert.notStrictEqual(first, second);
  });

  test('sessionClearInjections deletes .super/session-context.md', () => {
    sessionInjectContext('claude', tmp);
    const ctx = join(tmp, '.super', 'session-context.md');
    assert.ok(existsSync(ctx));
    sessionClearInjections(tmp);
    assert.ok(!existsSync(ctx), 'session-context.md should be removed');
  });

  // Cleanup tempdir.
  try { rmSync(tmp, { recursive: true, force: true }); } catch {}
})();

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
