// tests/test_catalog.mjs — Tests for catalog module
import { strict as assert } from 'assert';
import { isInstalled, installedClis, computeYoloSettingsUpdate, CLI_BINARY, buildMcpEntry, discoverPluginContents } from '../lib/catalog.mjs';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

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
  const valid = ['claude', 'gemini', 'codex', 'antigravity'];
  const clis = installedClis();
  for (const cli of clis) {
    assert.ok(valid.includes(cli), `Unexpected CLI: ${cli}`);
  }
});

// ─── Antigravity CLI (agy) ───────────────────────────────────────────────
console.log('\nAntigravity (agy)');

test('CLI_BINARY maps antigravity → agy', () => {
  assert.strictEqual(CLI_BINARY.antigravity, 'agy');
  assert.strictEqual(CLI_BINARY.claude, 'claude');
});

test('buildMcpEntry(antigravity) uses serverUrl for HTTP servers', () => {
  const entry = buildMcpEntry({ url: 'https://mcp.example/mcp', headers: { Authorization: 'Bearer x' } }, 'antigravity');
  assert.strictEqual(entry.serverUrl, 'https://mcp.example/mcp');
  assert.strictEqual(entry.url, undefined, 'must not emit a `url` field');
  assert.deepStrictEqual(entry.headers, { Authorization: 'Bearer x' });
});

test('buildMcpEntry(antigravity) keeps command/args for stdio servers', () => {
  const entry = buildMcpEntry({ command: 'npx', args: ['-y', 'some-mcp'], env: { K: 'v' } }, 'antigravity');
  assert.strictEqual(entry.command, 'npx');
  assert.deepStrictEqual(entry.args, ['-y', 'some-mcp']);
  assert.deepStrictEqual(entry.env, { K: 'v' });
  assert.strictEqual(entry.serverUrl, undefined);
});

test('buildMcpEntry(gemini) still uses url (regression)', () => {
  const entry = buildMcpEntry({ url: 'https://mcp.example/mcp' }, 'gemini');
  assert.strictEqual(entry.url, 'https://mcp.example/mcp');
  assert.strictEqual(entry.serverUrl, undefined);
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

// ─── discoverPluginContents (shared lib/ harvesting) ─────────────────────
console.log('\ndiscoverPluginContents');

function makeCliPluginRepo() {
  const repo = mkdtempSync(join(tmpdir(), 'super-plugin-'));
  // plugins/cli/{lib/env.mjs, skills/bigquery-cli/{SKILL.md,scripts/x.mjs}, commands/cli-setup.md}
  const skillScripts = join(repo, 'plugins', 'cli', 'skills', 'bigquery-cli', 'scripts');
  mkdirSync(skillScripts, { recursive: true });
  writeFileSync(join(repo, 'plugins', 'cli', 'skills', 'bigquery-cli', 'SKILL.md'), '---\nname: bigquery-cli\n---\n');
  writeFileSync(join(skillScripts, 'bigquery.mjs'), "import { loadEnv } from '../../../lib/env.mjs';\n");
  mkdirSync(join(repo, 'plugins', 'cli', 'lib'), { recursive: true });
  writeFileSync(join(repo, 'plugins', 'cli', 'lib', 'env.mjs'), 'export function loadEnv() {}\n');
  mkdirSync(join(repo, 'plugins', 'cli', 'commands'), { recursive: true });
  writeFileSync(join(repo, 'plugins', 'cli', 'commands', 'cli-setup.md'), '# cli-setup\n');
  return repo;
}

test('discoverPluginContents finds skills, commands, and the plugin-domain shared lib/', () => {
  const repo = makeCliPluginRepo();
  try {
    const { skills, commands, sharedLibs } = discoverPluginContents(repo);
    assert.deepStrictEqual(skills.map(s => s.name), ['bigquery-cli']);
    assert.deepStrictEqual(commands.map(c => c.name), ['cli-setup']);
    assert.strictEqual(sharedLibs.length, 1, 'should surface exactly one shared lib/');
    assert.ok(sharedLibs[0].endsWith(join('plugins', 'cli', 'lib')), `unexpected lib path: ${sharedLibs[0]}`);
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test('discoverPluginContents surfaces a root-level lib/ for repo-root skills', () => {
  const repo = mkdtempSync(join(tmpdir(), 'super-plugin-'));
  try {
    mkdirSync(join(repo, 'skills', 'foo'), { recursive: true });
    writeFileSync(join(repo, 'skills', 'foo', 'SKILL.md'), '---\nname: foo\n---\n');
    mkdirSync(join(repo, 'lib'), { recursive: true });
    writeFileSync(join(repo, 'lib', 'env.mjs'), '\n');
    const { skills, sharedLibs } = discoverPluginContents(repo);
    assert.deepStrictEqual(skills.map(s => s.name), ['foo']);
    assert.strictEqual(sharedLibs.length, 1);
    assert.ok(sharedLibs[0].endsWith(join(repo, 'lib')) || sharedLibs[0].endsWith('lib'));
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test('discoverPluginContents omits sharedLibs when there is no lib/', () => {
  const repo = mkdtempSync(join(tmpdir(), 'super-plugin-'));
  try {
    mkdirSync(join(repo, 'plugins', 'x', 'skills', 's'), { recursive: true });
    writeFileSync(join(repo, 'plugins', 'x', 'skills', 's', 'SKILL.md'), '---\nname: s\n---\n');
    const { skills, sharedLibs } = discoverPluginContents(repo);
    assert.deepStrictEqual(skills.map(s => s.name), ['s']);
    assert.deepStrictEqual(sharedLibs, []);
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
