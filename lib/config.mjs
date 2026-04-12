// lib/config.mjs — Configuration management for super
// Replaces config.sh + yaml_parse.py with native YAML/JSON handling

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname, basename } from 'path';
import yaml from 'js-yaml';

const CONFIG_FILE = 'super.config.yaml';

// ─── Project root discovery ──────────────────────────────────────────────────

export function findRoot(from) {
  return from || process.env.SUPER_PROJECT_DIR || process.cwd();
}

export function baseDir(from) { return join(findRoot(from), '.super'); }
export function sessionsDir(from) { return join(baseDir(from), 'sessions'); }
export function activePtr(from) { return join(baseDir(from), 'active'); }
export function logFile(from) { return join(baseDir(from), 'super.log'); }

// ─── Config file discovery ──────────────────────────────────────────────────

export function findConfig(from) {
  const root = findRoot(from);

  // Priority 1: .super/super.config.yaml
  const inSuper = join(root, '.super', CONFIG_FILE);
  if (existsSync(inSuper)) return inSuper;

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
