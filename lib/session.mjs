// lib/session.mjs — Session management
// Replaces session.sh — no more inline Python for context injection

import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync, statSync, readdirSync, unlinkSync, copyFileSync } from 'fs';
import { join, basename, dirname } from 'path';
import { findRoot, baseDir, sessionsDir, logFile } from './config.mjs';
import { cliIcon } from './ui.mjs';

// ─── Header helpers ─────────────────────────────────────────────────────────

function generateTitle(content) {
  let text = content
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return 'code snippet';
  return text
    .replace(/[^\w\s-]/g, '')
    .split(/\s+/)
    .slice(0, 6)
    .join(' ')
    .slice(0, 50);
}

function generateDescription(content) {
  let text = content
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return 'Shared a code snippet';
  return text.slice(0, 140);
}

function extractAllUserContent(sessionContent) {
  const userContents = [];
  const regex = /\n## [^\n]*👤 User\n\n([\s\S]*?)(?=\n> \*\*Tool\*\*|\n### |\n---\n\n|\n## |$)/g;
  let match;
  while ((match = regex.exec(sessionContent)) !== null) {
    userContents.push(match[1].trim());
  }
  return userContents.join(' ');
}

// Track turns since last title update per session file
const titleUpdateTracker = new Map();

function shouldUpdateTitle(file, currentContent) {
  // Count user turns in the session
  const userTurnCount = (currentContent.match(/^## [^\n]*👤 User/gm) || []).length;
  const lastUpdateTurn = titleUpdateTracker.get(file) || 0;

  // Update title every 3 user turns (or on first turn if untitled/auto)
  const currentTitle = currentContent.match(/^# Super Session: (.+)$/m)?.[1] || '';
  const isDefaultTitle = ['untitled', 'auto'].includes(currentTitle.trim());

  if (isDefaultTitle && userTurnCount === 1) {
    titleUpdateTracker.set(file, userTurnCount);
    return true;
  }

  if (userTurnCount - lastUpdateTurn >= 3) {
    titleUpdateTracker.set(file, userTurnCount);
    return true;
  }

  return false;
}

function updateSessionHeader(file, userContent) {
  if (!existsSync(file)) return;
  let content = readFileSync(file, 'utf8');

  // Only update title periodically based on conversation progression
  if (!shouldUpdateTitle(file, content)) return;

  const allUserContent = extractAllUserContent(content);
  const combinedContent = allUserContent || userContent;
  const title = generateTitle(combinedContent);
  const description = generateDescription(combinedContent);

  content = content.replace(/^# Super Session: .+$/m, `# Super Session: ${title}`);

  if (/^\*\*Description:\*\*/m.test(content)) {
    content = content.replace(/^\*\*Description:\*\* .+$/m, `**Description:** ${description}`);
  } else {
    content = content.replace(/^(\*\*File:\*\* .+)$/m, `$1\n**Description:** ${description}`);
  }

  writeFileSync(file, content);
}

// ─── Logging ────────────────────────────────────────────────────────────────

export function log(msg, from) {
  try {
    const ts = new Date().toTimeString().slice(0, 8);
    appendFileSync(logFile(from), `[${ts}] ${msg}\n`);
  } catch { /* ignore */ }
}

// ─── Active session ─────────────────────────────────────────────────────────

export function sessionFile(from) {
  if (process.env.SUPER_SESSION_FILE && existsSync(process.env.SUPER_SESSION_FILE)) {
    return process.env.SUPER_SESSION_FILE;
  }
  // Fallback: most recently modified session
  const dir = sessionsDir(from);
  if (!existsSync(dir)) return null;
  const files = readdirSync(dir)
    .filter(f => f.endsWith('.md'))
    .map(f => {
      const filepath = join(dir, f);
      return { filepath, mtime: statSync(filepath).mtimeMs };
    })
    .sort((a, b) => b.mtime - a.mtime);
  return files.length > 0 ? files[0].filepath : null;
}

// ─── Session creation ───────────────────────────────────────────────────────

export function sessionNew(title = 'untitled', from) {
  const safeTitle = title.toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-').replace(/-+/g, '-')
    .replace(/^-|-$/g, '').slice(0, 40) || 'untitled';

  const now = new Date();
  const ts = now.toISOString().slice(0, 19).replace(/T/, '_').replace(/:/g, '');
  const dir = sessionsDir(from);
  mkdirSync(dir, { recursive: true });

  const filename = `${ts}.md`;
  const filepath = join(dir, filename);
  const root = findRoot(from);

  const content = `# Super Session: ${title}

**Project:** ${basename(root)}
**Started:** ${now.toISOString().slice(0, 19).replace('T', ' ')}
**Directory:** ${process.cwd()}
**File:** ${filename}

---

`;
  writeFileSync(filepath, content);
  process.env.SUPER_SESSION_FILE = filepath;
  log(`New session: ${filepath}`, from);
  return filepath;
}

// ─── Session resume ─────────────────────────────────────────────────────────

export function sessionResume(filepath, from) {
  if (!existsSync(filepath)) throw new Error(`Session not found: ${filepath}`);
  process.env.SUPER_SESSION_FILE = filepath;
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
  appendFileSync(filepath, `\n---\n\n> ↩️  **Resumed** ${now}\n\n`);
  log(`Resumed: ${filepath}`, from);
  return filepath;
}

// ─── Session listing ────────────────────────────────────────────────────────

export function sessionList(from) {
  const dir = sessionsDir(from);
  if (!existsSync(dir)) return [];
  const active = sessionFile(from);

  return readdirSync(dir)
    .filter(f => f.endsWith('.md'))
    .sort().reverse()
    .map(f => {
      const filepath = join(dir, f);
      const content = readFileSync(filepath, 'utf8');
      const titleMatch = content.match(/^# Super Session: (.+)$/m);
      const startedMatch = content.match(/^\*\*Started:\*\* (.+)$/m);
      const turns = (content.match(/^## /gm) || []).length;
      return {
        filepath,
        filename: f,
        title: titleMatch?.[1] || f.replace('.md', ''),
        started: startedMatch?.[1] || '',
        turns,
        isActive: filepath === active,
      };
    });
}

// ─── Turn appending ─────────────────────────────────────────────────────────

export function sessionAppendTurn(cli, role, content, from) {
  let file = sessionFile(from);
  if (!file) file = sessionNew('auto', from);

  const ts = new Date().toTimeString().slice(0, 8);
  const icon = cliIcon(cli);

  const blocks = {
    user:          `\n---\n\n## ${icon} \`[${cli} ${ts}]\` 👤 User\n\n${content}\n`,
    assistant:     `\n### ${icon} \`[${cli} ${ts}]\` 🤖 Assistant\n\n${content}\n`,
    tool:          `\n> **Tool** \`${cli}\` \`[${ts}]\`\n> \n> \`\`\`\n${content.split('\n').slice(0, 20).map(l => `> ${l}`).join('\n')}\n> \`\`\`\n`,
    session_start: `\n---\n\n### ${icon} \`[${cli} ${ts}]\` 🚀 Started with **${cli}**\n\n`,
    session_end:   `\n### ${icon} \`[${cli} ${ts}]\` 🏁 Session ended (**${cli}**)\n\n`,
  };

  appendFileSync(file, blocks[role] || '');
  if (role === 'user') {
    updateSessionHeader(file, content);
  }
  log(`Appended ${role} from ${cli} → ${basename(file)}`, from);
}

// ─── Context injection ──────────────────────────────────────────────────────

const HEADER = '<!-- super:session-context -->';
const FOOTER = '<!-- /super:session-context -->';

export function sessionGetSummary(n = 50, from) {
  const file = sessionFile(from);
  if (!file || !existsSync(file)) return 'No active session.';
  const lines = readFileSync(file, 'utf8').split('\n').filter(l => l !== '---');
  return lines.slice(-n).join('\n');
}

export function sessionInjectContext(cli, from) {
  const root = findRoot(from);
  const summary = sessionGetSummary(80, from);
  const file = sessionFile(from);
  const activeName = file ? basename(file) : 'unknown';

  const targets = {
    claude: 'CLAUDE.md', gemini: 'GEMINI.md', codex: 'AGENTS.md', kimi: 'AGENTS.md',
  };
  const target = join(root, targets[cli?.toLowerCase()] || 'AGENTS.md');

  // Remove existing injection
  if (existsSync(target)) {
    const content = readFileSync(target, 'utf8');
    const cleaned = removeInjection(content);
    writeFileSync(target, cleaned);
  } else {
    writeFileSync(target, '');
  }

  // Append new context
  const injection = `
${HEADER}
## 📋 SuperCLI Cross-Session Context

Session: \`${activeName}\`

You are continuing a conversation that may have started in a different AI coding
assistant. The history below is the shared session log. Pick up where things
left off.

${summary}
${FOOTER}
`;
  appendFileSync(target, injection);
  log(`Injected context → ${target}`, from);
}

export function sessionClearInjections(from) {
  const root = findRoot(from);
  for (const f of ['CLAUDE.md', 'GEMINI.md', 'AGENTS.md']) {
    const target = join(root, f);
    if (!existsSync(target)) continue;
    const content = readFileSync(target, 'utf8');
    writeFileSync(target, removeInjection(content));
  }
  log('Cleared injections', from);
}

function removeInjection(content) {
  const lines = content.split('\n');
  const out = [];
  let skip = false;
  for (const line of lines) {
    if (line.includes(HEADER)) { skip = true; continue; }
    if (line.includes(FOOTER)) { skip = false; continue; }
    if (!skip) out.push(line);
  }
  return out.join('\n');
}

// ─── Transcript ─────────────────────────────────────────────────────────────

export function sessionSaveFinalTranscript(from) {
  const file = sessionFile(from);
  if (!file || !existsSync(file)) return;
  const dir = join(baseDir(from), 'transcripts');
  mkdirSync(dir, { recursive: true });
  const dest = join(dir, basename(file, '.md') + '-final.md');
  copyFileSync(file, dest);
  log(`Saved final transcript → ${dest}`, from);
}

// ─── Cleanup ────────────────────────────────────────────────────────────────

export function sessionCleanupOld(maxAgeDays = 7, from) {
  const dir = sessionsDir(from);
  if (!existsSync(dir)) return 0;
  const now = Date.now();
  let count = 0;
  for (const f of readdirSync(dir).filter(f => f.endsWith('.md'))) {
    const filepath = join(dir, f);
    const mtime = statSync(filepath).mtimeMs;
    const ageDays = (now - mtime) / 86400000;
    if (ageDays > maxAgeDays) {
      unlinkSync(filepath);
      count++;
    }
  }
  if (count > 0) log(`Cleaned up ${count} old session(s)`, from);
  return count;
}
