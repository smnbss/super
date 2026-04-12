// lib/interactive.mjs — Interactive selection menus
// Replaces interactive.sh — pure Node.js, no dependencies
// Three tiers: gum → arrow-key TUI → plain numbered

import { createInterface } from 'readline';
import { execSync } from 'child_process';
import { readFileSync, unlinkSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

function tmpFile() {
  return join(tmpdir(), `super-gum-${Date.now()}-${Math.random().toString(36).slice(2)}.txt`);
}

const hasGum = (() => { try { execSync('command -v gum', { stdio: 'ignore' }); return true; } catch { return false; } })();

function isReliableTTY() {
  if (!process.stdin.isTTY) return false;
  if (process.env.TERM === 'dumb') return false;
  if (process.env.CI || process.env.SSH_CLIENT || process.env.SSH_TTY) return false;
  return true;
}

// ─── Single select ──────────────────────────────────────────────────────────

export async function selectSingle(title, options, defaultIdx = 0) {
  if (hasGum) return gumSingle(title, options);
  if (isReliableTTY()) return arrowsSingle(title, options, defaultIdx);
  return numberedSingle(title, options, defaultIdx);
}

function gumSingle(title, options) {
  try {
    const tmp = tmpFile();
    execSync(
      `gum choose --height=10 --header ${JSON.stringify(title)} -- ${options.map(o => JSON.stringify(o)).join(' ')} > ${JSON.stringify(tmp)}`,
      { stdio: 'inherit' }
    );
    const result = readFileSync(tmp, 'utf8').trim();
    try { unlinkSync(tmp); } catch { /* ignore */ }
    const idx = options.indexOf(result);
    return idx >= 0 ? idx : null;
  } catch { return null; }
}

function arrowsSingle(title, options, cur) {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, terminal: false });
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const total = options.length;
    cur = Math.min(Math.max(cur, 0), total - 1);

    const render = () => {
      process.stderr.write(`\x1b[${total + 2}A\r`);
      process.stderr.write(`\x1b[2K${title}\n\x1b[2K\n`);
      for (let i = 0; i < total; i++) {
        if (i === cur) process.stderr.write(`\x1b[2K  \x1b[36m❯ ${options[i]}\x1b[0m\n`);
        else process.stderr.write(`\x1b[2K    ${options[i]}\n`);
      }
      process.stderr.write(`\x1b[2K\x1b[90m  ↑/↓ navigate · enter confirm · q quit\x1b[0m`);
    };

    // Initial render
    process.stderr.write(`${title}\n\n`);
    for (let i = 0; i < total; i++) {
      if (i === cur) process.stderr.write(`  \x1b[36m❯ ${options[i]}\x1b[0m\n`);
      else process.stderr.write(`    ${options[i]}\n`);
    }
    process.stderr.write(`\x1b[90m  ↑/↓ navigate · enter confirm · q quit\x1b[0m`);

    const cleanup = () => {
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdin.removeAllListeners('data');
      process.stderr.write('\n');
    };

    process.stdin.on('data', (data) => {
      const key = data.toString();
      if (key === '\x1b[A' || key === 'k') { if (cur > 0) cur--; render(); }
      else if (key === '\x1b[B' || key === 'j') { if (cur < total - 1) cur++; render(); }
      else if (key === '\r' || key === '\n') { cleanup(); resolve(cur); }
      else if (key === 'q' || key === 'Q' || key === '\x1b') { cleanup(); resolve(null); }
      else if (key >= '1' && key <= '9') {
        const n = parseInt(key) - 1;
        if (n < total) { cur = n; render(); }
      }
    });
  });
}

function numberedSingle(title, options, defaultIdx) {
  return new Promise((resolve) => {
    process.stderr.write(`${title}\n\n`);
    options.forEach((opt, i) => {
      const marker = i === defaultIdx ? '> ' : '  ';
      process.stderr.write(`${marker}${i + 1}. ${opt}\n`);
    });
    process.stderr.write(`\nSelect (1-${options.length}): `);

    const rl = createInterface({ input: process.stdin, output: process.stderr });
    rl.on('line', (line) => {
      const input = line.trim();
      if (input === 'q' || input === 'Q') { rl.close(); resolve(null); return; }
      const n = parseInt(input);
      if (n >= 1 && n <= options.length) { rl.close(); resolve(n - 1); return; }
      process.stderr.write(`Invalid. (1-${options.length}): `);
    });
  });
}

// ─── Multi select ───────────────────────────────────────────────────────────

export async function selectMulti(title, options) {
  if (hasGum) return gumMulti(title, options);
  if (isReliableTTY()) return arrowsMulti(title, options);
  return numberedMulti(title, options);
}

function gumMulti(title, options) {
  try {
    const tmp = tmpFile();
    execSync(
      `gum choose --no-limit --height=10 --header ${JSON.stringify(title)} -- ${options.map(o => JSON.stringify(o)).join(' ')} > ${JSON.stringify(tmp)}`,
      { stdio: 'inherit' }
    );
    const result = readFileSync(tmp, 'utf8').trim();
    try { unlinkSync(tmp); } catch { /* ignore */ }
    if (!result) return null;
    return result.split('\n').map(sel => options.indexOf(sel)).filter(i => i >= 0);
  } catch { return null; }
}

function arrowsMulti(title, options) {
  return new Promise((resolve) => {
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const total = options.length;
    let cur = 0;
    const sel = new Array(total).fill(false);

    const render = () => {
      process.stderr.write(`\x1b[${total + 2}A\r`);
      process.stderr.write(`\x1b[2K${title}\n\x1b[2K\n`);
      for (let i = 0; i < total; i++) {
        const ck = sel[i] ? '◉' : '○';
        if (i === cur) process.stderr.write(`\x1b[2K  \x1b[36m❯ ${ck} ${options[i]}\x1b[0m\n`);
        else process.stderr.write(`\x1b[2K    ${ck} ${options[i]}\n`);
      }
      process.stderr.write(`\x1b[2K\x1b[90m  ↑/↓ navigate · space toggle · a all · n none · enter confirm · q quit\x1b[0m`);
    };

    // Initial render
    process.stderr.write(`${title}\n\n`);
    for (let i = 0; i < total; i++) {
      const ck = sel[i] ? '◉' : '○';
      if (i === cur) process.stderr.write(`  \x1b[36m❯ ${ck} ${options[i]}\x1b[0m\n`);
      else process.stderr.write(`    ${ck} ${options[i]}\n`);
    }
    process.stderr.write(`\x1b[90m  ↑/↓ navigate · space toggle · a all · n none · enter confirm · q quit\x1b[0m`);

    const cleanup = () => {
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdin.removeAllListeners('data');
      process.stderr.write('\n');
    };

    process.stdin.on('data', (data) => {
      const key = data.toString();
      if (key === '\x1b[A' || key === 'k') { if (cur > 0) cur--; render(); }
      else if (key === '\x1b[B' || key === 'j') { if (cur < total - 1) cur++; render(); }
      else if (key === ' ') { sel[cur] = !sel[cur]; render(); }
      else if (key === 'a' || key === 'A') { sel.fill(true); render(); }
      else if (key === 'n' || key === 'N') { sel.fill(false); render(); }
      else if (key === '\r' || key === '\n') {
        cleanup();
        const indices = sel.map((s, i) => s ? i : -1).filter(i => i >= 0);
        resolve(indices.length > 0 ? indices : null);
      }
      else if (key === 'q' || key === 'Q' || key === '\x1b') { cleanup(); resolve(null); }
    });
  });
}

function numberedMulti(title, options) {
  return new Promise((resolve) => {
    process.stderr.write(`${title}\n\n`);
    options.forEach((opt, i) => process.stderr.write(`  ${i + 1}. ${opt}\n`));
    process.stderr.write(`\nEnter selections (space-separated, e.g. '1 3'), q to quit: `);

    const rl = createInterface({ input: process.stdin, output: process.stderr });
    rl.on('line', (line) => {
      const input = line.trim();
      if (input === 'q' || input === 'Q' || !input) { rl.close(); resolve(null); return; }
      const indices = input.split(/\s+/)
        .map(s => parseInt(s) - 1)
        .filter(n => n >= 0 && n < options.length);
      rl.close();
      resolve(indices.length > 0 ? indices : null);
    });
  });
}

// ─── Confirm ────────────────────────────────────────────────────────────────

export async function confirm(prompt, defaultYes = false) {
  if (hasGum) {
    try {
      execSync(`gum confirm ${JSON.stringify(prompt)}${defaultYes ? ' --default=yes' : ''}`, { stdio: 'inherit' });
      return true;
    } catch { return false; }
  }

  const hint = defaultYes ? '[Y/n]' : '[y/N]';
  return new Promise((resolve) => {
    process.stderr.write(`${prompt} ${hint} `);
    const rl = createInterface({ input: process.stdin, output: process.stderr });
    rl.on('line', (line) => {
      rl.close();
      const answer = line.trim().toLowerCase();
      if (answer === 'y' || answer === 'yes') resolve(true);
      else if (answer === 'n' || answer === 'no') resolve(false);
      else resolve(defaultYes);
    });
  });
}

// ─── Text input ─────────────────────────────────────────────────────────────

export async function input(prompt, defaultValue = '') {
  if (hasGum) {
    try {
      const tmp = tmpFile();
      execSync(
        `gum input --header ${JSON.stringify(prompt)} --value ${JSON.stringify(defaultValue)} > ${JSON.stringify(tmp)}`,
        { stdio: 'inherit' }
      );
      const result = readFileSync(tmp, 'utf8').trim();
      try { unlinkSync(tmp); } catch { /* ignore */ }
      return result || defaultValue;
    } catch { return defaultValue; }
  }

  return new Promise((resolve) => {
    process.stderr.write(`${prompt} [${defaultValue}]: `);
    const rl = createInterface({ input: process.stdin, output: process.stderr });
    rl.on('line', (line) => {
      rl.close();
      resolve(line.trim() || defaultValue);
    });
  });
}
