// tests/test_install_phase_mcp_boundary.mjs — Pins which install phase is
// allowed to touch ~/.claude.json's mcpServers.
//
// installPhaseInstall does the skill work (built-in skills + .claude/skills
// sync) and MUST leave ~/.claude.json alone. Only installPhaseConfigure, which
// rebuilds plugins and MCPs, clears it.
//
// Why this is pinned: the clear is `data.mcpServers = {}` — it empties the
// object rather than removing the keys super manages, so it also takes out
// user-scope MCPs from outside super's catalog (gbrain, mailtrap, …), and some
// of those need interactive OAuth and cannot be restored non-interactively.
// Anything that moves that call into the core phase turns a routine skill sync
// into a destructive one, so this test exists to fail loudly if that happens.

import { strict as assert } from 'assert';
import { mkdirSync, writeFileSync, readFileSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

const tmp = join(tmpdir(), `super-mcp-boundary-${process.pid}-${Date.now()}`);
mkdirSync(join(tmp, '.super'), { recursive: true });
process.env.SUPER_PROJECT_DIR = tmp;

const home = join(tmp, 'home');
mkdirSync(join(home, '.super'), { recursive: true });
process.env.HOME = home;

const { installPhaseInstall, installPhaseConfigure } = await import('../lib/catalog.mjs');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}\n    ${e.stack?.split('\n').slice(1, 3).join('\n    ')}`); failed++; }
}

console.log('Install-phase / ~/.claude.json MCP boundary tests');
console.log('═'.repeat(50));

// A catalog with one ENABLED mcp (super manages it) and one DISABLED (it does
// not) — the two sides of the cleanup predicate.
writeFileSync(join(tmp, '.super', 'super.config.yaml'), [
  'system: []',
  'clis: []',
  'skills: []',
  'plugins: []',
  'mcps:',
  '  linear:',
  '    type: http',
  '    url: https://mcp.linear.app/mcp',
  '    enabled: true',
  '  bigquery:',
  '    type: http',
  '    url: https://bigquery.googleapis.com/mcp',
  '    enabled: false',
  '',
].join('\n'));

const claudeJson = join(home, '.claude.json');
const seed = () => writeFileSync(claudeJson, JSON.stringify({
  mcpServers: {
    // Outside super's catalog — must survive. mailtrap has no self-heal, and
    // anything OAuth-based cannot be restored non-interactively.
    gbrain: { type: 'http', url: 'http://localhost:3131/mcp' },
    mailtrap: { command: 'npx', args: ['-y', 'mailtrap-mcp'] },
    // Enabled in the catalog: super writes this to settings.local.json, so a
    // same-named entry here really does shadow it and must be removed.
    linear: { type: 'http', url: 'https://stale.example/mcp' },
    // In the catalog but DISABLED: super never writes it, so this entry is the
    // user's own registration and must survive.
    bigquery: { type: 'http', url: 'https://user-registered.example/mcp' },
  },
  projects: { [tmp]: { mcpServers: { someproject: { command: 'x' }, linear: { command: 'stale' } } } },
}, null, 2));

const read = () => JSON.parse(readFileSync(claudeJson, 'utf8'));

seed();
installPhaseInstall(['claude'], { debugMode: false });

const ALL = ['bigquery', 'gbrain', 'linear', 'mailtrap'];

test('installPhaseInstall touches nothing at all', () => {
  const d = read();
  assert.deepEqual(Object.keys(d.mcpServers || {}).sort(), ALL,
    'the skill-sync phase must not clear ANY user-scope MCP');
  assert.deepEqual(Object.keys(d.projects?.[tmp]?.mcpServers || {}).sort(), ['linear', 'someproject']);
});

test('installPhaseInstall preserves entry contents, not just keys', () => {
  const d = read();
  assert.equal(d.mcpServers.gbrain.url, 'http://localhost:3131/mcp');
  assert.deepEqual(d.mcpServers.mailtrap.args, ['-y', 'mailtrap-mcp']);
});

test('installPhaseInstall is still non-destructive on a second run', () => {
  installPhaseInstall(['claude'], { debugMode: false });
  assert.deepEqual(Object.keys(read().mcpServers || {}).sort(), ALL);
});

// The configure phase is the only one allowed to touch ~/.claude.json, and it
// may remove ONLY the names super itself writes to settings.local.json.
seed();
installPhaseConfigure(['claude']);

test('configure removes the enabled catalog MCP that shadows settings.local.json', () => {
  assert.ok(!('linear' in (read().mcpServers || {})), 'enabled catalog entry should be cleaned');
});

test('configure preserves user-scope MCPs outside the catalog', () => {
  const m = read().mcpServers || {};
  assert.ok('gbrain' in m, 'gbrain must survive');
  assert.ok('mailtrap' in m, 'mailtrap must survive — it has no self-heal');
  assert.equal(m.mailtrap.command, 'npx', 'and survive intact, not as an empty stub');
});

test('configure preserves a DISABLED catalog name (super never writes it)', () => {
  const m = read().mcpServers || {};
  assert.ok('bigquery' in m, 'a disabled catalog entry here is the user\'s own registration');
  assert.equal(m.bigquery.url, 'https://user-registered.example/mcp');
});

test('configure applies the same predicate at project scope', () => {
  const p = read().projects?.[tmp]?.mcpServers || {};
  assert.ok(!('linear' in p), 'shadowing catalog entry removed');
  assert.ok('someproject' in p, 'unmanaged project entry kept');
});

test('configure is idempotent — a second run removes nothing more', () => {
  installPhaseConfigure(['claude']);
  const m = read().mcpServers || {};
  assert.deepEqual(Object.keys(m).sort(), ['bigquery', 'gbrain', 'mailtrap']);
});

rmSync(tmp, { recursive: true, force: true });

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
