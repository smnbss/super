// lib/catalog.mjs — Skills, plugins, MCPs install/uninstall
// Replaces catalog.sh — native JSON manipulation, no embedded Python

import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, lstatSync, cpSync, readdirSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import { findRoot, findConfig, catalogSystem, catalogClis, catalogSkills, catalogPlugins, catalogMcps, mcpItem, loadDotEnv } from './config.mjs';
import * as ui from './ui.mjs';

// ─── CLI detection ──────────────────────────────────────────────────────────

export function isInstalled(cli) {
  try { execSync(`command -v ${cli}`, { stdio: 'ignore' }); return true; } catch { return false; }
}

export function installedClis() {
  return ['claude', 'gemini', 'codex', 'kimi'].filter(isInstalled);
}

// ─── System prerequisites ──────────────────────────────────────────────────
// Each entry has: check (shell command, 0=satisfied), install (shell command)

function checkSatisfied(checkCmd) {
  if (!checkCmd) return false;
  try { execSync(checkCmd, { stdio: 'ignore' }); return true; } catch { return false; }
}

export function installSystem() {
  for (const dep of catalogSystem()) {
    if (!dep.enabled) continue;
    if (dep.check && checkSatisfied(dep.check)) {
      ui.muted(`  ${dep.name} — satisfied`);
      continue;
    }
    if (!dep.install) {
      ui.warn(`  ${dep.name} — no install command defined`);
      continue;
    }
    ui.info(`  Installing ${dep.name}...`);
    try {
      execSync(dep.install, { stdio: 'inherit', shell: true });
      ui.success(`  ${dep.name} installed`);
    } catch {
      ui.warn(`  ${dep.name} failed — run manually: ${dep.install}`);
    }
  }
}

// ─── CLI install ───────────────────────────────────────────────────────────

export function installClis() {
  for (const cli of catalogClis()) {
    if (!cli.enabled) continue;
    // Use check field if provided, otherwise fall back to command -v
    const satisfied = cli.check ? checkSatisfied(cli.check) : isInstalled(cli.name);
    if (satisfied) {
      ui.muted(`  ${cli.name} already installed`);
      continue;
    }
    if (!cli.install) {
      ui.warn(`  ${cli.name} — no install command defined`);
      continue;
    }
    ui.info(`  Installing ${cli.name}...`);
    try {
      execSync(cli.install, { stdio: 'inherit', shell: true });
      ui.success(`  ${cli.name} installed`);
    } catch {
      ui.warn(`  ${cli.name} failed — run manually: ${cli.install}`);
    }
  }
}

// ─── Skill install ──────────────────────────────────────────────────────────

function cloneSkillSource(name, source, dest) {
  if (existsSync(dest)) { ui.muted(`    ${name} already installed`); return true; }

  const parts = source.split('/');
  const [owner, repo] = parts;
  const subpath = parts.slice(2).join('/');

  try {
    if (!subpath) {
      execSync(`git clone --depth 1 "https://github.com/${owner}/${repo}.git" "${dest}"`, { stdio: 'ignore' });
    } else {
      const tmp = execSync('mktemp -d', { encoding: 'utf8' }).trim();
      execSync(`git clone --depth 1 "https://github.com/${owner}/${repo}.git" "${tmp}"`, { stdio: 'ignore' });
      const srcPath = join(tmp, subpath);
      if (!existsSync(srcPath)) {
        ui.warn(`    Path ${subpath} not found in ${owner}/${repo}`);
        rmSync(tmp, { recursive: true, force: true });
        return false;
      }
      execSync(`mv "${srcPath}" "${dest}"`);
      rmSync(tmp, { recursive: true, force: true });
    }

    // Run setup if present
    const setup = join(dest, 'setup');
    const setupSh = join(dest, 'setup.sh');
    if (existsSync(setup)) { try { execSync('./setup', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }
    else if (existsSync(setupSh)) { try { execSync('bash setup.sh', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }

    return true;
  } catch {
    ui.warn(`    Failed to clone ${name}`);
    return false;
  }
}

function skillDir(cli) {
  const root = findRoot();
  switch (cli) {
    case 'claude': return join(root, '.agents', 'skills');
    case 'gemini': return join(process.env.HOME, '.gemini', 'skills');
    case 'codex':  return join(process.env.HOME, '.codex', 'skills');
    case 'kimi':   return join(process.env.HOME, '.kimi', 'skills');
  }
}

function installSkillForCli(name, source, cli) {
  const dir = skillDir(cli);
  mkdirSync(dir, { recursive: true });
  const dest = join(dir, name);
  ui.info(`  [${cli}]`);
  if (cloneSkillSource(name, source, dest)) {
    ui.success(`    ${name} installed`);
  }
}

export function installSkill(name, source, selectedClis) {
  const clis = selectedClis || installedClis();
  for (const cli of clis) {
    installSkillForCli(name, source, cli);
  }
}

// ─── Plugin install ─────────────────────────────────────────────────────────

function installPluginForCli(name, source, cli) {
  if (cli === 'claude') {
    if (!isInstalled('claude')) { ui.warn(`  [claude] claude command not found`); return; }
    // Check if already installed
    const registry = join(process.env.HOME, '.claude', 'plugins', 'installed_plugins.json');
    if (existsSync(registry)) {
      try {
        const data = JSON.parse(readFileSync(registry, 'utf8'));
        const found = Object.keys(data.plugins || {}).some(k => k.includes(name) || k.includes(source));
        if (found) { ui.muted(`  [claude] ${name} already installed`); return; }
      } catch { /* */ }
    }
    ui.info(`  [claude] Installing via: claude plugins install ${source}`);
    try {
      execSync(`claude plugins install "${source}"`, { stdio: 'ignore' });
      ui.success(`  [claude] ${name} installed`);
    } catch {
      ui.warn(`  [claude] Failed — run manually: claude plugins install ${source}`);
    }
  } else {
    ui.muted(`  [${cli}] No plugin system — ${name} listed as reference only`);
  }
}

export function installPlugin(name, source, selectedClis) {
  const clis = selectedClis || installedClis();
  for (const cli of clis) {
    installPluginForCli(name, source, cli);
  }
}

// ─── Env reference resolution ───────────────────────────────────────────────
// Replaces $env:VAR_NAME patterns with values from .env.local / process.env.
// Returns { resolved, missing } where missing is a list of unresolved var names.

function resolveEnvRefs(obj, envMap) {
  const missing = [];

  function resolve(val) {
    if (typeof val === 'string') {
      return val.replace(/\$env:([A-Za-z_][A-Za-z0-9_]*)/g, (match, key) => {
        const resolved = envMap[key] ?? process.env[key];
        if (resolved === undefined) { missing.push(key); return ''; }
        return resolved;
      });
    }
    if (Array.isArray(val)) return val.map(resolve);
    if (val && typeof val === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(val)) out[k] = resolve(v);
      return out;
    }
    return val;
  }

  return { resolved: resolve(obj), missing };
}

// ─── Claude ~/.claude.json cleanup ─────────────────────────────────────────
// `claude mcp add` writes to ~/.claude.json (user-level + project-level).
// super writes to .claude/settings.local.json instead. Stale entries in
// ~/.claude.json shadow settings.local.json, so we clean them on install.

function cleanClaudeJsonMcps() {
  const globalConfig = join(process.env.HOME, '.claude.json');
  if (!existsSync(globalConfig)) return;

  let data;
  try { data = JSON.parse(readFileSync(globalConfig, 'utf8')); } catch { return; }
  let changed = false;

  // Clean user-level mcpServers
  if (data.mcpServers && Object.keys(data.mcpServers).length) {
    ui.muted(`  Cleaning stale user-level MCPs from ~/.claude.json: ${Object.keys(data.mcpServers).join(', ')}`);
    data.mcpServers = {};
    changed = true;
  }

  // Clean project-level mcpServers for current project
  const root = findRoot();
  const proj = data.projects?.[root];
  if (proj?.mcpServers && Object.keys(proj.mcpServers).length) {
    ui.muted(`  Cleaning stale project-level MCPs from ~/.claude.json: ${Object.keys(proj.mcpServers).join(', ')}`);
    proj.mcpServers = {};
    changed = true;
  }

  if (changed) {
    writeFileSync(globalConfig, JSON.stringify(data, null, 2) + '\n');
  }
}

// ─── MCP install ────────────────────────────────────────────────────────────

function mcpSettingsPath(cli) {
  const root = findRoot();
  switch (cli) {
    case 'claude': return join(root, '.claude', 'settings.local.json');
    case 'gemini': return join(root, '.gemini', 'settings.json');
    case 'codex':  return join(root, '.codex', 'config.json');
    case 'kimi':   return join(root, '.kimi', 'mcp.json');
  }
}

function readJsonFile(path, fallback) {
  if (!existsSync(path)) return fallback;
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return fallback; }
}

function writeJsonFile(path, data) {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
}

function buildMcpEntry(item, cli) {
  const isHttp = item.type === 'http' || item.url;

  switch (cli) {
    case 'claude':
    case 'gemini': {
      const entry = {};
      if (isHttp) {
        entry.url = item.url;
        if (item.headers && typeof item.headers === 'object') entry.headers = item.headers;
      } else {
        entry.command = item.command || '';
        if (item.args) entry.args = item.args;
      }
      if (item.env && typeof item.env === 'object') entry.env = item.env;
      return entry;
    }
    case 'codex': {
      const entry = {};
      if (isHttp) {
        entry.type = 'http';
        entry.url = item.url;
        if (item.headers && typeof item.headers === 'object') entry.headers = item.headers;
        if (item.auth) entry.auth = typeof item.auth === 'object' ? item.auth : { type: item.auth };
      } else {
        entry.type = 'stdio';
        entry.command = item.command || '';
        if (item.args) entry.args = item.args;
      }
      if (item.env && typeof item.env === 'object') entry.env = item.env;
      return entry;
    }
    case 'kimi': {
      const entry = {};
      if (isHttp) {
        entry.url = item.url;
        entry.transport = 'http';
        if (item.headers && typeof item.headers === 'object') entry.headers = item.headers;
        if (item.auth) entry.auth = item.auth;
      } else {
        entry.command = item.command || '';
        if (item.args) entry.args = item.args;
      }
      if (item.env && typeof item.env === 'object') entry.env = item.env;
      return entry;
    }
  }
}

function installMcpForCli(name, cli, envMap) {
  const item = mcpItem(name);
  if (!item) return;

  // Resolve $env:VAR references in the MCP definition
  const { resolved: resolvedItem, missing } = resolveEnvRefs(item, envMap || {});
  if (missing.length) {
    ui.warn(`  [${cli}] ${name}: missing env vars: ${missing.join(', ')} (check .env.local)`);
  }

  const settingsPath = mcpSettingsPath(cli);
  const fallback = cli === 'kimi' ? { mcpServers: {} } : {};
  const data = readJsonFile(settingsPath, fallback);

  if (cli === 'codex') {
    // Array format — update existing or add new
    const servers = data.mcpServers = data.mcpServers || [];
    const idx = servers.findIndex(s => s.name === name);
    const entry = buildMcpEntry(resolvedItem, cli);
    entry.name = name;
    if (idx >= 0) { servers[idx] = entry; }
    else { servers.push(entry); }
  } else {
    // Dict format (claude, gemini, kimi) — always overwrite to pick up env changes
    const servers = data.mcpServers = data.mcpServers || {};
    servers[name] = buildMcpEntry(resolvedItem, cli);
  }

  writeJsonFile(settingsPath, data);
  ui.success(`  [${cli}] ${name} configured`);
}

export function installMcp(name, envMap, selectedClis) {
  if (!envMap) envMap = loadDotEnv();
  const clis = selectedClis || installedClis();
  for (const cli of clis) {
    installMcpForCli(name, cli, envMap);
  }
}

// ─── Project bootstrap ─────────────────────────────────────────────────────

function bootstrapProject() {
  const root = findRoot();

  // Git init
  const gitDir = join(root, '.git');
  if (!existsSync(gitDir)) {
    ui.info('  Initializing git repo...');
    try { execSync('git init', { cwd: root, stdio: 'ignore' }); ui.success('  git initialized'); } catch { /* */ }
  }

  // .gitignore entries
  const gitignore = join(root, '.gitignore');
  const entries = ['.env.local', '.venv'];
  for (const entry of entries) {
    let content = '';
    if (existsSync(gitignore)) content = readFileSync(gitignore, 'utf8');
    if (!content.split('\n').includes(entry)) {
      writeFileSync(gitignore, content + (content.endsWith('\n') || !content ? '' : '\n') + entry + '\n');
    }
  }

  // .env.local from .env.example (non-interactive — just copy defaults)
  const envLocal = join(root, '.env.local');
  const envExample = join(root, '.env.example');
  if (!existsSync(envLocal) && existsSync(envExample)) {
    ui.info('  Creating .env.local from .env.example...');
    const content = readFileSync(envExample, 'utf8');
    writeFileSync(envLocal, content);
    ui.success('  .env.local created — edit it to add your secrets');
  }

  // Validate required keys
  if (existsSync(envLocal)) {
    const content = readFileSync(envLocal, 'utf8');
    const required = ['CLICKUP_TOKEN', 'LINEAR_TOKEN'];
    const missing = required.filter(key => {
      const match = content.match(new RegExp(`^${key}=(.*)$`, 'm'));
      return !match || !match[1].trim();
    });
    if (missing.length) {
      ui.warn(`  Missing values in .env.local: ${missing.join(', ')}`);
    }
  }
}

// ─── Batch install ──────────────────────────────────────────────────────────

export function installEnabled(selectedClis) {
  const cfg = findConfig();
  if (!cfg) return;

  ui.brand('Bootstrapping project...');
  ui.spacer();
  bootstrapProject();

  ui.spacer();
  ui.brand('Installing system prerequisites...');
  ui.spacer();
  installSystem();

  ui.spacer();
  ui.brand('Installing enabled CLIs...');
  ui.spacer();
  installClis();

  ui.spacer();
  ui.brand('Installing enabled skills...');
  ui.spacer();
  for (const skill of catalogSkills()) {
    if (!skill.enabled) continue;
    installSkill(skill.name, skill.source, selectedClis);
  }

  ui.spacer();
  ui.brand('Installing enabled plugins...');
  ui.spacer();
  for (const plugin of catalogPlugins()) {
    if (!plugin.enabled) continue;
    installPlugin(plugin.name, plugin.source, selectedClis);
  }

  ui.spacer();
  ui.brand('Configuring enabled MCPs...');
  cleanClaudeJsonMcps();
  const envMap = loadDotEnv();
  const envKeys = Object.keys(envMap);
  if (envKeys.length) {
    ui.muted(`  Loaded ${envKeys.length} vars from .env.local`);
  }
  ui.spacer();
  for (const mcp of catalogMcps()) {
    if (!mcp.enabled) continue;
    installMcp(mcp.name, envMap, selectedClis);
  }
}

// ─── Uninstall ──────────────────────────────────────────────────────────────

export function uninstallSkill(name) {
  let removed = 0;
  for (const cli of ['claude', 'gemini', 'codex', 'kimi']) {
    const dest = join(skillDir(cli), name);
    if (existsSync(dest) || (lstatSync(dest, { throwIfNoEntry: false })?.isSymbolicLink())) {
      rmSync(dest, { recursive: true, force: true });
      ui.success(`  [${cli}] ${name} uninstalled`);
      removed++;
    }
  }
  if (!removed) ui.muted(`  ${name} not found`);
}

export function uninstallMcp(name) {
  let removed = 0;
  for (const cli of ['claude', 'gemini', 'codex', 'kimi']) {
    const path = mcpSettingsPath(cli);
    if (!existsSync(path)) continue;
    const data = readJsonFile(path, {});

    if (cli === 'codex') {
      const servers = data.mcpServers || [];
      const filtered = servers.filter(s => s.name !== name);
      if (filtered.length < servers.length) {
        data.mcpServers = filtered;
        writeJsonFile(path, data);
        ui.success(`  [${cli}] ${name} removed`);
        removed++;
      }
    } else {
      if (data.mcpServers?.[name]) {
        delete data.mcpServers[name];
        writeJsonFile(path, data);
        ui.success(`  [${cli}] ${name} removed`);
        removed++;
      }
    }
  }
  if (!removed) ui.muted(`  ${name} not configured`);
}
