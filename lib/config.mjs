// lib/config.mjs — Configuration management for super
// Replaces config.sh + yaml_parse.py with native YAML/JSON handling

import { readFileSync, writeFileSync, existsSync, mkdirSync, lstatSync, realpathSync } from 'fs';
import { join, dirname, basename } from 'path';
import yaml from 'js-yaml';

const CONFIG_FILE = 'super.config.yaml';

// ─── Debug-only symlinks (must always be ignored) ───────────────────────────
// `super install` creates <project>/.CLI/.CLI → ~/.CLI for each CLI so
// developers can cd into the global home from inside a project. These links
// are a pure developer convenience — nothing in super or its skills should
// ever treat them as project content, read from them, write through them, or
// follow them during walk-up / recursion.
export const CLI_DEBUG_SYMLINK_NAMES = ['claude', 'codex', 'gemini', 'super'];

export function isCliDebugSymlink(path) {
  const base = basename(path);
  const parent = basename(dirname(path));
  if (base !== parent) return false;
  if (!CLI_DEBUG_SYMLINK_NAMES.includes(base.replace(/^\./, ''))) return false;
  try { return lstatSync(path).isSymbolicLink(); } catch { return false; }
}

// ─── Project root discovery ──────────────────────────────────────────────────

// Walk up from `start` to find the nearest directory that contains a REAL
// `.super/` child directory. The `<project>/.super/.super` symlink (→ ~/.super)
// is a debug convenience only — never a root marker — so we require `.super`
// to be a real directory, not a symlink.
//
// Two additional guardrails prevent the global install from being mistaken
// for a project root:
//   1. We stop before reaching $HOME. By convention, `$HOME/.super` is the
//      global install — never a project marker. Without this, running
//      `super install` from any directory that is not itself under a brain
//      project walks up past $HOME and treats home as the project root,
//      dumping `AGENTS.md`, `CLAUDE.md`, `.super/sessions/` etc. into $HOME.
//   2. Even if $HOME is unset or the layout is unusual, we skip any
//      candidate `.super/` whose realpath equals the realpath of the global
//      install ($HOME/.super).
function resolveGlobalSuperRealpath() {
  const home = process.env.HOME;
  if (!home) return null;
  try { return realpathSync(join(home, '.super')); } catch { return null; }
}

function walkUpForSuper(start) {
  const home = process.env.HOME;
  const globalSuper = resolveGlobalSuperRealpath();
  let dir = start;
  while (dir && dir !== '/') {
    if (home && dir === home) break; // never treat $HOME as a project root
    const candidate = join(dir, '.super');
    try {
      const st = lstatSync(candidate);
      if (st.isDirectory()) {
        let isGlobal = false;
        if (globalSuper) {
          try { isGlobal = realpathSync(candidate) === globalSuper; } catch { /* */ }
        }
        if (!isGlobal) return dir;
      }
    } catch { /* not present */ }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export function findRoot(from) {
  if (from) return from;
  if (process.env.SUPER_PROJECT_DIR) return process.env.SUPER_PROJECT_DIR;
  return walkUpForSuper(process.cwd()) || process.cwd();
}

export function baseDir(from) { return join(findRoot(from), '.super'); }
export function sessionsDir(from) { return join(baseDir(from), 'sessions'); }
export function logFile(from) { return join(baseDir(from), 'super.log'); }

// ─── Config file discovery ──────────────────────────────────────────────────

export function findConfig(from) {
  const root = findRoot(from);

  // Priority 1: <root>/.super/super.config.yaml — but only if `.super` is a
  // real directory. If `.super` is the debug symlink to ~/.super, skip it so
  // we don't accidentally read/write through the symlink.
  const superDir = join(root, '.super');
  try {
    const st = lstatSync(superDir);
    if (st.isDirectory()) {
      const inSuper = join(superDir, CONFIG_FILE);
      if (existsSync(inSuper)) return inSuper;
    }
  } catch { /* no .super dir */ }

  // Priority 2: project root
  const inRoot = join(root, CONFIG_FILE);
  if (existsSync(inRoot)) return inRoot;

  // Priority 3: home directory
  const inHome = join(process.env.HOME, '.super', CONFIG_FILE);
  if (existsSync(inHome)) return inHome;

  return null;
}

// ─── YAML read/write ────────────────────────────────────────────────────────

let _configCache = null;
let _configPath = null;

function loadConfig(from) {
  const path = findConfig(from);
  if (!path) return {};
  if (_configPath === path && _configCache) return _configCache;
  try {
    const raw = readFileSync(path, 'utf8');
    _configCache = yaml.load(raw) || {};
    _configPath = path;
    return _configCache;
  } catch {
    return {};
  }
}

export function invalidateCache() {
  _configCache = null;
  _configPath = null;
}

export function configGet(dotPath, from) {
  const d = loadConfig(from);
  return dotPath.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), d);
}

export function configEnabled(dotPath, from) {
  const v = configGet(dotPath, from);
  if (typeof v === 'boolean') return v;
  if (typeof v === 'string') return ['true', 'yes'].includes(v.toLowerCase());
  return false;
}

export function securitySetting(key, from) {
  return configGet(`security.${key}`, from) || '';
}

export function yoloMode(from) {
  return configEnabled('security.yoloMode', from);
}

// ─── Catalog readers ────────────────────────────────────────────────────────
// Return arrays of { name, source, description, enabled }

function readSection(section, from) {
  const d = loadConfig(from);
  const items = d[section];
  if (!items || typeof items !== 'object') return [];
  return Object.entries(items).map(([name, val]) => {
    if (typeof val !== 'object') return null;
    return {
      name,
      source: val.source || val.command || '',
      description: val.description || val.source || val.command || '',
      enabled: val.enabled !== false, // default true unless explicitly false
      ...val, // preserve all fields (type, url, args, env, etc.)
    };
  }).filter(Boolean);
}

export function catalogSystem(from) { return readSection('system', from); }
export function catalogClis(from) { return readSection('clis', from); }
export function catalogSkills(from) { return readSection('skills', from); }
export function catalogPlugins(from) { return readSection('plugins', from); }
export function catalogCommands(from) { return readSection('commands', from); }
export function catalogMcps(from) { return readSection('mcps', from); }


export function mcpItem(name, from) {
  const d = loadConfig(from);
  return d.mcps?.[name] || null;
}

// ─── Config write ───────────────────────────────────────────────────────────

export function configSet(dotPath, value, from) {
  const path = findConfig(from);
  if (!path) return;
  const d = loadConfig(from);
  const keys = dotPath.split('.');
  let obj = d;
  for (const k of keys.slice(0, -1)) {
    if (!obj[k] || typeof obj[k] !== 'object') obj[k] = {};
    obj = obj[k];
  }
  obj[keys.at(-1)] = value;
  writeFileSync(path, yaml.dump(d, { lineWidth: -1, noRefs: true }));
  invalidateCache();
}

export function configInit(from) {
  const root = findRoot(from);
  const superDir = join(root, '.super');
  const dest = join(superDir, CONFIG_FILE);
  mkdirSync(superDir, { recursive: true });
  if (existsSync(dest)) return dest;

  // Copy template from SUPER_HOME or create default
  const template = join(process.env.SUPER_HOME || '', CONFIG_FILE);
  if (existsSync(template)) {
    writeFileSync(dest, readFileSync(template, 'utf8'));
  } else {
    writeFileSync(dest, yaml.dump(defaultConfig()));
  }
  return dest;
}

function defaultConfig() {
  return {
    version: '3.0',
    security: {
      yoloMode: false,
      writesOutsideProject: 'ask',
      readsOutsideProject: 'allow',
      bashExternalCalls: 'ask',
      changeOwner: 'block',
      githubCommands: 'allow',
      dangerousRm: 'block',
      envAccess: 'block',
      sensitivePaths: 'block',
    },
    session: {
      autoName: true,
      sessionLog: true,
      transcriptLog: true,
      cleanupOnStart: true,
      maxAgeDays: 7,
      injectContext: true,
    },
    skills: {},
    plugins: {},
    mcps: {},
    project: { lintCommand: '', typeCheckCommand: '' },
    hooks: {
      preToolUse: { enabled: true },
      permissionRequest: { enabled: true, autoAllowReads: true, autoAllowSafeBash: true },
      sessionStart: { enabled: true },
      sessionEnd: { enabled: true, saveTranscript: true },
      stop: { enabled: true, saveTranscript: true },
    },
  };
}

// ─── Dotenv loader ─────────────────────────────────────────────────────────
// Reads .env and .env.local from project root, returns { KEY: "value" } map.
// .env.local values override .env values. Used by catalog.mjs during install
// to resolve $env:VAR_NAME references in MCP definitions.

export function loadDotEnv(from) {
  const root = findRoot(from);
  const envMap = {};

  for (const name of ['.env', '.env.local']) {
    const path = join(root, name);
    if (!existsSync(path)) continue;
    const lines = readFileSync(path, 'utf8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eq = trimmed.indexOf('=');
      if (eq < 0) continue;
      const key = trimmed.slice(0, eq).trim();
      let val = trimmed.slice(eq + 1).trim();
      // Strip surrounding quotes
      if ((val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      envMap[key] = val;
    }
  }
  return envMap;
}

// ─── Version ────────────────────────────────────────────────────────────────

export function superVersion() {
  const versionFile = join(process.env.SUPER_HOME || dirname(import.meta.dirname), 'VERSION');
  try { return readFileSync(versionFile, 'utf8').trim(); } catch { return 'unknown'; }
}
