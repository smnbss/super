// lib/fzf.mjs — Fuzzy finder integration
// Replaces fzf.sh

import { execSync } from 'child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'fs';
import { join, basename } from 'path';
import { sessionsDir } from './config.mjs';
import { sessionFile, sessionList } from './session.mjs';
import { selectSingle } from './interactive.mjs';
import { cliIcons, cliLabels } from './ui.mjs';
import { isInstalled } from './catalog.mjs';

const hasFzf = (() => { try { execSync('command -v fzf', { stdio: 'ignore' }); return true; } catch { return false; } })();

export function fzfIsAvailable() { return hasFzf; }

export async function fzfPickSession(from) {
  if (hasFzf) return fzfPickSessionFzf(from);
  return fallbackPickSession(from);
}

function fzfPickSessionFzf(from) {
  const sessions = sessionList(from);
  if (sessions.length === 0) return 'NEW';

  const lines = sessions.map(s => {
    const mtime = statSync(s.filepath).mtimeMs;
    const ageH = Math.floor((Date.now() - mtime) / 3600000);
    const age = ageH < 1 ? 'just now' : ageH < 24 ? `${ageH}h ago` : `${Math.floor(ageH / 24)}d ago`;
    const marker = s.isActive ? ' ◀ ACTIVE' : '';
    return `${s.filename.replace('.md', '')}|${age}|${s.turns} turns${marker}`;
  }).join('\n');

  try {
    const selected = execSync(
      `echo "${lines}" | fzf --header="Select session (ctrl-n for new)" --delimiter='|' --with-nth=1,2,3 --height=60% --border=rounded --prompt="Session > " --bind='ctrl-n:abort'`,
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
    ).trim();
    if (!selected) return 'NEW';
    const filename = selected.split('|')[0] + '.md';
    return join(sessionsDir(from), filename);
  } catch {
    return 'NEW';
  }
}

async function fallbackPickSession(from) {
  const sessions = sessionList(from);
  if (sessions.length === 0) return '';

  const options = sessions.map(s => {
    const marker = s.isActive ? ' ◀' : '';
    return `${s.started.padEnd(20)}  ${String(s.turns).padStart(2)} turns  ${s.title.padEnd(55)}${marker}`;
  });
  options.push('🆕 Start a new session');

  const choice = await selectSingle('Saved sessions (newest first)', options, 0);
  if (choice === null) return 'QUIT';
  if (choice === sessions.length) return '';
  return sessions[choice].filepath;
}

export async function fzfPickCli() {
  const clis = ['claude', 'gemini', 'codex'].filter(isInstalled);
  if (clis.length === 0) return null;
  if (clis.length === 1) return clis[0];

  const options = clis.map(cli => `${cliIcons[cli]}  ${cliLabels[cli]}`);
  const choice = await selectSingle('Which CLI would you like to use?', options, 0);
  if (choice === null) return null;
  return clis[choice];
}
