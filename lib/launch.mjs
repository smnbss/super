// lib/launch.mjs — Pure-logic helpers for cmdLaunch (testable, no side effects)

/**
 * Parse launch args into structured options + passthrough.
 * Super-specific flags (--resume, --title, --provider) are extracted;
 * everything else lands in passthrough[] for the target CLI.
 */
export function parseLaunchArgs(args) {
  let doResume = false, resumeFile = '', title = '', provider = '';
  const passthrough = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--resume' || args[i] === '-r') {
      doResume = true;
      if (args[i + 1] && !args[i + 1].startsWith('-')) { resumeFile = args[++i]; }
    } else if (args[i] === '--title' || args[i] === '-t') { title = args[++i] || '';
    } else if (args[i] === '--provider' || args[i] === '-P') { provider = (args[++i] || '').toLowerCase();
    } else { passthrough.push(args[i]); }
  }
  return { doResume, resumeFile, title, provider, passthrough };
}

/**
 * Known third-party providers.
 *
 * Two modes:
 *   wrapper  → provider wraps the CLI binary (e.g. `ollama launch claude ...`)
 *   envVars  → provider is reached by setting ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY
 *     baseUrl  → sets ANTHROPIC_BASE_URL
 *     apiKey   → sets ANTHROPIC_API_KEY to this literal value
 *     envKey   → reads ANTHROPIC_API_KEY from this env var
 */
export const PROVIDERS = {
  ollama:   { wrapper: 'ollama', wrapperArgs: ['launch'] },
  openai:   { envKey: 'OPENAI_API_KEY' },
  lmstudio: { baseUrl: 'http://localhost:1234/v1', apiKey: 'lm-studio' },
  groq:     { baseUrl: 'https://api.groq.com/openai/v1', envKey: 'GROQ_API_KEY' },
  together: { baseUrl: 'https://api.together.xyz/v1', envKey: 'TOGETHER_API_KEY' },
};

/**
 * Resolve a provider name into its execution strategy.
 *
 * Returns one of:
 *   { mode: 'wrapper', cmd: 'ollama', prefixArgs: ['launch', '<cli>'] }
 *   { mode: 'env', vars: { ANTHROPIC_BASE_URL?, ANTHROPIC_API_KEY? } }
 *
 * Throws on unknown provider or missing env var.
 *
 * @param {string} provider  — provider key (e.g. "ollama")
 * @param {string} cli       — target CLI name (e.g. "claude") — used for wrapper mode
 * @param {object} env       — environment map (defaults to process.env)
 */
export function resolveProvider(provider, cli = 'claude', env = process.env) {
  const p = PROVIDERS[provider];
  if (!p) {
    throw new Error(`Unknown provider: ${provider}. Available: ${Object.keys(PROVIDERS).join(', ')}`);
  }
  // Wrapper mode — provider binary wraps the CLI
  if (p.wrapper) {
    return { mode: 'wrapper', cmd: p.wrapper, prefixArgs: [...(p.wrapperArgs || []), cli] };
  }
  // Env-var mode — set ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY
  const vars = {};
  if (p.baseUrl) vars.ANTHROPIC_BASE_URL = p.baseUrl;
  if (p.apiKey) vars.ANTHROPIC_API_KEY = p.apiKey;
  if (p.envKey) {
    const key = env[p.envKey];
    if (!key) throw new Error(`Provider ${provider} requires ${p.envKey} to be set`);
    vars.ANTHROPIC_API_KEY = key;
  }
  return { mode: 'env', vars };
}

/**
 * Build the display label shown in the launch banner.
 * e.g. "Claude Code via ollama (glm-5:cloud)"
 */
export function buildBannerLabel(cliLabel, provider, passthrough) {
  const modelIdx = passthrough.indexOf('--model');
  const displayModel = modelIdx !== -1 ? passthrough[modelIdx + 1] : '';
  const providerLabel = provider ? ` via ${provider}` : '';
  const modelLabel = displayModel ? ` (${displayModel})` : '';
  return `${cliLabel}${providerLabel}${modelLabel}`;
}
