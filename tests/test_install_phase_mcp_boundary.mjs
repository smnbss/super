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

writeFileSync(join(tmp, '.super', 'super.config.yaml'),
  ['system: []', 'clis: []', 'skills: []', 'plugins: []', 'mcps: []', ''].join('\n'));

const claudeJson = join(home, '.claude.json');
const seed = () => writeFileSync(claudeJson, JSON.stringify({
  // Two user-scope MCPs outside super's catalog — the real-world case.
  mcpServers: {
    gbrain: { type: 'http', url: 'http://localhost:3131/mcp' },
    mailtrap: { command: 'npx', args: ['-y', 'mailtrap-mcp'] },
  },
  projects: { [tmp]: { mcpServers: { someproject: { command: 'x' } } } },
}, null, 2));

const read = () => JSON.parse(readFileSync(claudeJson, 'utf8'));

seed();
installPhaseInstall(['claude'], { debugMode: false });

test('installPhaseInstall preserves user-scope mcpServers', () => {
  const d = read();
  assert.deepEqual(Object.keys(d.mcpServers || {}).sort(), ['gbrain', 'mailtrap'],
    'the skill-sync phase must not clear user-scope MCPs');
});

test('installPhaseInstall preserves per-project mcpServers', () => {
  const d = read();
  assert.deepEqual(Object.keys(d.projects?.[tmp]?.mcpServers || {}), ['someproject']);
});

test('installPhaseInstall preserves the MCP entry contents, not just the keys', () => {
  const d = read();
  assert.equal(d.mcpServers.gbrain.url, 'http://localhost:3131/mcp');
  assert.deepEqual(d.mcpServers.mailtrap.args, ['-y', 'mailtrap-mcp']);
});

test('installPhaseInstall is still non-destructive on a second run', () => {
  installPhaseInstall(['claude'], { debugMode: false });
  assert.deepEqual(Object.keys(read().mcpServers || {}).sort(), ['gbrain', 'mailtrap']);
});

// Documents TODAY'S behaviour of the configure phase. This is the destructive
// half described in the header: it is asserted so the blast radius is explicit
// and any deliberate fix has to update this test on purpose.
test('installPhaseConfigure clears both scopes (known destructive behaviour)', () => {
  seed();
  installPhaseConfigure(['claude']);
  const d = read();
  assert.deepEqual(Object.keys(d.mcpServers || {}), [], 'configure empties user-scope MCPs today');
  assert.deepEqual(Object.keys(d.projects?.[tmp]?.mcpServers || {}), [], 'configure empties project MCPs today');
});

rmSync(tmp, { recursive: true, force: true });

console.log('═'.repeat(50));
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
