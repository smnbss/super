// tests/test_config.mjs — Tests for config module
import { strict as assert } from 'assert';
import { findRoot, findConfig, configGet, configEnabled, catalogSkills, catalogPlugins, catalogMcps, mcpItem, superVersion, invalidateCache } from '../lib/config.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Config Module Tests');
console.log('═'.repeat(50));

invalidateCache();

test('findRoot returns a directory', () => {
  const root = findRoot();
  assert.ok(root.length > 0);
});

test('findConfig finds super.config.yaml', () => {
  const cfg = findConfig();
  assert.ok(cfg && cfg.endsWith('super.config.yaml'));
});

test('superVersion returns a version string', () => {
  const v = superVersion();
  assert.ok(/^\d+\.\d+\.\d+/.test(v), `Got: ${v}`);
});

test('configGet reads security.yoloMode', () => {
  const v = configGet('security.yoloMode');
  assert.ok(typeof v === 'boolean' || typeof v === 'string');
});

test('configEnabled returns boolean', () => {
  const v = configEnabled('security.yoloMode');
  assert.ok(typeof v === 'boolean');
});

test('configGet reads nested path', () => {
  const v = configGet('session.maxAgeDays');
  assert.ok(v === 7 || typeof v === 'number');
});

test('configGet returns undefined for missing path', () => {
  const v = configGet('nonexistent.deep.path');
  assert.strictEqual(v, undefined);
});

// Catalog tests
test('catalogSkills returns array', () => {
  const skills = catalogSkills();
  assert.ok(Array.isArray(skills));
  assert.ok(skills.length > 0, 'Should have at least one skill');
});

test('catalogSkills items have required fields', () => {
  const skills = catalogSkills();
  const first = skills[0];
  assert.ok(first.name, 'Should have name');
  assert.ok(first.source, 'Should have source');
  assert.ok(typeof first.enabled === 'boolean', 'enabled should be boolean');
});

test('catalog enabled field defaults to true and is always boolean', () => {
  const skills = catalogSkills();
  skills.forEach(s => {
    assert.ok(typeof s.enabled === 'boolean', `skill ${s.name} enabled should be boolean`);
  });
  const mcps = catalogMcps();
  mcps.forEach(m => {
    assert.ok(typeof m.enabled === 'boolean', `mcp ${m.name} enabled should be boolean`);
  });
  const plugins = catalogPlugins();
  plugins.forEach(p => {
    assert.ok(typeof p.enabled === 'boolean', `plugin ${p.name} enabled should be boolean`);
  });
});

test('catalogPlugins returns array', () => {
  const plugins = catalogPlugins();
  assert.ok(Array.isArray(plugins));
});

test('catalogMcps returns array with type field', () => {
  const mcps = catalogMcps();
  assert.ok(Array.isArray(mcps));
  assert.ok(mcps.length > 0);
  const bq = mcps.find(m => m.name === 'bigquery');
  assert.ok(bq, 'Should have bigquery MCP');
  assert.strictEqual(bq.type, 'http');
});

test('mcpItem returns full config for bigquery', () => {
  const item = mcpItem('bigquery');
  assert.ok(item);
  assert.strictEqual(item.type, 'http');
  assert.ok(item.url.includes('bigquery'));
});

test('mcpItem returns full config for metabase (stdio)', () => {
  const item = mcpItem('metabase');
  assert.ok(item);
  assert.strictEqual(item.type, 'stdio');
  assert.strictEqual(item.command, 'npx');
  assert.ok(Array.isArray(item.args));
});

test('mcpItem returns null for nonexistent', () => {
  const item = mcpItem('nonexistent-mcp');
  assert.strictEqual(item, null);
});

test('catalogSkills does not leak section comments', () => {
  const skills = catalogSkills();
  const leaks = skills.filter(s => s.name.includes('Claude') || s.name.includes('───'));
  assert.strictEqual(leaks.length, 0, `Found leaked entries: ${leaks.map(s => s.name)}`);
});

test('catalogPlugins does not leak section comments', () => {
  const plugins = catalogPlugins();
  const leaks = plugins.filter(p => p.name.includes('Installed') || p.name.includes('───'));
  assert.strictEqual(leaks.length, 0, `Found leaked entries: ${leaks.map(p => p.name)}`);
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
