import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const DEFAULT_CONFIG = {
  openclaw: {
    home: '',
    workspace: ''
  },
  server: {
    host: '127.0.0.1',
    port: 5173
  },
  ui: {
    defaultLocale: 'en',
    showDebugToggle: false,
    defaultDebugVisible: false,
    showInfoToggle: true,
    defaultInfoPanelVisible: true,
    showThemeToggle: false
  },
  actor: {
    defaultVariantId: 'capy-claw-emoji'
  },
  telemetry: {
    pollMs: 2500
  }
};

function parseEnvFile(targetPath) {
  try {
    const raw = fs.readFileSync(targetPath, 'utf8');
    const result = {};
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) {
        continue;
      }
      const separatorIndex = trimmed.indexOf('=');
      if (separatorIndex === -1) {
        continue;
      }
      const key = trimmed.slice(0, separatorIndex).trim();
      let value = trimmed.slice(separatorIndex + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      result[key] = value;
    }
    return result;
  } catch {
    return {};
  }
}

function mergeConfig(base, extra) {
  return {
    ...base,
    ...extra,
    openclaw: {
      ...base.openclaw,
      ...(extra.openclaw || {})
    },
    server: {
      ...base.server,
      ...(extra.server || {})
    },
    ui: {
      ...base.ui,
      ...(extra.ui || {})
    },
    actor: {
      ...base.actor,
      ...(extra.actor || {})
    },
    telemetry: {
      ...base.telemetry,
      ...(extra.telemetry || {})
    }
  };
}

export function loadClawLibraryConfig() {
  const configPath = path.join(ROOT, 'clawlibrary.config.json');
  let fileConfig = {};
  try {
    fileConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch {
    fileConfig = {};
  }

  const envFromFiles = {
    ...parseEnvFile(path.join(ROOT, '.env')),
    ...parseEnvFile(path.join(ROOT, '.env.local'))
  };

  const env = {
    ...envFromFiles,
    ...process.env
  };

  const merged = mergeConfig(DEFAULT_CONFIG, fileConfig);
  const openclawHome = env.OPENCLAW_HOME || merged.openclaw.home || path.join(os.homedir(), '.openclaw');
  const openclawWorkspace = env.OPENCLAW_WORKSPACE || merged.openclaw.workspace || path.join(openclawHome, 'workspace');

  return {
    ...merged,
    openclaw: {
      home: openclawHome,
      workspace: openclawWorkspace
    }
  };
}

export const clawlibraryConfig = loadClawLibraryConfig();
