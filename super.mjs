#!/usr/bin/env node
// super.mjs — Cross-CLI session bridge
// Claude Code · Gemini CLI · Codex CLI · Kimi Code CLI

import { existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync, statSync, symlinkSync, unlinkSync, lstatSync, copyFileSync, chmodSync } from 'fs';
import { join, basename, dirname } from 'path';
import { execSync, execFileSync } from 'child_process';
import { fileURLToPath } from 'url';

import * as config from './lib/config.mjs';
import * as ui from './lib/ui.mjs';
import * as session from './lib/session.mjs';
import * as catalog from './lib/catalog.mjs';
import * as interactive from './lib/interactive.mjs';
import { fzfPickSession, fzfPickCli, fzfIsAvailable } from './lib/fzf.mjs';
import { securityCheck, formatBlockReason } from './lib/security.mjs';
import { runValidators } from './lib/validators.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
process.env.SUPER_HOME = process.env.SUPER_HOME || __dirname;
const SUPER_HOME = process.env.SUPER_HOME;
const VERSION = config.superVersion();

const CLI = {
  claude: { cmd: 'claude', icon: '🟠', label: 'Claude Code', ctx: 'CLAUDE.md' },
  gemini: { cmd: 'gemini', icon: '🔵', label: 'Gemini CLI', ctx: 'GEMINI.md' },
  codex:  { cmd: 'codex',  icon: '🟢', label: 'Codex CLI',  ctx: 'AGENTS.md' },
  kimi:   { cmd: 'kimi',   icon: '🟡', label: 'Kimi Code CLI', ctx: 'AGENTS.md' },
};

function die(msg) { ui.error(msg); process.exit(1); }

// ═══════════════════════════════════════════════════════════════════════════════
// STATUS & DOCTOR
// ═══════════════════════════════════════════════════════════════════════════════

function cmdStatus() {
  ui.banner(VERSION);
  ui.section('CLIs');
  for (const [name, c] of Object.entries(CLI)) {
    if (catalog.isInstalled(name)) {
      ui.print(`  ${c.icon}  ${ui.colors.success(c.label)}  ${ui.colors.muted(which(name))}`);
    } else {
      ui.print(`  ${c.icon}  ${ui.colors.error(c.label)}  ${ui.colors.muted('(not installed)')}`);
    }
  }

  ui.section('Sessions');
  const sessions = session.sessionList();
  const active = session.sessionFile();
  ui.print(`  📁 ${sessions.length} total`);

  if (active && existsSync(active)) {
    const content = readFileSync(active, 'utf8');
    const turns = (content.match(/^## /gm) || []).length;
    const size = statSync(active).size;
    ui.spacer();
    ui.print(`  ${ui.colors.success(ui.icons.active)} ${ui.colors.bold('ACTIVE:')} ${basename(active)}`);
    ui.print(`     ${turns} turns  |  ${ui.humanSize(size)}`);
  }

  ui.spacer();
  if (fzfIsAvailable()) ui.success('fzf integration ready');
  else ui.info('fzf not installed — using fallback menus');
  ui.spacer();
}

function cmdDoctor() {
  ui.banner(VERSION);
  ui.section('Health Check');
  let issues = 0;
  const root = config.findRoot();

  ui.muted('Checking CLI hooks...');
  const hookFiles = {
    claude: join(root, '.claude', 'settings.json'),
    gemini: join(root, '.gemini', 'settings.json'),
    codex:  join(root, '.codex', 'hooks.json'),
    kimi:   join(root, '.kimi', 'config.toml'),
  };
  for (const [name, path] of Object.entries(hookFiles)) {
    const c = CLI[name];
    if (existsSync(path)) {
      const content = readFileSync(path, 'utf8');
      if (content.includes('super')) {
        ui.success(`${c.icon} ${c.label} hooks installed`);
      } else {
        ui.warn(`${c.icon} ${c.label} hooks not found`);
        ui.muted(`      Run: super install ${name}`);
        issues++;
      }
    } else {
      ui.muted(`  ${c.icon} ${c.label} — no config file`);
    }
  }

  ui.spacer();
  ui.muted('Checking context files...');
  const claudeMd = join(root, 'CLAUDE.md');
  const geminiMd = join(root, 'GEMINI.md');
  const agentsMd = join(root, 'AGENTS.md');

  try {
    if (lstatSync(claudeMd).isSymbolicLink() && lstatSync(geminiMd).isSymbolicLink() && existsSync(agentsMd)) {
      ui.success('Context files correctly symlinked (AGENTS.md master)');
    } else {
      ui.warn('Context files not correctly symlinked');
      issues++;
    }
  } catch {
    ui.warn('Context files not set up');
    ui.muted('      Run: super install');
    issues++;
  }

  ui.spacer();
  ui.muted('Checking sessions...');
  const sessions = session.sessionList();
  ui.success(`${sessions.length} session(s) found`);

  ui.spacer();
  ui.rule();
  if (issues === 0) ui.success('All checks passed — super is healthy!');
  else ui.warn(`Found ${issues} issue(s) to address`);
}

// ═══════════════════════════════════════════════════════════════════════════════
// HOOKS INSTALLATION
// ═══════════════════════════════════════════════════════════════════════════════

function mergeJsonHooks(filePath, newData, idField) {
  let existing = {};
  if (existsSync(filePath)) {
    try { existing = JSON.parse(readFileSync(filePath, 'utf8')); } catch { /* */ }
  }

  // Merge env
  if (newData.env) {
    existing.env = { ...(existing.env || {}), ...newData.env };
  }

  // Merge hooks
  if (newData.hooks) {
    existing.hooks = existing.hooks || {};
    for (const [event, newDefs] of Object.entries(newData.hooks)) {
      if (!existing.hooks[event]) {
        existing.hooks[event] = newDefs;
      } else {
        for (const newDef of newDefs) {
          const newCmds = (newDef.hooks || []).map(h => h[idField] || '');
          const alreadyPresent = existing.hooks[event].some(existingDef =>
            (existingDef.hooks || []).some(h => newCmds.includes(h[idField] || ''))
          );
          if (!alreadyPresent) existing.hooks[event].push(newDef);
        }
      }
    }
  }

  writeFileSync(filePath, JSON.stringify(existing, null, 2) + '\n');
}

function expandTemplate(templatePath) {
  const raw = readFileSync(templatePath, 'utf8');
  return raw
    .replace(/\$SUPER_HOME/g, SUPER_HOME)
    .replace(/\{\{SUPER_HOME\}\}/g, '$SUPER_HOME');
}

function installHooksClaude() {
  const root = config.findRoot();
  const dir = join(root, '.claude'); mkdirSync(dir, { recursive: true });
  const sf = join(dir, 'settings.json');
  const template = join(SUPER_HOME, 'hooks', 'claude', 'settings.json.template');
  const data = JSON.parse(expandTemplate(template));
  if (existsSync(sf)) { mergeJsonHooks(sf, data, 'command'); ui.success(`Updated ${sf}`); }
  else { writeFileSync(sf, JSON.stringify(data, null, 2) + '\n'); ui.success(`Created ${sf}`); }
}

function installHooksGemini() {
  const root = config.findRoot();
  const dir = join(root, '.gemini'); mkdirSync(dir, { recursive: true });
  const gf = join(dir, 'settings.json');
  const template = join(SUPER_HOME, 'hooks', 'gemini', 'settings.json.template');
  const data = JSON.parse(expandTemplate(template));
  if (existsSync(gf)) { mergeJsonHooks(gf, data, 'name'); ui.success(`Updated ${gf}`); }
  else { writeFileSync(gf, JSON.stringify(data, null, 2) + '\n'); ui.success(`Created ${gf}`); }
}

function installHooksCodex() {
  const root = config.findRoot();
  const dir = join(root, '.codex'); mkdirSync(dir, { recursive: true });
  const hf = join(dir, 'hooks.json');
  const template = join(SUPER_HOME, 'hooks', 'codex', 'hooks.json.template');
  const data = JSON.parse(expandTemplate(template));
  if (existsSync(hf)) { mergeJsonHooks(hf, data, 'command'); ui.success(`Updated ${hf}`); }
  else { writeFileSync(hf, JSON.stringify(data, null, 2) + '\n'); ui.success(`Created ${hf}`); }
}

function installHooksKimi() {
  const root = config.findRoot();
  const dir = join(root, '.kimi'); mkdirSync(dir, { recursive: true });
  const cfg = join(dir, 'config.toml');
  const template = join(SUPER_HOME, 'hooks', 'kimi', 'config.toml.template');
  const expanded = expandTemplate(template);
  if (existsSync(cfg)) {
    const content = readFileSync(cfg, 'utf8');
    if (content.includes('super hooks for Kimi')) {
      ui.warn(`super hooks already in ${cfg} — skipping`);
    } else {
      writeFileSync(cfg, content + '\n# super hooks\n' + expanded + '\n');
      ui.success(`Updated ${cfg}`);
    }
  } else {
    writeFileSync(cfg, '# Kimi config\n# super hooks\n' + expanded + '\n');
    ui.success(`Created ${cfg}`);
  }
}

function installHooks(target) {
  const installers = { claude: installHooksClaude, gemini: installHooksGemini, codex: installHooksCodex, kimi: installHooksKimi };
  if (target === 'all') { Object.values(installers).forEach(fn => fn()); }
  else if (installers[target]) { installers[target](); }
  else die(`Unknown CLI: ${target}. Use: all|claude|gemini|codex|kimi`);
}

function setupContextFiles() {
  const root = config.findRoot();
  const claudeMd = join(root, 'CLAUDE.md');
  const geminiMd = join(root, 'GEMINI.md');
  const agentsMd = join(root, 'AGENTS.md');

  // Find existing non-symlink context file
  let existing = null;
  for (const f of [claudeMd, geminiMd, agentsMd]) {
    try { if (existsSync(f) && !lstatSync(f).isSymbolicLink()) { existing = f; break; } } catch { /* */ }
  }

  if (existing) {
    const targetName = basename(existing);
    ui.info(`Found existing ${targetName} — symlinking other context files`);
    for (const f of [claudeMd, geminiMd, agentsMd]) {
      if (f === existing) continue;
      try { unlinkSync(f); } catch { /* */ }
      symlinkSync(targetName, f);
      ui.success(`${basename(f)} → ${targetName}`);
    }
  } else {
    ui.info('Creating context files (AGENTS.md as master)');
    writeFileSync(agentsMd, '# Agents Configuration\n');
    ui.success('Created AGENTS.md');
    symlinkSync('AGENTS.md', claudeMd); ui.success('CLAUDE.md → AGENTS.md');
    symlinkSync('AGENTS.md', geminiMd); ui.success('GEMINI.md → AGENTS.md');
  }
}

function installConfigTemplate() {
  const root = config.findRoot();
  const superDir = join(root, '.super');
  const dest = join(superDir, 'super.config.yaml');
  mkdirSync(superDir, { recursive: true });
  if (existsSync(dest)) { ui.muted(`Config already exists: ${dest}`); return; }
  const projectConfig = join(root, 'super.config.yaml');
  const template = join(SUPER_HOME, 'super.config.yaml');
  if (existsSync(projectConfig)) { copyFileSync(projectConfig, dest); ui.success('Created .super/super.config.yaml from project config'); }
  else if (existsSync(template)) { copyFileSync(template, dest); ui.success('Created .super/super.config.yaml from template'); }
  else { config.configInit(); ui.success('Created .super/super.config.yaml with defaults'); }
}

async function cmdInstall(args) {
  const target = args[0];
  const root = config.findRoot();
  const isFirstTime = !existsSync(join(root, '.super', 'super.config.yaml')) && !existsSync(join(root, 'super.config.yaml'));

  if (!target) {
    // Interactive mode
    if (isFirstTime) { installConfigTemplate(); ui.spacer(); }

    // Pick CLIs
    const clis = catalog.installedClis();
    const options = clis.map(c => `${CLI[c].icon} ${CLI[c].label}`);
    const indices = await interactive.selectMulti('Select CLIs to install:', options);
    if (indices) {
      for (const idx of indices) installHooks(clis[idx]);
    }

    // Install catalog
    config.invalidateCache();
    if (config.findConfig()) {
      ui.spacer();
      if (await interactive.confirm('Install enabled skills, plugins & MCPs?', true)) {
        catalog.installEnabled();
      }
    }
  } else {
    // Non-interactive
    ui.brand(`Installing hooks (target: ${target})`);
    ui.spacer();
    installHooks(target);
    if (isFirstTime) { ui.spacer(); installConfigTemplate(); }
    config.invalidateCache();
    if (config.findConfig()) { ui.spacer(); catalog.installEnabled(); }
  }

  // Finish
  mkdirSync(config.sessionsDir(), { recursive: true });
  setupContextFiles();
  ui.spacer();
  ui.success(`Sessions folder ready: ${config.sessionsDir()}`);
  ui.muted(`Run ${ui.colors.bold('super launch <cli>')} to start your first session`);

  const sessions = session.sessionList();
  if (sessions.length === 0) {
    ui.spacer();
    ui.box(
      'What super does:', '',
      '1. Start: super claude',
      '2. Work — super logs silently',
      '3. Switch: super switch gemini',
      '4. Continue seamlessly', '',
      'Your conversation follows you.',
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// LAUNCH / RESUME / SWITCH
// ═══════════════════════════════════════════════════════════════════════════════

function cmdLaunch(cli, args = []) {
  if (!cli) { cmdMenu(); return; }
  cli = cli.toLowerCase();
  if (!CLI[cli]) die(`Unknown CLI: ${cli}`);
  if (!catalog.isInstalled(cli)) die(`${CLI[cli].label} is not installed`);

  let doResume = false, resumeFile = '', title = '';
  const passthrough = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--resume' || args[i] === '-r') {
      doResume = true;
      if (args[i + 1] && !args[i + 1].startsWith('-')) { resumeFile = args[++i]; }
    } else if (args[i] === '--title' || args[i] === '-t') { title = args[++i] || ''; }
    else { passthrough.push(args[i]); }
  }

  // Cleanup old sessions
  if (config.configEnabled('session.cleanupOnStart')) {
    const maxAge = config.configGet('session.maxAgeDays') || 7;
    session.sessionCleanupOld(maxAge);
  }

  let sf;
  if (resumeFile) {
    if (!existsSync(resumeFile)) resumeFile = join(config.sessionsDir(), resumeFile);
    sf = session.sessionResume(resumeFile);
  } else if (doResume) {
    // Would need async for fzf picker — for simplicity, create new
    sf = session.sessionNew(title || 'untitled');
  } else {
    sf = session.sessionNew(title || 'untitled');
  }

  const size = statSync(sf).size;
  if (size > 1048576) ui.warn(`Large session (${ui.humanSize(size)}) — context injection may be slow`);

  process.env.SUPER_SESSION_FILE = sf;
  session.sessionInjectContext(cli);

  ui.spacer();
  ui.rule(60);
  ui.print(`  ${CLI[cli].icon}  ${ui.colors.bold(CLI[cli].label)}`);
  ui.print(`  📄  ${basename(sf)}`);
  ui.rule(60);
  ui.spacer();

  // exec the CLI
  const cliArgs = [...cliDefaultArgs(cli), ...passthrough];
  try { execFileSync(CLI[cli].cmd, cliArgs, { stdio: 'inherit' }); }
  catch (e) { process.exit(e.status || 1); }
}

function cmdSwitch(toCli) {
  if (!toCli) die('Usage: super switch <cli>');
  toCli = toCli.toLowerCase();
  if (!CLI[toCli]) die(`Unknown CLI: ${toCli}`);
  if (!catalog.isInstalled(toCli)) die(`${CLI[toCli].label} is not installed`);

  let sf = session.sessionFile();
  if (!sf) sf = session.sessionNew('untitled');

  ui.print(`${ui.icons.bridge}  ${ui.colors.muted('Crossing the bridge to')} ${CLI[toCli].label}...`);
  ui.muted(`  Session: ${basename(sf)}`);
  session.sessionInjectContext(toCli);

  ui.spacer();
  ui.rule(60);
  ui.print(`  ${CLI[toCli].icon}  ${ui.colors.bold(CLI[toCli].label)}`);
  ui.print(`  📄  ${basename(sf)}`);
  ui.rule(60);
  ui.spacer();

  try { execFileSync(CLI[toCli].cmd, cliDefaultArgs(toCli), { stdio: 'inherit' }); }
  catch (e) { process.exit(e.status || 1); }
}

async function cmdResume(input) {
  if (input) {
    let sf = existsSync(input) ? input : join(config.sessionsDir(), input);
    if (!existsSync(sf)) die(`Session not found: ${input}`);
    ui.print(`${ui.icons.resume}  ${ui.colors.muted('Picking up where you left off...')}`);

    const cli = await fzfPickCli();
    if (!cli) { ui.info('Cancelled.'); return; }
    cmdLaunch(cli, ['--resume', sf]);
  } else {
    const picked = await fzfPickSession();
    if (picked === 'QUIT') { ui.info('Cancelled.'); return; }
    if (picked === 'NEW' || !picked) { await cmdMenu(); return; }

    const cli = await fzfPickCli();
    if (!cli) { ui.info('Cancelled.'); return; }
    cmdLaunch(cli, ['--resume', picked]);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SIMPLE COMMANDS
// ═══════════════════════════════════════════════════════════════════════════════

function cmdSessions() {
  const sessions = session.sessionList();
  if (sessions.length === 0) { ui.warn('No sessions found.'); return; }
  ui.section('Sessions');
  sessions.forEach((s, i) => {
    const marker = s.isActive ? ` ${ui.colors.success(ui.icons.active)}` : '';
    ui.print(`  ${ui.colors.bold(String(i + 1).padStart(2))}  ${s.title.padEnd(28)}  ${s.started.padEnd(16)}  ${s.turns} turns${marker}`);
  });
  ui.spacer();
}

function cmdLog(arg) {
  const sf = session.sessionFile();
  if (!sf) die('No active session');
  if (arg && /^\d+$/.test(arg)) {
    ui.section(`Last ${arg} turns`);
    const lines = readFileSync(sf, 'utf8').split('\n').filter(l => l !== '---');
    ui.print(lines.slice(-parseInt(arg) * 10).join('\n'));
  } else {
    ui.section(`Session: ${basename(sf)}`);
    ui.print(readFileSync(sf, 'utf8'));
  }
}

function cmdSave(note) {
  const sf = session.sessionFile();
  if (!sf) die('No active session');
  const msg = note || `Checkpoint at ${new Date().toISOString().slice(0, 19).replace('T', ' ')}`;
  session.sessionAppendTurn('super', 'tool', `💾 Checkpoint: ${msg}`);
  ui.success(`Checkpoint saved: ${msg}`);
}

function cmdCatchup() {
  const summary = session.sessionGetSummary(30);
  ui.section('Session Catchup');
  ui.print(summary);
}

function cmdCleanup(days) {
  const maxDays = parseInt(days) || 7;
  const count = session.sessionCleanupOld(maxDays);
  ui.success(`Cleaned up ${count} session(s) older than ${maxDays} days`);
}

function cmdClean() {
  ui.info('Removing context injections...');
  session.sessionClearInjections();
  ui.success('Done');
}

function cmdValidate() { runValidators(); }

function cmdConfig(args) {
  const sub = args[0] || 'show';
  if (sub === 'show') {
    const path = config.findConfig();
    if (!path) { ui.warn('No config file found'); return; }
    ui.print(readFileSync(path, 'utf8'));
  } else if (sub === 'init') {
    const path = config.configInit();
    ui.success(`Created config: ${path}`);
  } else if (sub === 'edit') {
    const path = config.findConfig() || config.configInit();
    execSync(`${process.env.EDITOR || 'vi'} "${path}"`, { stdio: 'inherit' });
  }
}

function cmdUninstall() {
  const root = config.findRoot();
  ui.brand('Removing super hooks...');
  for (const [name, hookFile] of Object.entries({
    claude: join(root, '.claude', 'settings.json'),
    gemini: join(root, '.gemini', 'settings.json'),
    codex: join(root, '.codex', 'hooks.json'),
  })) {
    if (!existsSync(hookFile)) continue;
    try {
      const data = JSON.parse(readFileSync(hookFile, 'utf8'));
      if (data.hooks) {
        for (const ev of Object.keys(data.hooks)) {
          data.hooks[ev] = data.hooks[ev].filter(g =>
            !(g.hooks || []).some(h => (h.command || h.name || '').includes('super'))
          );
          if (data.hooks[ev].length === 0) delete data.hooks[ev];
        }
      }
      writeFileSync(hookFile, JSON.stringify(data, null, 2) + '\n');
      ui.success(`Cleaned ${hookFile}`);
    } catch { /* */ }
  }
  session.sessionClearInjections();
  ui.spacer();
  ui.info(`Hooks removed. Sessions preserved at ${config.sessionsDir()}`);
}

// ═══════════════════════════════════════════════════════════════════════════════
// MENU
// ═══════════════════════════════════════════════════════════════════════════════

async function cmdMenu() {
  const sessions = session.sessionList();
  const hasSessions = sessions.length > 0;
  const active = session.sessionFile();

  ui.banner(VERSION);

  const options = ['🆕 Start a new session'];
  if (hasSessions) options.push('↩️  Resume a previous session');
  options.push('⚙️  Configure super (skills, plugins, MCPs)');
  options.push('🩺 Run health check (doctor)');
  options.push('🚪 Quit');

  const choice = await interactive.selectSingle('What would you like to do?', options, 0);
  if (choice === null) { ui.info('Bye!'); return; }

  let idx = 0;
  if (choice === idx) { const cli = await fzfPickCli(); if (cli) cmdLaunch(cli); return; }
  idx++;
  if (hasSessions && choice === idx) { await cmdResume(); return; }
  if (hasSessions) idx++;
  if (choice === idx) { await cmdInstall([]); return; }
  idx++;
  if (choice === idx) { cmdDoctor(); return; }
  idx++;
  ui.info('Bye!');
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELP
// ═══════════════════════════════════════════════════════════════════════════════

function cmdHelp() {
  ui.banner(VERSION);
  ui.print(`
USAGE
  super [command] [options]

COMMANDS
  install [target]     Install hooks (all|claude|gemini|codex|kimi)
  claude|gemini|codex|kimi  Launch CLI with session tracking
  resume [session]     Resume a previous session
  switch <cli>         Continue session in different CLI
  sessions             List all sessions
  log [N]              View session (last N turns)
  save [note]          Save checkpoint
  catchup              Show session summary
  doctor               Health check
  status               Show status
  config [show|init|edit]  Manage configuration
  cleanup [days]       Remove old sessions
  clean                Remove context injections
  validate             Run project validators
  uninstall            Remove super hooks
  help                 Show this help

SHORTCUTS
  super @              Jump to active session
  super !              New session
  super ?              Fuzzy search sessions

EXAMPLES
  super claude                    # New Claude session
  super claude --resume           # Resume with picker
  super gemini --title "fix auth" # Named session
  super switch gemini             # Continue in Gemini
  super doctor                    # Health check
`);
}

// ═══════════════════════════════════════════════════════════════════════════════
// QUICK SHORTCUTS
// ═══════════════════════════════════════════════════════════════════════════════

async function cmdQuickActive() {
  const active = session.sessionFile();
  if (!active) { ui.warn('No active session'); return; }
  const content = readFileSync(active, 'utf8');
  const lastTurn = (content.match(/^## .*/gm) || []).pop() || '';
  let cli = 'claude';
  if (lastTurn.includes('🔵')) cli = 'gemini';
  else if (lastTurn.includes('🟢')) cli = 'codex';
  else if (lastTurn.includes('🟡')) cli = 'kimi';
  cmdLaunch(cli, ['--resume', active]);
}

async function cmdQuickNew() {
  const cli = await fzfPickCli();
  if (cli) cmdLaunch(cli);
}

async function cmdQuickSearch() {
  const picked = await fzfPickSession();
  if (picked && picked !== 'QUIT' && picked !== 'NEW') {
    const cli = await fzfPickCli();
    if (cli) cmdLaunch(cli, ['--resume', picked]);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function which(cli) {
  try { return execSync(`command -v ${cli}`, { encoding: 'utf8' }).trim(); } catch { return ''; }
}

// Build CLI-specific default args (e.g. yolo mode, kimi mcp config)
function cliDefaultArgs(cli) {
  const args = [];
  // Yolo mode — auto-accept all tool calls
  if (config.yoloMode()) {
    const yoloFlag = {
      claude: '--dangerously-skip-permissions',
      gemini: '--yolo',
      codex:  '--full-auto',
      kimi:   '--yolo',
    }[cli];
    if (yoloFlag) args.push(yoloFlag);
  }
  // Kimi needs explicit MCP config path
  if (cli === 'kimi') {
    const root = config.findRoot();
    const mcpConfig = join(root, '.kimi', 'mcp.json');
    if (existsSync(mcpConfig)) args.push('--mcp-config-file', mcpConfig);
  }
  return args;
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN DISPATCH
// ═══════════════════════════════════════════════════════════════════════════════

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0] || 'menu';
  const rest = args.slice(1);

  switch (cmd) {
    case '@': await cmdQuickActive(); break;
    case '!': await cmdQuickNew(); break;
    case '?': await cmdQuickSearch(); break;
    case 'install': case 'i': await cmdInstall(rest); break;
    case 'launch': case 'l': case 'run': cmdLaunch(rest[0], rest.slice(1)); break;
    case 'resume': case 'r': await cmdResume(rest[0]); break;
    case 'sessions': case 'ls': case 'list': cmdSessions(); break;
    case 'switch': case 'sw': cmdSwitch(rest[0]); break;
    case 'log': case 'show': cmdLog(rest[0]); break;
    case 'doctor': case 'dr': cmdDoctor(); break;
    case 'clean': cmdClean(); break;
    case 'uninstall': cmdUninstall(); break;
    case 'status': case 's': cmdStatus(); break;
    case 'config': case 'cfg': cmdConfig(rest); break;
    case 'validate': case 'lint': cmdValidate(); break;
    case 'cleanup': cmdCleanup(rest[0]); break;
    case 'save': cmdSave(rest.join(' ')); break;
    case 'catchup': case 'c': cmdCatchup(); break;
    case '--version': case '-v': console.log(`super v${VERSION}`); break;
    case 'help': case '--help': case '-h': cmdHelp(); break;
    case 'menu': await cmdMenu(); break;
    case 'claude': case 'gemini': case 'codex': case 'kimi': cmdLaunch(cmd, rest); break;
    default: die(`Unknown command: ${cmd}. Run: super help`);
  }
}

main().catch(e => { console.error(e.message); process.exit(1); });
