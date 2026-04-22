// tests/test_install_phases.mjs — Verifies the install phases used by
// `super install`:
//   - installPhaseInstall: built-in skills + debug-link sync path.
//   - installPhaseConfigure: no-ops safely when super.config.yaml is empty
//     of externals.

import { strict as assert } from 'assert';
import { existsSync, mkdirSync, rmSync, writeFileSync, readFileSync, cpSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

// Point SUPER_PROJECT_DIR at a throwaway dir before importing catalog so
// `findRoot` resolves there and writes stay contained.
const tmp = join(tmpdir(), `super-install-phases-${process.pid}-${Date.now()}`);
mkdirSync(join(tmp, '.super'), { recursive: true });
process.env.SUPER_PROJECT_DIR = tmp;

const home = join(tmp, 'home');
mkdirSync(join(home, '.super'), { recursive: true });
process.env.HOME = home;

const { installPhaseInstall, installPhaseConfigure, scaffoldEnvLocal } = await import('../lib/catalog.mjs');
const { catalogPlugins, invalidateCache } = await import('../lib/config.mjs');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}\n    ${e.stack?.split('\n').slice(1, 3).join('\n    ')}`); failed++; }
}

console.log('Install-phase split tests');
console.log('═'.repeat(50));

// Minimal config — no external skills, plugins, or MCPs.
const cfgPath = join(tmp, '.super', 'super.config.yaml');
writeFileSync(cfgPath, [
  'system: []',
  'clis: []',
  'skills: []',
  'plugins: []',
  'mcps: []',
  '',
].join('\n'));

test('scaffoldEnvLocal copies SUPER_HOME/references/env.example when missing', () => {
  const envLocal = join(tmp, '.env.local');
  if (existsSync(envLocal)) rmSync(envLocal);
  scaffoldEnvLocal();
  assert.ok(existsSync(envLocal), '.env.local should have been created');
  const content = readFileSync(envLocal, 'utf8');
  assert.ok(content.includes('CLICKUP_TOKEN') || content.includes('LINEAR_TOKEN'),
    '.env.local should be seeded from the shipped sample');
});

test('scaffoldEnvLocal never overwrites an existing .env.local', () => {
  const envLocal = join(tmp, '.env.local');
  writeFileSync(envLocal, 'SENTINEL=1\n');
  scaffoldEnvLocal();
  assert.strictEqual(readFileSync(envLocal, 'utf8'), 'SENTINEL=1\n');
});

test('installPhaseInstall runs without touching the external catalog', () => {
  // Should not throw. With an empty selectedClis + no CLIs installed, the
  // built-in skill copy is a no-op, but the function must still return cleanly.
  installPhaseInstall([], { debugMode: false });
});

test('installPhaseInstall creates debug symlinks only when requested', () => {
  installPhaseInstall([], { debugMode: true });
  assert.ok(existsSync(join(tmp, '.super', '.super')), '.super/.super symlink should exist in debug mode');
  installPhaseInstall([], { debugMode: false });
  assert.ok(!existsSync(join(tmp, '.super', '.super')), '.super/.super symlink should be removed without debug mode');
});

test('installPhaseConfigure no-ops cleanly on an empty catalog', () => {
  // No external skills/plugins/mcps → all phase iterations loop 0 times.
  installPhaseConfigure([]);
});

test('project config only overrides enabled flags for shipped plugin metadata', () => {
  writeFileSync(join(home, '.super', 'super.config.yaml'), [
    'plugins:',
    '  marketing-skills:',
    '    source: coreyhaines31/marketingskills',
    '    enabled: true',
    '',
  ].join('\n'));

  writeFileSync(cfgPath, [
    'plugins:',
    '  marketing-skills:',
    '    source: marketingskills/marketing-skills',
    '    enabled: false',
    '',
  ].join('\n'));

  invalidateCache();
  const plugin = catalogPlugins().find(p => p.name === 'marketing-skills');
  assert.ok(plugin);
  assert.strictEqual(plugin.source, 'coreyhaines31/marketingskills');
  assert.strictEqual(plugin.enabled, false);
});

// Cleanup.
try { rmSync(tmp, { recursive: true, force: true }); } catch {}

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
