// tests/test_syntax.mjs — Syntax validation to catch merge conflicts
import { strict as assert } from 'assert';
import { execSync } from 'child_process';
import { readFileSync } from 'fs';
import { globSync } from 'fs';

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.log(`  ✗ ${name}: ${e.message}`); failed++; }
}

console.log('Syntax Validation Tests');
console.log('═'.repeat(50));

const MERGE_CONFLICT_MARKERS = ['<<<<<<<', '=======', '>>>>>>>'];

// All JS/TS/MJS files in the project (excluding node_modules)
const jsFiles = [
  'super.mjs',
  'lib/*.mjs',
  'tests/*.mjs',
  'hooks/**/*.sh',
];

test('No merge conflict markers in super.mjs', () => {
  const content = readFileSync('super.mjs', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in lib/session.mjs', () => {
  const content = readFileSync('lib/session.mjs', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in lib/fzf.mjs', () => {
  const content = readFileSync('lib/fzf.mjs', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in lib/launch.mjs', () => {
  const content = readFileSync('lib/launch.mjs', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in hooks/claude/session_start.sh', () => {
  const content = readFileSync('hooks/claude/session_start.sh', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in hooks/claude/user_prompt.sh', () => {
  const content = readFileSync('hooks/claude/user_prompt.sh', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

test('No merge conflict markers in hooks/claude/stop.sh', () => {
  const content = readFileSync('hooks/claude/stop.sh', 'utf8');
  for (const marker of MERGE_CONFLICT_MARKERS) {
    assert.ok(!content.includes(marker), `Found merge conflict marker: ${marker}`);
  }
});

// Syntax validation using Node.js
test('super.mjs has valid syntax', () => {
  try {
    execSync('node --check super.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/session.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/session.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/fzf.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/fzf.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/launch.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/launch.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/config.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/config.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/ui.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/ui.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/catalog.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/catalog.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/interactive.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/interactive.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/security.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/security.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('lib/validators.mjs has valid syntax', () => {
  try {
    execSync('node --check lib/validators.mjs', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

// Bash syntax validation
test('hooks/claude/session_start.sh has valid syntax', () => {
  try {
    execSync('bash -n hooks/claude/session_start.sh', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('hooks/claude/user_prompt.sh has valid syntax', () => {
  try {
    execSync('bash -n hooks/claude/user_prompt.sh', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

test('hooks/claude/stop.sh has valid syntax', () => {
  try {
    execSync('bash -n hooks/claude/stop.sh', { stdio: 'pipe' });
  } catch (e) {
    throw new Error(`Syntax error: ${e.message}`);
  }
});

console.log(`\n${'═'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed);
