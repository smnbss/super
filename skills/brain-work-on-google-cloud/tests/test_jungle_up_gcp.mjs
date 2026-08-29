#!/usr/bin/env node
// Static guards over jungle_up_gcp.sh. No GCP call, no VM, no network.
//
//   node tests/test_jungle_up_gcp.mjs
//
// ⚠️ jungle_up_gcp.sh referenced this file in two comments from the day it was
//    written, and the file did not exist. Five functions were defined and called by
//    nothing, SKILL.md documented all five as live, and three of them failed silently
//    on a real run before anyone noticed. See SIM-63.
//
// The dead-code check below is the one that matters. Everything else here is cheap.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const script = readFileSync(join(root, 'jungle_up_gcp.sh'), 'utf8');

const failures = [];
const check = (name, ok, detail) => {
  if (ok) return;
  failures.push(detail ? `${name}\n    ${detail}` : name);
};

// ---------------------------------------------------------------------------
// 1. Never revoke the operator's ADC.
//
// The VM ADC holds the SAME refresh token as the laptop, so a server-side revoke
// destroys the operator's local credentials. Delete the files instead.
// ---------------------------------------------------------------------------
check(
  'must never call `gcloud auth application-default revoke`',
  !/application-default\s+revoke/.test(stripComments(script)),
  'Delete the credential files in scrub_credentials instead.',
);

// ---------------------------------------------------------------------------
// 2. No function may be defined and never called.
//
// This is the guard that would have caught stack_up, derive_services,
// inject_agent_auth and fetch_agent_token_from_secret_manager.
// ---------------------------------------------------------------------------
const code = stripComments(script);
const defined = [...code.matchAll(/^([a-z_][a-z0-9_]*)\s*\(\)\s*\{/gm)].map((m) => m[1]);
check('script defines functions', defined.length > 0);

// A verb reached only through the `main` case statement is still called.
const dead = defined.filter((fn) => {
  const uses = [...code.matchAll(new RegExp(`\\b${fn}\\b`, 'g'))].length;
  return uses < 2; // the definition itself is one
});
check(
  'no function may be defined and never called',
  dead.length === 0,
  `dead: ${dead.join(', ')}`,
);

// ---------------------------------------------------------------------------
// 3. Every credential the script writes must be scrubbed before capture.
//
// ~/.claude-env was written by inject_agent_auth and absent from scrub_credentials,
// so the golden image shipped a live LiteLLM token.
// ---------------------------------------------------------------------------
const scrub = section(code, 'scrub_credentials');
for (const path of [
  '~/.config/gcloud/application_default_credentials.json',
  '~/.npmrc',
  '~/.composer/auth.json',
  '~/.docker/config.json',
  '~/.git-credentials',
  '~/.claude-env',
]) {
  check(`scrub_credentials removes ${path}`, scrub.includes(path));
}

// ---------------------------------------------------------------------------
// 4. The agent credential must be purged before it is rewritten.
//
// Without this, a failed Secret Manager fetch leaves the golden image's stale
// ~/.claude-env in place and the agent silently uses the wrong endpoint.
// ---------------------------------------------------------------------------
const injectAgent = section(code, 'inject_agent_auth');
check(
  'inject_agent_auth purges ~/.claude-env before writing',
  /rm -f ~\/\.claude-env/.test(injectAgent),
  'A failed fetch must yield no credential, never a stale one.',
);

// ---------------------------------------------------------------------------
// 5. A missing agent credential must fail, not warn.
// ---------------------------------------------------------------------------
const fetchFn = section(code, 'fetch_agent_token_from_secret_manager');
check(
  'fetch_agent_token_from_secret_manager returns non-zero on failure',
  !/agent_token_help\s*\n\s*return 0/.test(fetchFn),
  'Returning 0 on a missing token defers the failure into tmux.',
);

// ---------------------------------------------------------------------------
// 6. The firewall is never opened to the world.
// ---------------------------------------------------------------------------
check(
  'no 0.0.0.0/0 firewall source range',
  !/--source-ranges[= ]["']?0\.0\.0\.0\/0/.test(code),
  'resolve_source_cidr scopes the rule to one address and aborts otherwise.',
);

// ---------------------------------------------------------------------------
// 7. gcloud port lists must name a protocol per port.
//
// `--allow=tcp:22,80,443` makes gcloud read 80 and 443 as protocol names.
// ---------------------------------------------------------------------------
for (const m of code.matchAll(/--allow[= ]([^\s"']+)/g)) {
  check(
    `--allow entry "${m[1]}" names a protocol for every port`,
    m[1].split(',').every((part) => /^[a-z]+:/.test(part)),
    'Write tcp:22,tcp:80,tcp:443.',
  );
}

// ---------------------------------------------------------------------------
// 8. Every verb in usage() is dispatched in main(), and the reverse.
// ---------------------------------------------------------------------------
const usage = section(code, 'usage');
const mainFn = section(code, 'main');
for (const verb of ['create', 'up', 'list', 'stop', 'rm', 'mount', 'unmount', 'refresh-ip']) {
  check(`usage() documents session ${verb}`, usage.includes(`session ${verb}`));
  check(`main() dispatches session ${verb}`, new RegExp(`\\b${verb}\\)`).test(mainFn));
}

// ---------------------------------------------------------------------------

function stripComments(text) {
  return text
    .split('\n')
    .filter((line) => !/^\s*#/.test(line))
    .join('\n');
}

// Body of a shell function, from its `name() {` to the first column-0 `}`.
function section(text, name) {
  const start = text.indexOf(`${name}() {`);
  if (start === -1) return '';
  const end = text.indexOf('\n}', start);
  return text.slice(start, end === -1 ? undefined : end);
}

if (failures.length > 0) {
  console.error(`FAIL (${failures.length})`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('ok — jungle_up_gcp.sh guards pass');
