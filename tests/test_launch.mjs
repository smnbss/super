// tests/test_launch.mjs — Tests for launch arg parsing, provider resolution, and banner
import { strict as assert } from 'assert';
import { parseLaunchArgs, resolveProvider, buildBannerLabel, PROVIDERS } from '../lib/launch.mjs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('parseLaunchArgs');
console.log('═'.repeat(50));

test('empty args', () => {
  const r = parseLaunchArgs([]);
  assert.strictEqual(r.doResume, false);
  assert.strictEqual(r.resumeFile, '');
  assert.strictEqual(r.title, '');
  assert.strictEqual(r.provider, '');
  assert.deepStrictEqual(r.passthrough, []);
});

test('--model passes through to CLI', () => {
  const r = parseLaunchArgs(['--model', 'opus']);
  assert.deepStrictEqual(r.passthrough, ['--model', 'opus']);
  assert.strictEqual(r.provider, '');
});

test('--model sonnet passes through', () => {
  const r = parseLaunchArgs(['--model', 'sonnet']);
  assert.deepStrictEqual(r.passthrough, ['--model', 'sonnet']);
});

test('--model haiku passes through', () => {
  const r = parseLaunchArgs(['--model', 'haiku']);
  assert.deepStrictEqual(r.passthrough, ['--model', 'haiku']);
});

test('--provider is extracted, not passed through', () => {
  const r = parseLaunchArgs(['--provider', 'ollama']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, []);
});

test('-P short flag works', () => {
  const r = parseLaunchArgs(['-P', 'ollama']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, []);
});

test('--provider + --model: provider extracted, model passes through', () => {
  const r = parseLaunchArgs(['--provider', 'ollama', '--model', 'glm-5:cloud']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'glm-5:cloud']);
});

test('--model before --provider works the same', () => {
  const r = parseLaunchArgs(['--model', 'kimi-k2.5:cloud', '--provider', 'ollama']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'kimi-k2.5:cloud']);
});

test('-P ollama --model minimax-m2.5:cloud', () => {
  const r = parseLaunchArgs(['-P', 'ollama', '--model', 'minimax-m2.5:cloud']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'minimax-m2.5:cloud']);
});

test('--resume flag extracted', () => {
  const r = parseLaunchArgs(['--resume']);
  assert.strictEqual(r.doResume, true);
  assert.strictEqual(r.resumeFile, '');
});

test('--resume with file', () => {
  const r = parseLaunchArgs(['--resume', '2026-04-15_170604.md']);
  assert.strictEqual(r.doResume, true);
  assert.strictEqual(r.resumeFile, '2026-04-15_170604.md');
});

test('-r short flag works', () => {
  const r = parseLaunchArgs(['-r']);
  assert.strictEqual(r.doResume, true);
});

test('--title extracted', () => {
  const r = parseLaunchArgs(['--title', 'fix auth']);
  assert.strictEqual(r.title, 'fix auth');
  assert.deepStrictEqual(r.passthrough, []);
});

test('-t short flag works', () => {
  const r = parseLaunchArgs(['-t', 'my session']);
  assert.strictEqual(r.title, 'my session');
});

test('all flags combined', () => {
  const r = parseLaunchArgs([
    '--resume', 'session.md',
    '--title', 'test',
    '--provider', 'ollama',
    '--model', 'glm-5:cloud',
    '--some-other-flag',
  ]);
  assert.strictEqual(r.doResume, true);
  assert.strictEqual(r.resumeFile, 'session.md');
  assert.strictEqual(r.title, 'test');
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'glm-5:cloud', '--some-other-flag']);
});

test('unknown flags pass through untouched', () => {
  const r = parseLaunchArgs(['--dangerously-skip-permissions', '--verbose', 'foo']);
  assert.deepStrictEqual(r.passthrough, ['--dangerously-skip-permissions', '--verbose', 'foo']);
});

test('provider value is lowercased', () => {
  const r = parseLaunchArgs(['--provider', 'OLLama']);
  assert.strictEqual(r.provider, 'ollama');
});

// ═══════════════════════════════════════════════════════════════════════════════
console.log('\nresolveProvider');
console.log('═'.repeat(50));

// --- Wrapper providers (ollama) ---

test('ollama returns wrapper mode', () => {
  const r = resolveProvider('ollama', 'claude');
  assert.strictEqual(r.mode, 'wrapper');
  assert.strictEqual(r.cmd, 'ollama');
  assert.deepStrictEqual(r.prefixArgs, ['launch', 'claude']);
});

test('ollama wrapper includes correct CLI name', () => {
  const r = resolveProvider('ollama', 'gemini');
  assert.deepStrictEqual(r.prefixArgs, ['launch', 'gemini']);
});

test('ollama wrapper defaults cli to claude', () => {
  const r = resolveProvider('ollama');
  assert.deepStrictEqual(r.prefixArgs, ['launch', 'claude']);
});

// --- Env-var providers ---

test('lmstudio returns env mode with baseUrl and apiKey', () => {
  const r = resolveProvider('lmstudio');
  assert.strictEqual(r.mode, 'env');
  assert.strictEqual(r.vars.ANTHROPIC_BASE_URL, 'http://localhost:1234/v1');
  assert.strictEqual(r.vars.ANTHROPIC_API_KEY, 'lm-studio');
});

test('openai reads OPENAI_API_KEY from env', () => {
  const r = resolveProvider('openai', 'claude', { OPENAI_API_KEY: 'sk-test-123' });
  assert.strictEqual(r.mode, 'env');
  assert.strictEqual(r.vars.ANTHROPIC_API_KEY, 'sk-test-123');
  assert.strictEqual(r.vars.ANTHROPIC_BASE_URL, undefined);
});

test('groq reads GROQ_API_KEY and sets baseUrl', () => {
  const r = resolveProvider('groq', 'claude', { GROQ_API_KEY: 'gsk-test' });
  assert.strictEqual(r.mode, 'env');
  assert.strictEqual(r.vars.ANTHROPIC_API_KEY, 'gsk-test');
  assert.strictEqual(r.vars.ANTHROPIC_BASE_URL, 'https://api.groq.com/openai/v1');
});

test('together reads TOGETHER_API_KEY and sets baseUrl', () => {
  const r = resolveProvider('together', 'claude', { TOGETHER_API_KEY: 'tog-test' });
  assert.strictEqual(r.mode, 'env');
  assert.strictEqual(r.vars.ANTHROPIC_API_KEY, 'tog-test');
  assert.strictEqual(r.vars.ANTHROPIC_BASE_URL, 'https://api.together.xyz/v1');
});

// --- Error cases ---

test('unknown provider throws', () => {
  assert.throws(
    () => resolveProvider('badprovider'),
    /Unknown provider: badprovider/
  );
});

test('openai without env var throws', () => {
  assert.throws(
    () => resolveProvider('openai', 'claude', {}),
    /requires OPENAI_API_KEY/
  );
});

test('groq without env var throws', () => {
  assert.throws(
    () => resolveProvider('groq', 'claude', {}),
    /requires GROQ_API_KEY/
  );
});

test('together without env var throws', () => {
  assert.throws(
    () => resolveProvider('together', 'claude', {}),
    /requires TOGETHER_API_KEY/
  );
});

test('resolveProvider does not mutate process.env', () => {
  const before = process.env.ANTHROPIC_BASE_URL;
  resolveProvider('ollama', 'claude');
  assert.strictEqual(process.env.ANTHROPIC_BASE_URL, before);
});

test('error message lists all available providers', () => {
  try {
    resolveProvider('nope');
    assert.fail('Should have thrown');
  } catch (e) {
    for (const name of Object.keys(PROVIDERS)) {
      assert.ok(e.message.includes(name), `Missing provider ${name} in error`);
    }
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
console.log('\nbuildBannerLabel');
console.log('═'.repeat(50));

test('basic label, no provider or model', () => {
  assert.strictEqual(buildBannerLabel('Claude Code', '', []), 'Claude Code');
});

test('with model only', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', '', ['--model', 'opus']),
    'Claude Code (opus)'
  );
});

test('with provider only', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', 'ollama', []),
    'Claude Code via ollama'
  );
});

test('with provider and model', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', 'ollama', ['--model', 'glm-5:cloud']),
    'Claude Code via ollama (glm-5:cloud)'
  );
});

test('model with colon in name', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', 'ollama', ['--model', 'kimi-k2.5:cloud']),
    'Claude Code via ollama (kimi-k2.5:cloud)'
  );
});

test('model not at start of passthrough', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', '', ['--verbose', '--model', 'sonnet', '--debug']),
    'Claude Code (sonnet)'
  );
});

test('--model without value does not crash', () => {
  assert.strictEqual(
    buildBannerLabel('Claude Code', '', ['--model']),
    'Claude Code'
  );
});

test('gemini label works', () => {
  assert.strictEqual(
    buildBannerLabel('Gemini CLI', '', ['--model', 'gemini-2.5-pro']),
    'Gemini CLI (gemini-2.5-pro)'
  );
});

// ═══════════════════════════════════════════════════════════════════════════════
console.log('\nEnd-to-end arg → env scenarios');
console.log('═'.repeat(50));

test('super claude: no args → no provider, no model, empty passthrough', () => {
  const r = parseLaunchArgs([]);
  assert.strictEqual(r.provider, '');
  assert.deepStrictEqual(r.passthrough, []);
});

test('super claude --model opus → passthrough only', () => {
  const r = parseLaunchArgs(['--model', 'opus']);
  assert.strictEqual(r.provider, '');
  assert.deepStrictEqual(r.passthrough, ['--model', 'opus']);
});

test('super claude --provider ollama --model glm-5:cloud → wrapper + passthrough', () => {
  const r = parseLaunchArgs(['--provider', 'ollama', '--model', 'glm-5:cloud']);
  assert.strictEqual(r.provider, 'ollama');
  const prov = resolveProvider(r.provider, 'claude');
  assert.strictEqual(prov.mode, 'wrapper');
  assert.strictEqual(prov.cmd, 'ollama');
  assert.deepStrictEqual(prov.prefixArgs, ['launch', 'claude']);
  assert.deepStrictEqual(r.passthrough, ['--model', 'glm-5:cloud']);
});

test('super claude --provider ollama --model minimax-m2.5:cloud', () => {
  const r = parseLaunchArgs(['--provider', 'ollama', '--model', 'minimax-m2.5:cloud']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'minimax-m2.5:cloud']);
  const label = buildBannerLabel('Claude Code', r.provider, r.passthrough);
  assert.strictEqual(label, 'Claude Code via ollama (minimax-m2.5:cloud)');
});

test('super claude --provider ollama --model kimi-k2.5:cloud', () => {
  const r = parseLaunchArgs(['--provider', 'ollama', '--model', 'kimi-k2.5:cloud']);
  assert.strictEqual(r.provider, 'ollama');
  assert.deepStrictEqual(r.passthrough, ['--model', 'kimi-k2.5:cloud']);
  const label = buildBannerLabel('Claude Code', r.provider, r.passthrough);
  assert.strictEqual(label, 'Claude Code via ollama (kimi-k2.5:cloud)');
});

// ═══════════════════════════════════════════════════════════════════════════════
// Ollama Cloud regression guard
// The bug: a refactor switched ollama from wrapper mode (ollama launch claude ...)
// to env-var mode (ANTHROPIC_BASE_URL=localhost:11434), which hit local Ollama
// instead of Ollama Cloud. These tests ensure ollama ALWAYS uses wrapper mode.
// ═══════════════════════════════════════════════════════════════════════════════
console.log('\nOllama Cloud regression guard');
console.log('═'.repeat(50));

// Helper: simulate what super.mjs does to build the final exec call
function simulateExec(cliName, userArgs) {
  const { provider, passthrough } = parseLaunchArgs(userArgs);
  const providerResult = provider ? resolveProvider(provider, cliName) : null;
  // cliDefaultArgs omitted (yolo flags etc.) — we test the provider path only
  const cliArgs = [...passthrough];
  if (providerResult && providerResult.mode === 'wrapper') {
    return { bin: providerResult.cmd, args: [...providerResult.prefixArgs, ...cliArgs] };
  }
  return { bin: cliName, args: cliArgs };
}

test('ollama provider MUST use wrapper mode, never env mode', () => {
  const r = resolveProvider('ollama', 'claude');
  assert.strictEqual(r.mode, 'wrapper', 'ollama must be wrapper mode — env mode hits local, not Ollama Cloud');
  assert.ok(!r.vars, 'ollama must not set env vars');
});

test('ollama MUST NOT set ANTHROPIC_BASE_URL', () => {
  const r = resolveProvider('ollama', 'claude');
  assert.strictEqual(r.mode, 'wrapper');
  // Double-check there's no vars sneaking in
  assert.strictEqual(r.vars, undefined);
});

test('ollama provider config must not have baseUrl or apiKey', () => {
  const p = PROVIDERS.ollama;
  assert.strictEqual(p.baseUrl, undefined, 'ollama must not have baseUrl — it uses wrapper mode');
  assert.strictEqual(p.apiKey, undefined, 'ollama must not have apiKey — it uses wrapper mode');
  assert.strictEqual(p.envKey, undefined, 'ollama must not have envKey — it uses wrapper mode');
  assert.ok(p.wrapper, 'ollama must have wrapper field');
});

test('super claude --provider ollama → exec: ollama launch claude', () => {
  const exec = simulateExec('claude', ['--provider', 'ollama']);
  assert.strictEqual(exec.bin, 'ollama');
  assert.deepStrictEqual(exec.args, ['launch', 'claude']);
});

test('super claude --provider ollama --model kimi-k2.5:cloud → exec: ollama launch claude --model kimi-k2.5:cloud', () => {
  const exec = simulateExec('claude', ['--provider', 'ollama', '--model', 'kimi-k2.5:cloud']);
  assert.strictEqual(exec.bin, 'ollama');
  assert.deepStrictEqual(exec.args, ['launch', 'claude', '--model', 'kimi-k2.5:cloud']);
});

test('super claude --provider ollama --model minimax-m2.5:cloud → exec: ollama launch claude --model minimax-m2.5:cloud', () => {
  const exec = simulateExec('claude', ['--provider', 'ollama', '--model', 'minimax-m2.5:cloud']);
  assert.strictEqual(exec.bin, 'ollama');
  assert.deepStrictEqual(exec.args, ['launch', 'claude', '--model', 'minimax-m2.5:cloud']);
});

test('super claude --provider ollama --model glm-5:cloud → exec: ollama launch claude --model glm-5:cloud', () => {
  const exec = simulateExec('claude', ['--provider', 'ollama', '--model', 'glm-5:cloud']);
  assert.strictEqual(exec.bin, 'ollama');
  assert.deepStrictEqual(exec.args, ['launch', 'claude', '--model', 'glm-5:cloud']);
});

test('without --provider → exec: claude (direct, no ollama)', () => {
  const exec = simulateExec('claude', ['--model', 'opus']);
  assert.strictEqual(exec.bin, 'claude');
  assert.deepStrictEqual(exec.args, ['--model', 'opus']);
});

test('env-var providers never produce wrapper exec', () => {
  for (const name of ['openai', 'lmstudio', 'groq', 'together']) {
    const fakeEnv = { OPENAI_API_KEY: 'x', GROQ_API_KEY: 'x', TOGETHER_API_KEY: 'x' };
    const r = resolveProvider(name, 'claude', fakeEnv);
    assert.strictEqual(r.mode, 'env', `${name} should be env mode`);
    assert.ok(r.vars, `${name} should have vars`);
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
