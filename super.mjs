#!/usr/bin/env node
// super.mjs — Cross-CLI session bridge
// Claude Code · Gemini CLI · Codex CLI

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
import { parseLaunchArgs, resolveProvider, buildBannerLabel, buildWrapperArgs } from './lib/launch.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
process.env.SUPER_HOME = process.env.SUPER_HOME || __dirname;
const SUPER_HOME = process.env.SUPER_HOME;
const VERSION = config.superVersion();

// Ensure standard user-install locations are on PATH so `command -v <cli>`
// and execFileSync find CLIs installed there (e.g. ~/.local/bin/claude) even
// when the parent shell's PATH is stale — common right after `super install`
// writes the PATH export to ~/.profile mid-session.
{
  const home = process.env.HOME || '';
  const pathParts = (process.env.PATH || '').split(':');
  const extra = [home && join(home, '.local', 'bin'), SUPER_HOME].filter(Boolean);
  for (const dir of extra) {
    if (!pathParts.includes(dir)) pathParts.unshift(dir);
  }
  process.env.PATH = pathParts.join(':');
}

const CLI = {
  claude: { cmd: 'claude', icon: '🟠', label: 'Claude Code', ctx: 'CLAUDE.md' },
  gemini: { cmd: 'gemini', icon: '🔵', label: 'Gemini CLI', ctx: 'GEMINI.md' },
  codex:  { cmd: 'codex',  icon: '🟢', label: 'Codex CLI',  ctx: 'AGENTS.md' },
};

function die(msg) { ui.error(msg); process.exit(1); }

// ─── Auto-update ─────────────────────────────────────────────────────────────

const UPDATE_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 hours

function shouldCheckUpdates() {
  const marker = join(SUPER_HOME, '.last-update-check');
  if (!existsSync(marker)) return true;
  const last = parseInt(readFileSync(marker, 'utf8').trim(), 10) || 0;
  return (Date.now() - last) > UPDATE_INTERVAL_MS;
}

function markUpdateChecked() {
  try { writeFileSync(join(SUPER_HOME, '.last-update-check'), String(Date.now()) + '\n'); } catch {}
}

function autoUpdate() {
  if (!shouldCheckUpdates()) return;

  const start = Date.now();
  ui.muted('Auto-update check...');

  // Update super itself (best-effort). --rebase --autostash lets the pull
  // succeed even when the user has local edits under ~/.super/skills/.
  try {
    ui.muted('  Pulling super updates...');
    execSync('git pull --rebase --autostash', { cwd: SUPER_HOME, stdio: 'ignore', timeout: 15000 });
    execSync('npm install', { cwd: SUPER_HOME, stdio: 'ignore', timeout: 30000 });
  } catch {}

  // Update all installed CLIs using their catalog install/upgrade command
  for (const cliCfg of config.catalogClis()) {
    if (!cliCfg.install || !catalog.isInstalled(cliCfg.name)) continue;
    let cmd = cliCfg.install;
    // uv tool install does not upgrade; switch to upgrade when already installed
    if (cmd.includes('uv tool install')) {
      cmd = cmd.replace(/uv tool install/g, 'uv tool upgrade');
    }
    try {
      ui.muted(`  Updating ${cliCfg.name}...`);
      execSync(cmd, { stdio: 'ignore', shell: true, timeout: 120000 });
    } catch {}
  }

  // Refresh global super-skill symlinks in each CLI's ~/.<cli>/skills dir.
  // Cheap filesystem-only op; picks up any new skills that a just-pulled
  // super release added without requiring another `super install` run.
  try { catalog.ensureGlobalSuperSkills(null, { silent: true }); } catch {}

  markUpdateChecked();
  ui.muted(`Auto-update done (${ui.elapsed(start)})`);
}

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

  ui.muted('Checking super installation...');
  const superNodeModules = join(SUPER_HOME, 'node_modules');
  if (existsSync(superNodeModules)) {
    ui.success('super dependencies installed');
  } else {
    ui.warn('super dependencies missing — run: cd ~/.super && npm install');
    issues++;
  }

  ui.spacer();
  ui.muted('Checking CLI hooks...');
  const hookFiles = {
    claude: join(root, '.claude', 'settings.json'),
    gemini: join(root, '.gemini', 'settings.json'),
    codex:  join(root, '.codex', 'hooks.json'),
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

function installHooks(target) {
  const installers = { claude: installHooksClaude, gemini: installHooksGemini, codex: installHooksCodex };
  if (target === 'all') { Object.values(installers).forEach(fn => fn()); }
  else if (installers[target]) { installers[target](); }
  else die(`Unknown CLI: ${target}. Use: all|claude|gemini|codex`);
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
  const installStart = Date.now();
  const target = args[0];
  const root = config.findRoot();

  // Refuse to install into $HOME or into the global install dir itself.
  // Without this, a fresh directory with no ancestor `.super/` used to walk
  // all the way up and treat $HOME as the project root — scattering
  // .super/sessions/, .claude/settings.json etc. across $HOME.
  const home = process.env.HOME;
  if (home && root === home) {
    die(`Refusing to install into $HOME (${home}).\n  cwd: ${process.cwd()}\n  Create or cd into a project directory and re-run 'super install'.`);
  }
  if (root === SUPER_HOME) {
    die(`Refusing to install into the super install dir itself (${SUPER_HOME}).\n  cwd: ${process.cwd()}\n  Create or cd into a project directory and re-run 'super install'.`);
  }

  const isFirstTime = !existsSync(join(root, '.super', 'super.config.yaml')) && !existsSync(join(root, 'super.config.yaml'));

  // Force update global ~/.super first. --rebase --autostash preserves any
  // local edits under ~/.super/skills/ (or anywhere else) so the pull — and
  // therefore the downstream built-in-skill sync — actually lands.
  ui.brand('Updating super...');
  ui.spacer();
  try {
    execSync('git pull --rebase --autostash', { cwd: SUPER_HOME, stdio: 'inherit', timeout: 15000 });
    execSync('npm install', { cwd: SUPER_HOME, stdio: 'inherit', timeout: 30000 });
    ui.success('super updated');
  } catch {
    ui.warn('super update failed — continuing with current version');
  }
  ui.spacer();

  // Write the project config template so the catalog has something to read.
  if (isFirstTime) { installConfigTemplate(); ui.spacer(); }
  config.invalidateCache();

  // System prereqs + CLI binaries come from the catalog, not super-setup.
  let cliResults = { installed: [], failed: [], skipped: [] };
  if (config.findConfig()) {
    ui.brand('Installing system prerequisites...');
    ui.spacer();
    catalog.installSystem();
    ui.spacer();
    ui.brand('Installing enabled CLIs...');
    ui.spacer();
    cliResults = catalog.installClis();
    ui.spacer();

    ui.section('Installation Summary');
    if (cliResults.installed.length > 0) {
      ui.success(`  ✅ Installed: ${cliResults.installed.join(', ')}`);
    }
    if (cliResults.skipped.length > 0) {
      ui.muted(`  ⏭️  Already present: ${cliResults.skipped.join(', ')}`);
    }
    if (cliResults.failed.length > 0) {
      ui.error(`  ❌ Failed: ${cliResults.failed.map(f => f.name).join(', ')}`);
      ui.spacer();
      ui.warn('Failed installations:');
      for (const fail of cliResults.failed) ui.muted(`    • ${fail.name}: ${fail.reason}`);
      ui.spacer();
      ui.info('To retry manually:');
      const cfg = config.catalogClis().filter(c => cliResults.failed.some(f => f.name === c.name));
      for (const cli of cfg) if (cli.install) ui.muted(`    ${cli.name}: ${cli.install}`);
    }
    ui.spacer();
  }

  // Pick CLIs and install hooks.
  //   `super install --all`            → skip prompt, install hooks for all detected CLIs
  //   `super install <claude|codex|gemini>` → install hooks only for that CLI
  //   `super install`                  → interactive multi-select (default)
  let selectedClis = null;
  const clis = catalog.installedClis();
  if (target === '--all' || clis.length === 0) {
    ui.brand('Installing hooks for all available CLIs');
    ui.spacer();
    installHooks('all');
    selectedClis = clis;
  } else if (target) {
    ui.brand(`Installing hooks for ${target}`);
    ui.spacer();
    installHooks(target);
    selectedClis = target === 'all' ? clis : [target];
  } else {
    const options = clis.map(c => `${CLI[c].icon} ${CLI[c].label}`);
    const indices = await interactive.selectMulti('Select CLIs to configure:', options);
    if (indices && indices.length > 0) {
      selectedClis = indices.map(idx => clis[idx]);
      for (const cli of selectedClis) installHooks(cli);
    } else {
      ui.warn('No CLIs selected — installing all available hooks.');
      installHooks('all');
      selectedClis = clis;
    }
  }

  // Core phase: bootstrap + built-in skills shipped in $SUPER_HOME/skills,
  // CLI home symlinks, and skill-dir sync. Never pulls external skills,
  // plugins, or MCPs — those live in `super configure`.
  if (config.findConfig()) {
    catalog.installPhaseInstall(selectedClis);
  }

  // Also keep super's built-in skills fresh in the CLI's GLOBAL skill dir
  // (~/.claude/skills, ~/.codex/skills) so skills like /super-clone invoked
  // outside a brain project use the latest shipped version. Symlinks point
  // directly at $SUPER_HOME/skills so super's git-pull auto-update applies
  // to these too without needing another `super install` pass.
  ui.spacer();
  ui.brand('Syncing super skills to global CLI dirs...');
  ui.spacer();
  catalog.ensureGlobalSuperSkills(selectedClis);
  ui.spacer();

  // Ensure SUPER_HOME is on PATH in shell profile (idempotent).
  const profile = process.platform === 'darwin'
    ? join(process.env.HOME, '.zshrc')
    : join(process.env.HOME, '.profile');
  const marker = 'export SUPER_HOME=';
  try {
    const content = existsSync(profile) ? readFileSync(profile, 'utf8') : '';
    if (!content.includes(marker)) {
      const snippet = `\n# super CLI\nexport SUPER_HOME="${SUPER_HOME}"\nexport PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"\n`;
      writeFileSync(profile, content + snippet);
      ui.success(`Added SUPER_HOME to ~/${basename(profile)}`);
    }
  } catch {}

  mkdirSync(config.sessionsDir(), { recursive: true });
  ui.spacer();
  ui.success(`Sessions folder ready: ${config.sessionsDir()}`);
  ui.success(`Total install time: ${ui.elapsed(installStart)}`);

  ui.spacer();
  ui.box(
    'Next steps', '',
    '1. Edit .env.local and fill in credentials',
    '   (only the sources you actually use need values)', '',
    '2. Launch a CLI: super launch <claude|codex|gemini>', '',
    '3. Inside the CLI, run /super-setup to configure the brain',
    '   (writes brain.config.yml, installs external skills, plugins,',
    '   MCPs, context files, and — if you enable gws — walks you',
    '   through Google Workspace OAuth + `gws auth login`)',
  );
}

async function cmdConfigure(args) {
  const start = Date.now();
  const root = config.findRoot();
  const home = process.env.HOME;
  if (home && root === home) {
    die(`Refusing to configure in $HOME (${home}).\n  cwd: ${process.cwd()}\n  Run 'super install' from inside a project first.`);
  }
  if (root === SUPER_HOME) {
    die(`Refusing to configure the super install dir itself (${SUPER_HOME}).`);
  }

  if (!config.findConfig()) {
    die("No super.config.yaml found — run 'super install' first.");
  }

  // Scope to installed CLIs unless the caller narrows it.
  const installed = catalog.installedClis();
  let selectedClis = installed;
  const target = args[0];
  if (target && target !== '--all') {
    if (!CLI[target]) die(`Unknown CLI: ${target}. Use: all|claude|gemini|codex`);
    if (!installed.includes(target)) die(`${CLI[target].label} is not installed — run 'super install' first.`);
    selectedClis = [target];
  }

  catalog.installPhaseConfigure(selectedClis);
  setupContextFiles();
  ui.spacer();
  ui.success(`Configure complete (${ui.elapsed(start)})`);
  ui.muted(`Run ${ui.colors.bold('super launch <cli>')} to start a session`);
}

// ═══════════════════════════════════════════════════════════════════════════════
// LAUNCH / RESUME / SWITCH
// ═══════════════════════════════════════════════════════════════════════════════

function extractModelFromPassthrough(passthrough) {
  const modelIdx = passthrough.indexOf('--model');
  if (modelIdx !== -1 && passthrough[modelIdx + 1]) {
    return passthrough[modelIdx + 1];
  }
  // Also check for shorthand -m
  const shortIdx = passthrough.indexOf('-m');
  if (shortIdx !== -1 && passthrough[shortIdx + 1]) {
    return passthrough[shortIdx + 1];
  }
  return '';
}

function cmdLaunch(cli, args = []) {
  if (!cli) { cmdMenu(); return; }
  cli = cli.toLowerCase();
  if (!CLI[cli]) die(`Unknown CLI: ${cli}`);
  if (!catalog.isInstalled(cli)) die(`${CLI[cli].label} is not installed`);
  autoUpdate(cli);

  const { doResume, resumeFile: resumeArg, title, provider, passthrough } = parseLaunchArgs(args);
  let resumeFile = resumeArg;

  // Resolve provider (if any) before session setup
  let providerResult = null;
  if (provider) {
    try {
      providerResult = resolveProvider(provider, cli);
      if (providerResult.mode === 'env') Object.assign(process.env, providerResult.vars);
    } catch (e) { die(e.message); }
  }

  // Extract model from passthrough args
  const model = extractModelFromPassthrough(passthrough);

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
    sf = session.sessionNew(title || 'untitled', cli, provider || '', model);
  } else {
    sf = session.sessionNew(title || 'untitled', cli, provider || '', model);
  }

  const size = statSync(sf).size;
  if (size > 1048576) ui.warn(`Large session (${ui.humanSize(size)}) — context injection may be slow`);

  process.env.SUPER_SESSION_FILE = sf;
  session.sessionInjectContext(cli);

  ui.spacer();
  ui.rule(60);
  const label = buildBannerLabel(CLI[cli].label, provider, passthrough);
  ui.print(`  ${CLI[cli].icon}  ${ui.colors.bold(label)}`);
  ui.print(`  📄  ${basename(sf)}`);
  ui.rule(60);
  ui.spacer();

  // exec the CLI
  const defaults = cliDefaultArgs(cli);
  const isYolo = config.yoloMode();
  if (providerResult && providerResult.mode === 'wrapper') {
    const wrapperArgs = buildWrapperArgs(providerResult, passthrough, defaults, isYolo);
    try { execFileSync(providerResult.cmd, wrapperArgs, { stdio: 'inherit' }); }
    catch (e) { process.exit(e.status || 1); }
  } else {
    const cliArgs = [...defaults, ...passthrough];
    try { execFileSync(CLI[cli].cmd, cliArgs, { stdio: 'inherit' }); }
    catch (e) { process.exit(e.status || 1); }
  }
}

function cmdSwitch(toCli) {
  if (!toCli) die('Usage: super switch <cli>');
  toCli = toCli.toLowerCase();
  if (!CLI[toCli]) die(`Unknown CLI: ${toCli}`);
  if (!catalog.isInstalled(toCli)) die(`${CLI[toCli].label} is not installed`);
  autoUpdate(toCli);

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

    // Read session metadata for recovery options
    const sessionContent = readFileSync(picked, 'utf8');
    const originalCliMatch = sessionContent.match(/^\*\*CLI:\*\* (.+)$/m);
    const originalModelMatch = sessionContent.match(/^\*\*Model:\*\* (.+)$/m);
    const originalProviderMatch = sessionContent.match(/^\*\*Provider:\*\* (.+)$/m);

    const originalCli = originalCliMatch?.[1] || 'claude';
    const originalModel = originalModelMatch?.[1] || '';
    const originalProvider = originalProviderMatch?.[1] || '';

    // Build recovery options
    const modelInfo = originalModel ? ` [${originalModel}]` : '';
    const cliIcon = { claude: '🟠', gemini: '🔵', codex: '🟢' }[originalCli] || '⚪';

    const options = [
      `↩️  Resume with same settings (${cliIcon} ${originalCli}${modelInfo})`,
      '🔀 Switch CLI only',
      '⚙️  Switch model only',
      '🔀⚙️  Switch both CLI and model',
      '❌ Cancel'
    ];

    const choice = await interactive.selectSingle('Resume session — which settings?', options, 0);
    if (choice === null || choice === 4) { ui.info('Cancelled.'); return; }

    let launchCli = originalCli;
    let launchArgs = ['--resume', picked];

    if (choice === 0) {
      // Same settings — use original CLI, model, provider
      launchCli = originalCli;
      if (originalProvider) launchArgs.push('--provider', originalProvider);
      if (originalModel) launchArgs.push('--model', originalModel);
    } else if (choice === 1) {
      // Switch CLI only — pick new CLI, keep model/provider
      const newCli = await fzfPickCli();
      if (!newCli) { ui.info('Cancelled.'); return; }
      launchCli = newCli;
      if (originalProvider) launchArgs.push('--provider', originalProvider);
      if (originalModel) launchArgs.push('--model', originalModel);
    } else if (choice === 2) {
      // Switch model only — keep CLI, pick new model
      if (originalCli === 'claude') {
        const modelOptions = [
          '🟠 Opus (default)',
          '⚡ Sonnet',
          '🪶 Haiku',
          '🌐 Ollama provider →',
        ];
        const modelChoice = await interactive.selectSingle('Select model:', modelOptions, 0);
        if (modelChoice === null) { ui.info('Cancelled.'); return; }

        switch (modelChoice) {
          case 0: break; // default
          case 1: launchArgs.push('--model', 'sonnet'); break;
          case 2: launchArgs.push('--model', 'haiku'); break;
          case 3: {
            const ollamaOptions = [
              'Kimi K2.5 (kimi-k2.5:cloud)',
              'MiniMax M2.5 (minimax-m2.5:cloud)',
              'GLM 5 (glm-5:cloud)',
              'Gemma 4 31B (gemma4:31b-cloud)',
            ];
            const ollamaChoice = await interactive.selectSingle('Ollama model?', ollamaOptions, 0);
            if (ollamaChoice === null) { ui.info('Cancelled.'); return; }
            const ollamaModels = ['kimi-k2.5:cloud', 'minimax-m2.5:cloud', 'glm-5:cloud', 'gemma4:31b-cloud'];
            launchArgs.push('--provider', 'ollama', '--model', ollamaModels[ollamaChoice]);
            break;
          }
        }
      }
    } else if (choice === 3) {
      // Switch both CLI and model
      const newCli = await fzfPickCli();
      if (!newCli) { ui.info('Cancelled.'); return; }
      launchCli = newCli;

      // Prompt for model if Claude
      if (newCli === 'claude') {
        const modelOptions = [
          '🟠 Opus (default)',
          '⚡ Sonnet',
          '🪶 Haiku',
          '🌐 Ollama provider →',
        ];
        const modelChoice = await interactive.selectSingle('Select model:', modelOptions, 0);
        if (modelChoice === null) { ui.info('Cancelled.'); return; }

        switch (modelChoice) {
          case 0: break; // default
          case 1: launchArgs.push('--model', 'sonnet'); break;
          case 2: launchArgs.push('--model', 'haiku'); break;
          case 3: {
            const ollamaOptions = [
              'Kimi K2.5 (kimi-k2.5:cloud)',
              'MiniMax M2.5 (minimax-m2.5:cloud)',
              'GLM 5 (glm-5:cloud)',
              'Gemma 4 31B (gemma4:31b-cloud)',
            ];
            const ollamaChoice = await interactive.selectSingle('Ollama model?', ollamaOptions, 0);
            if (ollamaChoice === null) { ui.info('Cancelled.'); return; }
            const ollamaModels = ['kimi-k2.5:cloud', 'minimax-m2.5:cloud', 'glm-5:cloud', 'gemma4:31b-cloud'];
            launchArgs.push('--provider', 'ollama', '--model', ollamaModels[ollamaChoice]);
            break;
          }
        }
      }
    }

    cmdLaunch(launchCli, launchArgs);
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
    const cliIcon = { claude: '🟠', gemini: '🔵', codex: '🟢' }[s.cli] || '⚪';
    const modelInfo = s.model ? ` [${s.model}]` : '';
    ui.print(`  ${ui.colors.bold(String(i + 1).padStart(2))}  ${cliIcon}  ${s.started.padEnd(20)}  ${String(s.turns).padStart(2)} turns  ${s.title.padEnd(40)}${modelInfo}${marker}`);
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

  ui.banner(VERSION);

  const options = ['🚀 Launch a new session'];
  if (hasSessions) options.push('↩️  Resume a previous session');
  options.push('⚙️  Configure super (skills, plugins, MCPs)');
  options.push('🩺 Run health check (doctor)');
  options.push('🚪 Quit');

  const choice = await interactive.selectSingle('What would you like to do?', options, 0);
  if (choice === null) { ui.info('Bye!'); return; }

  let idx = 0;
  if (choice === idx) { await launchWizard(); return; }
  idx++;
  if (hasSessions && choice === idx) { await cmdResume(); return; }
  if (hasSessions) idx++;
  if (choice === idx) { await cmdInstall([]); return; }
  idx++;
  if (choice === idx) { cmdDoctor(); return; }
  idx++;
  ui.info('Bye!');
}

// ─── Launch wizard (interactive CLI + model/provider picker) ────────────────

const OLLAMA_MODELS = [
  { label: 'Kimi K2.5',    model: 'kimi-k2.5:cloud' },
  { label: 'MiniMax M2.5', model: 'minimax-m2.5:cloud' },
  { label: 'GLM 5',        model: 'glm-5:cloud' },
  { label: 'Gemma 4 31B',  model: 'gemma4:31b-cloud' },
];

async function launchWizard() {
  // Step 1: Pick CLI
  const clis = ['claude', 'gemini', 'codex'].filter(c => catalog.isInstalled(c));
  if (clis.length === 0) { die('No CLI tools installed. Run: super install'); return; }

  const cliOptions = clis.map(c => `${CLI[c].icon}  ${CLI[c].label}`);
  const cliChoice = await interactive.selectSingle('Which CLI?', cliOptions, 0);
  if (cliChoice === null) return;
  const cli = clis[cliChoice];

  // Step 2: For Claude, pick model or provider
  if (cli === 'claude') {
    const modeOptions = [
      '🟠 Opus (default)',
      '⚡ Sonnet',
      '🪶 Haiku',
      '🌐 Ollama provider →',
    ];
    const modeChoice = await interactive.selectSingle('Model / provider?', modeOptions, 0);
    if (modeChoice === null) return;

    switch (modeChoice) {
      case 0: cmdLaunch('claude', []); break;
      case 1: cmdLaunch('claude', ['--model', 'sonnet']); break;
      case 2: cmdLaunch('claude', ['--model', 'haiku']); break;
      case 3: {
        const ollamaOptions = OLLAMA_MODELS.map(m => `${m.label} (${m.model})`);
        const ollamaChoice = await interactive.selectSingle('Ollama model?', ollamaOptions, 0);
        if (ollamaChoice === null) return;
        cmdLaunch('claude', ['--provider', 'ollama', '--model', OLLAMA_MODELS[ollamaChoice].model]);
        break;
      }
    }
  } else {
    cmdLaunch(cli, []);
  }
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
  install [target]     Install super, hooks, CLIs, and built-in skills (all|claude|gemini|codex)
  configure [target]   Install external skills, plugins & MCPs + context files (called by /super-setup)
  claude|gemini|codex  Launch CLI with session tracking
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

OPTIONS (launch)
  --resume, -r           Resume a session
  --title, -t <name>     Named session
  --provider, -P <name>  Model provider (ollama|openai|lmstudio|groq|together)

EXAMPLES
  super claude                    # New Claude session
  super claude --model opus       # Explicit model
  super claude --resume           # Resume with picker
  super gemini --title "fix auth" # Named session
  super claude --provider ollama --model glm-5:cloud  # Ollama provider
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

// Build CLI-specific default args (e.g. yolo mode)
function cliDefaultArgs(cli) {
  const args = [];
  if (config.yoloMode()) {
    const yoloFlag = {
      claude: '--dangerously-skip-permissions',
      gemini: '--yolo',
      codex:  '--full-auto',
    }[cli];
    if (yoloFlag) args.push(yoloFlag);
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
    case 'configure': case 'setup': await cmdConfigure(rest); break;
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
    case 'claude': case 'gemini': case 'codex': cmdLaunch(cmd, rest); break;
    default: die(`Unknown command: ${cmd}. Run: super help`);
  }
}

main().catch(e => { console.error(e.message); process.exit(1); });
