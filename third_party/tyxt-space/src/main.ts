import Phaser from 'phaser';
import appConfig from '../clawlibrary.config.json';
import type { ResourcePartitionId } from './core/types';
import { LibraryScene } from './runtime/scene/LibraryScene';
import {
  buildLegacySceneSnapshot,
  createTyxtMockHomeData,
  getTyxtRoomProfile,
  listTyxtInteractiveHotspots,
  loadTyxtAgentRegistry,
  mapLegacyResourceToTyxtRoom,
  type TyxtAgentRegistry,
  type TyxtHomeData,
  type TyxtInteractivePoint,
  type TyxtQuickActionId,
  type TyxtRoomId,
  type TyxtStatus
} from './adapters/tyxtAdapter';

const BASE_WIDTH = 1920;
const BASE_HEIGHT = 1080;
const DATA_REFRESH_MS = Math.max(2200, appConfig.telemetry.pollMs);
const ROOM_STORAGE_KEY = 'tyxt-space-active-room-v1';
const AGENT_STORAGE_KEY = 'tyxt-space-selected-agent-v1';
const CHAT_ENTRY_STORAGE_KEY = 'tyxt-space-chat-entry-v1';
const CHAT_WINDOW_NAME = 'tyxt-space-chat-webui';
const WEBUI_FOCUS_CHANNEL_NAME = 'tyxt-webui-focus-v1';
const WEBUI_PING_TIMEOUT_MS = 320;
const HEADER_STATUS_REFRESH_MS = 60_000;
const HEADER_STATUS_USER_STORAGE_KEY = 'tyxt-space-header-user-id-v1';
const HEADER_STATUS_AUTH_TOKEN_STORAGE_KEY = 'tyxt-space-header-auth-token-v1';

type TyxtChatEntryKind = 'private' | 'group' | 'theater';

type TyxtChatEntryConfig = Record<TyxtChatEntryKind, string>;

type WebUiFocusMessage =
  | {
      type: 'tyxt_webui_ping';
      requestId: string;
      kind: TyxtChatEntryKind;
      targetUrl: string;
      issuedAt: number;
    }
  | {
      type: 'tyxt_webui_pong';
      requestId: string;
      tabId: string;
      issuedAt: number;
    }
  | {
      type: 'tyxt_webui_activate';
      requestId: string;
      tabId: string;
      kind: TyxtChatEntryKind;
      targetUrl: string;
      issuedAt: number;
    };

const CHAT_ENTRY_QUERY_KEYS: Record<TyxtChatEntryKind, string> = {
  private: 'tyxtPrivateUrl',
  group: 'tyxtGroupUrl',
  theater: 'tyxtTheaterUrl'
};

const CHAT_ENTRY_DEFAULTS: TyxtChatEntryConfig = {
  private: 'https://127.0.0.1:5000/',
  group: 'https://127.0.0.1:5000/?entry=group',
  theater: 'https://127.0.0.1:5000/?entry=theater'
};

const VALID_ROOM_IDS: TyxtRoomId[] = [
  'main_hall',
  'study',
  'workshop',
  'theater',
  'observatory',
  'message_wall',
  'gallery'
];

const VALID_LEGACY_RESOURCE_IDS = new Set<ResourcePartitionId>([
  'document',
  'images',
  'memory',
  'skills',
  'gateway',
  'log',
  'mcp',
  'schedule',
  'alarm',
  'agent',
  'task_queues',
  'break_room'
]);

const ROOM_ICON_MAP: Record<string, string> = {
  home: 'MH',
  book: 'ST',
  tool: 'WS',
  mask: 'TH',
  eye: 'OB',
  message: 'MW',
  image: 'GL'
};

const scene = new LibraryScene();

await loadUiFonts();

const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: 'app',
  transparent: true,
  audio: {
    context: (() => {
      const context = new (window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)();
      const resume = () => {
        void context.resume();
      };
      window.addEventListener('pointerdown', resume, { once: true });
      return context;
    })()
  },
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_HORIZONTALLY,
    width: BASE_WIDTH,
    height: BASE_HEIGHT
  },
  input: {
    activePointers: 3
  },
  scene: [scene]
});

type SceneSelectPayload = {
  resourceId?: string;
};

type TyxtHeaderStatusSnapshot = {
  backend: TyxtStatus;
  weatherText: string;
  weatherTone: TyxtStatus;
  loadedAt: string | null;
};

type TyxtHeaderStatusApiPayload = {
  ok?: boolean;
  backend?: unknown;
  weather_text?: unknown;
  weather_state?: unknown;
  fetched_at?: unknown;
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

type TyxtInteractionProfileItem = {
  id?: string;
  name: string;
  subtitle?: string;
  text: string;
  photo_label: string;
  photo_url?: string;
  photo_url_secondary?: string;
};

type GalleryPhotoSlot = 'primary' | 'secondary';

type TyxtInteractionProfilesSection = {
  kind: 'profiles';
  label: string;
  items: TyxtInteractionProfileItem[];
};

type TyxtInteractionSection =
  | TyxtInteractionMetricSection
  | TyxtInteractionListSection
  | TyxtInteractionLogSection
  | TyxtInteractionProfilesSection;

type TyxtInteractionPayload = {
  room_id: TyxtRoomId;
  point_id: string;
  title: string;
  summary: string;
  sections: TyxtInteractionSection[];
  updated_at: string;
};

type TyxtInteractionApiPayload = {
  ok?: boolean;
  data?: TyxtInteractionPayload;
  error?: string;
};

type AppState = {
  activeRoomId: TyxtRoomId;
  selectedAgentId: string | null;
  tick: number;
  data: TyxtHomeData | null;
  sceneBound: boolean;
  spawnedAgentIds: Set<string>;
  modeNote: string;
  agentRegistry: TyxtAgentRegistry | null;
  headerStatus: TyxtHeaderStatusSnapshot;
  headerUserId: string | null;
  headerAuthToken: string | null;
  selectedHotspotId: string | null;
  interactionPanel: TyxtInteractionPayload | null;
  interactionLoading: boolean;
  interactionError: string | null;
  gallerySelectedProfileId: string | null;
  galleryDraftById: Record<string, string>;
  gallerySaving: boolean;
  galleryMessage: string | null;
  galleryMessageTone: 'ok' | 'error' | 'info' | null;
};

const state: AppState = {
  activeRoomId: loadStoredRoom(),
  selectedAgentId: loadStoredAgent(),
  tick: 0,
  data: null,
  sceneBound: false,
  spawnedAgentIds: new Set<string>(),
  modeNote: 'TYXT local mock',
  agentRegistry: null,
  headerStatus: {
    backend: 'partial',
    weatherText: '读取中',
    weatherTone: 'standby',
    loadedAt: null
  },
  headerUserId: loadStoredHeaderStatusUserId(),
  headerAuthToken: loadStoredHeaderStatusAuthToken(),
  selectedHotspotId: null,
  interactionPanel: null,
  interactionLoading: false,
  interactionError: null,
  gallerySelectedProfileId: null,
  galleryDraftById: {},
  gallerySaving: false,
  galleryMessage: null,
  galleryMessageTone: null
};

const dom = {
  headerSpaceName: byId<HTMLElement>('header-space-name'),
  headerSpaceDesc: byId<HTMLElement>('header-space-desc'),
  roomNavList: byId<HTMLElement>('room-nav-list'),
  hotspotList: byId<HTMLElement>('interactive-hotspots'),
  roomSummary: byId<HTMLElement>('room-summary'),
  agentOverview: byId<HTMLElement>('agent-overview'),
  systemStatus: byId<HTMLElement>('system-status'),
  recentEvents: byId<HTMLElement>('recent-events'),
  quickActions: byId<HTMLElement>('quick-actions'),
  interactionPanel: byId<HTMLElement>('interaction-panel'),
  interactionDisplay: byId<HTMLElement>('interaction-display')
};

bindDomEvents();
void refreshAgentRegistry();
void refreshHeaderStatus();
refreshPage();

window.setInterval(() => {
  state.tick += 1;
  refreshPage();
}, DATA_REFRESH_MS);

window.setInterval(() => {
  void refreshAgentRegistry();
}, 20_000);

window.setInterval(() => {
  void refreshHeaderStatus();
}, HEADER_STATUS_REFRESH_MS);

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing required element: #${id}`);
  }
  return element as T;
}

async function loadUiFonts(): Promise<void> {
  if (!('fonts' in document)) {
    return;
  }
  await Promise.allSettled([
    document.fonts.load('400 20px "VT323"')
  ]);
}

async function refreshAgentRegistry(): Promise<void> {
  const registry = await loadTyxtAgentRegistry();
  if (!registry || registry.agents.length === 0) {
    return;
  }

  const previousDefaultAgentId = state.agentRegistry?.default_agent_id ?? null;
  state.agentRegistry = registry;

  const selectedAgentStillValid = !!state.selectedAgentId
    && registry.agents.some((agent) => agent.agent_id === state.selectedAgentId);

  if (!selectedAgentStillValid) {
    state.selectedAgentId = registry.default_agent_id ?? registry.agents[0]?.agent_id ?? null;
  }

  const defaultChanged = previousDefaultAgentId !== registry.default_agent_id;
  if (defaultChanged) {
    state.modeNote = 'Synced project agent registry.';
    refreshPage();
  }
}

async function refreshHeaderStatus(): Promise<void> {
  const fallbackBackend = state.data?.system_status.backend ?? state.headerStatus.backend;

  try {
    const params = new URLSearchParams();
    params.set('t', String(Date.now()));
    if (state.headerUserId) {
      params.set('user_id', state.headerUserId);
    }
    const headers: Record<string, string> = {};
    if (state.headerAuthToken) {
      headers['X-TYXT-Auth-Token'] = state.headerAuthToken;
    }

    const response = await fetch(`/api/tyxt/header-status?${params.toString()}`, {
      method: 'GET',
      cache: 'no-store',
      headers
    });
    if (!response.ok) {
      throw new Error(`header-status ${response.status}`);
    }

    const payload = await response.json() as TyxtHeaderStatusApiPayload;
    state.headerStatus = {
      backend: normalizeTyxtStatus(payload.backend, fallbackBackend),
      weatherText: normalizeWeatherText(payload.weather_text),
      weatherTone: normalizeTyxtStatus(payload.weather_state, 'standby'),
      loadedAt: new Date().toISOString()
    };
  } catch {
    state.headerStatus = {
      backend: fallbackBackend,
      weatherText: state.headerStatus.weatherText || '天气读取失败',
      weatherTone: state.headerStatus.weatherTone,
      loadedAt: state.headerStatus.loadedAt
    };
  }

  refreshPage();
}

function normalizeTyxtStatus(value: unknown, fallback: TyxtStatus): TyxtStatus {
  if (value === 'online' || value === 'offline' || value === 'partial' || value === 'ready' || value === 'running' || value === 'standby') {
    return value;
  }
  return fallback;
}

function normalizeWeatherText(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : '';
  return text || '未设置';
}

function loadStoredHeaderStatusUserId(): string | null {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = String(
      params.get('user_id')
      || params.get('userId')
      || params.get('tyxt_user_id')
      || ''
    ).trim();
    if (fromQuery) {
      window.localStorage.setItem(HEADER_STATUS_USER_STORAGE_KEY, fromQuery);
      return fromQuery;
    }
    return window.localStorage.getItem(HEADER_STATUS_USER_STORAGE_KEY);
  } catch {
    return null;
  }
}

function loadStoredHeaderStatusAuthToken(): string | null {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = String(
      params.get('tyxt_auth_token')
      || params.get('mobile_auth_token')
      || params.get('x_tyxt_auth_token')
      || ''
    ).trim();
    if (fromQuery) {
      window.localStorage.setItem(HEADER_STATUS_AUTH_TOKEN_STORAGE_KEY, fromQuery);
      return fromQuery;
    }
    return window.localStorage.getItem(HEADER_STATUS_AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function loadStoredRoom(): TyxtRoomId {
  try {
    const saved = window.localStorage.getItem(ROOM_STORAGE_KEY);
    if (saved && VALID_ROOM_IDS.includes(saved as TyxtRoomId)) {
      return saved as TyxtRoomId;
    }
  } catch {
    // ignore storage failures
  }
  return 'main_hall';
}

function loadStoredAgent(): string | null {
  try {
    return window.localStorage.getItem(AGENT_STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveStoredRoom(roomId: TyxtRoomId): void {
  try {
    window.localStorage.setItem(ROOM_STORAGE_KEY, roomId);
  } catch {
    // ignore storage failures
  }
}

function saveStoredAgent(agentId: string | null): void {
  try {
    if (!agentId) {
      window.localStorage.removeItem(AGENT_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(AGENT_STORAGE_KEY, agentId);
  } catch {
    // ignore storage failures
  }
}

function loadStoredChatEntryConfig(): Partial<TyxtChatEntryConfig> {
  try {
    const raw = window.localStorage.getItem(CHAT_ENTRY_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as Partial<TyxtChatEntryConfig>;
    return typeof parsed === 'object' && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function resolveTyxtChatEntryUrl(kind: TyxtChatEntryKind): string {
  const params = new URLSearchParams(window.location.search);
  const queryKey = CHAT_ENTRY_QUERY_KEYS[kind];
  const fromQuery = normalizeChatUrl(params.get(queryKey));
  if (fromQuery) {
    return fromQuery;
  }

  const stored = loadStoredChatEntryConfig();
  const fromStorage = normalizeChatUrl(stored[kind]);
  if (fromStorage) {
    return fromStorage;
  }

  return CHAT_ENTRY_DEFAULTS[kind];
}

function normalizeChatUrl(value: string | null | undefined): string | null {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) {
    return null;
  }

  try {
    const withProtocol = /^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(text)
      ? text
      : `https://${text}`;
    const parsed = new URL(withProtocol);
    if (parsed.protocol === 'http:') {
      parsed.protocol = 'https:';
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function focusExistingWebUiTab(kind: TyxtChatEntryKind, targetUrl: string): Promise<boolean> {
  if (typeof BroadcastChannel === 'undefined') {
    return Promise.resolve(false);
  }

  return new Promise<boolean>((resolve) => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let channel: BroadcastChannel | null = null;
    let timerId = 0;
    let settled = false;

    const finish = (focused: boolean) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timerId) {
        window.clearTimeout(timerId);
      }
      if (channel) {
        try {
          channel.close();
        } catch {
          // Ignore channel close errors.
        }
      }
      resolve(focused);
    };

    try {
      channel = new BroadcastChannel(WEBUI_FOCUS_CHANNEL_NAME);
    } catch {
      finish(false);
      return;
    }

    channel.onmessage = (event: MessageEvent<WebUiFocusMessage>) => {
      const payload = event.data;
      if (!payload || payload.type !== 'tyxt_webui_pong' || payload.requestId !== requestId) {
        return;
      }
      const tabId = typeof payload.tabId === 'string' ? payload.tabId.trim() : '';
      if (!tabId) {
        return;
      }
      try {
        channel?.postMessage({
          type: 'tyxt_webui_activate',
          requestId,
          tabId,
          kind,
          targetUrl,
          issuedAt: Date.now()
        } satisfies WebUiFocusMessage);
      } catch {
        // Ignore send failure and continue fallback.
      }
      finish(true);
    };

    timerId = window.setTimeout(() => finish(false), WEBUI_PING_TIMEOUT_MS);
    try {
      channel.postMessage({
        type: 'tyxt_webui_ping',
        requestId,
        kind,
        targetUrl,
        issuedAt: Date.now()
      } satisfies WebUiFocusMessage);
    } catch {
      finish(false);
    }
  });
}

async function openTyxtChat(kind: TyxtChatEntryKind, modeNote: string): Promise<void> {
  const targetUrl = resolveTyxtChatEntryUrl(kind);
  state.modeNote = modeNote;
  refreshPage();

  const focusedExisting = await focusExistingWebUiTab(kind, targetUrl);
  if (focusedExisting) {
    return;
  }

  const popup = window.open(targetUrl, CHAT_WINDOW_NAME);
  if (popup && !popup.closed) {
    popup.focus();
    return;
  }

  window.location.assign(targetUrl);
}

function refreshPage(): void {
  const nextData = createTyxtMockHomeData({
    activeRoomId: state.activeRoomId,
    selectedAgentId: state.selectedAgentId,
    tick: state.tick,
    agentRegistry: state.agentRegistry
  });

  state.data = nextData;
  state.selectedAgentId = nextData.selected_agent_id;
  saveStoredRoom(state.activeRoomId);
  saveStoredAgent(state.selectedAgentId);

  renderHeader(nextData);
  renderRoomNavigation(nextData);
  renderHotspots(nextData);
  ensureActiveHotspot(nextData);
  renderRoomSummary(nextData);
  renderAgents(nextData);
  renderSystemStatus(nextData);
  renderRecentEvents(nextData);
  renderQuickActions(nextData);
  renderInteractionPanel();
  syncScene(nextData);
}

function renderHeader(data: TyxtHomeData): void {
  dom.headerSpaceName.textContent = `TYXT 可视化空间 · ${data.space.name}`;
  dom.headerSpaceDesc.textContent = data.space.description;
}

function renderRoomNavigation(data: TyxtHomeData): void {
  dom.roomNavList.innerHTML = data.rooms.map((room) => {
    const icon = ROOM_ICON_MAP[room.icon] ?? room.name.slice(0, 2);
    const isActive = room.id === state.activeRoomId;
    return `
      <button class="room-nav-item" type="button" data-room-id="${room.id}" data-active="${isActive ? 'true' : 'false'}">
        <span class="room-nav-icon">${escapeHtml(icon)}</span>
        <span class="room-nav-name">${escapeHtml(room.name)}</span>
      </button>
    `;
  }).join('');
}

function renderHotspots(data: TyxtHomeData): void {
  const hotspots = hotspotsForRoom(data.space.id);
  dom.hotspotList.innerHTML = hotspots.map((point) => `
    <button
      class="hotspot-item"
      type="button"
      data-point-id="${point.id}"
      data-active="${point.id === state.selectedHotspotId ? 'true' : 'false'}"
    >
      <strong>${escapeHtml(point.label)}</strong>
      <span>${escapeHtml(point.detail)}</span>
    </button>
  `).join('');
}

function hotspotsForRoom(roomId: TyxtRoomId): TyxtInteractivePoint[] {
  return listTyxtInteractiveHotspots(roomId);
}

function ensureActiveHotspot(data: TyxtHomeData): void {
  const hotspots = hotspotsForRoom(data.space.id);
  if (hotspots.length === 0) {
    state.selectedHotspotId = null;
    state.interactionPanel = null;
    state.interactionLoading = false;
    state.interactionError = null;
    return;
  }

  const selectedExists = !!state.selectedHotspotId && hotspots.some((point) => point.id === state.selectedHotspotId);
  if (!selectedExists) {
    const firstPoint = hotspots[0];
    state.selectedHotspotId = firstPoint.id;
    state.interactionPanel = null;
    state.interactionError = null;
    void loadInteractionPanel(data.space.id, firstPoint);
    return;
  }

  if (state.interactionPanel
    && (state.interactionPanel.room_id !== data.space.id || state.interactionPanel.point_id !== state.selectedHotspotId)
  ) {
    state.interactionPanel = null;
  }
}

function renderRoomSummary(data: TyxtHomeData): void {
  const profile = getTyxtRoomProfile(data.space.id);
  dom.roomSummary.textContent = `${profile.title}。${profile.description} 当前状态：${profile.status_hint}`;
}

function renderAgents(data: TyxtHomeData): void {
  dom.agentOverview.innerHTML = data.agents.map((agent) => {
    const isSelected = agent.agent_id === state.selectedAgentId;
    return `
      <button class="agent-item" type="button" data-agent-id="${agent.agent_id}" data-active="${isSelected ? 'true' : 'false'}">
        <strong>${escapeHtml(agent.display_name)}</strong>
        <div>${displayAgentStatus(agent.status)} · ${displayMood(agent.mood)} · ${escapeHtml(roomDisplayName(data, agent.current_room))}</div>
      </button>
    `;
  }).join('');
}

function renderSystemStatus(data: TyxtHomeData): void {
  const backendStatus = state.headerStatus.backend || data.system_status.backend;
  const entries: Array<{ label: string; valueText: string; tone: TyxtStatus }> = [
    {
      label: '后端健康',
      valueText: displayStatus(backendStatus),
      tone: backendStatus
    },
    {
      label: '天气预报',
      valueText: state.headerStatus.weatherText,
      tone: state.headerStatus.weatherTone
    }
  ];

  dom.systemStatus.innerHTML = entries.map((entry) => `
    <div class="status-row">
      <span>${escapeHtml(entry.label)}</span>
      <strong class="${statusToneClass(entry.tone)}">${escapeHtml(entry.valueText)}</strong>
    </div>
  `).join('');
}

function renderRecentEvents(data: TyxtHomeData): void {
  if (data.events.length === 0) {
    dom.recentEvents.innerHTML = '<div class="event-item">暂无事件</div>';
    return;
  }

  dom.recentEvents.innerHTML = data.events.map((event) => `
    <div class="event-item">
      <strong>${escapeHtml(event.title)}</strong>
      <div>${escapeHtml(event.detail)}</div>
      <div>${escapeHtml(roomDisplayName(data, event.room_id))} · ${escapeHtml(formatClock(event.occurred_at))}</div>
    </div>
  `).join('');
}

function renderQuickActions(data: TyxtHomeData): void {
  dom.quickActions.innerHTML = data.quick_actions.map((action) => `
    <button class="quick-action-item" type="button" data-action-id="${action.id}">
      <strong>${escapeHtml(action.label)}</strong>
      <span>${escapeHtml(action.hint)}</span>
    </button>
  `).join('');
}

function renderInteractionPanel(): void {
  if (state.interactionLoading) {
    applyInteractionPanelScrollMode(null);
    dom.interactionDisplay.innerHTML = '<div class="interaction-loading">正在加载交互内容...</div>';
    return;
  }

  if (state.interactionError) {
    applyInteractionPanelScrollMode(null);
    dom.interactionDisplay.innerHTML = `<div class="interaction-error">${escapeHtml(state.interactionError)}</div>`;
    return;
  }

  const payload = state.interactionPanel;
  if (!payload) {
    applyInteractionPanelScrollMode(null);
    dom.interactionDisplay.innerHTML = '<div class="interaction-empty">点击左侧「空间交互点」查看对应内容。</div>';
    return;
  }

  applyInteractionPanelScrollMode(payload);

  if (payload.room_id === 'gallery') {
    dom.interactionDisplay.innerHTML = renderGalleryPanel(payload);
    scheduleGalleryPhotoWallSizing();
    return;
  }

  if (shouldRenderSplitLayout(payload)) {
    dom.interactionDisplay.innerHTML = renderSplitPanel(payload);
    return;
  }

  const sectionsHtml = payload.sections.map((section) => renderInteractionSection(section)).join('');
  dom.interactionDisplay.innerHTML = `
    <h3 class="interaction-title">${escapeHtml(compactInteractionTitle(payload.title))}</h3>
    <div class="interaction-sections">
      ${sectionsHtml || '<div class="interaction-empty">暂无展示内容。</div>'}
    </div>
  `;
}

let galleryPhotoWallResizeRaf = 0;

function scheduleGalleryPhotoWallSizing(): void {
  if (galleryPhotoWallResizeRaf) {
    window.cancelAnimationFrame(galleryPhotoWallResizeRaf);
  }
  galleryPhotoWallResizeRaf = window.requestAnimationFrame(() => {
    galleryPhotoWallResizeRaf = 0;
    resizeGalleryPhotoWalls();
  });
}

function resizeGalleryPhotoWalls(): void {
  const walls = dom.interactionDisplay.querySelectorAll<HTMLElement>('.gallery-photo-wall');
  if (walls.length === 0) {
    return;
  }
  const rootStyle = window.getComputedStyle(document.documentElement);
  const unifiedFrameHeight = Number.parseFloat(rootStyle.getPropertyValue('--gallery-unified-frame-height') || '0') || 220;

  walls.forEach((wall) => {
    const stage = wall.closest<HTMLElement>('.gallery-photo-stage');
    if (!stage) {
      return;
    }

    const stageWidth = Math.floor(stage.clientWidth);
    const stageHeight = Math.floor(stage.clientHeight);
    if (stageWidth <= 0 || stageHeight <= 0) {
      return;
    }

    const computed = window.getComputedStyle(wall);
    const gap = Number.parseFloat(computed.columnGap || computed.gap || '10') || 10;
    const doublePortraitPhotoWall = wall.classList.contains('gallery-photo-wall--double-portrait');
    const widthFactor = doublePortraitPhotoWall ? (4 / 3) : (2 / 3);
    const widthPadding = doublePortraitPhotoWall ? gap : 0;
    const maxHeightByWidth = (stageWidth - widthPadding) / widthFactor;
    let fitHeight = Math.floor(Math.min(stageHeight, maxHeightByWidth));
    if (!doublePortraitPhotoWall && unifiedFrameHeight > 0) {
      fitHeight = Math.min(fitHeight, unifiedFrameHeight);
    }

    const galleryLayout = wall.closest<HTMLElement>('.gallery-owner-layout, .gallery-agent-layout');
    const ownerLayout = wall.closest<HTMLElement>('.gallery-owner-layout');
    const agentLayout = wall.closest<HTMLElement>('.gallery-agent-layout');
    const boundedLayout = ownerLayout ?? agentLayout;
    let reservedHeight = 0;
    if (boundedLayout) {
      let layoutHeight = boundedLayout.clientHeight;
      const fillLayout = boundedLayout.closest<HTMLElement>('.interaction-fill-layout');
      if (fillLayout) {
        const fillLayoutStyle = window.getComputedStyle(fillLayout);
        const layoutGap = Number.parseFloat(fillLayoutStyle.rowGap || fillLayoutStyle.gap || '0') || 0;
        const titleEl = fillLayout.querySelector<HTMLElement>('.interaction-title');
        const titleHeight = titleEl ? titleEl.offsetHeight : 0;
        const availableLayoutHeight = Math.floor(fillLayout.clientHeight - titleHeight - layoutGap);
        if (availableLayoutHeight > 0) {
          layoutHeight = availableLayoutHeight;
        }
      }
      if (layoutHeight > 0) {
        const editorCard = boundedLayout.querySelector<HTMLElement>('.gallery-editor-card');
        const actions = editorCard?.querySelector<HTMLElement>('.gallery-actions') ?? null;
        const editorCardStyle = editorCard ? window.getComputedStyle(editorCard) : null;
        const paddingTop = editorCardStyle ? Number.parseFloat(editorCardStyle.paddingTop || '0') || 0 : 0;
        const paddingBottom = editorCardStyle ? Number.parseFloat(editorCardStyle.paddingBottom || '0') || 0 : 0;
        const actionsMarginTop = actions ? (Number.parseFloat(window.getComputedStyle(actions).marginTop || '0') || 0) : 0;
        const actionsHeight = actions ? actions.offsetHeight : 0;
        reservedHeight = Math.ceil(paddingTop + paddingBottom + actionsMarginTop + actionsHeight + 6);
        const maxHeightByLayout = Math.floor(layoutHeight - reservedHeight);
        if (maxHeightByLayout > 0) {
          fitHeight = Math.min(fitHeight, maxHeightByLayout);
        }
      }
    }

    const nextHeight = Math.max(64, fitHeight);
    wall.style.setProperty('--gallery-frame-height', `${nextHeight}px`);
    if (galleryLayout) {
      galleryLayout.style.setProperty('--gallery-frame-height', `${nextHeight}px`);
    }
    const photoCard = wall.closest<HTMLElement>('.gallery-photo-card');
    if (photoCard) {
      photoCard.style.setProperty('--gallery-frame-height', `${nextHeight}px`);
    }

    if (ownerLayout) {
      ownerLayout.style.setProperty('--gallery-owner-frame-height', `${nextHeight}px`);
    }
    if (agentLayout) {
      const agentPanelHeight = nextHeight + reservedHeight;
      agentLayout.style.setProperty('--gallery-agent-panel-height', `${agentPanelHeight}px`);
    }
  });
}

function applyInteractionPanelScrollMode(payload: TyxtInteractionPayload | null): void {
  const isSplitLayoutMode = !!payload && shouldRenderSplitLayout(payload);
  const isBedroomLogMode = !!payload
    && payload.room_id === 'message_wall'
    && payload.sections.some((section) => section.kind === 'log');
  const isGalleryMode = !!payload && payload.room_id === 'gallery';
  dom.interactionPanel.dataset.scrollMode = (isBedroomLogMode || isSplitLayoutMode || isGalleryMode) ? 'inner-only' : 'default';
}

function renderGalleryPanel(payload: TyxtInteractionPayload): string {
  const section = payload.sections.find((item) => item.kind === 'profiles') as TyxtInteractionProfilesSection | undefined;
  const title = `<h3 class="interaction-title">${escapeHtml(compactInteractionTitle(payload.title))}</h3>`;
  if (!section || section.items.length === 0) {
    return `${title}<div class="interaction-empty">暂无简介内容。</div>`;
  }

  if (payload.point_id === 'gallery-owner-intro') {
    const item = section.items[0];
    const itemId = resolveProfileItemId(item, 'owner');
    const text = getGalleryDraftText(itemId, item.text);
    const statusHtml = renderGalleryStatus();

    return `
      <div class="interaction-fill-layout gallery-fill-layout">
        ${title}
        <div class="gallery-owner-layout">
          <section class="interaction-card gallery-panel-card gallery-editor-card">
            <div class="gallery-owner-content">
              <div class="gallery-photo-card gallery-owner-photo-card">
                <div class="gallery-photo-stage">
                  ${renderGalleryPhotoControl(item, 'owner', itemId)}
                </div>
              </div>
              <textarea
                class="gallery-editor"
                data-gallery-editor="true"
                data-profile-id="${escapeHtml(itemId)}"
                data-intro-kind="owner"
                placeholder="请输入主人简介"
              >${escapeHtml(text)}</textarea>
            </div>
            <div class="gallery-actions">
              <button
                class="gallery-save-btn"
                type="button"
                data-gallery-save="owner"
                data-profile-id="${escapeHtml(itemId)}"
                ${state.gallerySaving ? 'disabled' : ''}
              >${state.gallerySaving ? '保存中...' : '保存'}</button>
              <button
                class="gallery-delete-btn"
                type="button"
                data-gallery-photo-delete="owner"
                data-profile-id="${escapeHtml(itemId)}"
                data-photo-slot="primary"
                ${state.gallerySaving ? 'disabled' : ''}
              >删除照片</button>
              ${statusHtml}
            </div>
          </section>
        </div>
      </div>
    `;
  }

  const selectedId = ensureGallerySelectedProfileId(section.items);
  const selectedItem = section.items.find((item) => resolveProfileItemId(item) === selectedId) ?? section.items[0];
  const selectedItemId = resolveProfileItemId(selectedItem);
  const selectedText = getGalleryDraftText(selectedItemId, selectedItem.text);
  const statusHtml = renderGalleryStatus();
  const identityListHtml = section.items.map((item) => {
    const itemId = resolveProfileItemId(item);
    const active = itemId === selectedItemId;
    return `
      <button
        class="gallery-identity-item"
        type="button"
        data-gallery-select-id="${escapeHtml(itemId)}"
        data-active="${active ? 'true' : 'false'}"
      >
        <span class="gallery-identity-title">${escapeHtml(item.subtitle || 'Agent')}</span>
        <strong class="gallery-identity-item-name">${escapeHtml(item.name)}</strong>
      </button>
    `;
  }).join('');

  return `
    <div class="interaction-fill-layout gallery-fill-layout">
      ${title}
      <div class="gallery-agent-layout">
        <section class="interaction-card gallery-panel-card gallery-identity-card">
          <div class="gallery-identity-list">${identityListHtml}</div>
        </section>
        <section class="interaction-card gallery-panel-card gallery-editor-card">
          <div class="gallery-agent-content">
            <div class="gallery-photo-card gallery-agent-photo-card">
              <div class="gallery-photo-stage">
                ${renderGalleryPhotoControl(selectedItem, 'agent', selectedItemId)}
              </div>
            </div>
            <textarea
              class="gallery-editor"
              data-gallery-editor="true"
              data-profile-id="${escapeHtml(selectedItemId)}"
              data-intro-kind="agent"
              placeholder="请输入 Agent 简介"
            >${escapeHtml(selectedText)}</textarea>
          </div>
          <div class="gallery-actions">
            <button
              class="gallery-save-btn"
              type="button"
              data-gallery-save="agent"
              data-profile-id="${escapeHtml(selectedItemId)}"
              ${state.gallerySaving ? 'disabled' : ''}
            >${state.gallerySaving ? '保存中...' : '保存'}</button>
            <button
              class="gallery-delete-btn"
              type="button"
              data-gallery-photo-delete="agent"
              data-profile-id="${escapeHtml(selectedItemId)}"
              data-photo-slot="primary"
              ${state.gallerySaving ? 'disabled' : ''}
            >删除照片</button>
            ${statusHtml}
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderGalleryPhotoInput(introKind: 'owner' | 'agent', profileId: string, slot: GalleryPhotoSlot): string {
  return `
    <input
      class="gallery-photo-input"
      type="file"
      accept="image/png,image/jpeg,image/webp,image/gif"
      data-gallery-photo-input="true"
      data-intro-kind="${introKind}"
      data-profile-id="${escapeHtml(profileId)}"
      data-photo-slot="${slot}"
      hidden
    />
  `;
}

function renderGalleryPhotoControl(item: TyxtInteractionProfileItem, introKind: 'owner' | 'agent', profileId: string): string {
  const primaryPhotoUrl = resolveProfilePhotoUrl(item, 'primary');
  const primaryPhotoContent = primaryPhotoUrl
    ? `<img class="gallery-photo-image" src="${escapeHtml(primaryPhotoUrl)}" alt="${escapeHtml(item.name)}" />`
    : `<span class="gallery-photo-placeholder">竖版照片框</span>`;
  const wallClass = 'gallery-photo-wall';
  const frameClass = 'photo-frame gallery-photo-frame gallery-photo-button gallery-photo-frame--main';

  return `
    <div class="${wallClass}">
      <div class="gallery-photo-slot">
        <button
          class="${frameClass}"
          type="button"
          data-gallery-photo-pick="true"
          data-intro-kind="${introKind}"
          data-profile-id="${escapeHtml(profileId)}"
          data-photo-slot="primary"
            ${state.gallerySaving ? 'disabled' : ''}
        >
          ${primaryPhotoContent}
        </button>
      </div>
    </div>
    ${renderGalleryPhotoInput(introKind, profileId, 'primary')}
  `;
}

function resolveProfileItemId(item: TyxtInteractionProfileItem, fallbackPrefix = 'agent'): string {
  const rawId = String(item.id ?? '').trim();
  if (rawId) {
    return rawId;
  }
  const name = String(item.name ?? '').trim();
  if (name) {
    return `${fallbackPrefix}:${name}`;
  }
  return `${fallbackPrefix}:unknown`;
}

function pickFirstNonEmptyString(values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string') {
      const text = value.trim();
      if (text) {
        return text;
      }
    }
  }
  return '';
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === 'object' && value !== null) {
    return value as Record<string, unknown>;
  }
  return null;
}

function normalizeGalleryPhotoUrl(value: unknown): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) {
    return '';
  }

  const normalized = raw.replaceAll('\\', '/');
  if (normalized.startsWith('data:') || normalized.startsWith('blob:')) {
    return normalized;
  }
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return '';
  }
  if (normalized.startsWith('//')) {
    return `${window.location.protocol}${normalized}`;
  }
  if (/^https?:\/\//i.test(normalized)) {
    try {
      const parsed = new URL(normalized);
      const host = parsed.hostname.toLowerCase();
      const currentHost = window.location.hostname.toLowerCase();
      if (host === currentHost || host === '127.0.0.1' || host === 'localhost') {
        return `${parsed.pathname}${parsed.search}${parsed.hash}`;
      }
      return parsed.toString();
    } catch {
      return normalized;
    }
  }
  if (normalized.startsWith('/')) {
    return normalized;
  }
  if (normalized.startsWith('api/')) {
    return `/${normalized}`;
  }
  return normalized;
}

function resolveProfilePhotoUrl(item: TyxtInteractionProfileItem, slot: GalleryPhotoSlot = 'primary'): string {
  const rawItem = item as unknown as Record<string, unknown>;
  const nestedPhoto = asRecord(rawItem.photo);
  const candidate = slot === 'secondary'
    ? pickFirstNonEmptyString([
      item.photo_url_secondary,
      rawItem.photoUrlSecondary,
      rawItem.photo_url_secondary,
      rawItem.photo_path_secondary,
      rawItem.photoPathSecondary,
      rawItem.secondary_url,
      nestedPhoto?.secondary_url,
      nestedPhoto?.secondaryUrl
    ])
    : pickFirstNonEmptyString([
      item.photo_url,
      rawItem.photoUrl,
      rawItem.photo_url_primary,
      rawItem.photoUrlPrimary,
      rawItem.photo_path_primary,
      rawItem.photoPathPrimary,
      rawItem.photo_path,
      rawItem.photoPath,
      rawItem.url,
      nestedPhoto?.url
    ]);
  return normalizeGalleryPhotoUrl(candidate);
}

function resolveGalleryPhotoUrlFromSaveResponse(payload: Record<string, unknown>): string {
  const nested = asRecord(payload.data);
  const candidate = pickFirstNonEmptyString([
    payload.photo_url,
    payload.photoUrl,
    payload.url,
    nested?.photo_url,
    nested?.photoUrl,
    nested?.url
  ]);
  return normalizeGalleryPhotoUrl(candidate);
}

function ensureGallerySelectedProfileId(items: TyxtInteractionProfileItem[]): string {
  const availableIds = items.map((item) => resolveProfileItemId(item));
  if (state.gallerySelectedProfileId && availableIds.includes(state.gallerySelectedProfileId)) {
    return state.gallerySelectedProfileId;
  }
  state.gallerySelectedProfileId = availableIds[0] ?? null;
  return state.gallerySelectedProfileId || '';
}

function getGalleryDraftText(profileId: string, fallbackText: string): string {
  const draft = state.galleryDraftById[profileId];
  if (typeof draft === 'string') {
    return draft;
  }
  return fallbackText;
}

function renderGalleryStatus(): string {
  if (!state.galleryMessage) {
    return '';
  }
  const tone = state.galleryMessageTone || 'info';
  return `<span class="gallery-status tone-${escapeHtml(tone)}">${escapeHtml(state.galleryMessage)}</span>`;
}

function syncGalleryDraftsFromPayload(payload: TyxtInteractionPayload | null): void {
  if (!payload || payload.room_id !== 'gallery') {
    state.gallerySelectedProfileId = null;
    return;
  }

  const profilesSection = payload.sections.find((section) => section.kind === 'profiles') as TyxtInteractionProfilesSection | undefined;
  if (!profilesSection) {
    state.gallerySelectedProfileId = null;
    return;
  }

  const availableIds = new Set<string>();
  for (const item of profilesSection.items) {
    const itemId = resolveProfileItemId(item, payload.point_id === 'gallery-owner-intro' ? 'owner' : 'agent');
    availableIds.add(itemId);
    if (typeof state.galleryDraftById[itemId] !== 'string') {
      state.galleryDraftById[itemId] = item.text;
    }
  }

  for (const key of Object.keys(state.galleryDraftById)) {
    if (!availableIds.has(key)) {
      delete state.galleryDraftById[key];
    }
  }

  if (payload.point_id === 'gallery-agent-intro') {
    if (!state.gallerySelectedProfileId || !availableIds.has(state.gallerySelectedProfileId)) {
      state.gallerySelectedProfileId = profilesSection.items.length > 0
        ? resolveProfileItemId(profilesSection.items[0])
        : null;
    }
  } else {
    state.gallerySelectedProfileId = profilesSection.items.length > 0
      ? resolveProfileItemId(profilesSection.items[0], 'owner')
      : null;
  }
}

async function saveGalleryIntro(kind: 'owner' | 'agent', profileId: string): Promise<void> {
  const payload = state.interactionPanel;
  if (!payload || payload.room_id !== 'gallery') {
    return;
  }

  const textValue = String(
    state.galleryDraftById[profileId]
    ?? dom.interactionDisplay.querySelector<HTMLTextAreaElement>(`textarea[data-gallery-editor="true"][data-profile-id="${CSS.escape(profileId)}"]`)?.value
    ?? ''
  );

  state.gallerySaving = true;
  state.galleryMessage = null;
  state.galleryMessageTone = null;
  renderInteractionPanel();

  try {
    const response = await fetch('/api/tyxt/gallery-intro-save', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        intro_kind: kind,
        target_id: kind === 'agent' ? profileId : undefined,
        text: textValue,
        agent_id: state.selectedAgentId || undefined,
        user_id: state.headerUserId || undefined
      })
    });

    const data = await response.json() as { ok?: boolean; text?: string; error?: string };
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `save ${response.status}`);
    }

    const savedText = String(data.text ?? textValue);
    state.galleryDraftById[profileId] = savedText;

    const profilesSection = payload.sections.find((section) => section.kind === 'profiles') as TyxtInteractionProfilesSection | undefined;
    if (profilesSection) {
      for (const item of profilesSection.items) {
        const itemId = resolveProfileItemId(item, kind === 'owner' ? 'owner' : 'agent');
        if (itemId === profileId) {
          item.text = savedText;
          break;
        }
      }
    }

    state.galleryMessage = '已保存';
    state.galleryMessageTone = 'ok';
  } catch (error) {
    state.galleryMessage = `保存失败：${error instanceof Error ? error.message : String(error)}`;
    state.galleryMessageTone = 'error';
  } finally {
    state.gallerySaving = false;
    renderInteractionPanel();
  }
}

async function fileToDataBase64(file: File): Promise<{ base64: string; mimeType: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const raw = String(reader.result ?? '');
      const match = raw.match(/^data:([^;]+);base64,(.+)$/);
      if (!match) {
        reject(new Error('image data invalid'));
        return;
      }
      resolve({
        mimeType: match[1],
        base64: match[2]
      });
    };
    reader.onerror = () => {
      reject(new Error('read image failed'));
    };
    reader.readAsDataURL(file);
  });
}

async function saveGalleryPhoto(
  kind: 'owner' | 'agent',
  profileId: string,
  slot: GalleryPhotoSlot,
  file: File
): Promise<void> {
  const payload = state.interactionPanel;
  if (!payload || payload.room_id !== 'gallery') {
    return;
  }
  if (!file || !String(file.type || '').startsWith('image/')) {
    state.galleryMessage = '请选择图片文件';
    state.galleryMessageTone = 'error';
    renderInteractionPanel();
    return;
  }

  state.gallerySaving = true;
  state.galleryMessage = null;
  state.galleryMessageTone = null;
  renderInteractionPanel();

  try {
    const encoded = await fileToDataBase64(file);
    const response = await fetch('/api/tyxt/gallery-photo-save', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        intro_kind: kind,
        target_id: kind === 'agent' ? profileId : undefined,
        photo_slot: slot,
        file_name: file.name,
        mime_type: encoded.mimeType,
        data_base64: encoded.base64,
        user_id: state.headerUserId || undefined
      })
    });

    const data = await response.json() as Record<string, unknown>;
    if (!response.ok || data.ok !== true) {
      const errorMessage = pickFirstNonEmptyString([data.error, data.msg]);
      throw new Error(errorMessage || `photo save ${response.status}`);
    }

    const photoUrl = resolveGalleryPhotoUrlFromSaveResponse(data) || `data:${encoded.mimeType};base64,${encoded.base64}`;
    if (photoUrl) {
      const profilesSection = payload.sections.find((section) => section.kind === 'profiles') as TyxtInteractionProfilesSection | undefined;
      if (profilesSection) {
        for (const item of profilesSection.items) {
          const itemId = resolveProfileItemId(item, kind === 'owner' ? 'owner' : 'agent');
          if (itemId === profileId) {
            if (slot === 'secondary' && kind === 'agent') {
              item.photo_url_secondary = photoUrl;
            } else {
              item.photo_url = photoUrl;
            }
            break;
          }
        }
      }
    }

    state.galleryMessage = photoUrl.startsWith('data:') ? '照片已更新（本地预览）' : '照片已更新';
    state.galleryMessageTone = 'ok';
    await reloadActiveInteractionPanel();
  } catch (error) {
    state.galleryMessage = `上传失败：${error instanceof Error ? error.message : String(error)}`;
    state.galleryMessageTone = 'error';
  } finally {
    state.gallerySaving = false;
    renderInteractionPanel();
  }
}

async function deleteGalleryPhoto(
  kind: 'owner' | 'agent',
  profileId: string,
  slot: GalleryPhotoSlot
): Promise<void> {
  const payload = state.interactionPanel;
  if (!payload || payload.room_id !== 'gallery') {
    return;
  }

  state.gallerySaving = true;
  state.galleryMessage = null;
  state.galleryMessageTone = null;
  renderInteractionPanel();

  try {
    const response = await fetch('/api/tyxt/gallery-photo-delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        intro_kind: kind,
        target_id: kind === 'agent' ? profileId : undefined,
        photo_slot: slot,
        user_id: state.headerUserId || undefined
      })
    });

    const data = await response.json() as Record<string, unknown>;
    if (!response.ok || data.ok !== true) {
      const errorMessage = pickFirstNonEmptyString([data.error, data.msg]);
      throw new Error(errorMessage || `photo delete ${response.status}`);
    }

    const profilesSection = payload.sections.find((section) => section.kind === 'profiles') as TyxtInteractionProfilesSection | undefined;
    if (profilesSection) {
      for (const item of profilesSection.items) {
        const itemId = resolveProfileItemId(item, kind === 'owner' ? 'owner' : 'agent');
        if (itemId === profileId) {
          if (slot === 'secondary' && kind === 'agent') {
            item.photo_url_secondary = '';
          } else {
            item.photo_url = '';
          }
          break;
        }
      }
    }

    state.galleryMessage = '照片已删除';
    state.galleryMessageTone = 'ok';
    await reloadActiveInteractionPanel();
  } catch (error) {
    state.galleryMessage = `删除失败：${error instanceof Error ? error.message : String(error)}`;
    state.galleryMessageTone = 'error';
  } finally {
    state.gallerySaving = false;
    renderInteractionPanel();
  }
}

function shouldRenderSplitLayout(payload: TyxtInteractionPayload): boolean {
  return payload.room_id === 'main_hall'
    || payload.room_id === 'study'
    || payload.room_id === 'workshop'
    || payload.room_id === 'theater'
    || payload.room_id === 'observatory';
}

function compactInteractionTitle(title: string): string {
  return title.replaceAll(' · ', '·').replaceAll('· ', '·').replaceAll(' ·', '·');
}

function renderSplitPanel(payload: TyxtInteractionPayload): string {
  const sections = payload.sections;
  const metricIndex = sections.findIndex((section) => section.kind === 'metric');
  const leftIndex = metricIndex >= 0 ? metricIndex : 0;
  const leftSection = sections[leftIndex];
  const rightSections = sections.filter((_, index) => index !== leftIndex);

  const leftHtml = leftSection
    ? renderSplitLeftSection(leftSection)
    : '<section class="interaction-card"><div class="interaction-empty">暂无统计数据。</div></section>';

  const rightHtml = rightSections.length > 0
    ? rightSections.map((section) => renderInteractionSection(section)).join('')
    : '<section class="interaction-card"><div class="interaction-empty">暂无明细内容。</div></section>';

  const rightStackHtml = `<div class="interaction-sections">${rightHtml}</div>`;

  return `
    <div class="interaction-fill-layout">
      <h3 class="interaction-title">${escapeHtml(compactInteractionTitle(payload.title))}</h3>
      <div class="interaction-split-grid">
        ${leftHtml}
        ${rightStackHtml}
      </div>
    </div>
  `;
}

function renderSplitLeftSection(section: TyxtInteractionSection): string {
  if (section.kind !== 'metric') {
    return renderInteractionSection(section);
  }

  return `
    <section class="interaction-card">
      <h4>${escapeHtml(section.label)}</h4>
      <div class="interaction-metric">${escapeHtml(section.value)}</div>
      <div class="interaction-hint">${escapeHtml(section.hint)}</div>
    </section>
  `;
}

function renderInteractionSection(section: TyxtInteractionSection): string {
  if (section.kind === 'metric') {
    return `
      <section class="interaction-card">
        <h4>${escapeHtml(section.label)}</h4>
        <div class="interaction-metric">${escapeHtml(section.value)}</div>
        <div class="interaction-hint">${escapeHtml(section.hint)}</div>
      </section>
    `;
  }

  if (section.kind === 'list') {
    let itemsHtml = `<div class="interaction-hint">${escapeHtml(section.empty_text)}</div>`;
    if (section.items.length > 0) {
      const itemRows = section.items.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
      itemsHtml = section.ordered
        ? `<ol class="interaction-list interaction-list-ordered">${itemRows}</ol>`
        : `<ul class="interaction-list">${itemRows}</ul>`;
    }
    return `
      <section class="interaction-card">
        <h4>${escapeHtml(section.label)}</h4>
        ${itemsHtml}
      </section>
    `;
  }

  if (section.kind === 'log') {
    return `
      <section class="interaction-card">
        <h4>${escapeHtml(section.label)}</h4>
        <pre class="interaction-log">${escapeHtml(section.text || '(空日志)')}</pre>
        <div class="interaction-path">${escapeHtml(section.path)}</div>
      </section>
    `;
  }

  const profilesHtml = section.items.length > 0
    ? section.items.map((item) => `
      <article class="profile-item">
        <strong>${escapeHtml(item.name)}</strong>
        <div class="photo-frame">${escapeHtml(item.photo_label || '照片框')}</div>
        <div class="text-frame">${escapeHtml(item.text)}</div>
      </article>
    `).join('')
    : '<div class="interaction-empty">暂无简介内容。</div>';

  return `
    <section class="interaction-card">
      <h4>${escapeHtml(section.label)}</h4>
      <div class="profile-grid">
        ${profilesHtml}
      </div>
    </section>
  `;
}

async function reloadActiveInteractionPanel(): Promise<void> {
  const activePointId = String(state.selectedHotspotId || '').trim();
  if (!activePointId) {
    return;
  }
  const activePoint = hotspotsForRoom(state.activeRoomId).find((point) => point.id === activePointId);
  if (!activePoint) {
    return;
  }
  await loadInteractionPanel(state.activeRoomId, activePoint);
}

async function loadInteractionPanel(roomId: TyxtRoomId, point: TyxtInteractivePoint): Promise<void> {
  const targetPointId = point.id;
  state.interactionLoading = true;
  state.interactionError = null;
  renderInteractionPanel();

  try {
    const params = new URLSearchParams();
    params.set('room_id', roomId);
    params.set('point_id', targetPointId);
    if (state.selectedAgentId) {
      params.set('agent_id', state.selectedAgentId);
    }
    if (state.headerUserId) {
      params.set('user_id', state.headerUserId);
    }
    params.set('t', String(Date.now()));

    const response = await fetch(`/api/tyxt/interactive-content?${params.toString()}`, {
      cache: 'no-store'
    });

    if (!response.ok) {
      throw new Error(`interactive-content ${response.status}`);
    }

    const payload = await response.json() as TyxtInteractionApiPayload;
    if (!payload.ok || !payload.data) {
      throw new Error(String(payload.error || '交互内容返回为空'));
    }

    if (state.activeRoomId !== roomId || state.selectedHotspotId !== targetPointId) {
      return;
    }

    state.interactionPanel = payload.data;
    syncGalleryDraftsFromPayload(payload.data);
    state.interactionError = null;
  } catch (error) {
    if (state.activeRoomId === roomId && state.selectedHotspotId === targetPointId) {
      state.interactionPanel = null;
      state.interactionError = `交互内容加载失败：${error instanceof Error ? error.message : String(error)}`;
    }
  } finally {
    if (state.activeRoomId === roomId && state.selectedHotspotId === targetPointId) {
      state.interactionLoading = false;
      renderInteractionPanel();
    }
  }
}

function bindDomEvents(): void {
  window.addEventListener('resize', () => {
    scheduleGalleryPhotoWallSizing();
  });

  dom.roomNavList.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-room-id]');
    if (!button) {
      return;
    }
    const roomId = button.dataset.roomId as TyxtRoomId | undefined;
    if (!roomId || !VALID_ROOM_IDS.includes(roomId)) {
      return;
    }
    switchRoom(roomId, `房间切换：${roomDisplayNameFromId(roomId)}`);
  });

  dom.hotspotList.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-point-id]');
    if (!button) {
      return;
    }
    const pointId = String(button.dataset.pointId || '').trim();
    if (!pointId) {
      return;
    }
    const points = hotspotsForRoom(state.activeRoomId);
    const point = points.find((item) => item.id === pointId);
    if (!point) {
      return;
    }
    state.selectedHotspotId = point.id;
    state.modeNote = `交互点：${point.label}`;
    state.galleryMessage = null;
    state.galleryMessageTone = null;
    state.gallerySaving = false;
    refreshPage();
    void loadInteractionPanel(state.activeRoomId, point);
  });

  dom.agentOverview.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-agent-id]');
    if (!button) {
      return;
    }
    const agentId = button.dataset.agentId;
    if (!agentId) {
      return;
    }
    state.selectedAgentId = agentId;
    state.modeNote = `当前选中 Agent：${agentId}`;
    refreshPage();
    const activePoint = hotspotsForRoom(state.activeRoomId).find((item) => item.id === state.selectedHotspotId);
    if (activePoint) {
      void loadInteractionPanel(state.activeRoomId, activePoint);
    }
  });

  dom.quickActions.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-action-id]');
    if (!button) {
      return;
    }
    const actionId = button.dataset.actionId as TyxtQuickActionId | undefined;
    if (!actionId) {
      return;
    }
    handleQuickAction(actionId);
  });

  dom.interactionDisplay.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const selectButton = target.closest<HTMLButtonElement>('button[data-gallery-select-id]');
    if (selectButton) {
      const nextId = String(selectButton.dataset.gallerySelectId || '').trim();
      if (!nextId) {
        return;
      }
      state.gallerySelectedProfileId = nextId;
      state.galleryMessage = null;
      state.galleryMessageTone = null;
      renderInteractionPanel();
      return;
    }

    const photoButton = target.closest<HTMLButtonElement>('button[data-gallery-photo-pick]');
    if (photoButton) {
      const introKind = String(photoButton.dataset.introKind || '').trim().toLowerCase();
      const profileId = String(photoButton.dataset.profileId || '').trim();
      const slot = String(photoButton.dataset.photoSlot || 'primary').trim().toLowerCase();
      if ((introKind !== 'owner' && introKind !== 'agent') || !profileId) {
        return;
      }
      if (slot !== 'primary' && slot !== 'secondary') {
        return;
      }
      const inputSelector = `input[data-gallery-photo-input="true"][data-intro-kind="${introKind}"][data-profile-id="${CSS.escape(profileId)}"][data-photo-slot="${slot}"]`;
      const input = dom.interactionDisplay.querySelector<HTMLInputElement>(inputSelector);
      if (input) {
        input.click();
      }
      return;
    }

    const deleteButton = target.closest<HTMLButtonElement>('button[data-gallery-photo-delete]');
    if (deleteButton) {
      const introKind = String(deleteButton.dataset.galleryPhotoDelete || '').trim().toLowerCase();
      const profileId = String(deleteButton.dataset.profileId || '').trim();
      const slot = String(deleteButton.dataset.photoSlot || 'primary').trim().toLowerCase();
      if ((introKind !== 'owner' && introKind !== 'agent') || !profileId) {
        return;
      }
      if (slot !== 'primary' && slot !== 'secondary') {
        return;
      }
      void deleteGalleryPhoto(introKind as 'owner' | 'agent', profileId, slot as GalleryPhotoSlot);
      return;
    }

    const saveButton = target.closest<HTMLButtonElement>('button[data-gallery-save]');
    if (!saveButton) {
      return;
    }
    const introKind = String(saveButton.dataset.gallerySave || '').trim();
    const profileId = String(saveButton.dataset.profileId || '').trim();
    if ((introKind !== 'owner' && introKind !== 'agent') || !profileId) {
      return;
    }
    void saveGalleryIntro(introKind as 'owner' | 'agent', profileId);
  });

  dom.interactionDisplay.addEventListener('input', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLTextAreaElement)) {
      return;
    }
    if (target.dataset.galleryEditor !== 'true') {
      return;
    }
    const profileId = String(target.dataset.profileId || '').trim();
    if (!profileId) {
      return;
    }
    state.galleryDraftById[profileId] = target.value;
  });

  dom.interactionDisplay.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    if (target.dataset.galleryPhotoInput !== 'true') {
      return;
    }
    const introKind = String(target.dataset.introKind || '').trim().toLowerCase();
    const profileId = String(target.dataset.profileId || '').trim();
    const slot = String(target.dataset.photoSlot || 'primary').trim().toLowerCase();
    const file = target.files?.[0];
    target.value = '';
    if ((introKind !== 'owner' && introKind !== 'agent') || !profileId || !file) {
      return;
    }
    if (slot !== 'primary' && slot !== 'secondary') {
      return;
    }
    void saveGalleryPhoto(introKind as 'owner' | 'agent', profileId, slot as GalleryPhotoSlot, file);
  });
}

function handleQuickAction(actionId: TyxtQuickActionId): void {
  if (actionId === 'open_chat') {
    void openTyxtChat('private', '快捷操作：进入 TYXT 私聊');
    return;
  }

  if (actionId === 'open_group_chat') {
    void openTyxtChat('group', '快捷操作：进入 TYXT 群聊');
    return;
  }

  if (actionId === 'open_theater') {
    void openTyxtChat('theater', '快捷操作：进入 TYXT 剧场模式');
    return;
  }

  if (actionId === 'view_memory') {
    switchRoom('study', '快捷操作：查看记忆区');
    return;
  }

  if (actionId === 'open_tools') {
    switchRoom('workshop', '快捷操作：进入工坊能力区');
    return;
  }

  state.modeNote = '设置入口为占位，后续阶段接入本地配置。';
  refreshPage();
}

function switchRoom(roomId: TyxtRoomId, modeNote: string): void {
  state.activeRoomId = roomId;
  state.modeNote = modeNote;
  refreshPage();
}

function syncScene(data: TyxtHomeData): void {
  const activeScene = getActiveScene();
  if (!activeScene) {
    state.sceneBound = false;
    state.spawnedAgentIds.clear();
    return;
  }

  activeScene.setLocale('zh');
  activeScene.setDebugVisualsVisible(false);

  if (!state.sceneBound) {
    bindSceneEvents(activeScene);
    state.sceneBound = true;
    state.spawnedAgentIds.clear();
  }

  const snapshot = buildLegacySceneSnapshot(data);
  activeScene.applyTelemetrySnapshot(snapshot);
  syncSceneAgents(activeScene, data);
}

function resolvePrimarySceneAgent(data: TyxtHomeData) {
  const onlineAgents = data.agents.filter((agent) => agent.status !== 'offline');
  if (onlineAgents.length === 0) {
    return data.agents[0] ?? null;
  }

  if (data.selected_agent_id) {
    const selectedAgent = onlineAgents.find((agent) => agent.agent_id === data.selected_agent_id);
    if (selectedAgent) {
      return selectedAgent;
    }
  }

  return onlineAgents[0];
}

function bindSceneEvents(activeScene: LibraryScene): void {
  activeScene.events.on('select-resource', (eventPayload: string | SceneSelectPayload) => {
    const resourceId = resolveResourceId(eventPayload);
    if (!resourceId) {
      return;
    }
    const roomId = mapLegacyResourceToTyxtRoom(resourceId);
    switchRoom(roomId, `场景交互：切换到${roomDisplayNameFromId(roomId)}`);
  });
}

function resolveResourceId(payload: string | SceneSelectPayload): ResourcePartitionId | null {
  const candidate = typeof payload === 'string' ? payload : payload.resourceId;
  if (!candidate) {
    return null;
  }
  if (!VALID_LEGACY_RESOURCE_IDS.has(candidate as ResourcePartitionId)) {
    return null;
  }
  return candidate as ResourcePartitionId;
}

function syncSceneAgents(activeScene: LibraryScene, data: TyxtHomeData): void {
  const primaryAgent = resolvePrimarySceneAgent(data);
  const primaryAgentLabel = primaryAgent ? `默认Agent · ${primaryAgent.display_name}` : '默认Agent';
  activeScene.setPrimaryAgentLabel(primaryAgentLabel);

  // Main map should only show the primary agent avatar.
  for (const previousAgentId of state.spawnedAgentIds) {
    activeScene.despawnAgentActor(previousAgentId);
  }
  state.spawnedAgentIds.clear();
}

function getActiveScene(): LibraryScene | null {
  if (!game.scene.isActive('LibraryScene')) {
    return null;
  }
  return game.scene.getScene('LibraryScene') as LibraryScene;
}

function roomDisplayName(data: TyxtHomeData, roomId: TyxtRoomId): string {
  return data.rooms.find((room) => room.id === roomId)?.name ?? roomDisplayNameFromId(roomId);
}

function roomDisplayNameFromId(roomId: TyxtRoomId): string {
  if (roomId === 'main_hall') return '主厅';
  if (roomId === 'study') return '书房';
  if (roomId === 'workshop') return '工坊';
  if (roomId === 'theater') return '剧场';
  if (roomId === 'observatory') return '档案室';
  if (roomId === 'message_wall') return '卧室';
  return '展厅';
}

function displayStatus(status: TyxtStatus): string {
  if (status === 'online') return '在线';
  if (status === 'offline') return '离线';
  if (status === 'partial') return '部分可用';
  if (status === 'ready') return '就绪';
  if (status === 'running') return '运行中';
  return '待机';
}

function displayAgentStatus(status: 'online' | 'busy' | 'idle' | 'offline'): string {
  if (status === 'online') return '在线';
  if (status === 'busy') return '忙碌';
  if (status === 'idle') return '空闲';
  return '离线';
}

function displayMood(mood: 'calm' | 'focused' | 'curious' | 'tired'): string {
  if (mood === 'calm') return '平稳';
  if (mood === 'focused') return '专注';
  if (mood === 'curious') return '探索';
  return '疲劳';
}

function statusToneClass(status: TyxtStatus): string {
  if (status === 'online' || status === 'ready' || status === 'running') return 'tone-online';
  if (status === 'partial' || status === 'standby') return 'tone-partial';
  return 'tone-offline';
}


function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '--:--';
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}













