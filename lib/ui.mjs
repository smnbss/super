// lib/ui.mjs — Terminal output, colors, and UI components
// Replaces ui.sh — zero dependencies, raw ANSI codes

const isTTY = process.stderr.isTTY;
const c = (code) => isTTY ? `\x1b[${code}m` : '';
const reset = c(0);

// ─── Colors ─────────────────────────────────────────────────────────────────

export const colors = {
  primary:   (s) => `${c(36)}${s}${reset}`,   // cyan
  success:   (s) => `${c(32)}${s}${reset}`,   // green
  warning:   (s) => `${c(33)}${s}${reset}`,   // yellow
  error:     (s) => `${c(31)}${s}${reset}`,   // red
  muted:     (s) => `${c(90)}${s}${reset}`,   // bright black
  accent:    (s) => `${c(35)}${s}${reset}`,   // magenta
  bold:      (s) => `${c(1)}${s}${reset}`,
  dim:       (s) => `${c(2)}${s}${reset}`,
  underline: (s) => `${c(4)}${s}${reset}`,
};

// ─── Icons ──────────────────────────────────────────────────────────────────

export const icons = {
  ok: '✓', error: '✗', warning: '⚠', info: 'ℹ',
  arrow: '→', bullet: '•', diamond: '◆',
  active: '◀', bridge: '🔀', checkpoint: '💾',
  file: '📄', resume: '↩️', newSession: '🆕',
};

export const cliIcons = { claude: '🟠', gemini: '🔵', codex: '🟢', kimi: '🟡' };
export const cliLabels = {
  claude: 'Claude Code', gemini: 'Gemini CLI', codex: 'Codex CLI', kimi: 'Kimi Code CLI',
};

// ─── Output functions ───────────────────────────────────────────────────────

export function print(...args)   { console.log(...args); }
export function brand(...args)   { print(`${colors.primary(icons.bridge)} ${args.join(' ')}`); }
export function success(...args) { print(`${colors.success(icons.ok)} ${args.join(' ')}`); }
export function error(...args)   { console.error(`${colors.error(icons.error)} ${args.join(' ')}`); }
export function warn(...args)    { print(`${colors.warning(icons.warning)} ${args.join(' ')}`); }
export function info(...args)    { print(`${colors.muted(icons.info)} ${args.join(' ')}`); }
export function muted(...args)   { print(`${colors.muted(args.join(' '))}`); }
export function bold(...args)    { print(`${colors.bold(args.join(' '))}`); }

// ─── Layout ─────────────────────────────────────────────────────────────────

export function spacer(n = 1) { for (let i = 0; i < n; i++) print(''); }

export function rule(width = 60, ch = '─') { print(ch.repeat(width)); }

export function section(title) {
  spacer();
  bold(title);
  rule(40);
}

export function box(...lines) {
  const maxW = Math.max(...lines.map(l => l.length));
  const w = maxW + 4;
  print(`┌${'─'.repeat(w - 2)}┐`);
  for (const line of lines) print(`│ ${line.padEnd(maxW)} │`);
  print(`└${'─'.repeat(w - 2)}┘`);
}

// ─── Banner ─────────────────────────────────────────────────────────────────

export function banner(version) {
  spacer();
  print(`  ${colors.primary('╭──────────────────────────────────────────╮')}`);
  print(`  ${colors.primary('│')}  🔀  ${colors.bold('super')} ${colors.muted(`v${version}`)}                   ${colors.primary('│')}`);
  print(`  ${colors.primary('│')}  Cross-CLI session bridge                ${colors.primary('│')}`);
  print(`  ${colors.primary('╰──────────────────────────────────────────╯')}`);
  spacer();
}

// ─── Helpers ────────────────────────────────────────────────────────────────

export function humanSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${Math.round(bytes / 1024)}KB`;
  return `${Math.round(bytes / 1048576)}MB`;
}

export function cliIcon(name) {
  return cliIcons[name?.toLowerCase()] || '⚪';
}
