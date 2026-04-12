import type { Connect } from 'vite';
import fs from 'node:fs/promises';
import path from 'node:path';
import { defineConfig } from 'vite';
import { execFile } from 'node:child_process';
import { clawlibraryConfig } from './scripts/clawlibrary-config.mjs';
import { createOpenClawSnapshot, findSnapshotResource, resolveOpenClawPath } from './scripts/openclaw-telemetry.mjs';

const TEXT_PREVIEW_LIMIT_BYTES = 180 * 1024;
const LIVE_OVERVIEW_CACHE_TTL_MS = 20 * 1000;
const LIVE_DETAIL_CACHE_TTL_MS = 5 * 60 * 1000;
const LIVE_OVERVIEW_CACHE_PATH = path.join(
  clawlibraryConfig.openclaw.home,
  'cache',
  'clawlibrary-live-overview.json'
);
const LIVE_DETAIL_CACHE_ROOT = path.join(
  clawlibraryConfig.openclaw.home,
  'cache',
  'clawlibrary-resource-details'
);
const TAIL_PREVIEW_EXTENSIONS = new Set(['.txt', '.log', '.jsonl']);
const TYXT_PROJECT_ROOT = process.env.TYXT_PROJECT_ROOT?.trim()
  ? path.resolve(process.env.TYXT_PROJECT_ROOT.trim())
  : path.resolve(process.cwd(), '..', '..');
const TYXT_CONFIG_PATH = path.join(TYXT_PROJECT_ROOT, 'config.json');
const TYXT_AGENTS_REGISTRY_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'agents_registry.json');
const TYXT_USER_PROFILES_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'user_profiles.json');
const TYXT_GROUP_CHATS_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'group_chats.json');
const TYXT_THEATER_THEATERS_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'theater', 'theaters.json');
const TYXT_PERSONA_CONFIG_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'persona_config.json');
const TYXT_GALLERY_INTRO_PATH = path.join(TYXT_PROJECT_ROOT, 'configs', 'gallery_intro.json');
const TYXT_GALLERY_PHOTOS_ROOT = path.join(TYXT_PROJECT_ROOT, 'configs', 'gallery_photos');
const TYXT_SHARED_ROOT = path.join(TYXT_PROJECT_ROOT, 'Ollama_agent_shared');
const TYXT_RUNTIME_PRIVATE_ROOT = path.join(TYXT_SHARED_ROOT, 'runtime_logs', 'private');
const TYXT_SHARED_DOCUMENTS_ROOT = path.join(TYXT_SHARED_ROOT, 'documents');
const TYXT_VAULT_DOCS_ROOT = path.join(TYXT_SHARED_ROOT, 'vault_docs');
const TYXT_IDLE_WORK_RUMINATION_ROOT = path.join(TYXT_SHARED_ROOT, 'idle_work', 'rumination');
const TYXT_DEEPTHINK_ROOT = path.join(TYXT_SHARED_ROOT, 'deepthink');
const TYXT_MEMORY_DB_ROOT = path.join(TYXT_PROJECT_ROOT, 'memory_db');
const TYXT_MEMORY_DB_THEATER_ROOT = path.join(TYXT_PROJECT_ROOT, 'memory_db_theater', 'theater');
const TYXT_OFFICE_PROJECTS_ROOT = path.join(TYXT_PROJECT_ROOT, 'state', 'office_projects');
const TYXT_PROFILES_ROOT = path.join(TYXT_PROJECT_ROOT, 'profiles');
const TYXT_BACKEND_BASE_CANDIDATES = Array.from(new Set([
  process.env.TYXT_BACKEND_BASE_URL?.trim() || '',
  process.env.TYXT_WEBUI_BASE_URL?.trim() || '',
  'http://127.0.0.1:5000',
  'https://127.0.0.1:5000'
]
  .map((item) => String(item || '').trim().replace(/\/+$/, ''))
  .filter(Boolean)
));
const IMAGE_CONTENT_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml'
};
const TEXT_CONTENT_TYPES: Record<string, string> = {
  '.md': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.log': 'text/plain; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jsonl': 'application/x-ndjson; charset=utf-8',
  '.yaml': 'application/yaml; charset=utf-8',
  '.yml': 'application/yaml; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.toml': 'text/plain; charset=utf-8',
  '.ini': 'text/plain; charset=utf-8',
  '.cfg': 'text/plain; charset=utf-8',
  '.conf': 'text/plain; charset=utf-8',
  '.py': 'text/plain; charset=utf-8',
  '.js': 'text/plain; charset=utf-8',
  '.mjs': 'text/plain; charset=utf-8',
  '.cjs': 'text/plain; charset=utf-8',
  '.ts': 'text/plain; charset=utf-8',
  '.tsx': 'text/plain; charset=utf-8',
  '.jsx': 'text/plain; charset=utf-8',
  '.sh': 'text/plain; charset=utf-8',
  '.bash': 'text/plain; charset=utf-8',
  '.zsh': 'text/plain; charset=utf-8',
  '.css': 'text/plain; charset=utf-8',
  '.html': 'text/plain; charset=utf-8',
  '.xml': 'text/plain; charset=utf-8',
  '.sql': 'text/plain; charset=utf-8'
};

type PreviewKind = 'markdown' | 'json' | 'text';
type PreviewReadMode = 'full' | 'head' | 'tail';
type CachedSnapshot = Awaited<ReturnType<typeof createOpenClawSnapshot>>;

let cachedLiveOverview: CachedSnapshot | null = null;
let cachedLiveOverviewLoaded = false;
let liveOverviewRefreshPromise: Promise<CachedSnapshot> | null = null;
const cachedLiveDetailByKey = new Map<string, CachedSnapshot>();
const cachedLiveDetailLoadedKeys = new Set<string>();
const liveDetailRefreshPromisesByKey = new Map<string, Promise<CachedSnapshot>>();

type TyxtRegistryAgentPayload = {
  agent_id: string;
  display_name: string;
  agent_title: string;
  agent_name: string;
  profile_root: string;
  enabled: boolean;
};

type TyxtHeaderTone = 'online' | 'offline' | 'partial' | 'ready' | 'running' | 'standby';

type TyxtHeaderStatusPayload = {
  backend: TyxtHeaderTone;
  weather_text: string;
  weather_state: TyxtHeaderTone;
  source: string | null;
  fetched_at: string;
};

type TyxtInteractionMetricSection = {
  kind: 'metric';
  label: string;
  value: string;
  hint: string;
};

type TyxtInteractionListSection = {
  kind: 'list';
  label: string;
  items: string[];
  empty_text: string;
  ordered?: boolean;
};

type TyxtInteractionLogSection = {
  kind: 'log';
  label: string;
  path: string;
  text: string;
};

type TyxtInteractionProfilesSection = {
  kind: 'profiles';
  label: string;
  items: Array<{
    id?: string;
    name: string;
    subtitle?: string;
    text: string;
    photo_label: string;
    photo_url?: string;
    photo_url_secondary?: string;
  }>;
};

type TyxtInteractionSection =
  | TyxtInteractionMetricSection
  | TyxtInteractionListSection
  | TyxtInteractionLogSection
  | TyxtInteractionProfilesSection;

type TyxtInteractionDetailPayload = {
  room_id: string;
  point_id: string;
  title: string;
  summary: string;
  sections: TyxtInteractionSection[];
  updated_at: string;
};

type TyxtInteractiveQueryContext = {
  agent_id?: string;
  user_id?: string;
};

type TyxtUserProfileEntry = {
  user_id?: unknown;
  role?: unknown;
  updated_at?: unknown;
};

async function readJsonFileSafe(targetPath: string): Promise<unknown | null> {
  try {
    const raw = await fs.readFile(targetPath, 'utf8');
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

type TyxtGalleryIntroConfig = {
  owner?: {
    text?: unknown;
    photo_path?: unknown;
    photo_path_primary?: unknown;
    photo_path_secondary?: unknown;
    photo_updated_at?: unknown;
    photo_updated_at_primary?: unknown;
    photo_updated_at_secondary?: unknown;
    updated_at?: unknown;
    updated_by?: unknown;
  };
  agents?: Record<string, {
    text?: unknown;
    photo_path?: unknown;
    photo_path_primary?: unknown;
    photo_path_secondary?: unknown;
    photo_updated_at?: unknown;
    photo_updated_at_primary?: unknown;
    photo_updated_at_secondary?: unknown;
    updated_at?: unknown;
    updated_by?: unknown;
  }>;
};

async function readTyxtGalleryIntroConfig(): Promise<TyxtGalleryIntroConfig> {
  const payload = asRecord(await readJsonFileSafe(TYXT_GALLERY_INTRO_PATH));
  return {
    owner: asRecord(payload.owner),
    agents: asRecord(payload.agents) as TyxtGalleryIntroConfig['agents']
  };
}

async function writeTyxtGalleryIntroConfig(config: TyxtGalleryIntroConfig): Promise<void> {
  const normalizedAgents: Record<string, {
    text: string;
    photo_path: string;
    photo_path_primary: string;
    photo_path_secondary: string;
    photo_updated_at: string;
    photo_updated_at_primary: string;
    photo_updated_at_secondary: string;
    updated_at: string;
    updated_by: string;
  }> = {};
  const sourceAgents = asRecord(config.agents);
  for (const [agentId, rowRaw] of Object.entries(sourceAgents)) {
    const row = asRecord(rowRaw);
    const normalizedAgentId = asString(agentId);
    if (!normalizedAgentId) {
      continue;
    }
    normalizedAgents[normalizedAgentId] = {
      text: asString(row.text),
      photo_path: asString(row.photo_path),
      photo_path_primary: asString(row.photo_path_primary),
      photo_path_secondary: asString(row.photo_path_secondary),
      photo_updated_at: asString(row.photo_updated_at),
      photo_updated_at_primary: asString(row.photo_updated_at_primary),
      photo_updated_at_secondary: asString(row.photo_updated_at_secondary),
      updated_at: asString(row.updated_at, new Date().toISOString()),
      updated_by: asString(row.updated_by)
    };
  }

  const out = {
    owner: {
      text: asString(asRecord(config.owner).text),
      photo_path: asString(asRecord(config.owner).photo_path),
      photo_path_primary: asString(asRecord(config.owner).photo_path_primary),
      photo_path_secondary: asString(asRecord(config.owner).photo_path_secondary),
      photo_updated_at: asString(asRecord(config.owner).photo_updated_at),
      photo_updated_at_primary: asString(asRecord(config.owner).photo_updated_at_primary),
      photo_updated_at_secondary: asString(asRecord(config.owner).photo_updated_at_secondary),
      updated_at: asString(asRecord(config.owner).updated_at, new Date().toISOString()),
      updated_by: asString(asRecord(config.owner).updated_by)
    },
    agents: normalizedAgents
  };

  await fs.mkdir(path.dirname(TYXT_GALLERY_INTRO_PATH), { recursive: true });
  await fs.writeFile(TYXT_GALLERY_INTRO_PATH, `${JSON.stringify(out, null, 2)}\n`, 'utf8');
}

function safeGalleryId(value: unknown, fallback: string): string {
  const base = asString(value);
  const normalized = (base || fallback)
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
  return normalized || fallback;
}

function resolveImageExtension(mimeType: string, fileName: string): string {
  const normalizedMime = asString(mimeType).toLowerCase();
  if (normalizedMime === 'image/png') return '.png';
  if (normalizedMime === 'image/jpeg' || normalizedMime === 'image/jpg') return '.jpg';
  if (normalizedMime === 'image/webp') return '.webp';
  if (normalizedMime === 'image/gif') return '.gif';

  const ext = path.extname(asString(fileName)).toLowerCase();
  if (ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.webp' || ext === '.gif') {
    return ext === '.jpeg' ? '.jpg' : ext;
  }
  return '.png';
}

type GalleryPhotoSlot = 'primary' | 'secondary';

function normalizePhotoSlot(value: unknown): GalleryPhotoSlot {
  return String(value ?? '').trim().toLowerCase() === 'secondary' ? 'secondary' : 'primary';
}

function galleryPhotoUrl(introKind: 'owner' | 'agent', targetId: string, versionTag: string, photoSlot: GalleryPhotoSlot = 'primary'): string {
  const query = new URLSearchParams();
  query.set('intro_kind', introKind);
  if (introKind === 'agent') {
    query.set('target_id', targetId);
    query.set('photo_slot', photoSlot);
  }
  query.set('t', versionTag || String(Date.now()));
  return `/api/tyxt/gallery-photo?${query.toString()}`;
}

function normalizeTyxtRegistryAgents(raw: unknown): TyxtRegistryAgentPayload[] {
  const sourceRows = Array.isArray((raw as { agents?: unknown })?.agents)
    ? ((raw as { agents: unknown[] }).agents)
    : [];

  const dedupe = new Set<string>();
  const out: TyxtRegistryAgentPayload[] = [];

  for (const row of sourceRows) {
    const item = typeof row === 'object' && row !== null ? row as Record<string, unknown> : {};
    const agentId = String(item.agent_id ?? '').trim();
    if (!agentId || dedupe.has(agentId)) {
      continue;
    }

    const enabled = item.enabled !== false;
    if (!enabled) {
      continue;
    }

    const displayName = String(item.agent_name ?? item.display_name ?? item.agent_title ?? agentId).trim() || agentId;
    const agentTitle = String(item.agent_title ?? '').trim();
    const agentName = String(item.agent_name ?? '').trim();
    const profileRoot = String(item.profile_root ?? '').trim();

    dedupe.add(agentId);
    out.push({
      agent_id: agentId,
      display_name: displayName,
      agent_title: agentTitle,
      agent_name: agentName,
      profile_root: profileRoot,
      enabled
    });
  }

  return out;
}

async function getTyxtApiToken(): Promise<string> {
  const configRaw = await readJsonFileSafe(TYXT_CONFIG_PATH);
  return String((configRaw as { mobile_link_api_key?: unknown })?.mobile_link_api_key ?? '').trim();
}

function normalizeTyxtUserId(value: unknown): string {
  return String(value ?? '').trim();
}

async function listTyxtHeaderUserCandidates(preferredUserId?: string | null): Promise<string[]> {
  const ordered = new Set<string>();
  const preferred = normalizeTyxtUserId(preferredUserId);
  if (preferred) {
    ordered.add(preferred);
  }

  const raw = await readJsonFileSafe(TYXT_USER_PROFILES_PATH);
  const rows = typeof raw === 'object' && raw !== null
    ? Object.values(raw as Record<string, TyxtUserProfileEntry>)
    : [];

  const normalizedRows = rows
    .map((row) => {
      const userId = normalizeTyxtUserId(row.user_id);
      const role = String(row.role ?? '').trim().toLowerCase();
      const updatedAt = Number(row.updated_at ?? 0);
      return {
        userId,
        role,
        updatedAt: Number.isFinite(updatedAt) ? updatedAt : 0
      };
    })
    .filter((row) => !!row.userId)
    .sort((a, b) => {
      if (a.role === 'admin' && b.role !== 'admin') return -1;
      if (b.role === 'admin' && a.role !== 'admin') return 1;
      return b.updatedAt - a.updatedAt;
    });

  for (const row of normalizedRows) {
    ordered.add(row.userId);
  }

  return [...ordered];
}

async function getTyxtAgentsRegistryPayload(): Promise<{
  agents: TyxtRegistryAgentPayload[];
  default_agent_id: string | null;
  source: string;
  loaded_at: string;
}> {
  const [registryRaw, configRaw] = await Promise.all([
    readJsonFileSafe(TYXT_AGENTS_REGISTRY_PATH),
    readJsonFileSafe(TYXT_CONFIG_PATH)
  ]);

  const agents = normalizeTyxtRegistryAgents(registryRaw);
  const preferredDefaultId = String((configRaw as { default_agent_id?: unknown })?.default_agent_id ?? '').trim();
  const defaultAgentId = agents.some((agent) => agent.agent_id === preferredDefaultId)
    ? preferredDefaultId
    : (agents[0]?.agent_id ?? null);

  return {
    agents,
    default_agent_id: defaultAgentId,
    source: TYXT_AGENTS_REGISTRY_PATH,
    loaded_at: new Date().toISOString()
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

function asString(value: unknown, fallback = ''): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function relativeToProject(absPath: string): string {
  try {
    return path.relative(TYXT_PROJECT_ROOT, absPath).replaceAll('\\', '/');
  } catch {
    return absPath;
  }
}

function tailLines(text: string, maxLines = 16, maxChars = 2800): string {
  const safeText = String(text || '').trim();
  if (!safeText) {
    return '(空日志)';
  }
  const lines = safeText.split(/\r?\n/);
  const clippedLines = lines.slice(Math.max(0, lines.length - maxLines));
  let merged = clippedLines.join('\n');
  if (merged.length > maxChars) {
    merged = `...${merged.slice(merged.length - maxChars)}`;
  }
  return merged;
}

async function listImmediateDirNames(rootDir: string): Promise<string[]> {
  try {
    const entries = await fs.readdir(rootDir, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
      .map((entry) => entry.name)
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  } catch {
    return [];
  }
}

async function collectFilesRecursive(
  rootDir: string,
  matcher: (fileName: string, fullPath: string) => boolean,
  maxCount = 600
): Promise<string[]> {
  const results: string[] = [];
  const stack: string[] = [rootDir];

  while (stack.length > 0 && results.length < maxCount) {
    const currentDir = stack.pop();
    if (!currentDir) {
      continue;
    }

    let entries: Awaited<ReturnType<typeof fs.readdir>>;
    try {
      entries = await fs.readdir(currentDir, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.')) {
          stack.push(fullPath);
        }
        continue;
      }
      if (!entry.isFile()) {
        continue;
      }
      if (matcher(entry.name, fullPath)) {
        results.push(fullPath);
        if (results.length >= maxCount) {
          break;
        }
      }
    }
  }

  return results;
}

function resolveTyxtPath(rawPath: string, fallbackPath: string): string {
  const candidate = String(rawPath || '').trim();
  if (!candidate) {
    return fallbackPath;
  }
  return path.isAbsolute(candidate)
    ? path.resolve(candidate)
    : path.resolve(TYXT_PROJECT_ROOT, candidate);
}

function normalizeProfileUserId(value: unknown): string {
  const raw = asString(value);
  if (!raw) {
    return '';
  }
  return raw.replace(/^qq_/i, '').trim();
}

function resolveProfileFileUserCandidates(filePath: string, payload: Record<string, unknown>): string[] {
  const parentDir = path.basename(path.dirname(filePath));
  const grandParentDir = path.basename(path.dirname(path.dirname(filePath)));
  const candidates = [
    normalizeProfileUserId(payload.user_id),
    normalizeProfileUserId(parentDir),
    normalizeProfileUserId(grandParentDir)
  ].filter(Boolean);
  return [...new Set(candidates)];
}

async function loadKnownTyxtUserIds(): Promise<Set<string>> {
  const payload = asRecord(await readJsonFileSafe(TYXT_USER_PROFILES_PATH));
  const known = new Set<string>();
  for (const [key, rowRaw] of Object.entries(payload)) {
    const row = asRecord(rowRaw);
    const keyUserId = normalizeProfileUserId(key);
    const rowUserId = normalizeProfileUserId(row.user_id);
    if (keyUserId) {
      known.add(keyUserId);
    }
    if (rowUserId) {
      known.add(rowUserId);
    }
  }
  return known;
}

function isRealUserProfileId(userId: string, knownUserIds: Set<string>): boolean {
  if (!userId) {
    return false;
  }
  if (knownUserIds.size > 0) {
    return knownUserIds.has(userId);
  }
  return /^\d{5,}$/.test(userId);
}

async function listTyxtLoungeProfileRoots(): Promise<string[]> {
  const payload = asRecord(await readJsonFileSafe(TYXT_AGENTS_REGISTRY_PATH));
  const rows = Array.isArray(payload.agents) ? payload.agents : [];
  const roots = new Set<string>();

  for (const row of rows) {
    const item = asRecord(row);
    if (item.enabled === false) {
      continue;
    }
    const resolvedRoot = resolveTyxtPath(asString(item.profile_root), TYXT_PROFILES_ROOT);
    roots.add(resolvedRoot);
  }

  if (roots.size === 0) {
    roots.add(TYXT_PROFILES_ROOT);
  }
  return [...roots];
}

async function resolveTyxtProfileRootForAgent(agentId?: string | null): Promise<string> {
  const registry = await getTyxtAgentsRegistryPayload();
  const requestedAgentId = asString(agentId);
  const targetAgent = (
    registry.agents.find((row) => row.enabled !== false && row.agent_id === requestedAgentId)
    ?? registry.agents.find((row) => row.enabled !== false && row.agent_id === registry.default_agent_id)
    ?? registry.agents.find((row) => row.enabled !== false)
    ?? null
  );
  return resolveTyxtPath(targetAgent?.profile_root || '', TYXT_PROFILES_ROOT);
}

async function collectTyxtProfileFilesFromLoungeRoots(
  fileName: 'memory_strips.json' | 'profile.json',
  maxCount = 800
): Promise<string[]> {
  const roots = await listTyxtLoungeProfileRoots();
  const normalizedFileName = fileName.toLowerCase();
  const dedupe = new Set<string>();

  for (const root of roots) {
    const files = await collectFilesRecursive(
      root,
      (name) => name.toLowerCase() === normalizedFileName,
      maxCount
    );
    for (const file of files) {
      dedupe.add(path.resolve(file));
      if (dedupe.size >= maxCount) {
        return [...dedupe];
      }
    }
  }

  return [...dedupe];
}

function containsCjk(text: string): boolean {
  return /[\u3400-\u9fff]/.test(text);
}

function collectLocalizedSamples(
  rows: Array<{ text: string; ts: number }>,
  limit = 24
): string[] {
  const dedupe = new Set<string>();
  const uniqueRows = rows
    .map((row) => ({ text: asString(row.text), ts: Number.isFinite(row.ts) ? row.ts : 0 }))
    .filter((row) => !!row.text)
    .filter((row) => {
      const key = row.text.trim();
      if (!key || dedupe.has(key)) {
        return false;
      }
      dedupe.add(key);
      return true;
    });

  const zhRows = uniqueRows.filter((row) => containsCjk(row.text));
  const selectedRows = zhRows.length > 0 ? zhRows : uniqueRows;
  return selectedRows.slice(0, limit).map((row) => row.text);
}

async function listPrivateChatWindows(): Promise<{ count: number; latestTitles: string[] }> {
  const indexFiles = await collectFilesRecursive(
    TYXT_RUNTIME_PRIVATE_ROOT,
    (name) => /^_window_index_.+\.json$/i.test(name),
    1200
  );

  const rows: Array<{ title: string; mtime: number }> = [];
  for (const file of indexFiles) {
    const payload = asRecord(await readJsonFileSafe(file));
    const title = asString(payload.chat_title) || asString(payload.window_name) || path.basename(file).replace(/^_window_index_/i, '').replace(/\.json$/i, '');
    const stat = await fs.stat(file).catch(() => null);
    rows.push({
      title,
      mtime: stat ? stat.mtimeMs : 0
    });
  }

  rows.sort((a, b) => b.mtime - a.mtime);
  const dedupe = new Set<string>();
  const latestTitles: string[] = [];
  for (const row of rows) {
    const normalized = row.title.trim();
    if (!normalized || dedupe.has(normalized)) {
      continue;
    }
    dedupe.add(normalized);
    latestTitles.push(normalized);
    if (latestTitles.length >= 10) {
      break;
    }
  }

  return {
    count: rows.length,
    latestTitles
  };
}

async function listGroupChatsSummary(): Promise<{ count: number; names: string[] }> {
  const payload = asRecord(await readJsonFileSafe(TYXT_GROUP_CHATS_PATH));
  const groupsRaw = Array.isArray(payload.groups) ? payload.groups : [];
  const names = groupsRaw
    .map((row) => {
      const item = asRecord(row);
      return asString(item.group_name) || asString(item.group_id) || '未命名群聊';
    })
    .filter(Boolean)
    .slice(0, 20);
  return {
    count: groupsRaw.length,
    names
  };
}

async function listOfficeProjectsSummary(): Promise<{ count: number; names: string[] }> {
  const files = await collectFilesRecursive(
    TYXT_OFFICE_PROJECTS_ROOT,
    (name) => name.toLowerCase().endsWith('.json'),
    200
  );
  const projects = new Map<string, { name: string; updatedAt: number }>();

  for (const file of files) {
    const payload = asRecord(await readJsonFileSafe(file));
    const rows = Array.isArray(payload.projects) ? payload.projects : [];
    for (const row of rows) {
      const item = asRecord(row);
      const projectId = asString(item.id);
      if (!projectId) {
        continue;
      }
      const projectName = asString(item.name) || projectId;
      const updatedAtText = asString(item.updatedAt) || asString(item.updated_at);
      const updatedAt = Number.isFinite(Date.parse(updatedAtText)) ? Date.parse(updatedAtText) : 0;
      projects.set(projectId, { name: projectName, updatedAt });
    }
  }

  const names = [...projects.values()]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .map((item) => item.name)
    .slice(0, 20);

  return {
    count: projects.size,
    names
  };
}

async function listSharedDocuments(): Promise<string[]> {
  const docExts = new Set([
    '.txt', '.md', '.json', '.jsonl', '.csv', '.doc', '.docx', '.pdf', '.xlsx', '.xls', '.ppt', '.pptx'
  ]);

  const docs = new Set<string>();

  const sharedFiles = await collectFilesRecursive(
    TYXT_SHARED_DOCUMENTS_ROOT,
    (name) => docExts.has(path.extname(name).toLowerCase()),
    400
  );
  for (const file of sharedFiles) {
    docs.add(relativeToProject(file));
  }

  const vaultListFiles = await collectFilesRecursive(
    TYXT_VAULT_DOCS_ROOT,
    (name) => name.toLowerCase() === 'list.json',
    400
  );
  for (const file of vaultListFiles) {
    const payload = asRecord(await readJsonFileSafe(file));
    const items = Array.isArray(payload.items) ? payload.items : [];
    for (const row of items) {
      const item = asRecord(row);
      const label = asString(item.title) || asString(item.path) || asString(item.name);
      if (label) {
        docs.add(label);
      }
    }
  }

  return [...docs].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')).slice(0, 40);
}

async function countChromaDatabases(): Promise<{
  privateCount: number;
  theaterCount: number;
  sampleNames: string[];
}> {
  const privateDirs = await listImmediateDirNames(TYXT_MEMORY_DB_ROOT);
  const theaterDirs = await listImmediateDirNames(TYXT_MEMORY_DB_THEATER_ROOT);
  const sampleNames = [...privateDirs.slice(0, 6), ...theaterDirs.slice(0, 4)]
    .map((name) => name.trim())
    .filter(Boolean);

  return {
    privateCount: privateDirs.length,
    theaterCount: theaterDirs.length,
    sampleNames
  };
}

async function listTheatersSummary(): Promise<Array<{ id: string; name: string; enabled: boolean }>> {
  const payload = asRecord(await readJsonFileSafe(TYXT_THEATER_THEATERS_PATH));
  const rows = Array.isArray(payload.theaters) ? payload.theaters : [];
  return rows
    .map((row) => {
      const item = asRecord(row);
      return {
        id: asString(item.theater_id),
        name: asString(item.name, '未命名剧场'),
        enabled: item.enabled !== false
      };
    })
    .filter((row) => !!row.id)
    .slice(0, 30);
}

async function countMemoryStripsSummary(context: TyxtInteractiveQueryContext = {}): Promise<{
  totalStrips: number;
  fileCount: number;
  sampleTexts: string[];
}> {
  const rawRequestedUserId = normalizeProfileUserId(context.user_id);
  const fallbackUserCandidates = rawRequestedUserId ? [rawRequestedUserId] : await listTyxtHeaderUserCandidates(null);
  const requestedUserId = normalizeProfileUserId(fallbackUserCandidates[0] || '');

  const [knownUserIds, profileRoot] = await Promise.all([
    loadKnownTyxtUserIds(),
    resolveTyxtProfileRootForAgent(context.agent_id)
  ]);

  const files = requestedUserId
    ? [path.join(profileRoot, requestedUserId, 'memory_strips.json')]
    : await collectTyxtProfileFilesFromLoungeRoots('memory_strips.json', 1200);

  let totalStrips = 0;
  let fileCount = 0;
  const rows: Array<{ text: string; updatedAt: number }> = [];

  for (const file of files) {
    const payload = asRecord(await readJsonFileSafe(file));
    const userCandidates = resolveProfileFileUserCandidates(file, payload);
    const matchedUserId = userCandidates.find((candidate) => isRealUserProfileId(candidate, knownUserIds));
    if (!matchedUserId) {
      continue;
    }
    if (requestedUserId && matchedUserId !== requestedUserId) {
      continue;
    }

    fileCount += 1;
    const strips = Array.isArray(payload.strips) ? payload.strips : [];
    for (const row of strips) {
      const item = asRecord(row);
      const text = asString(item.text);
      if (!text) {
        continue;
      }
      totalStrips += 1;
      const updatedAtValue = Number(item.updated_at ?? item.created_at ?? 0);
      const updatedAt = Number.isFinite(updatedAtValue) ? updatedAtValue : 0;
      rows.push({ text, updatedAt });
    }
  }

  rows.sort((a, b) => b.updatedAt - a.updatedAt);
  const sampleTexts = collectLocalizedSamples(
    rows.map((row) => ({ text: row.text, ts: row.updatedAt })),
    24
  );

  return { totalStrips, fileCount, sampleTexts };
}

async function countUserProfilesSummary(context: TyxtInteractiveQueryContext = {}): Promise<{
  totalFacts: number;
  fileCount: number;
  sampleFacts: string[];
}> {
  const rawRequestedUserId = normalizeProfileUserId(context.user_id);
  const fallbackUserCandidates = rawRequestedUserId ? [rawRequestedUserId] : await listTyxtHeaderUserCandidates(null);
  const requestedUserId = normalizeProfileUserId(fallbackUserCandidates[0] || '');

  const [knownUserIds, profileRoot] = await Promise.all([
    loadKnownTyxtUserIds(),
    resolveTyxtProfileRootForAgent(context.agent_id)
  ]);

  const files = requestedUserId
    ? [path.join(profileRoot, requestedUserId, 'profile.json')]
    : await collectTyxtProfileFilesFromLoungeRoots('profile.json', 1200);

  let totalFacts = 0;
  let fileCount = 0;
  const rows: Array<{ text: string; createdAt: number }> = [];

  for (const file of files) {
    const payload = asRecord(await readJsonFileSafe(file));
    const userCandidates = resolveProfileFileUserCandidates(file, payload);
    const matchedUserId = userCandidates.find((candidate) => isRealUserProfileId(candidate, knownUserIds));
    if (!matchedUserId) {
      continue;
    }
    if (requestedUserId && matchedUserId !== requestedUserId) {
      continue;
    }

    fileCount += 1;
    const facts = Array.isArray(payload.facts) ? payload.facts : [];
    for (const row of facts) {
      const item = asRecord(row);
      const text = asString(item.text);
      if (!text) {
        continue;
      }
      totalFacts += 1;
      const createdAtValue = Number(item.created_at ?? item.last_seen_at ?? 0);
      const createdAt = Number.isFinite(createdAtValue) ? createdAtValue : 0;
      rows.push({ text, createdAt });
    }
  }

  rows.sort((a, b) => b.createdAt - a.createdAt);
  const sampleFacts = collectLocalizedSamples(
    rows.map((row) => ({ text: row.text, ts: row.createdAt })),
    24
  );

  return { totalFacts, fileCount, sampleFacts };
}

async function loadLatestLogSnippet(
  rootDir: string,
  fileMatcher: (fileName: string) => boolean
): Promise<{ path: string; content: string }> {
  const files = await collectFilesRecursive(rootDir, (name) => fileMatcher(name), 300);
  if (files.length === 0) {
    return {
      path: '未找到日志文件',
      content: '(暂无日志)'
    };
  }

  let bestPath = files[0];
  let bestMtime = 0;
  for (const file of files) {
    const stat = await fs.stat(file).catch(() => null);
    const mtime = stat ? stat.mtimeMs : 0;
    if (mtime >= bestMtime) {
      bestMtime = mtime;
      bestPath = file;
    }
  }

  const raw = await fs.readFile(bestPath, 'utf8').catch(() => '');
  return {
    path: relativeToProject(bestPath),
    content: tailLines(raw, 16, 2600)
  };
}

async function loadLatestDeepthinkSnippet(context: TyxtInteractiveQueryContext = {}): Promise<{ path: string; content: string }> {
  const targetAgentId = asString(context.agent_id).toLowerCase();

  const primary = await loadLatestLogSnippet(
    TYXT_DEEPTHINK_ROOT,
    (name) => {
      const lower = name.toLowerCase();
      if (!lower.endsWith('.md')) return false;
      if (!lower.includes('deepthink')) return false;
      if (lower.includes('draft')) return false;
      if (targetAgentId) return lower.includes(targetAgentId);
      return true;
    }
  );
  if (primary.path !== '未找到日志文件') {
    return primary;
  }

  const fallbackNoDraft = await loadLatestLogSnippet(
    TYXT_DEEPTHINK_ROOT,
    (name) => {
      const lower = name.toLowerCase();
      return lower.endsWith('.md') && lower.includes('deepthink') && !lower.includes('draft');
    }
  );
  if (fallbackNoDraft.path !== '未找到日志文件') {
    return fallbackNoDraft;
  }

  return loadLatestLogSnippet(
    TYXT_DEEPTHINK_ROOT,
    (name) => {
      const lower = name.toLowerCase();
      return lower.endsWith('.md') && lower.includes('deepthink');
    }
  );
}

async function buildTyxtInteractiveDetailPayload(
  roomId: string,
  pointId: string,
  context: TyxtInteractiveQueryContext = {}
): Promise<TyxtInteractionDetailPayload> {
  if (pointId === 'hall-private-chat') {
    const privateSummary = await listPrivateChatWindows();
    return {
      room_id: roomId || 'main_hall',
      point_id: pointId,
      title: '主厅 · 私聊',
      summary: '展示当前私聊聊天框数量与最近会话窗口。',
      sections: [
        {
          kind: 'metric',
          label: '当前私聊聊天框',
          value: `${privateSummary.count} 个`,
          hint: '按 runtime_logs/private 中窗口索引统计。'
        },
        {
          kind: 'list',
          label: '最近私聊窗口',
          items: privateSummary.latestTitles,
          empty_text: '暂无私聊窗口。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'hall-group-chat') {
    const groupSummary = await listGroupChatsSummary();
    return {
      room_id: roomId || 'main_hall',
      point_id: pointId,
      title: '主厅 · 群聊',
      summary: '展示当前群聊数量与群名称列表。',
      sections: [
        {
          kind: 'metric',
          label: '当前聊天群',
          value: `${groupSummary.count} 个`,
          hint: '按 configs/group_chats.json 统计。'
        },
        {
          kind: 'list',
          label: '群聊列表',
          items: groupSummary.names,
          empty_text: '暂无群聊。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'study-projects') {
    const projectSummary = await listOfficeProjectsSummary();
    return {
      room_id: roomId || 'study',
      point_id: pointId,
      title: '书房 · 项目',
      summary: '展示当前项目数量，并列出最近项目。',
      sections: [
        {
          kind: 'metric',
          label: '当前项目总数',
          value: `${projectSummary.count} 个`,
          hint: '按 state/office_projects 下所有用户项目聚合去重。'
        },
        {
          kind: 'list',
          label: '最近项目',
          items: projectSummary.names,
          empty_text: '暂无项目。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'workshop-shared-files') {
    const docs = await listSharedDocuments();
    return {
      room_id: roomId || 'workshop',
      point_id: pointId,
      title: '工坊 · 共享文件',
      summary: '展示共享文件夹中的文档清单。',
      sections: [
        {
          kind: 'metric',
          label: '共享文档数量',
          value: `${docs.length} 份`,
          hint: '来源：Ollama_agent_shared/documents 与 vault_docs 索引。'
        },
        {
          kind: 'list',
          label: '文档清单',
          items: docs,
          empty_text: '共享文件夹暂时没有可展示的文档。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'workshop-memory-db') {
    const chromaSummary = await countChromaDatabases();
    return {
      room_id: roomId || 'workshop',
      point_id: pointId,
      title: '工坊 · 记忆库',
      summary: '展示 ChromaDB 数据库数量。',
      sections: [
        {
          kind: 'metric',
          label: 'ChromaDB 数据库',
          value: `${chromaSummary.privateCount + chromaSummary.theaterCount} 个`,
          hint: `私聊/通用库 ${chromaSummary.privateCount} 个，剧场库 ${chromaSummary.theaterCount} 个。`
        },
        {
          kind: 'list',
          label: '数据库样例',
          items: chromaSummary.sampleNames,
          empty_text: '暂无数据库目录。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'theater-shows') {
    const theaters = await listTheatersSummary();
    return {
      room_id: roomId || 'theater',
      point_id: pointId,
      title: '剧场 · 剧目',
      summary: '展示创想区配置下的剧场 ID 与剧场名。',
      sections: [
        {
          kind: 'metric',
          label: '剧场数量',
          value: `${theaters.length} 个`,
          hint: '来源：configs/theater/theaters.json。'
        },
        {
          kind: 'list',
          label: '剧场清单',
          items: theaters.map((item) => `${item.id} · ${item.name}${item.enabled ? '' : '（停用）'}`),
          empty_text: '暂无剧场配置。'
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'archive-memory-strips') {
    const stripSummary = await countMemoryStripsSummary(context);
    return {
      room_id: roomId || 'observatory',
      point_id: pointId,
      title: '档案室 · 记忆条',
      summary: '展示当前记忆条条数。',
      sections: [
        {
          kind: 'metric',
          label: '记忆条总条数',
          value: `${stripSummary.totalStrips} 条`,
          hint: `共扫描 ${stripSummary.fileCount} 份 memory_strips.json。`
        },
        {
          kind: 'list',
          label: '记忆条内容',
          items: stripSummary.sampleTexts,
          empty_text: '暂无记忆条内容。',
          ordered: true
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'archive-user-profiles') {
    const profileSummary = await countUserProfilesSummary(context);
    return {
      room_id: roomId || 'observatory',
      point_id: pointId,
      title: '档案室 · 用户画像',
      summary: '展示当前用户画像条数。',
      sections: [
        {
          kind: 'metric',
          label: '用户画像条目',
          value: `${profileSummary.totalFacts} 条`,
          hint: `facts 汇总，覆盖 ${profileSummary.fileCount} 份 profile.json。`
        },
        {
          kind: 'list',
          label: '用户画像内容',
          items: profileSummary.sampleFacts,
          empty_text: '暂无用户画像内容。',
          ordered: true
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'bedroom-rumination-log') {
    const log = await loadLatestLogSnippet(TYXT_IDLE_WORK_RUMINATION_ROOT, (name) => /rumination.*\.txt$/i.test(name));
    return {
      room_id: roomId || 'message_wall',
      point_id: pointId,
      title: '卧室 · 反刍层',
      summary: '展示最近一次反刍层日志。',
      sections: [
        {
          kind: 'log',
          label: '最近反刍层日志',
          path: log.path,
          text: log.content
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'bedroom-deepthink-log') {
    const log = await loadLatestDeepthinkSnippet(context);
    return {
      room_id: roomId || 'message_wall',
      point_id: pointId,
      title: '卧室 · 深度思考层',
      summary: '展示最近一次深度思考层日志。',
      sections: [
        {
          kind: 'log',
          label: '最近深度思考层日志',
          path: log.path,
          text: log.content
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'gallery-owner-intro') {
    const galleryIntro = await readTyxtGalleryIntroConfig();
    const userProfilesPayload = asRecord(await readJsonFileSafe(TYXT_USER_PROFILES_PATH));
    const personaPayload = asRecord(await readJsonFileSafe(TYXT_PERSONA_CONFIG_PATH));
    const userRows = Object.values(userProfilesPayload).map((row) => asRecord(row));
    const adminRow = userRows.find((row) => asString(row.role).toLowerCase() === 'admin') ?? userRows[0] ?? {};
    const ownerName = asString(adminRow.nickname) || asString(adminRow.user_id) || '系统主人';
    const defaultOwnerText = [
      `昵称：${ownerName}`,
      `用户ID：${asString(adminRow.user_id, '未知')}`,
      `身份：${asString(adminRow.role, '未标注')}`,
      `角色设定：${asString(personaPayload.agent_title, '未配置')}`
    ].join('\n');
    const ownerRow = asRecord(galleryIntro.owner);
    const ownerText = asString(ownerRow.text) || defaultOwnerText;
    const ownerId = asString(adminRow.user_id, 'owner');
    const ownerPhotoPath = asString(ownerRow.photo_path_primary) || asString(ownerRow.photo_path);
    const ownerPhotoVersion = asString(ownerRow.photo_updated_at_primary) || asString(ownerRow.photo_updated_at) || asString(ownerRow.updated_at) || new Date().toISOString();
    const ownerPhotoUrl = ownerPhotoPath ? galleryPhotoUrl('owner', ownerId, ownerPhotoVersion) : '';
    return {
      room_id: roomId || 'gallery',
      point_id: pointId,
      title: '展厅 · 主人简介',
      summary: '展示主人简介（照片框 + 文字框）。',
      sections: [
        {
          kind: 'profiles',
          label: '主人简介卡',
          items: [
            {
              id: ownerId,
              name: ownerName,
              subtitle: '主人',
              photo_label: `${ownerName} 照片框`,
              text: ownerText,
              photo_url: ownerPhotoUrl || undefined
            }
          ]
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  if (pointId === 'gallery-agent-intro') {
    const galleryIntro = await readTyxtGalleryIntroConfig();
    const registryPayload = asRecord(await readJsonFileSafe(TYXT_AGENTS_REGISTRY_PATH));
    const agentsRaw = Array.isArray(registryPayload.agents) ? registryPayload.agents : [];
    const agents = agentsRaw
      .map((row) => asRecord(row))
      .filter((row) => row.enabled !== false)
      .map((row) => {
        const agentId = asString(row.agent_id);
        const name = asString(row.agent_name) || asString(row.display_name) || agentId || 'Agent';
        const title = asString(row.agent_title, 'Agent');
        const model = asString(row.main_model);
        const introRow = asRecord(asRecord(galleryIntro.agents)[agentId]);
        const defaultText = [
          `称谓：${title}`,
          `姓名：${name}`,
          model ? `模型：${model}` : ''
        ].filter(Boolean).join('\n');
        const introOverride = asString(introRow.text);
        const text = introOverride || defaultText || '暂无详细描述';
        const primaryPhotoPath = asString(introRow.photo_path_primary) || asString(introRow.photo_path);
        const primaryPhotoVersion = asString(introRow.photo_updated_at_primary) || asString(introRow.photo_updated_at) || asString(introRow.updated_at) || new Date().toISOString();
        const primaryPhotoUrl = primaryPhotoPath ? galleryPhotoUrl('agent', agentId, primaryPhotoVersion, 'primary') : '';
        const secondaryPhotoPath = asString(introRow.photo_path_secondary);
        const secondaryPhotoVersion = asString(introRow.photo_updated_at_secondary) || asString(introRow.updated_at) || new Date().toISOString();
        const secondaryPhotoUrl = secondaryPhotoPath ? galleryPhotoUrl('agent', agentId, secondaryPhotoVersion, 'secondary') : '';
        return {
          id: agentId,
          subtitle: title,
          name,
          photo_label: `${name} 照片框`,
          text,
          photo_url: primaryPhotoUrl || undefined,
          photo_url_secondary: secondaryPhotoUrl || undefined
        };
      })
      .slice(0, 8);

    return {
      room_id: roomId || 'gallery',
      point_id: pointId,
      title: '展厅 · Agent简介',
      summary: '展示 Agent 简介（照片框 + 文字框）。',
      sections: [
        {
          kind: 'profiles',
          label: 'Agent 简介卡',
          items: agents
        }
      ],
      updated_at: new Date().toISOString()
    };
  }

  return {
    room_id: roomId || 'main_hall',
    point_id: pointId,
    title: '交互内容',
    summary: '该交互点暂未定义展示内容。',
    sections: [
      {
        kind: 'metric',
        label: '状态',
        value: '未配置',
        hint: '请在 room_profiles 中配置对应 point_id。'
      }
    ],
    updated_at: new Date().toISOString()
  };
}

function contentTypeForPath(target: string): string {
  const ext = path.extname(target).toLowerCase();
  return IMAGE_CONTENT_TYPES[ext] || TEXT_CONTENT_TYPES[ext] || 'application/octet-stream';
}

function previewKindForPath(target: string): PreviewKind | null {
  const ext = path.extname(target).toLowerCase();
  if (ext === '.md') {
    return 'markdown';
  }
  if (ext === '.json') {
    return 'json';
  }
  if (ext in TEXT_CONTENT_TYPES) {
    return 'text';
  }
  return null;
}

async function readTextPreview(
  target: string,
  requestedMode: Exclude<PreviewReadMode, 'full'>,
  limit = TEXT_PREVIEW_LIMIT_BYTES
): Promise<{ content: string; truncated: boolean; readMode: PreviewReadMode }> {
  const handle = await fs.open(target, 'r');
  try {
    const stat = await handle.stat();
    const bytesToRead = Math.min(limit, stat.size);
    const offset = requestedMode === 'tail'
      ? Math.max(0, stat.size - bytesToRead)
      : 0;
    const buffer = Buffer.alloc(bytesToRead);
    await handle.read(buffer, 0, bytesToRead, offset);
    return {
      content: buffer.toString('utf8'),
      truncated: stat.size > limit,
      readMode: stat.size > limit ? requestedMode : 'full'
    };
  } finally {
    await handle.close();
  }
}

function formatPreviewContent(kind: PreviewKind, raw: string): string {
  if (kind === 'json') {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }
  return raw;
}

async function buildDirectoryPreview(target: string, rawPath: string) {
  const entries = await fs.readdir(target, { withFileTypes: true });
  const readmeEntry = entries.find((entry) => entry.isFile() && /^readme(?:\.[A-Za-z0-9_-]+)?$/i.test(entry.name));

  if (readmeEntry) {
    const readmePath = path.join(target, readmeEntry.name);
    const kind = previewKindForPath(readmePath) ?? 'text';
    const preview = await readTextPreview(readmePath, 'head');
    return {
      ok: true,
      kind,
      path: rawPath,
      contentType: contentTypeForPath(readmePath),
      content: formatPreviewContent(kind, preview.content),
      truncated: preview.truncated,
      readMode: preview.readMode
    };
  }

  const childDirs = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
  const childFiles = entries.filter((entry) => entry.isFile()).map((entry) => entry.name).sort();
  const runtimeHints = [
    'package.json',
    'pyproject.toml',
    'requirements.txt',
    'Cargo.toml',
    'go.mod',
    'README.md',
    'README',
    'src',
    'app.py',
    'main.py'
  ].filter((name) => childFiles.includes(name) || childDirs.includes(name));

  const summary = [
    `# ${path.basename(target)}`,
    '',
    'No README found for this directory.',
    '',
    `Path: \`${rawPath}\``,
    '',
    runtimeHints.length ? `Detected project signals: ${runtimeHints.map((entry) => `\`${entry}\``).join(', ')}` : 'Detected project signals: none',
    '',
    childDirs.length ? 'Subdirectories:' : 'Subdirectories: none',
    ...(childDirs.length ? childDirs.slice(0, 8).map((entry) => `- \`${entry}/\``) : []),
    '',
    childFiles.length ? 'Files:' : 'Files: none',
    ...(childFiles.length ? childFiles.slice(0, 10).map((entry) => `- \`${entry}\``) : [])
  ].join('\n');

  return {
    ok: true,
    kind: 'markdown' as const,
    path: rawPath,
    contentType: 'text/markdown; charset=utf-8',
    content: summary,
    truncated: false,
    readMode: 'full' as const
  };
}

async function loadCachedSnapshot(cachePath: string): Promise<CachedSnapshot | null> {
  try {
    const raw = await fs.readFile(cachePath, 'utf8');
    return JSON.parse(raw) as CachedSnapshot;
  } catch {
    return null;
  }
}

async function loadCachedLiveOverview(): Promise<void> {
  if (cachedLiveOverviewLoaded) {
    return;
  }
  cachedLiveOverviewLoaded = true;
  cachedLiveOverview = await loadCachedSnapshot(LIVE_OVERVIEW_CACHE_PATH);
}

function detailCacheKeyOf(resourceId: string): string {
  return resourceId === 'gateway' ? 'gateway+task_queues' : resourceId;
}

function detailResourceIdsFor(resourceId: string): string[] {
  return resourceId === 'gateway' ? ['gateway', 'task_queues'] : [resourceId];
}

function detailCachePathOf(cacheKey: string): string {
  return path.join(LIVE_DETAIL_CACHE_ROOT, `${cacheKey}.json`);
}

async function loadCachedLiveDetail(cacheKey: string): Promise<CachedSnapshot | null> {
  if (cachedLiveDetailLoadedKeys.has(cacheKey)) {
    return cachedLiveDetailByKey.get(cacheKey) ?? null;
  }
  cachedLiveDetailLoadedKeys.add(cacheKey);
  const snapshot = await loadCachedSnapshot(detailCachePathOf(cacheKey));
  if (snapshot) {
    cachedLiveDetailByKey.set(cacheKey, snapshot);
  }
  return snapshot;
}

async function persistLiveDetail(cacheKey: string, snapshot: CachedSnapshot): Promise<void> {
  await fs.mkdir(LIVE_DETAIL_CACHE_ROOT, { recursive: true });
  await persistCachedSnapshot(detailCachePathOf(cacheKey), snapshot);
}

async function refreshLiveDetail(cacheKey: string, resourceIds: string[]): Promise<CachedSnapshot> {
  const pending = liveDetailRefreshPromisesByKey.get(cacheKey);
  if (pending) {
    return pending;
  }
  const request = createOpenClawSnapshot({
    mock: false,
    itemResourceIds: resourceIds,
    includeExcerpt: false
  })
    .then(async (snapshot) => {
      cachedLiveDetailByKey.set(cacheKey, snapshot);
      await persistLiveDetail(cacheKey, snapshot);
      return snapshot;
    })
    .finally(() => {
      liveDetailRefreshPromisesByKey.delete(cacheKey);
    });
  liveDetailRefreshPromisesByKey.set(cacheKey, request);
  return request;
}

async function getLiveDetailSnapshot(resourceId: string): Promise<CachedSnapshot> {
  const cacheKey = detailCacheKeyOf(resourceId);
  const resourceIds = detailResourceIdsFor(resourceId);
  const cached = await loadCachedLiveDetail(cacheKey);
  if (cached && cachedSnapshotAgeMs(cached) < LIVE_DETAIL_CACHE_TTL_MS) {
    return cached;
  }
  if (cached) {
    void refreshLiveDetail(cacheKey, resourceIds);
    return cached;
  }
  return refreshLiveDetail(cacheKey, resourceIds);
}

function cachedSnapshotAgeMs(snapshot: CachedSnapshot | null): number {
  if (!snapshot?.generatedAt) {
    return Number.POSITIVE_INFINITY;
  }
  const time = new Date(snapshot.generatedAt).getTime();
  return Number.isNaN(time) ? Number.POSITIVE_INFINITY : Date.now() - time;
}

async function persistCachedSnapshot(cachePath: string, snapshot: CachedSnapshot): Promise<void> {
  await fs.mkdir(path.dirname(cachePath), { recursive: true });
  await fs.writeFile(cachePath, JSON.stringify(snapshot), 'utf8');
}

async function refreshLiveOverview(): Promise<CachedSnapshot> {
  if (liveOverviewRefreshPromise) {
    return liveOverviewRefreshPromise;
  }
  liveOverviewRefreshPromise = createOpenClawSnapshot({ mock: false, includeItems: false })
    .then(async (snapshot) => {
      cachedLiveOverview = snapshot;
      await persistCachedSnapshot(LIVE_OVERVIEW_CACHE_PATH, snapshot);
      return snapshot;
    })
    .finally(() => {
      liveOverviewRefreshPromise = null;
    });
  return liveOverviewRefreshPromise;
}

void loadCachedLiveOverview()
  .then(async () => {
    if (!cachedLiveOverview || cachedSnapshotAgeMs(cachedLiveOverview) >= LIVE_OVERVIEW_CACHE_TTL_MS) {
      await refreshLiveOverview();
    }
  })
  .catch(() => {
    // ignore warmup failures; middleware will retry on demand
  });

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function weatherCodeToZh(code: number | null): string {
  if (code === null) return "";
  if (code === 0) return "晴";
  if (code === 1 || code === 2 || code === 3) return "多云";
  if (code === 45 || code === 48) return "雾";
  if (code >= 51 && code <= 67) return "雨";
  if (code >= 71 && code <= 77) return "雪";
  if (code >= 80 && code <= 82) return "阵雨";
  if (code >= 95) return "雷雨";
  return "天气";
}

function formatWeatherSummary(payload: Record<string, unknown>): { text: string; tone: TyxtHeaderTone } {
  const city = String(payload.city ?? "").trim();
  const cityLabel = city || "本地";
  const min = toFiniteNumber(payload.temp_min);
  const max = toFiniteNumber(payload.temp_max);
  const currentTemp = toFiniteNumber(payload.temperature);
  const weatherCode = toFiniteNumber(payload.weather_code);
  const weatherLabel = weatherCodeToZh(weatherCode === null ? null : Math.trunc(weatherCode));
  const unit = String(payload.temperature_unit ?? "°C").trim() || "°C";
  const normalizedUnit = unit === "°C" ? "℃" : unit;

  if (min !== null && max !== null) {
    return {
      text: `${cityLabel} ${weatherLabel} ${Math.round(min)}/${Math.round(max)}${normalizedUnit}`.trim(),
      tone: "online"
    };
  }

  if (currentTemp !== null) {
    return {
      text: `${cityLabel} ${weatherLabel} ${Math.round(currentTemp)}${normalizedUnit}`.trim(),
      tone: "online"
    };
  }

  return {
    text: `${cityLabel} 已设置`,
    tone: "standby"
  };
}

async function fetchTyxtHeaderStatusPayload(
  preferredUserId?: string | null,
  requestMobileAuthToken?: string | null
): Promise<TyxtHeaderStatusPayload> {
  const authToken = await getTyxtApiToken();
  const userCandidates = await listTyxtHeaderUserCandidates(preferredUserId);
  const mobileAuthToken = normalizeTyxtUserId(requestMobileAuthToken);

  for (const baseUrl of TYXT_BACKEND_BASE_CANDIDATES) {
    try {
      const headers: Record<string, string> = {
        Accept: "application/json"
      };
      if (mobileAuthToken) {
        headers['X-TYXT-Auth-Token'] = mobileAuthToken;
      }
      if (authToken) {
        headers['X-API-Key'] = authToken;
      }

      const healthResponse = await fetch(`${baseUrl}/health`, {
        method: "GET",
        headers,
        redirect: "follow"
      });
      if (!healthResponse.ok) {
        continue;
      }

      const perBaseUsers = userCandidates.length > 0 ? userCandidates : [''];
      let hasNoLocation = false;
      let weatherAuthRequired = false;
      let weatherServerError = false;

      for (const userId of perBaseUsers) {
        const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
        const response = await fetch(`${baseUrl}/tools/weather${query}`, {
          method: "GET",
          headers,
          redirect: "follow"
        });

        const payload = await response.json().catch(() => null) as Record<string, unknown> | null;

        if (response.ok && payload && payload.ok === true) {
          const weather = formatWeatherSummary(payload);
          return {
            backend: "online",
            weather_text: weather.text,
            weather_state: weather.tone,
            source: baseUrl,
            fetched_at: new Date().toISOString()
          };
        }

        if (response.status === 400 && payload?.error === 'no_location') {
          hasNoLocation = true;
          continue;
        }

        if (response.status === 400) {
          hasNoLocation = true;
          continue;
        }

        if (response.status === 401 || response.status === 403) {
          weatherAuthRequired = true;
          continue;
        }

        if (response.status >= 500) {
          weatherServerError = true;
          continue;
        }
      }

      if (weatherServerError) {
        return {
          backend: "partial",
          weather_text: "天气服务异常",
          weather_state: "partial",
          source: baseUrl,
          fetched_at: new Date().toISOString()
        };
      }

      if (hasNoLocation) {
        return {
          backend: "online",
          weather_text: "天气未设置",
          weather_state: "standby",
          source: baseUrl,
          fetched_at: new Date().toISOString()
        };
      }

      if (weatherAuthRequired) {
        return {
          backend: "online",
          weather_text: "需登录后显示",
          weather_state: "standby",
          source: baseUrl,
          fetched_at: new Date().toISOString()
        };
      }

      return {
        backend: "online",
        weather_text: "天气未设置",
        weather_state: "standby",
        source: baseUrl,
        fetched_at: new Date().toISOString()
      };
    } catch {
      // try next candidate base url
    }
  }

  return {
    backend: "offline",
    weather_text: "天气服务离线",
    weather_state: "offline",
    source: null,
    fetched_at: new Date().toISOString()
  };
}

function telemetryMiddleware() {
  return async (req: Connect.IncomingMessage, res: Connect.ServerResponse, next: Connect.NextFunction) => {
    if (req.url?.startsWith('/api/tyxt/header-status') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const preferredUserId = String(
          requestUrl.searchParams.get('user_id')
          || requestUrl.searchParams.get('userId')
          || ''
        ).trim();
        const mobileAuthToken = String(
          req.headers['x-tyxt-auth-token']
          || req.headers['x_tyxt_auth_token']
          || ''
        ).trim();

        const payload = await fetchTyxtHeaderStatusPayload(
          preferredUserId || null,
          mobileAuthToken || null
        );
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, ...payload }));
      } catch (error) {
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: false,
          backend: 'offline',
          weather_text: '天气服务离线',
          weather_state: 'offline',
          source: null,
          fetched_at: new Date().toISOString(),
          error: error instanceof Error ? error.message : String(error)
        }));
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/agents-registry') && req.method === 'GET') {
      try {
        const payload = await getTyxtAgentsRegistryPayload();
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, ...payload }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/interactive-content') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const roomId = asString(requestUrl.searchParams.get('room_id') || requestUrl.searchParams.get('roomId'));
        const pointId = asString(requestUrl.searchParams.get('point_id') || requestUrl.searchParams.get('pointId'));
        const agentId = asString(requestUrl.searchParams.get('agent_id') || requestUrl.searchParams.get('agentId'));
        const userId = asString(requestUrl.searchParams.get('user_id') || requestUrl.searchParams.get('userId'));
        if (!pointId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'point_id is empty' }));
          return;
        }

        const payload = await buildTyxtInteractiveDetailPayload(roomId, pointId, {
          agent_id: agentId || undefined,
          user_id: userId || undefined
        });
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, data: payload }));
      } catch (error) {
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        }));
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/gallery-photo') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const introKind = asString(requestUrl.searchParams.get('intro_kind') || requestUrl.searchParams.get('kind')).toLowerCase();
        const targetId = asString(requestUrl.searchParams.get('target_id') || requestUrl.searchParams.get('targetId'));
        const photoSlot = normalizePhotoSlot(requestUrl.searchParams.get('photo_slot') || requestUrl.searchParams.get('photoSlot'));
        if (introKind !== 'owner' && introKind !== 'agent') {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'intro_kind invalid' }));
          return;
        }
        if (introKind === 'agent' && !targetId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'target_id required' }));
          return;
        }

        const config = await readTyxtGalleryIntroConfig();
        const targetRow = introKind === 'owner'
          ? asRecord(config.owner)
          : asRecord(asRecord(config.agents)[targetId]);
        const photoPath = introKind === 'owner'
          ? (asString(targetRow.photo_path_primary) || asString(targetRow.photo_path))
          : (photoSlot === 'secondary'
            ? asString(targetRow.photo_path_secondary)
            : (asString(targetRow.photo_path_primary) || asString(targetRow.photo_path)));
        if (!photoPath) {
          res.statusCode = 404;
          res.end('');
          return;
        }

        const absPath = resolveTyxtPath(photoPath, TYXT_PROJECT_ROOT);
        const projectRoot = path.resolve(TYXT_PROJECT_ROOT);
        const normalizedPath = path.resolve(absPath);
        if (normalizedPath !== projectRoot && !normalizedPath.startsWith(`${projectRoot}${path.sep}`)) {
          res.statusCode = 403;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'photo path denied' }));
          return;
        }

        const binary = await fs.readFile(normalizedPath);
        res.statusCode = 200;
        res.setHeader('Content-Type', contentTypeForPath(normalizedPath));
        res.setHeader('Cache-Control', 'public, max-age=60');
        res.end(binary);
      } catch {
        res.statusCode = 404;
        res.end('');
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/gallery-photo-save') && req.method === 'POST') {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        const body = asRecord(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
        const introKind = asString(body.intro_kind || body.kind).toLowerCase();
        const targetId = asString(body.target_id || body.targetId);
        const photoSlot = normalizePhotoSlot(body.photo_slot || body.photoSlot);
        const mimeType = asString(body.mime_type || body.mimeType).toLowerCase();
        const fileName = asString(body.file_name || body.fileName);
        const dataBase64 = asString(body.data_base64 || body.base64);
        const userId = asString(body.user_id || body.userId);
        const nowIso = new Date().toISOString();

        if (introKind !== 'owner' && introKind !== 'agent') {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'intro_kind invalid' }));
          return;
        }
        if (introKind === 'agent' && !targetId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'target_id required for agent photo' }));
          return;
        }
        if (!dataBase64) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'data_base64 is empty' }));
          return;
        }

        const ext = resolveImageExtension(mimeType, fileName);
        const filePrefix = introKind === 'owner'
          ? 'owner'
          : `agent_${safeGalleryId(targetId, 'agent')}_${photoSlot}`;

        await fs.mkdir(TYXT_GALLERY_PHOTOS_ROOT, { recursive: true });
        const oldFiles = await fs.readdir(TYXT_GALLERY_PHOTOS_ROOT).catch(() => []);
        for (const oldName of oldFiles) {
          if (oldName.toLowerCase().startsWith(`${filePrefix.toLowerCase()}.`)) {
            await fs.unlink(path.join(TYXT_GALLERY_PHOTOS_ROOT, oldName)).catch(() => undefined);
          }
        }

        const binary = Buffer.from(dataBase64, 'base64');
        if (binary.length === 0 || binary.length > 12 * 1024 * 1024) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: '图片大小不合法（0~12MB）' }));
          return;
        }

        const outputName = `${filePrefix}${ext}`;
        const outputAbsPath = path.join(TYXT_GALLERY_PHOTOS_ROOT, outputName);
        await fs.writeFile(outputAbsPath, binary);

        const relPhotoPath = path.posix.join('configs', 'gallery_photos', outputName);
        const config = await readTyxtGalleryIntroConfig();
        if (introKind === 'owner') {
          config.owner = {
            ...asRecord(config.owner),
            photo_path: relPhotoPath,
            photo_path_primary: relPhotoPath,
            photo_updated_at: nowIso,
            photo_updated_at_primary: nowIso,
            updated_at: nowIso,
            updated_by: userId
          };
        } else {
          const agents = asRecord(config.agents);
          const current = asRecord(agents[targetId]);
          const nextAgent = {
            ...current,
            updated_at: nowIso,
            updated_by: userId
          } as Record<string, unknown>;
          if (photoSlot === 'secondary') {
            nextAgent.photo_path_secondary = relPhotoPath;
            nextAgent.photo_updated_at_secondary = nowIso;
          } else {
            nextAgent.photo_path = relPhotoPath;
            nextAgent.photo_path_primary = relPhotoPath;
            nextAgent.photo_updated_at = nowIso;
            nextAgent.photo_updated_at_primary = nowIso;
          }
          agents[targetId] = {
            ...nextAgent
          };
          config.agents = agents;
        }
        await writeTyxtGalleryIntroConfig(config);

        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: true,
          intro_kind: introKind,
          target_id: targetId || null,
          photo_slot: photoSlot,
          photo_url: galleryPhotoUrl(introKind as 'owner' | 'agent', targetId, nowIso, photoSlot),
          updated_at: nowIso
        }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        }));
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/gallery-photo-delete') && req.method === 'POST') {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        const body = asRecord(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
        const introKind = asString(body.intro_kind || body.kind).toLowerCase();
        const targetId = asString(body.target_id || body.targetId);
        const photoSlot = normalizePhotoSlot(body.photo_slot || body.photoSlot);
        const userId = asString(body.user_id || body.userId);
        const nowIso = new Date().toISOString();

        if (introKind !== 'owner' && introKind !== 'agent') {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'intro_kind invalid' }));
          return;
        }
        if (introKind === 'agent' && !targetId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'target_id required for agent photo' }));
          return;
        }

        const config = await readTyxtGalleryIntroConfig();
        const deleteFileSafely = async (relPath: string): Promise<void> => {
          const normalizedRelPath = asString(relPath);
          if (!normalizedRelPath) {
            return;
          }
          const absPath = resolveTyxtPath(normalizedRelPath, TYXT_PROJECT_ROOT);
          const projectRoot = path.resolve(TYXT_PROJECT_ROOT);
          const normalizedAbsPath = path.resolve(absPath);
          if (normalizedAbsPath !== projectRoot && !normalizedAbsPath.startsWith(`${projectRoot}${path.sep}`)) {
            return;
          }
          await fs.unlink(normalizedAbsPath).catch(() => undefined);
        };

        if (introKind === 'owner') {
          const owner = asRecord(config.owner);
          const toDelete = asString(owner.photo_path_primary) || asString(owner.photo_path);
          await deleteFileSafely(toDelete);
          config.owner = {
            ...owner,
            photo_path: '',
            photo_path_primary: '',
            photo_updated_at: nowIso,
            photo_updated_at_primary: nowIso,
            updated_at: nowIso,
            updated_by: userId
          };
        } else {
          const agents = asRecord(config.agents);
          const current = asRecord(agents[targetId]);
          const nextAgent = {
            ...current,
            updated_at: nowIso,
            updated_by: userId
          } as Record<string, unknown>;
          if (photoSlot === 'secondary') {
            await deleteFileSafely(asString(current.photo_path_secondary));
            nextAgent.photo_path_secondary = '';
            nextAgent.photo_updated_at_secondary = nowIso;
          } else {
            await deleteFileSafely(asString(current.photo_path_primary) || asString(current.photo_path));
            nextAgent.photo_path = '';
            nextAgent.photo_path_primary = '';
            nextAgent.photo_updated_at = nowIso;
            nextAgent.photo_updated_at_primary = nowIso;
          }
          agents[targetId] = { ...nextAgent };
          config.agents = agents;
        }

        await writeTyxtGalleryIntroConfig(config);

        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: true,
          intro_kind: introKind,
          target_id: targetId || null,
          photo_slot: photoSlot,
          updated_at: nowIso
        }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        }));
      }
      return;
    }

    if (req.url?.startsWith('/api/tyxt/gallery-intro-save') && req.method === 'POST') {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        const body = asRecord(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
        const introKind = asString(body.intro_kind || body.kind).toLowerCase();
        const targetId = asString(body.target_id || body.targetId);
        const text = String(body.text ?? '').trim();
        const userId = asString(body.user_id || body.userId);
        const nowIso = new Date().toISOString();

        if ((introKind !== 'owner' && introKind !== 'agent')) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'intro_kind invalid' }));
          return;
        }
        if (introKind === 'agent' && !targetId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'target_id required for agent intro' }));
          return;
        }

        const config = await readTyxtGalleryIntroConfig();
        if (introKind === 'owner') {
          const currentOwner = asRecord(config.owner);
          config.owner = {
            ...currentOwner,
            text,
            updated_at: nowIso,
            updated_by: userId
          };
        } else {
          const agents = asRecord(config.agents);
          const currentAgent = asRecord(agents[targetId]);
          agents[targetId] = {
            ...currentAgent,
            text,
            updated_at: nowIso,
            updated_by: userId
          };
          config.agents = agents;
        }

        await writeTyxtGalleryIntroConfig(config);

        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: true,
          intro_kind: introKind,
          target_id: targetId || null,
          text,
          updated_at: nowIso
        }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/open') && req.method === 'POST') {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
        const target = resolveOpenClawPath(body.openPath || body.path || '');
        if (!target) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'invalid path' }));
          return;
        }
        await new Promise<void>((resolve, reject) => {
          execFile('open', [target], (error) => {
            if (error) {
              reject(error);
              return;
            }
            resolve();
          });
        });
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: true }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/file') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const rawPath = requestUrl.searchParams.get('path') || '';
        const target = resolveOpenClawPath(rawPath);
        if (!target) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'invalid path' }));
          return;
        }
        const file = await fs.readFile(target);
        res.statusCode = 200;
        res.setHeader('Content-Type', contentTypeForPath(target));
        res.setHeader('Cache-Control', 'no-store');
        res.end(file);
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/preview') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const rawPath = requestUrl.searchParams.get('path') || '';
        const target = resolveOpenClawPath(rawPath);
        if (!target) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'invalid path' }));
          return;
        }

        const stat = await fs.stat(target);
        if (stat.isDirectory()) {
          res.statusCode = 200;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.setHeader('Cache-Control', 'no-store');
          res.end(JSON.stringify(await buildDirectoryPreview(target, rawPath)));
          return;
        }

        const ext = path.extname(target).toLowerCase();
        const kind = previewKindForPath(target) ?? 'text';
        const requestedMode = TAIL_PREVIEW_EXTENSIONS.has(ext) ? 'tail' : 'head';
        const preview = await readTextPreview(target, requestedMode);
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({
          ok: true,
          kind,
          path: rawPath,
          contentType: contentTypeForPath(target),
          content: formatPreviewContent(kind, preview.content),
          truncated: preview.truncated,
          readMode: preview.readMode
        }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/resource') && req.method === 'GET') {
      try {
        const requestUrl = new URL(req.url, 'http://127.0.0.1');
        const wantsMock = requestUrl.searchParams.get('mock') === '1';
        const resourceId = requestUrl.searchParams.get('resourceId') || '';
        if (!resourceId) {
          res.statusCode = 400;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'missing resourceId' }));
          return;
        }

        let snapshot: CachedSnapshot;
        if (wantsMock) {
          snapshot = await createOpenClawSnapshot({
            mock: true,
            itemResourceIds: resourceId === 'gateway' ? ['gateway', 'task_queues'] : [resourceId],
            includeExcerpt: false
          });
        } else {
          snapshot = await getLiveDetailSnapshot(resourceId);
        }

        const resource = findSnapshotResource(snapshot, resourceId);
        if (!resource) {
          res.statusCode = 404;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify({ ok: false, error: 'resource not found' }));
          return;
        }

        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, resource }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/agent-focus') && req.method === 'GET') {
      try {
        // Read all focus-*.json files from ~/.openclaw/subagents/
        const subagentsDir = path.join(clawlibraryConfig.openclaw.home, 'subagents');
        type FocusEntry = { runId: string; resourceId: string; detail?: string };
        const focuses: FocusEntry[] = [];
        try {
          const entries = await fs.readdir(subagentsDir);
          const focusFiles = entries.filter((f) => f.startsWith('focus-') && f.endsWith('.json'));
          for (const file of focusFiles) {
            try {
              const raw = await fs.readFile(path.join(subagentsDir, file), 'utf8');
              const data = JSON.parse(raw) as { resourceId?: string; detail?: string; label?: string };
              if (data.resourceId) {
                const runId = file.replace(/^focus-/, '').replace(/\.json$/, '');
                const entry: FocusEntry = { runId, resourceId: data.resourceId, detail: data.detail };
                focuses.push(entry);
                // Also register under label if present (so label-based focus files match subagent ids)
                if (data.label) {
                  focuses.push({ runId: data.label, resourceId: data.resourceId, detail: data.detail });
                }
              }
            } catch { /* skip malformed */ }
          }
        } catch { /* dir doesn't exist */ }
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, focuses }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/processes') && req.method === 'GET') {
      try {
        // Read the exec-processes registry written by ClawBot when launching background agents
        const registryPath = path.join(clawlibraryConfig.openclaw.home, 'exec-processes.json');
        type ProcessEntry = { id: string; label: string; command: string; status: string; startedAt?: string };
        let processes: ProcessEntry[] = [];
        try {
          const raw = await fs.readFile(registryPath, 'utf8');
          const all = JSON.parse(raw) as ProcessEntry[];
          processes = all.filter((p) => p.status === 'running');
        } catch {
          // file doesn't exist — return empty list
        }
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, processes }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (req.url?.startsWith('/api/openclaw/chat') && req.method === 'GET') {
      try {
        const messages = await readChatMessages();
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(JSON.stringify({ ok: true, messages }));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
      }
      return;
    }

    if (!req.url?.startsWith('/api/openclaw/snapshot')) {
      next();
      return;
    }

    try {
      const requestUrl = new URL(req.url, 'http://127.0.0.1');
      const wantsMock = requestUrl.searchParams.get('mock') === '1';
      let snapshot: CachedSnapshot;
      if (wantsMock) {
        snapshot = await createOpenClawSnapshot({ mock: true, includeItems: false });
      } else {
        await loadCachedLiveOverview();
        if (cachedLiveOverview && cachedSnapshotAgeMs(cachedLiveOverview) < LIVE_OVERVIEW_CACHE_TTL_MS) {
          snapshot = cachedLiveOverview;
        } else if (cachedLiveOverview) {
          void refreshLiveOverview();
          snapshot = cachedLiveOverview;
        } else {
          snapshot = await refreshLiveOverview();
        }
      }
      // Override focus with main session auto-focus if available and recent
      let overriddenSnapshot = snapshot;
      if (!wantsMock) {
        try {
          const mainFocusPath = path.join(clawlibraryConfig.openclaw.home, 'subagents', 'focus-main.json');
          const mainFocusStat = await fs.stat(mainFocusPath).catch(() => null);
          if (mainFocusStat && (Date.now() - mainFocusStat.mtimeMs) < 90_000) {
            const mainFocusRaw = await fs.readFile(mainFocusPath, 'utf8');
            const mainFocus = JSON.parse(mainFocusRaw) as { resourceId?: string; detail?: string; _isMain?: boolean };
            if (mainFocus._isMain && mainFocus.detail) {
              overriddenSnapshot = {
                ...snapshot,
                focus: {
                  ...snapshot.focus,
                  resourceId: mainFocus.resourceId || snapshot.focus.resourceId,
                  detail: mainFocus.detail,
                  reason: 'main session active'
                }
              };
            }
          }
        } catch { /* best-effort: fall through to original snapshot */ }
      }

      res.statusCode = 200;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Cache-Control', 'no-store');
      res.end(JSON.stringify(wantsMock ? snapshot : {
        ...overriddenSnapshot,
        resources: overriddenSnapshot.resources.map(({ items, ...resource }) => resource)
      }));
    } catch (error) {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
    }
  };
}

// ── Live Chat endpoint ──────────────────────────────────────────────────────

const SESSIONS_DIR = path.join(clawlibraryConfig.openclaw.home, 'agents', 'main', 'sessions');
const CHAT_MAX_MESSAGES = 30;

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  senderName: string;
  timestamp: string;
}

function extractSenderName(rawText: string): string {
  // Parse the Sender (untrusted metadata) block for "name" field
  const match = rawText.match(/Sender \(untrusted metadata\)[^`]*```json\s*(\{[^`]+\})/);
  if (match) {
    try {
      const parsed = JSON.parse(match[1]) as Record<string, string>;
      const full = parsed.name || parsed.label || '';
      // Truncate to first name only (up to first space)
      const firstName = full.split(' ')[0];
      if (firstName) return firstName;
    } catch { /* ignore */ }
  }
  return 'User';
}

function cleanUserText(rawText: string): string {
  // Remove Conversation info block
  let text = rawText.replace(/Conversation info \(untrusted metadata\)[^\n]*\n```json[\s\S]*?```\n?/g, '');
  // Remove Sender block
  text = text.replace(/Sender \(untrusted metadata\)[^\n]*\n```json[\s\S]*?```\n?/g, '');
  // Remove Replied message block
  text = text.replace(/Replied message \(untrusted, for context\)[^\n]*\n```json[\s\S]*?```\n?/g, '');
  // Remove To send an image back instructions
  text = text.replace(/To send an image back[^\n]*\n?/g, '');
  // Remove System: lines
  text = text.replace(/^System:.*$/gm, '');
  // Remove [Queued messages while agent was busy] wrapper
  text = text.replace(/\[Queued messages while agent was busy\][\s\S]*?---\s*Queued #\d+\s*/g, '');
  // Remove [media attached: ...] lines
  text = text.replace(/\[media attached:[^\]]*\]\s*/g, '');
  // Mark <media:audio> tags as placeholder (will be replaced by transcription)
  text = text.replace(/<media:[^>]+>/g, '[audio]');
  // If only media attachment line was present, mark as audio too
  if (!text && rawText.includes('media attached')) text = '[audio]';
  return text.trim();
}

function extractSonioxTranscription(toolResultText: string): string | null {
  // Try each { ... } block by finding balanced braces
  let i = 0;
  while (i < toolResultText.length) {
    const start = toolResultText.indexOf('{', i);
    if (start === -1) break;
    let depth = 0;
    let end = -1;
    for (let k = start; k < toolResultText.length; k++) {
      if (toolResultText[k] === '{') depth++;
      else if (toolResultText[k] === '}') {
        depth--;
        if (depth === 0) { end = k; break; }
      }
    }
    if (end === -1) break;
    const jsonStr = toolResultText.slice(start, end + 1);
    try {
      const parsed = JSON.parse(jsonStr) as Record<string, unknown>;
      // Soniox transcript response has "text" (string) + "tokens" (array) + "id"
      if (
        typeof parsed.text === 'string' &&
        parsed.text.trim().length > 5 &&
        (Array.isArray(parsed.tokens) || typeof parsed.id === 'string')
      ) {
        return parsed.text.trim();
      }
    } catch { /* skip */ }
    i = end + 1;
  }
  return null;
}

async function readChatMessages(): Promise<ChatMessage[]> {
  let files: string[] = [];
  try {
    const entries = await fs.readdir(SESSIONS_DIR);
    files = entries
      .filter((f) => f.endsWith('.jsonl') && !f.includes('.reset') && !f.includes('.deleted'))
      .map((f) => path.join(SESSIONS_DIR, f));
  } catch { return []; }

  if (files.length === 0) return [];

  // Find most recently modified session file
  const stats = await Promise.all(files.map(async (f) => ({ f, mtime: (await fs.stat(f)).mtimeMs })));
  stats.sort((a, b) => b.mtime - a.mtime);
  const activeFile = stats[0].f;

  const raw = await fs.readFile(activeFile, 'utf8');
  const lines = raw.split('\n').filter(Boolean);

  // Parse all entries first so we can look ahead for transcriptions
  type Entry = {
    timestamp?: string;
    message?: { role?: string; content?: unknown; toolCallId?: string };
  };
  const entries: Entry[] = [];
  for (const line of lines) {
    try { entries.push(JSON.parse(line) as Entry); } catch { /* skip */ }
  }

  const messages: ChatMessage[] = [];

  for (let i = 0; i < entries.length; i++) {
    const obj = entries[i];
    const msg = obj.message;
    if (!msg) continue;
    const role = msg.role;
    if (role !== 'user' && role !== 'assistant') continue;

    let rawText = '';
    const content = msg.content;
    if (typeof content === 'string') {
      rawText = content;
    } else if (Array.isArray(content)) {
      for (const c of content as Array<{ type?: string; text?: string }>) {
        if (c.type === 'text' && c.text) { rawText = c.text; break; }
      }
    }
    if (!rawText.trim()) continue;

    if (role === 'user') {
      const senderName = extractSenderName(rawText);
      let text = cleanUserText(rawText);
      if (!text) continue;

      // If message had audio, look ahead for Soniox transcription in toolResults
      if (text.includes('[audio]')) {
        for (let j = i + 1; j < Math.min(i + 25, entries.length); j++) {
          const nextMsg = entries[j].message;
          if (!nextMsg) continue;
          // Stop if we hit another user message
          if (nextMsg.role === 'user') break;

          if (nextMsg.role === 'toolResult') {
            const nc = nextMsg.content;
            const toolTexts: string[] = [];
            if (Array.isArray(nc)) {
              for (const c of nc as Array<{ type?: string; text?: string }>) {
                if (c.type === 'text' && c.text) toolTexts.push(c.text);
              }
            } else if (typeof nc === 'string') {
              toolTexts.push(nc);
            }

            for (const t of toolTexts) {
              // Strategy 1: structured Soniox JSON with "text" + "tokens"/"id"
              const structured = extractSonioxTranscription(t);
              if (structured) {
                text = text.replace('[audio]', `🎙 "${structured}"`);
                break;
              }
              // Strategy 2: plain text toolResult that looks like a transcription
              // (non-empty, no shell output markers, reasonable length, not a path/error)
              const trimmed = t.trim();
              if (
                trimmed.length > 10 &&
                trimmed.length < 1000 &&
                !trimmed.startsWith('{') &&
                !trimmed.startsWith('/') &&
                !trimmed.includes('FILE_ID') &&
                !trimmed.includes('TX_ID') &&
                !trimmed.includes('Successfully') &&
                !trimmed.includes('\n') // single line = likely transcription
              ) {
                text = text.replace('[audio]', `🎙 "${trimmed}"`);
                break;
              }
            }
            if (!text.includes('[audio]')) break;
          }
        }
      }

      messages.push({ role: 'user', text, senderName, timestamp: obj.timestamp ?? '' });
    } else {
      const text = rawText.trim();
      if (!text) continue;
      messages.push({ role: 'assistant', text, senderName: 'ClawBot', timestamp: obj.timestamp ?? '' });
    }
  }

  // Return last N messages
  return messages.slice(-CHAT_MAX_MESSAGES);
}

export default defineConfig({
  plugins: [
    {
      name: 'openclaw-telemetry-bridge',
      configureServer(server) {
        server.middlewares.use(telemetryMiddleware());
      },
      configurePreviewServer(server) {
        server.middlewares.use(telemetryMiddleware());
      }
    }
  ],
  build: {
    emptyOutDir: false
  },
  server: {
    host: clawlibraryConfig.server.host,
    port: clawlibraryConfig.server.port,
    strictPort: true,
    allowedHosts: 'all'
  }
});



