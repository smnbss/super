// lib/catalog.mjs — Skills, plugins, MCPs install/uninstall
// Replaces catalog.sh — native JSON manipulation, no embedded Python

import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, lstatSync, cpSync, readdirSync, symlinkSync, unlinkSync, readlinkSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import { findRoot, findConfig, catalogSystem, catalogClis, catalogSkills, catalogPlugins, catalogCommands, catalogMcps, mcpItem, loadDotEnv } from './config.mjs';
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
  const deps = catalogSystem().filter(d => d.enabled);
  if (!deps.length) { ui.muted('  No system prerequisites configured'); return; }
  for (let i = 0; i < deps.length; i++) {
    const dep = deps[i];
    ui.step('System', i + 1, deps.length, dep.name);
    if (dep.check && checkSatisfied(dep.check)) {
      ui.muted(`  ${dep.name} — already satisfied`);
      continue;
    }
    if (!dep.install) {
      ui.warn(`  ${dep.name} — no install command defined`);
      continue;
    }
    ui.info(`  Installing ${dep.name}...`);
    const start = Date.now();
    try {
      execSync(dep.install, { stdio: 'inherit', shell: true });
      ui.success(`  ${dep.name} installed (${ui.elapsed(start)})`);
    } catch {
      ui.warn(`  ${dep.name} failed — run manually: ${dep.install}`);
    }
  }
}

// ─── CLI install ───────────────────────────────────────────────────────────

export function installClis() {
  const clis = catalogClis().filter(c => c.enabled);
  if (!clis.length) { ui.muted('  No CLIs configured'); return; }
  for (let i = 0; i < clis.length; i++) {
    const cli = clis[i];
    ui.step('CLI', i + 1, clis.length, cli.name);
    // Use check field if provided, otherwise fall back to command -v
    const satisfied = cli.check ? checkSatisfied(cli.check) : isInstalled(cli.name);
    if (satisfied) {
      ui.muted(`  ${cli.name} — already installed`);
      continue;
    }
    if (!cli.install) {
      ui.warn(`  ${cli.name} — no install command defined`);
      continue;
    }
    ui.info(`  Installing ${cli.name}...`);
    const start = Date.now();
    try {
      execSync(cli.install, { stdio: 'inherit', shell: true });
      ui.success(`  ${cli.name} installed (${ui.elapsed(start)})`);
    } catch {
      ui.warn(`  ${cli.name} failed — run manually: ${cli.install}`);
    }
  }
}

// ─── Skill install ──────────────────────────────────────────────────────────

function cloneSkillSource(name, source, dest) {
  // If already installed: update via git pull (full repos) or delete + re-clone (subpath extracts)
  if (existsSync(dest)) {
    if (existsSync(join(dest, '.git'))) {
      try {
        ui.muted(`    ${name}: pulling latest...`);
        const start = Date.now();
        execSync('git checkout -- . && git pull', { cwd: dest, stdio: 'ignore' });
        ui.muted(`    ${name} updated (${ui.elapsed(start)})`);
        return true;
      } catch {
        ui.muted(`    ${name}: pull failed, re-cloning...`);
        rmSync(dest, { recursive: true, force: true });
      }
    } else {
      // Subpath extract (no .git) — remove and re-clone to get latest
      ui.muted(`    ${name}: refreshing subpath extract...`);
      rmSync(dest, { recursive: true, force: true });
    }
  }

  const parts = source.split('/');
  const [owner, repo] = parts;
  const subpath = parts.slice(2).join('/');

  // Prefer gh repo clone for private repos, fall back to git clone
  const hasGh = isInstalled('gh');

  try {
    const start = Date.now();
    ui.muted(`    ${name}: cloning ${owner}/${repo}${subpath ? '/' + subpath : ''}...`);
    if (!subpath) {
      if (hasGh) {
        execSync(`gh repo clone "${owner}/${repo}" "${dest}" -- --depth 1`, { stdio: 'ignore' });
      } else {
        execSync(`git clone --depth 1 "https://github.com/${owner}/${repo}.git" "${dest}"`, { stdio: 'ignore' });
      }
    } else {
      const tmp = execSync('mktemp -d', { encoding: 'utf8' }).trim();
      if (hasGh) {
        execSync(`gh repo clone "${owner}/${repo}" "${tmp}" -- --depth 1`, { stdio: 'ignore' });
      } else {
        execSync(`git clone --depth 1 "https://github.com/${owner}/${repo}.git" "${tmp}"`, { stdio: 'ignore' });
      }
      const srcPath = join(tmp, subpath);
      if (!existsSync(srcPath)) {
        ui.warn(`    Path ${subpath} not found in ${owner}/${repo}`);
        rmSync(tmp, { recursive: true, force: true });
        return false;
      }
      execSync(`mv "${srcPath}" "${dest}"`);
      rmSync(tmp, { recursive: true, force: true });
    }
    ui.muted(`    ${name}: cloned (${ui.elapsed(start)})`);

    // Run setup if present
    const setup = join(dest, 'setup');
    const setupSh = join(dest, 'setup.sh');
    if (existsSync(setup)) {
      ui.muted(`    ${name}: running setup...`);
      try { execSync('./setup', { cwd: dest, stdio: 'ignore' }); } catch { /* */ }
    }
    else if (existsSync(setupSh)) {
      ui.muted(`    ${name}: running setup.sh...`);
      try { execSync('bash setup.sh', { cwd: dest, stdio: 'ignore' }); } catch { /* */ }
    }

    return true;
  } catch {
    ui.warn(`    Failed to clone ${name} from ${source}`);
    return false;
  }
}

function skillDir(cli) {
  const root = findRoot();
  // All CLIs read project-local skills via symlinks; install to the canonical source.
  return join(root, '.agents', 'skills');
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

// ─── Harvest tracking ───────────────────────────────────────────────────────
const _harvestedSkills = new Set();
const _harvestedCommands = new Set();

// ─── Built-in skill install ────────────────────────────────────────────────
// Copies skills shipped inside $SUPER_HOME/skills/ to each CLI's skill dir.

export function installBuiltinSkills(selectedClis) {
  const superHome = process.env.SUPER_HOME;
  if (!superHome) return;
  const builtinDir = join(superHome, 'skills');
  if (!existsSync(builtinDir)) return;

  const clis = selectedClis || installedClis();
  for (const name of readdirSync(builtinDir)) {
    const src = join(builtinDir, name);
    if (!lstatSync(src).isDirectory()) continue;
    for (const cli of clis) {
      const dir = skillDir(cli);
      mkdirSync(dir, { recursive: true });
      const dest = join(dir, name);
      if (existsSync(dest)) { rmSync(dest, { recursive: true, force: true }); }
      try {
        cpSync(src, dest, { recursive: true });
        ui.success(`  [${cli}] ${name} installed`);
      } catch {
        ui.warn(`  [${cli}] ${name} failed to copy`);
      }
    }
  }
}

function ensureCliSkillsSymlink(cli) {
  const root = findRoot();
  const agentsSkills = join(root, '.agents', 'skills');
  const cliSkills = join(root, `.${cli}`, 'skills');

  if (!existsSync(agentsSkills)) return;

  // Gemini natively reads .agents/skills as its project agent skills directory,
  // so a .gemini/skills symlink to .agents/skills causes every skill to appear
  // twice (skill conflicts). For Gemini we migrate any real directory contents
  // and then leave the path absent so it uses .agents/skills directly.
  if (cli === 'gemini') {
    if (existsSync(cliSkills)) {
      const stat = lstatSync(cliSkills, { throwIfNoEntry: false });
      if (stat && stat.isDirectory() && !stat.isSymbolicLink()) {
        let migrated = 0;
        for (const item of readdirSync(cliSkills)) {
          const src = join(cliSkills, item);
          const dest = join(agentsSkills, item);
          if (existsSync(dest)) continue;
          if (!lstatSync(src).isDirectory()) continue;
          cpSync(src, dest, { recursive: true });
          migrated++;
        }
        if (migrated) ui.success(`  Migrated ${migrated} skills from .gemini/skills → .agents/skills`);
      }
      rmSync(cliSkills, { recursive: true, force: true });
      ui.success(`  Removed .gemini/skills (Gemini reads .agents/skills directly)`);
    }
    return;
  }

  // If the CLI skills path exists as a real directory, migrate its contents
  // into the shared .agents/skills pool before replacing it with a symlink.
  if (existsSync(cliSkills)) {
    const stat = lstatSync(cliSkills, { throwIfNoEntry: false });
    if (stat && stat.isDirectory() && !stat.isSymbolicLink()) {
      let migrated = 0;
      for (const item of readdirSync(cliSkills)) {
        const src = join(cliSkills, item);
        const dest = join(agentsSkills, item);
        if (existsSync(dest)) continue;
        if (!lstatSync(src).isDirectory()) continue;
        cpSync(src, dest, { recursive: true });
        migrated++;
      }
      if (migrated) ui.success(`  Migrated ${migrated} skills from ~/${cli}/skills → .agents/skills`);
      rmSync(cliSkills, { recursive: true, force: true });
    } else if (stat && stat.isSymbolicLink()) {
      unlinkSync(cliSkills);
    }
  } else {
    mkdirSync(join(root, `.${cli}`), { recursive: true });
  }

  try {
    symlinkSync('../.agents/skills', cliSkills);
    ui.success(`  .${cli}/skills → .agents/skills`);
  } catch (err) {
    ui.warn(`  Failed to create .${cli}/skills symlink: ${err.message}`);
  }
}

function ensureClaudeSkillsDirectory() {
  const root = findRoot();
  const agentsSkills = join(root, '.agents', 'skills');
  const claudeSkills = join(root, '.claude', 'skills');

  if (!existsSync(agentsSkills)) return;

  // Remove the old global symlink if present so we can manage per-skill symlinks
  if (existsSync(claudeSkills)) {
    const stat = lstatSync(claudeSkills, { throwIfNoEntry: false });
    if (stat && stat.isSymbolicLink()) {
      unlinkSync(claudeSkills);
    } else if (stat && stat.isDirectory()) {
      // Clean up stale symlinks and harvested skills from a previous run
      for (const item of readdirSync(claudeSkills)) {
        const itemPath = join(claudeSkills, item);
        const stat2 = lstatSync(itemPath, { throwIfNoEntry: false });
        if (!stat2 || !stat2.isSymbolicLink()) continue;
        if (_harvestedSkills.has(item) || !existsSync(join(agentsSkills, item))) {
          unlinkSync(itemPath);
        }
      }
    }
  }

  mkdirSync(claudeSkills, { recursive: true });

  let linked = 0, existing = 0;
  for (const skillName of readdirSync(agentsSkills)) {
    if (_harvestedSkills.has(skillName)) continue;
    const src = join(agentsSkills, skillName);
    const dest = join(claudeSkills, skillName);
    if (!lstatSync(src).isDirectory()) continue;
    if (existsSync(dest)) { existing++; continue; }
    try {
      symlinkSync(join('..', '..', '.agents', 'skills', skillName), dest);
      linked++;
    } catch (err) {
      ui.warn(`  Failed to symlink ${skillName} to .claude/skills: ${err.message}`);
    }
  }
  const total = linked + existing;
  ui.success(`  .claude/skills: ${total} project skills${linked ? ` (${linked} new)` : ''}, ${_harvestedSkills.size} harvested hidden`);
}

function ensureClaudeCommandsDirectory() {
  const root = findRoot();
  const agentsCommands = join(root, '.agents', 'commands');
  const claudeCommands = join(root, '.claude', 'commands');

  if (!existsSync(agentsCommands)) return;

  if (existsSync(claudeCommands)) {
    const stat = lstatSync(claudeCommands, { throwIfNoEntry: false });
    if (stat && stat.isSymbolicLink()) {
      unlinkSync(claudeCommands);
    } else if (stat && stat.isDirectory()) {
      for (const file of readdirSync(claudeCommands)) {
        const itemPath = join(claudeCommands, file);
        const stat2 = lstatSync(itemPath, { throwIfNoEntry: false });
        if (!stat2 || !stat2.isSymbolicLink()) continue;
        const cmdName = file.replace(/\.md$/, '');
        if (_harvestedCommands.has(cmdName) || !existsSync(join(agentsCommands, file))) {
          unlinkSync(itemPath);
        }
      }
    }
  }

  mkdirSync(claudeCommands, { recursive: true });

  let linked = 0, existing = 0;
  for (const file of readdirSync(agentsCommands)) {
    if (!file.endsWith('.md')) continue;
    const cmdName = file.replace(/\.md$/, '');
    if (_harvestedCommands.has(cmdName)) continue;
    const dest = join(claudeCommands, file);
    if (existsSync(dest)) { existing++; continue; }
    try {
      symlinkSync(join('..', '..', '.agents', 'commands', file), dest);
      linked++;
    } catch (err) {
      ui.warn(`  Failed to symlink ${file} to .claude/commands: ${err.message}`);
    }
  }
  const totalCmds = linked + existing;
  ui.success(`  .claude/commands: ${totalCmds} project commands${linked ? ` (${linked} new)` : ''}`);
}

function ensureCliHomeSymlink(cli) {
  const root = findRoot();
  const cliDir = join(root, `.${cli}`);
  const linkPath = join(cliDir, `.${cli}`);
  const targetPath = join(process.env.HOME, `.${cli}`);

  if (!existsSync(cliDir)) {
    mkdirSync(cliDir, { recursive: true });
  }

  if (existsSync(linkPath)) {
    const stat = lstatSync(linkPath, { throwIfNoEntry: false });
    if (stat && !stat.isSymbolicLink()) {
      ui.muted(`  .${cli}/.${cli} exists as a real file/directory — leaving it alone`);
      return;
    }
    unlinkSync(linkPath);
  }

  try {
    symlinkSync(targetPath, linkPath);
    ui.success(`  .${cli}/.${cli} → ~/.${cli}`);
  } catch (err) {
    ui.warn(`  Failed to create .${cli}/.${cli} symlink: ${err.message}`);
  }
}

// ─── Claude plugin cache harvester ───────────────────────────────────────────
// For plugins that can't be cloned directly, we ask Claude to install them,
// then harvest skills, commands, and portable MCPs from its cache for other CLIs.

let _marketplacesUpdated = false;

function ensureClaudeMarketplacesUpdated() {
  if (_marketplacesUpdated) return;
  if (!isInstalled('claude')) return;
  try {
    ui.info('  Updating Claude marketplaces...');
    const start = Date.now();
    execSync('claude plugins marketplace update', { stdio: 'ignore' });
    _marketplacesUpdated = true;
    ui.success(`  Claude marketplaces updated (${ui.elapsed(start)})`);
  } catch (err) {
    ui.warn(`  Failed to update Claude marketplaces: ${err.message}`);
  }
}

function readClaudeKnownMarketplaces() {
  const path = join(process.env.HOME, '.claude', 'plugins', 'known_marketplaces.json');
  return readJsonFile(path, {});
}

function resolveClaudeMarketplaceName(source) {
  const marketplaces = readClaudeKnownMarketplaces();
  for (const [name, info] of Object.entries(marketplaces)) {
    if (info.source?.repo === source) return name;
    if (info.source?.repo?.endsWith('/' + source)) return name;
  }
  return source.split('/')[0];
}

function installClaudePlugin(pluginName, marketplaceName) {
  if (!isInstalled('claude')) return false;
  try {
    ui.info(`  Installing ${pluginName}@${marketplaceName} via Claude CLI...`);
    const start = Date.now();
    execSync(`claude plugins install "${pluginName}@${marketplaceName}"`, { stdio: 'ignore' });
    ui.success(`  Installed ${pluginName}@${marketplaceName} (${ui.elapsed(start)})`);
    return true;
  } catch (err) {
    ui.warn(`  Failed to install ${pluginName}@${marketplaceName}: ${err.message}`);
    return false;
  }
}

function readClaudeInstalledPlugins() {
  const path = join(process.env.HOME, '.claude', 'plugins', 'installed_plugins.json');
  return readJsonFile(path, { version: 2, plugins: {} });
}

function getClaudePluginInstallPath(pluginName, marketplaceName) {
  const installed = readClaudeInstalledPlugins();
  const key = `${pluginName}@${marketplaceName}`;
  const entries = installed.plugins?.[key];
  if (!entries || !entries.length) return null;
  const root = findRoot();
  const projectEntry = entries.find(e => e.projectPath === root);
  return projectEntry?.installPath || entries[0]?.installPath;
}

function installHarvestedSkill(skillPath, skillName, root) {
  _harvestedSkills.add(skillName);
  const destDir = join(root, '.agents', 'skills');
  mkdirSync(destDir, { recursive: true });
  const dest = join(destDir, skillName);
  const existed = existsSync(dest);
  if (existed) rmSync(dest, { recursive: true, force: true });
  cpSync(skillPath, dest, { recursive: true });
  const setup = join(dest, 'setup');
  const setupSh = join(dest, 'setup.sh');
  if (existsSync(setup)) { try { execSync('./setup', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }
  else if (existsSync(setupSh)) { try { execSync('bash setup.sh', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }
  ui.success(`  ${skillName} ${existed ? 'updated' : 'installed'} (from Claude cache)`);
}

function harvestClaudePluginSkills(installPath, root) {
  const skillsDir = join(installPath, 'skills');
  if (!existsSync(skillsDir) || !lstatSync(skillsDir).isDirectory()) return 0;
  let count = 0;
  for (const skillName of readdirSync(skillsDir)) {
    const skillPath = join(skillsDir, skillName);
    if (!existsSync(join(skillPath, 'SKILL.md'))) continue;
    installHarvestedSkill(skillPath, skillName, root);
    count++;
  }
  return count;
}

function harvestClaudePluginCommands(installPath, root) {
  const commandsDir = join(installPath, 'commands');
  if (!existsSync(commandsDir) || !lstatSync(commandsDir).isDirectory()) return 0;
  const destDir = join(root, '.agents', 'commands');
  mkdirSync(destDir, { recursive: true });
  let count = 0;
  for (const file of readdirSync(commandsDir)) {
    if (!file.endsWith('.md')) continue;
    const cmdName = file.replace(/\.md$/, '');
    _harvestedCommands.add(cmdName);
    const src = join(commandsDir, file);
    const dest = join(destDir, file);
    const existed = existsSync(dest);
    cpSync(src, dest);
    ui.success(`  ${cmdName} command ${existed ? 'updated' : 'installed'} (from Claude cache)`);
    count++;
  }
  return count;
}

function rewriteClaudeMcpJson(mcpData, installPath) {
  const jsonStr = JSON.stringify(mcpData);
  const rewritten = jsonStr.replace(/\$\{CLAUDE_PLUGIN_ROOT\}/g, installPath);
  return JSON.parse(rewritten);
}

function harvestClaudePluginMcps(installPath, selectedClis) {
  const mcpPath = join(installPath, '.mcp.json');
  if (!existsSync(mcpPath)) return 0;
  let mcpData;
  try {
    mcpData = JSON.parse(readFileSync(mcpPath, 'utf8'));
  } catch {
    return 0;
  }
  mcpData = rewriteClaudeMcpJson(mcpData, installPath);
  let servers = mcpData.mcpServers || mcpData;
  if (!servers || typeof servers !== 'object') return 0;

  const clis = (selectedClis || installedClis()).filter(c => c !== 'claude');
  let count = 0;
  for (const [name, def] of Object.entries(servers)) {
    if (!def || typeof def !== 'object') continue;
    const item = { ...def };
    for (const cli of clis) {
      installMcpEntryForCli(name, cli, item);
    }
    count++;
  }
  return count;
}

// ─── Plugin install ─────────────────────────────────────────────────────────
// Plugins are Claude marketplace repos that bundle skills + commands.
// Installing a plugin:
//   1. Clones the repo, discovers plugins/*/skills/ and plugins/*/commands/
//   2. Installs discovered skills to .agents/skills/ (all CLIs)
//   3. Installs discovered commands to .agents/commands/ (Claude only)
//   4. Writes extraKnownMarketplaces + enabledPlugins to .claude/settings.json

function clonePluginRepo(source) {
  const [owner, repo] = source.split('/');
  const hasGh = isInstalled('gh');
  const tmp = execSync('mktemp -d', { encoding: 'utf8' }).trim();
  try {
    ui.muted(`  Cloning ${owner}/${repo}...`);
    const start = Date.now();
    if (hasGh) {
      execSync(`gh repo clone "${owner}/${repo}" "${tmp}" -- --depth 1`, { stdio: 'ignore' });
    } else {
      execSync(`git clone --depth 1 "https://github.com/${owner}/${repo}.git" "${tmp}"`, { stdio: 'ignore' });
    }
    ui.muted(`  Cloned ${owner}/${repo} (${ui.elapsed(start)})`);
    return tmp;
  } catch {
    ui.muted(`  ${owner}/${repo} not clonable — will use Claude marketplace`);
    rmSync(tmp, { recursive: true, force: true });
    return null;
  }
}

function discoverPluginContents(repoDir) {
  const skills = [];
  const commands = [];
  const pluginsDir = join(repoDir, 'plugins');
  if (!existsSync(pluginsDir)) return { skills, commands };

  for (const domain of readdirSync(pluginsDir)) {
    const domainDir = join(pluginsDir, domain);
    if (!existsSync(domainDir) || !lstatSync(domainDir).isDirectory()) continue;

    // Discover skills: plugins/<domain>/skills/<name>/SKILL.md
    const skillsDir = join(domainDir, 'skills');
    if (existsSync(skillsDir) && lstatSync(skillsDir).isDirectory()) {
      for (const skillName of readdirSync(skillsDir)) {
        const skillPath = join(skillsDir, skillName);
        if (existsSync(join(skillPath, 'SKILL.md'))) {
          skills.push({ name: skillName, path: skillPath });
        }
      }
    }

    // Discover commands: plugins/<domain>/commands/*.md
    const commandsDir = join(domainDir, 'commands');
    if (existsSync(commandsDir) && lstatSync(commandsDir).isDirectory()) {
      for (const file of readdirSync(commandsDir)) {
        if (file.endsWith('.md')) {
          commands.push({ name: file.replace(/\.md$/, ''), path: join(commandsDir, file) });
        }
      }
    }
  }
  return { skills, commands };
}

function configureClaudeMarketplace(name, source, repoDir) {
  const root = findRoot();
  const sf = join(root, '.claude', 'settings.json');
  if (!existsSync(sf)) return;

  let settings;
  try { settings = JSON.parse(readFileSync(sf, 'utf8')); } catch { return; }

  if (!settings.extraKnownMarketplaces) settings.extraKnownMarketplaces = {};
  if (!settings.enabledPlugins) settings.enabledPlugins = {};

  const alreadyConfigured = settings.extraKnownMarketplaces[name] &&
    Object.keys(settings.enabledPlugins).some(k => k.endsWith(`@${name}`));
  if (alreadyConfigured) {
    ui.muted(`  [claude] ${name} marketplace already configured`);
    return;
  }

  settings.extraKnownMarketplaces[name] = {
    source: { source: 'github', repo: source },
    autoUpdate: true,
  };

  // Discover plugin names from marketplace.json (if repo was cloned)
  let pluginNames = [];
  const mktFile = repoDir ? join(repoDir, '.claude-plugin', 'marketplace.json') : null;
  if (mktFile && existsSync(mktFile)) {
    try {
      const mkt = JSON.parse(readFileSync(mktFile, 'utf8'));
      pluginNames = (mkt.plugins || []).map(p => p.name);
    } catch { /* */ }
  }

  if (pluginNames.length) {
    for (const pn of pluginNames) settings.enabledPlugins[`${pn}@${name}`] = true;
  } else {
    settings.enabledPlugins[`${name}@${name}`] = true;
  }

  writeFileSync(sf, JSON.stringify(settings, null, 2) + '\n');
  ui.success(`  [claude] ${name} marketplace configured`);
}

export function installPlugin(name, source, selectedClis) {
  const clis = selectedClis || installedClis();
  const root = findRoot();
  const hasClaude = isInstalled('claude');

  // Clone the plugin repo to discover skills + commands
  const repoDir = clonePluginRepo(source);
  let directSkills = 0;
  let directCommands = 0;

  if (repoDir) {
    try {
      const { skills, commands } = discoverPluginContents(repoDir);

      // Install discovered skills to .agents/skills/ (always overwrite to get latest)
      if (skills.length) {
        const destDir = join(root, '.agents', 'skills');
        mkdirSync(destDir, { recursive: true });
        for (const skill of skills) {
          const dest = join(destDir, skill.name);
          const existed = existsSync(dest);
          if (existed) rmSync(dest, { recursive: true, force: true });
          cpSync(skill.path, dest, { recursive: true });
          // Run setup if present
          const setup = join(dest, 'setup');
          const setupSh = join(dest, 'setup.sh');
          if (existsSync(setup)) { try { execSync('./setup', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }
          else if (existsSync(setupSh)) { try { execSync('bash setup.sh', { cwd: dest, stdio: 'ignore' }); } catch { /* */ } }
          ui.success(`  ${skill.name} ${existed ? 'updated' : 'installed'}`);
        }
        directSkills = skills.length;
      }

      // Install discovered commands to .agents/commands/ (always overwrite to get latest)
      if (commands.length) {
        const destDir = join(root, '.agents', 'commands');
        mkdirSync(destDir, { recursive: true });
        for (const cmd of commands) {
          const dest = join(destDir, cmd.name + '.md');
          const existed = existsSync(dest);
          cpSync(cmd.path, dest);
          ui.success(`  ${cmd.name} command ${existed ? 'updated' : 'installed'}`);
        }
        directCommands = commands.length;
      }

      // Configure Claude marketplace (with repo for marketplace.json discovery)
      if (hasClaude) {
        configureClaudeMarketplace(name, source, repoDir);
        // Mark directly-cloned skills as harvested so they're hidden from
        // .claude/skills — Claude will load them from its native plugin cache
        // instead, preventing duplication. Commands are NOT harvested because
        // Claude only reads commands from .claude/commands/, not from its
        // plugin cache.
        for (const skill of skills) {
          _harvestedSkills.add(skill.name);
        }
      }
    } finally {
      rmSync(repoDir, { recursive: true, force: true });
    }
  } else {
    // Clone failed — still configure Claude marketplace
    if (hasClaude) {
      configureClaudeMarketplace(name, source, null);
    }
  }

  // If direct clone yielded nothing, bootstrap via Claude CLI and harvest for other CLIs
  if (directSkills === 0 && directCommands === 0 && hasClaude) {
    ensureClaudeMarketplacesUpdated();
    const pluginName = source.split('/').pop();
    const marketplaceName = resolveClaudeMarketplaceName(source);
    if (marketplaceName && pluginName) {
      const ok = installClaudePlugin(pluginName, marketplaceName);
      if (ok) {
        const installPath = getClaudePluginInstallPath(pluginName, marketplaceName);
        if (installPath) {
          harvestClaudePluginSkills(installPath, root);
          harvestClaudePluginCommands(installPath, root);
          harvestClaudePluginMcps(installPath, selectedClis);
        } else {
          ui.warn(`  Claude installed ${pluginName} but install path not found in registry`);
        }
      }
    }
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

function geminiHasExtension(name) {
  const extDir = join(process.env.HOME, '.gemini', 'extensions', name);
  // Also check with common suffixes like -mcp
  const extDirMcp = join(process.env.HOME, '.gemini', 'extensions', name + '-mcp');
  return existsSync(extDir) || existsSync(extDirMcp);
}

function installMcpEntryForCli(name, cli, item) {
  // Skip if Gemini already has this as a global extension (avoids "already registered" warnings)
  if (cli === 'gemini' && geminiHasExtension(name)) {
    ui.muted(`  [${cli}] ${name} — already registered as Gemini extension, skipping`);
    return;
  }
  const settingsPath = mcpSettingsPath(cli);
  const fallback = cli === 'kimi' ? { mcpServers: {} } : {};
  const data = readJsonFile(settingsPath, fallback);

  if (cli === 'codex') {
    // Array format — update existing or add new
    const servers = data.mcpServers = data.mcpServers || [];
    const idx = servers.findIndex(s => s.name === name);
    const entry = buildMcpEntry(item, cli);
    entry.name = name;
    if (idx >= 0) { servers[idx] = entry; }
    else { servers.push(entry); }
  } else {
    // Dict format (claude, gemini, kimi) — always overwrite to pick up env changes
    const servers = data.mcpServers = data.mcpServers || {};
    servers[name] = buildMcpEntry(item, cli);
  }

  writeJsonFile(settingsPath, data);
  ui.success(`  [${cli}] ${name} configured`);
}

function installMcpForCli(name, cli, envMap) {
  const item = mcpItem(name);
  if (!item) return;

  // Resolve $env:VAR references in the MCP definition
  const { resolved: resolvedItem, missing } = resolveEnvRefs(item, envMap || {});
  if (missing.length) {
    ui.warn(`  [${cli}] ${name}: missing env vars: ${missing.join(', ')} (check .env.local)`);
  }

  installMcpEntryForCli(name, cli, resolvedItem);
}

export function installMcp(name, envMap, selectedClis) {
  if (!envMap) envMap = loadDotEnv();
  const clis = selectedClis || installedClis();
  for (const cli of clis) {
    installMcpForCli(name, cli, envMap);
  }
}

// ─── Project bootstrap ─────────────────────────────────────────────────────

function ensureGitignore() {
  const root = findRoot();
  const gitDir = join(root, '.git');
  if (!existsSync(gitDir)) return;

  const gitignore = join(root, '.gitignore');
  const entries = [
    '.env.local', '.venv',
    '.super/', '.kimi/', '.codex/', '.claude/', '.gemini/', '.agents/',
    '.super/.super', '.kimi/.kimi', '.codex/.codex', '.claude/.claude', '.gemini/.gemini'
  ];
  for (const entry of entries) {
    let content = '';
    if (existsSync(gitignore)) content = readFileSync(gitignore, 'utf8');
    if (!content.split('\n').includes(entry)) {
      writeFileSync(gitignore, content + (content.endsWith('\n') || !content ? '' : '\n') + entry + '\n');
    }
  }
}

function bootstrapProject() {
  const root = findRoot();

  // Git init
  const gitDir = join(root, '.git');
  if (!existsSync(gitDir)) {
    ui.info('  Initializing git repo...');
    try { execSync('git init', { cwd: root, stdio: 'ignore' }); ui.success('  git initialized'); } catch { /* */ }
  }

  ensureGitignore();

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

export function installEnabled(selectedClis, { skipPrereqs = false } = {}) {
  const cfg = findConfig();
  if (!cfg) return;
  const installStart = Date.now();

  // Always ensure gitignore entries are up to date
  ensureGitignore();

  // Count total phases for progress
  const phases = [];
  if (!skipPrereqs) phases.push('bootstrap', 'system', 'clis');
  phases.push('skills', 'links', 'plugins', 'skill-sync', 'mcps');
  let phaseIdx = 0;
  const phaseHeader = (label) => {
    phaseIdx++;
    ui.spacer();
    ui.brand(`[${phaseIdx}/${phases.length}] ${label}`);
    ui.spacer();
    return Date.now();
  };

  if (!skipPrereqs) {
    let ps = phaseHeader('Bootstrapping project...');
    bootstrapProject();
    ui.muted(`  Phase done (${ui.elapsed(ps)})`);

    ps = phaseHeader('Installing system prerequisites...');
    installSystem();
    ui.muted(`  Phase done (${ui.elapsed(ps)})`);

    ps = phaseHeader('Installing enabled CLIs...');
    installClis();
    ui.muted(`  Phase done (${ui.elapsed(ps)})`);
  }

  let ps = phaseHeader('Installing enabled skills...');
  const skills = catalogSkills().filter(s => s.enabled);
  for (let i = 0; i < skills.length; i++) {
    ui.step('Skill', i + 1, skills.length, skills[i].name);
    installSkill(skills[i].name, skills[i].source, selectedClis);
  }
  installBuiltinSkills(selectedClis);
  ui.muted(`  Phase done — ${skills.length} skills (${ui.elapsed(ps)})`);

  const targetClis = selectedClis || installedClis();

  ps = phaseHeader('Linking CLI home directories...');
  for (const cli of targetClis) {
    ensureCliHomeSymlink(cli);
  }
  ensureCliHomeSymlink('super');
  ui.muted(`  Phase done (${ui.elapsed(ps)})`);

  ps = phaseHeader('Installing enabled plugins...');
  const plugins = catalogPlugins().filter(p => p.enabled);
  for (let i = 0; i < plugins.length; i++) {
    ui.step('Plugin', i + 1, plugins.length, plugins[i].name);
    const pluginStart = Date.now();
    installPlugin(plugins[i].name, plugins[i].source, selectedClis);
    ui.muted(`  ${plugins[i].name} done (${ui.elapsed(pluginStart)})`);
  }
  ui.muted(`  Phase done — ${plugins.length} plugins (${ui.elapsed(ps)})`);

  ps = phaseHeader('Syncing skills to CLI directories...');
  for (const cli of targetClis) {
    if (cli === 'claude') {
      ensureClaudeSkillsDirectory();
      ensureClaudeCommandsDirectory();
    } else {
      ensureCliSkillsSymlink(cli);
    }
  }
  ui.muted(`  Phase done (${ui.elapsed(ps)})`);

  ps = phaseHeader('Configuring enabled MCPs...');
  cleanClaudeJsonMcps();
  const envMap = loadDotEnv();
  const envKeys = Object.keys(envMap);
  if (envKeys.length) {
    ui.muted(`  Loaded ${envKeys.length} vars from .env.local`);
  }
  ui.spacer();
  const mcps = catalogMcps().filter(m => m.enabled);
  for (let i = 0; i < mcps.length; i++) {
    ui.step('MCP', i + 1, mcps.length, mcps[i].name);
    installMcp(mcps[i].name, envMap, selectedClis);
  }
  ui.muted(`  Phase done — ${mcps.length} MCPs (${ui.elapsed(ps)})`);

  // Total elapsed
  ui.spacer();
  ui.success(`Install complete (${ui.elapsed(installStart)})`);
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
