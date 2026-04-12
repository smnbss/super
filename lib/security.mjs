// lib/security.mjs — Security enforcement for hooks
// Replaces security.sh — cleaner pattern matching, no grep

import { findRoot, configEnabled, securitySetting, yoloMode } from './config.mjs';

const SAFE_PATTERNS = [
  /^ls(\s|$)/, /^cd\s/, /^pwd$/, /^cat\s/, /^head\s/, /^tail\s/,
  /^grep\s/, /^find\s/, /^git status/, /^git log/, /^git diff/,
  /^git branch/, /^git remote/, /^git config --local/, /^echo\s/,
  /^mkdir -p\s/, /^which\s/, /^command -v/,
];

const EXTERNAL_PATTERNS = [
  /curl.*-X POST/, /curl.*--data/, /curl.*-d\s/,
  /npm publish/, /npm unpublish/, /docker push/, /docker rm/,
  /kubectl apply/, /kubectl delete/,
  /gh pr create/, /gh release create/,
  /git push/,
];

const DANGEROUS_RM = /rm\s+-(r|f|rf|fr).*([/]\s*|\s+[/]|~|\$HOME)/;

const SENSITIVE_PATHS = [
  '~/.ssh', '~/.aws', '~/.kube', '~/.docker',
  '~/.npmrc', '~/.pypirc', '~/.git-credentials',
  '/etc/passwd', '/etc/shadow', '.env', '.env.local',
];

function isOutsideProject(path) {
  const root = findRoot();
  return !path.startsWith(root) && !path.startsWith('/tmp') && !path.startsWith(`${process.env.HOME}/.super`);
}

function isSensitivePath(path) {
  return SENSITIVE_PATHS.some(p => path.includes(p));
}

// Returns: 0 = allow, 1 = block, 2 = ask
export function securityCheck(tool, input) {
  if (yoloMode()) return 0;

  switch (tool) {
    case 'Bash': {
      const cmd = input.command || '';
      if (DANGEROUS_RM.test(cmd)) {
        const s = securitySetting('dangerousRm');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
      }
      if (EXTERNAL_PATTERNS.some(p => p.test(cmd))) {
        const s = securitySetting('bashExternalCalls');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
        if (s === 'allow') return 0;
      }
      if (SAFE_PATTERNS.some(p => p.test(cmd))) {
        if (configEnabled('hooks.permissionRequest.autoAllowSafeBash')) return 0;
      }
      break;
    }

    case 'Write': case 'Edit': case 'MultiEdit': {
      const path = input.path || '';
      if (isOutsideProject(path)) {
        const s = securitySetting('writesOutsideProject');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
      }
      if (isSensitivePath(path)) {
        const s = securitySetting('sensitivePaths');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
      }
      if (path.includes('.env')) {
        const s = securitySetting('envAccess');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
      }
      break;
    }

    case 'Read': case 'Glob': case 'Grep': {
      if (configEnabled('hooks.permissionRequest.autoAllowReads')) return 0;
      const path = input.path || input.pattern || '';
      if (isSensitivePath(path)) {
        const s = securitySetting('sensitivePaths');
        if (s === 'block') return 1;
        if (s === 'ask') return 2;
      }
      break;
    }
  }

  return 0;
}

export function formatBlockReason(tool, reason) {
  return `
╔════════════════════════════════════════════════════════════════╗
║  🔒 SUPER SECURITY BLOCK                                       ║
╠════════════════════════════════════════════════════════════════╣
║  Tool: ${tool}
║  Reason: ${reason}
╚════════════════════════════════════════════════════════════════╝

This action was blocked by super security settings.
Edit super.config.yaml to change security settings.`;
}
