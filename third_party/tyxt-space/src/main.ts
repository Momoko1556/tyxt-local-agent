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
const ACTOR_SETTINGS_REFRESH_MS = 60_000;

type TyxtChatEntryKind = 'private' | 'group' | 'theater';

type TyxtChatEntryConfig = Record<TyxtChatEntryKind, string>;

type TyxtSettingsActionId = 'house' | 'furniture' | 'character' | 'shop' | 'interaction';
type TyxtSettingsMode = TyxtSettingsActionId;
type TyxtViewMode = 'normal' | 'settings';
type TyxtHouseFormat = 'png' | 'webp';
type TyxtHouseSettingsSubMode = 'import' | 'wall' | 'label' | null;
type TyxtFurnitureFormat = 'png' | 'webp';
type TyxtFurnitureDirection = 'front' | 'left' | 'right' | 'back';
type TyxtFurnitureCategory =
  | 'sofa'
  | 'bed'
  | 'table'
  | 'chair'
  | 'bookcase'
  | 'display_case'
  | 'workbench'
  | 'lighting'
  | 'decoration';
type TyxtFurnitureSettingsSubMode = 'import' | 'place' | null;
type TyxtWallShapeType = 'square' | 'rectangle' | 'triangle' | 'circle' | 'trapezoid';
type TyxtInteractionSettingsSubMode = 'action_point' | 'interaction_box' | null;

const HOUSE_ALLOWED_MIME_TYPES = new Set(['image/png', 'image/webp']);
const HOUSE_MAX_FILE_BYTES = 5 * 1024 * 1024;
const HOUSE_MIN_WIDTH = 1200;
const HOUSE_MIN_HEIGHT = 800;
const HOUSE_RATIO_TOLERANCE = 0.01;
const FURNITURE_ALLOWED_MIME_TYPES = new Set(['image/png', 'image/webp']);
const FURNITURE_MAX_FILE_BYTES = 5 * 1024 * 1024;
const FURNITURE_MIN_WIDTH = 32;
const FURNITURE_MIN_HEIGHT = 32;
const FURNITURE_DEFAULT_SPRITE_CELL_WIDTH = 96;
const FURNITURE_DEFAULT_SPRITE_CELL_HEIGHT = 96;
const FURNITURE_CATEGORIES: TyxtFurnitureCategory[] = [
  'sofa',
  'bed',
  'table',
  'chair',
  'bookcase',
  'display_case',
  'workbench',
  'lighting',
  'decoration'
];
const FURNITURE_CATEGORY_LABELS: Record<TyxtFurnitureCategory, string> = {
  sofa: '沙发',
  bed: '床',
  table: '桌子',
  chair: '椅子',
  bookcase: '书柜',
  display_case: '展示柜',
  workbench: '工作台',
  lighting: '灯具',
  decoration: '装饰品'
};
const FURNITURE_DIRECTION_LABELS: Record<TyxtFurnitureDirection, string> = {
  front: '正面',
  left: '左侧',
  right: '右侧',
  back: '背面'
};
const FURNITURE_IMPORT_DIRECTION_ORDER: TyxtFurnitureDirection[] = ['front', 'left', 'back', 'right'];
const FURNITURE_PLACEMENT_TURN_ORDER: TyxtFurnitureDirection[] = ['front', 'right', 'back', 'left'];
const FURNITURE_DIRECTION_FRAME_INDEX: Record<TyxtFurnitureDirection, number> = {
  front: 0,
  left: 1,
  back: 2,
  right: 3
};

const WALL_SHAPE_LABELS: Record<TyxtWallShapeType, string> = {
  square: '正方形',
  rectangle: '长方形',
  triangle: '三角形',
  circle: '圆形',
  trapezoid: '梯形'
};

const SETTINGS_ACTION_LABELS: Record<TyxtSettingsActionId, string> = {
  house: '房屋',
  furniture: '家具',
  character: '人物',
  shop: '商店',
  interaction: '交互'
};

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

type SceneEditorLinkedSettingsMode = 'house' | 'furniture' | 'interaction' | null;

type SceneEditorModeChangedPayload = {
  enabled?: boolean;
  tool?: 'wall' | 'furniture' | 'interaction' | 'room_label';
  suggestedSettingsMode?: SceneEditorLinkedSettingsMode;
};

type SceneEditorHudChangedPayload = {
  visible?: boolean;
  text?: string;
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

type TyxtHouseItem = {
  id: string;
  name: string;
  file_name: string;
  width: number;
  height: number;
  ratio: number;
  format: TyxtHouseFormat;
  file_size: number;
  imported_at: string;
  asset_url: string;
  is_current: boolean;
};

type TyxtHouseCatalogPayload = {
  ok?: boolean;
  houses?: TyxtHouseItem[];
  current_house_id?: string | null;
  baseline_house_id?: string | null;
  baseline_ratio?: number | null;
  ratio_tolerance?: number | null;
  drop_folder_path?: string | null;
  drop_scan_report?: {
    imported?: number;
    skipped?: number;
    failed?: number;
    notes?: string[];
  } | null;
  error?: string;
};

type TyxtHouseUploadDraft = {
  file: File;
  preview_url: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  ratio: number;
  format: TyxtHouseFormat | 'unknown';
};

type TyxtHouseValidationReport = {
  passed: boolean;
  file_name: string;
  format_label: string;
  format_pass: boolean;
  file_size: number;
  file_size_pass: boolean;
  width: number;
  height: number;
  min_size_pass: boolean;
  current_ratio: number;
  baseline_ratio: number | null;
  ratio_pass: boolean;
  ratio_delta_percent: number | null;
  reasons: string[];
  suggestions: string[];
};

type TyxtFurnitureDirectionAsset = {
  file_name: string;
  asset_url: string;
  width: number;
  height: number;
  format: TyxtFurnitureFormat;
  file_size: number;
  frame_width?: number;
  frame_height?: number;
};

type TyxtFurnitureAssetItem = {
  id: string;
  name: string;
  category: TyxtFurnitureCategory;
  imported_at: string;
  directions: Record<TyxtFurnitureDirection, TyxtFurnitureDirectionAsset>;
};

type TyxtFurnitureCatalogPayload = {
  ok?: boolean;
  categories?: TyxtFurnitureCategory[];
  assets?: TyxtFurnitureAssetItem[];
  error?: string;
};

type TyxtActorCatalogItem = {
  id: string;
  name: string;
  demo_url: string;
};

type TyxtActorSettingsPayload = {
  ok?: boolean;
  actors?: TyxtActorCatalogItem[];
  assignments?: Record<string, string>;
  default_actor_id?: string;
  error?: string;
};

type TyxtSceneMapPayload = {
  ok?: boolean;
  scene_map?: unknown;
  error?: string;
};

type TyxtFurnitureDraftDirection = {
  file: File;
  preview_url: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  format: TyxtFurnitureFormat | 'unknown';
};

type TyxtFurnitureSpriteCellSetting = {
  width: number;
  height: number;
  valid: boolean;
  reason: string | null;
};

type TyxtSceneInteractionPoint = {
  id: string;
  label: string;
  interaction_type: string;
  sprite_key?: string;
  sprite_total_frames?: number;
  sprite_frame_width?: number;
  sprite_frame_height?: number;
  sprite_fps?: number;
};

type TyxtSceneInteractionBox = {
  id: string;
  label: string;
  interaction_name: string;
  interaction_type: string;
  sprite_key?: string;
  sprite_total_frames?: number;
  sprite_frame_width?: number;
  sprite_frame_height?: number;
  sprite_fps?: number;
};

type TyxtInteractionEditorSnapshot = {
  mode: 'action_point' | 'interaction_box';
  selectedActionPointId: string | null;
  selectedInteractionBoxId: string | null;
  actionPoints: TyxtSceneInteractionPoint[];
  interactionBoxes: TyxtSceneInteractionBox[];
};

type TyxtInteractionPointEditorDraft = {
  kind: 'action_point';
  id: string;
  label: string;
  interactionType: string;
  spriteKey: string;
  spriteTotalFramesInput: string;
  spriteFrameWidthInput: string;
  spriteFrameHeightInput: string;
  spriteFpsInput: string;
};

type TyxtInteractionBoxEditorDraft = {
  kind: 'interaction_box';
  id: string;
  label: string;
  interactionName: string;
  interactionType: string;
  spriteKey: string;
  spriteTotalFramesInput: string;
  spriteFrameWidthInput: string;
  spriteFrameHeightInput: string;
  spriteFpsInput: string;
};

type TyxtInteractionEditorDraft = TyxtInteractionPointEditorDraft | TyxtInteractionBoxEditorDraft;

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
  houseCatalog: TyxtHouseItem[];
  houseCurrentId: string | null;
  houseBaselineId: string | null;
  houseBaselineRatio: number | null;
  houseRatioTolerance: number;
  houseCatalogLoading: boolean;
  houseCatalogError: string | null;
  houseDropFolderPath: string | null;
  houseDraft: TyxtHouseUploadDraft | null;
  houseValidation: TyxtHouseValidationReport | null;
  houseImporting: boolean;
  houseSettingCurrentId: string | null;
  houseMessage: string | null;
  houseMessageTone: 'ok' | 'error' | 'info' | null;
  viewMode: TyxtViewMode;
  settingsMode: TyxtSettingsMode | null;
  settingsMenuOpen: boolean;
  houseSettingsSubMode: TyxtHouseSettingsSubMode;
  furnitureSettingsSubMode: TyxtFurnitureSettingsSubMode;
  interactionSettingsSubMode: TyxtInteractionSettingsSubMode;
  interactionEditorModalOpen: boolean;
  interactionEditorDraft: TyxtInteractionEditorDraft | null;
  interactionEditorMessage: string | null;
  interactionEditorMessageTone: 'ok' | 'error' | 'info' | null;
  furnitureCategorySelected: TyxtFurnitureCategory;
  furnitureCatalog: TyxtFurnitureAssetItem[];
  furnitureCatalogLoading: boolean;
  furnitureCatalogError: string | null;
  furnitureMessage: string | null;
  furnitureMessageTone: 'ok' | 'error' | 'info' | null;
  actorCatalog: TyxtActorCatalogItem[];
  agentActorAssignments: Record<string, string>;
  agentActorDraftAssignments: Record<string, string>;
  actorSettingsLoading: boolean;
  actorSettingsSaving: boolean;
  actorSettingsMessage: string | null;
  actorSettingsMessageTone: 'ok' | 'error' | 'info' | null;
  furnitureImporting: boolean;
  furnitureImportCategory: TyxtFurnitureCategory;
  furnitureImportName: string;
  furnitureSpriteCellWidthInput: string;
  furnitureSpriteCellHeightInput: string;
  furnitureImportDirection: TyxtFurnitureDirection;
  furnitureSpriteSheetDraft: TyxtFurnitureDraftDirection | null;
  furnitureDraftByDirection: Partial<Record<TyxtFurnitureDirection, TyxtFurnitureDraftDirection>>;
  furniturePlacementPanelOpen: boolean;
  furniturePlacementAssetId: string | null;
  furniturePlacementDirection: TyxtFurnitureDirection;
  wallShapeSelection: TyxtWallShapeType;
  sceneEditorHudVisible: boolean;
  sceneEditorHudText: string;
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
  galleryMessageTone: null,
  houseCatalog: [],
  houseCurrentId: null,
  houseBaselineId: null,
  houseBaselineRatio: null,
  houseRatioTolerance: HOUSE_RATIO_TOLERANCE,
  houseCatalogLoading: false,
  houseCatalogError: null,
  houseDropFolderPath: null,
  houseDraft: null,
  houseValidation: null,
  houseImporting: false,
  houseSettingCurrentId: null,
  houseMessage: null,
  houseMessageTone: null,
  viewMode: 'normal',
  settingsMode: null,
  settingsMenuOpen: false,
  houseSettingsSubMode: null,
  furnitureSettingsSubMode: null,
  interactionSettingsSubMode: null,
  interactionEditorModalOpen: false,
  interactionEditorDraft: null,
  interactionEditorMessage: null,
  interactionEditorMessageTone: null,
  furnitureCategorySelected: 'sofa',
  furnitureCatalog: [],
  furnitureCatalogLoading: false,
  furnitureCatalogError: null,
  furnitureMessage: null,
  furnitureMessageTone: null,
  actorCatalog: [],
  agentActorAssignments: {},
  agentActorDraftAssignments: {},
  actorSettingsLoading: false,
  actorSettingsSaving: false,
  actorSettingsMessage: null,
  actorSettingsMessageTone: null,
  furnitureImporting: false,
  furnitureImportCategory: 'sofa',
  furnitureImportName: '',
  furnitureSpriteCellWidthInput: String(FURNITURE_DEFAULT_SPRITE_CELL_WIDTH),
  furnitureSpriteCellHeightInput: String(FURNITURE_DEFAULT_SPRITE_CELL_HEIGHT),
  furnitureImportDirection: 'front',
  furnitureSpriteSheetDraft: null,
  furnitureDraftByDirection: {},
  furniturePlacementPanelOpen: false,
  furniturePlacementAssetId: null,
  furniturePlacementDirection: 'front',
  wallShapeSelection: 'rectangle',
  sceneEditorHudVisible: false,
  sceneEditorHudText: ''
};

let sceneMapProjectSyncStarted = false;

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
  spaceMain: byId<HTMLElement>('space-main'),
  settingsModePanel: byId<HTMLElement>('settings-mode-panel'),
  settingsModeTitle: byId<HTMLElement>('settings-mode-title'),
  settingsModeDescription: byId<HTMLElement>('settings-mode-description'),
  settingsModeContent: byId<HTMLElement>('settings-mode-content'),
  settingsModeClose: byId<HTMLButtonElement>('settings-mode-close'),
  settingsDock: byId<HTMLElement>('settings-dock'),
  houseFloatingOverlay: byId<HTMLElement>('house-floating-overlay'),
  houseFloatingWindow: byId<HTMLElement>('house-floating-window'),
  houseFloatingTitle: byId<HTMLElement>('house-floating-title'),
  houseFloatingDescription: byId<HTMLElement>('house-floating-description'),
  houseFloatingContent: byId<HTMLElement>('house-floating-content'),
  houseFloatingClose: byId<HTMLButtonElement>('house-floating-close'),
  settingsToggle: byId<HTMLButtonElement>('settings-toggle'),
  settingsMenu: byId<HTMLElement>('settings-menu'),
  houseSettingsMenu: byId<HTMLElement>('house-settings-menu'),
  furnitureSettingsMenu: byId<HTMLElement>('furniture-settings-menu'),
  interactionSettingsMenu: byId<HTMLElement>('interaction-settings-menu'),
  furnitureCategoryMenu: byId<HTMLElement>('furniture-category-menu'),
  wallShapeMenu: byId<HTMLElement>('wall-shape-menu'),
  wallEditorControls: byId<HTMLElement>('wall-editor-controls'),
  wallEditorSave: byId<HTMLButtonElement>('wall-editor-save'),
  wallEditorExit: byId<HTMLButtonElement>('wall-editor-exit'),
  roomLabelEditorControls: byId<HTMLElement>('room-label-editor-controls'),
  roomLabelEditorSave: byId<HTMLButtonElement>('room-label-editor-save'),
  roomLabelEditorExit: byId<HTMLButtonElement>('room-label-editor-exit'),
  furnitureEditorControls: byId<HTMLElement>('furniture-editor-controls'),
  furnitureEditorSave: byId<HTMLButtonElement>('furniture-editor-save'),
  furnitureEditorExit: byId<HTMLButtonElement>('furniture-editor-exit'),
  furnitureEditorDirectionLeft: byId<HTMLButtonElement>('furniture-editor-direction-left'),
  furnitureEditorDirectionRight: byId<HTMLButtonElement>('furniture-editor-direction-right'),
  furnitureEditorScaleDown: byId<HTMLButtonElement>('furniture-editor-scale-down'),
  furnitureEditorScaleUp: byId<HTMLButtonElement>('furniture-editor-scale-up'),
  interactionEditorControls: byId<HTMLElement>('interaction-editor-controls'),
  interactionEditorOpen: byId<HTMLButtonElement>('interaction-editor-open'),
  interactionEditorSave: byId<HTMLButtonElement>('interaction-editor-save'),
  interactionEditorExit: byId<HTMLButtonElement>('interaction-editor-exit'),
  furniturePlacementPanel: byId<HTMLElement>('furniture-placement-panel'),
  sceneEditorHudOverlay: byId<HTMLElement>('scene-editor-hud-overlay'),
  interactionPanel: byId<HTMLElement>('interaction-panel'),
  interactionDisplay: byId<HTMLElement>('interaction-display')
};

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
  if (state.settingsMode === 'character') {
    initializeActorDraftAssignments();
  }

  const defaultChanged = previousDefaultAgentId !== registry.default_agent_id;
  if (defaultChanged) {
    state.modeNote = 'Synced project agent registry.';
    refreshPage();
  }
}

async function refreshActorSettings(options: { silent?: boolean } = {}): Promise<void> {
  if (state.actorSettingsLoading) {
    return;
  }
  state.actorSettingsLoading = true;
  if (!options.silent) {
    refreshPage();
  }
  try {
    const response = await fetch(`/api/tyxt/actors?t=${Date.now()}`, { cache: 'no-store' });
    const payload = await response.json() as TyxtActorSettingsPayload;
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || `actors ${response.status}`));
    }
    state.actorCatalog = Array.isArray(payload.actors)
      ? payload.actors
        .map((actor) => ({
          id: normalizeActorFolderId(actor.id),
          name: String(actor.name || actor.id || '').trim(),
          demo_url: String(actor.demo_url || '').trim()
        }))
        .filter((actor) => Boolean(actor.id))
      : [];
    state.agentActorAssignments = normalizeActorAssignments(payload.assignments);
    if (state.settingsMode === 'character') {
      initializeActorDraftAssignments();
    }
    state.actorSettingsMessage = state.actorCatalog.length > 0 ? null : '未找到可用人物资源。';
    state.actorSettingsMessageTone = state.actorCatalog.length > 0 ? null : 'error';
  } catch (error) {
    state.actorSettingsMessage = `人物设置加载失败：${error instanceof Error ? error.message : String(error)}`;
    state.actorSettingsMessageTone = 'error';
  } finally {
    state.actorSettingsLoading = false;
    refreshPage();
  }
}

async function syncProjectSceneMap(activeScene: LibraryScene): Promise<void> {
  const revisionAtStart = activeScene.getSceneMapRevision();
  try {
    const payload = await fetchJsonWithTimeout<TyxtSceneMapPayload>(
      `/api/tyxt/scene-map?t=${Date.now()}`,
      { cache: 'no-store' },
      10_000
    );
    if (!payload.ok) {
      throw new Error(String(payload.error || 'scene-map load failed'));
    }
    if (payload.scene_map) {
      if (activeScene.getSceneMapRevision() !== revisionAtStart) {
        return;
      }
      activeScene.applySceneMapData(payload.scene_map, { persistLocal: true, silent: true });
      return;
    }

    if (activeScene.getSceneMapRevision() === revisionAtStart && activeScene.hasStoredSceneMapData()) {
      await saveProjectSceneMap(activeScene);
    }
  } catch (error) {
    console.warn('[TYXT] Project scene map sync skipped:', error);
  }
}

async function saveProjectSceneMap(activeScene: LibraryScene): Promise<void> {
  const payload = await fetchJsonWithTimeout<TyxtSceneMapPayload>('/api/tyxt/scene-map', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ scene_map: activeScene.getSceneMapDataSnapshot() })
  }, 10_000);
  if (!payload.ok) {
    throw new Error(String(payload.error || 'scene-map save failed'));
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

function normalizeActorFolderId(value: unknown): string {
  const text = String(value ?? '').trim().slice(0, 80);
  return /^[a-zA-Z0-9._-]+$/.test(text) ? text : '';
}

function actorCatalogIdSet(): Set<string> {
  return new Set(state.actorCatalog.map((actor) => actor.id));
}

function defaultActorId(): string {
  return state.actorCatalog[0]?.id ?? '';
}

function actorById(actorId: string): TyxtActorCatalogItem | null {
  return state.actorCatalog.find((actor) => actor.id === actorId) ?? null;
}

function normalizeActorAssignments(rawAssignments: unknown): Record<string, string> {
  const validActorIds = actorCatalogIdSet();
  const out: Record<string, string> = {};
  const source = rawAssignments && typeof rawAssignments === 'object'
    ? rawAssignments as Record<string, unknown>
    : {};
  for (const [agentIdRaw, actorIdRaw] of Object.entries(source)) {
    const agentId = String(agentIdRaw || '').trim();
    const actorId = normalizeActorFolderId(actorIdRaw);
    if (agentId && actorId && validActorIds.has(actorId)) {
      out[agentId] = actorId;
    }
  }
  return out;
}

function agentRowsForActorSettings(): Array<{ agent_id: string; display_name: string }> {
  const registryAgents = (state.agentRegistry?.agents ?? [])
    .filter((agent) => agent.enabled !== false)
    .map((agent) => ({
      agent_id: agent.agent_id,
      display_name: agent.display_name || agent.agent_name || agent.agent_title || agent.agent_id
    }));
  if (registryAgents.length > 0) {
    return registryAgents;
  }
  return (state.data?.agents ?? []).map((agent) => ({
    agent_id: agent.agent_id,
    display_name: agent.display_name || agent.agent_id
  }));
}

function effectiveActorIdForAgent(agentId: string | null | undefined): string {
  const defaultId = defaultActorId();
  if (!agentId) {
    return defaultId;
  }
  const assigned = normalizeActorFolderId(state.agentActorAssignments[agentId]);
  return assigned && actorCatalogIdSet().has(assigned) ? assigned : defaultId;
}

function initializeActorDraftAssignments(): void {
  const defaultId = defaultActorId();
  const validActorIds = actorCatalogIdSet();
  const nextDraft: Record<string, string> = {};
  for (const agent of agentRowsForActorSettings()) {
    const assigned = normalizeActorFolderId(state.agentActorAssignments[agent.agent_id]);
    nextDraft[agent.agent_id] = assigned && validActorIds.has(assigned) ? assigned : defaultId;
  }
  state.agentActorDraftAssignments = nextDraft;
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

type InputSelectionSnapshot = {
  id: string;
  selectionStart: number | null;
  selectionEnd: number | null;
};

let interactionSpritePreviewTimer: number | null = null;
const settingsComposingInputIds = new Set<string>();

const SETTINGS_EDITABLE_INPUT_IDS = new Set([
  'furniture-import-name',
  'furniture-sprite-cell-width',
  'furniture-sprite-cell-height',
  'interaction-edit-label',
  'interaction-edit-interaction-name',
  'interaction-edit-interaction-type',
  'interaction-edit-sprite-key',
  'interaction-edit-sprite-frames',
  'interaction-edit-sprite-width',
  'interaction-edit-sprite-height',
  'interaction-edit-sprite-fps'
]);

function captureSettingsInputSelection(): InputSelectionSnapshot | null {
  const active = document.activeElement;
  if (!(active instanceof HTMLInputElement)) {
    return null;
  }
  if (!SETTINGS_EDITABLE_INPUT_IDS.has(active.id)) {
    return null;
  }
  return {
    id: active.id,
    selectionStart: active.selectionStart,
    selectionEnd: active.selectionEnd
  };
}

function isSettingsInputComposing(): boolean {
  if (settingsComposingInputIds.size > 0) {
    return true;
  }
  const active = document.activeElement;
  if (!(active instanceof HTMLInputElement)) {
    return false;
  }
  if (!SETTINGS_EDITABLE_INPUT_IDS.has(active.id)) {
    return false;
  }
  return active.dataset.imeComposing === 'true';
}

function restoreSettingsInputSelection(snapshot: InputSelectionSnapshot | null): void {
  if (!snapshot) {
    return;
  }
  const input = document.getElementById(snapshot.id);
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  input.focus({ preventScroll: true });
  if (snapshot.selectionStart !== null && snapshot.selectionEnd !== null) {
    try {
      input.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
    } catch {
      // Ignore selection restore failures for non-text input types.
    }
  }
}

function refreshPage(): void {
  const composingSettingsInput = isSettingsInputComposing();
  const inputSelectionSnapshot = composingSettingsInput ? null : captureSettingsInputSelection();
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
  renderSettingsMenu();
  if (!composingSettingsInput) {
    renderSettingsModePanel();
    restoreSettingsInputSelection(inputSelectionSnapshot);
    syncInteractionSpritePreview();
    renderFurniturePlacementPanel();
  }
  renderQuickActions(nextData);
  renderInteractionPanel();
  renderSceneEditorHud();
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

function renderSettingsMenu(): void {
  const lockHouseSubMenu = state.settingsMode === 'house'
    && (state.houseSettingsSubMode === 'wall' || state.houseSettingsSubMode === 'label');
  const effectiveMenuOpen = state.settingsMenuOpen || lockHouseSubMenu;
  dom.settingsToggle.setAttribute('aria-expanded', effectiveMenuOpen ? 'true' : 'false');
  dom.settingsMenu.hidden = !effectiveMenuOpen;
  const actionButtons = dom.settingsMenu.querySelectorAll<HTMLButtonElement>('button[data-setting-action]');
  actionButtons.forEach((button) => {
    const actionId = button.dataset.settingAction as TyxtSettingsActionId | undefined;
    button.dataset.active = actionId && state.settingsMode === actionId ? 'true' : 'false';
  });

  const houseMenuVisible = state.settingsMode === 'house' && (state.settingsMenuOpen || lockHouseSubMenu);
  dom.houseSettingsMenu.hidden = !houseMenuVisible;
  const houseActionButtons = dom.houseSettingsMenu.querySelectorAll<HTMLButtonElement>('button[data-house-setting-action]');
  houseActionButtons.forEach((button) => {
    const action = String(button.dataset.houseSettingAction || '').trim();
    const isActive = (
      (action === 'import' && state.houseSettingsSubMode === 'import')
      || (action === 'wall' && state.houseSettingsSubMode === 'wall')
      || (action === 'label' && state.houseSettingsSubMode === 'label')
    );
    button.dataset.active = isActive ? 'true' : 'false';
  });

  const wallMenuVisible = state.settingsMode === 'house' && state.houseSettingsSubMode === 'wall';
  dom.wallShapeMenu.hidden = !wallMenuVisible;
  const wallShapeButtons = dom.wallShapeMenu.querySelectorAll<HTMLButtonElement>('button[data-wall-shape-type]');
  wallShapeButtons.forEach((button) => {
    const shape = button.dataset.wallShapeType as TyxtWallShapeType | undefined;
    button.dataset.active = shape === state.wallShapeSelection ? 'true' : 'false';
  });

  const furnitureMenuVisible = state.settingsMenuOpen && state.settingsMode === 'furniture';
  dom.furnitureSettingsMenu.hidden = !furnitureMenuVisible;
  const furnitureActionButtons = dom.furnitureSettingsMenu.querySelectorAll<HTMLButtonElement>('button[data-furniture-setting-action]');
  furnitureActionButtons.forEach((button) => {
    const action = String(button.dataset.furnitureSettingAction || '').trim();
    const isActive = (
      (action === 'import' && state.furnitureSettingsSubMode === 'import')
      || (action === 'place' && state.furnitureSettingsSubMode === 'place')
    );
    button.dataset.active = isActive ? 'true' : 'false';
  });

  const furnitureCategoryMenuVisible = furnitureMenuVisible && state.furnitureSettingsSubMode === 'place';
  dom.furnitureCategoryMenu.hidden = !furnitureCategoryMenuVisible;
  const categoryButtons = dom.furnitureCategoryMenu.querySelectorAll<HTMLButtonElement>('button[data-furniture-category]');
  categoryButtons.forEach((button) => {
    const category = String(button.dataset.furnitureCategory || '') as TyxtFurnitureCategory;
    button.dataset.active = category === state.furnitureCategorySelected ? 'true' : 'false';
  });

  const interactionMenuVisible = state.settingsMenuOpen && state.settingsMode === 'interaction';
  dom.interactionSettingsMenu.hidden = !interactionMenuVisible;
  const interactionActionButtons = dom.interactionSettingsMenu.querySelectorAll<HTMLButtonElement>('button[data-interaction-setting-action]');
  interactionActionButtons.forEach((button) => {
    const action = String(button.dataset.interactionSettingAction || '').trim();
    const isActive = (
      (action === 'action-point' && state.interactionSettingsSubMode === 'action_point')
      || (action === 'interaction-box' && state.interactionSettingsSubMode === 'interaction_box')
    );
    button.dataset.active = isActive ? 'true' : 'false';
  });

  dom.wallEditorControls.hidden = state.houseSettingsSubMode !== 'wall';
  dom.roomLabelEditorControls.hidden = !(state.settingsMode === 'house' && state.houseSettingsSubMode === 'label');
  dom.furnitureEditorControls.hidden = !(state.settingsMode === 'furniture' && state.furnitureSettingsSubMode === 'place');
  const interactionEditorVisible = state.settingsMode === 'interaction' && state.interactionSettingsSubMode !== null;
  dom.interactionEditorControls.hidden = !interactionEditorVisible;
  if (interactionEditorVisible) {
    dom.interactionEditorOpen.textContent = state.interactionSettingsSubMode === 'interaction_box' ? 'i编辑' : '编辑';
  }
  const shouldCollapseInteractionPanel = state.settingsMenuOpen
    || (state.settingsMode === 'house' && (
      state.houseSettingsSubMode === 'wall'
      || state.houseSettingsSubMode === 'label'
    ))
    || (state.settingsMode === 'furniture' && (
      state.furnitureSettingsSubMode === 'place'
      || state.furnitureSettingsSubMode === 'import'
    ))
    || (state.settingsMode === 'interaction' && (
      state.interactionSettingsSubMode !== null
      || state.interactionEditorModalOpen
    ));
  dom.interactionPanel.dataset.collapsed = shouldCollapseInteractionPanel ? 'true' : 'false';
  dom.spaceMain.dataset.interactionCollapsed = shouldCollapseInteractionPanel ? 'true' : 'false';
}

function renderSceneEditorHud(): void {
  const showHud = state.sceneEditorHudVisible && state.sceneEditorHudText.trim().length > 0;
  dom.sceneEditorHudOverlay.hidden = !showHud;
  dom.sceneEditorHudOverlay.textContent = showHud ? state.sceneEditorHudText : '';
}

function renderFurniturePlacementPanel(): void {
  const shouldShow = state.settingsMode === 'furniture'
    && state.furnitureSettingsSubMode === 'place'
    && state.settingsMenuOpen
    && state.furniturePlacementPanelOpen;
  dom.furniturePlacementPanel.hidden = !shouldShow;
  if (!shouldShow) {
    dom.furniturePlacementPanel.innerHTML = '';
    return;
  }
  const category = state.furnitureCategorySelected;
  const assets = state.furnitureCatalog.filter((item) => item.category === category);
  const listHtml = assets.length > 0
    ? assets.map((asset) => {
      const front = asset.directions.front;
      const isActive = asset.id === state.furniturePlacementAssetId;
      return `
        <button class="furniture-card-btn" type="button" data-furniture-action="select-placement-asset" data-furniture-asset-id="${escapeHtml(asset.id)}" data-active="${isActive ? 'true' : 'false'}">
          <div class="furniture-card-thumb"><img src="${escapeHtml(resolveRuntimeAssetUrl(front.asset_url))}" alt="${escapeHtml(asset.name)}" /></div>
          <div class="furniture-card-title">${escapeHtml(asset.name)}</div>
          <div class="furniture-card-meta">${escapeHtml(FURNITURE_CATEGORY_LABELS[asset.category])}</div>
        </button>
      `;
    }).join('')
    : '<div class="furniture-placement-empty">当前分类暂无家具，请先导入。</div>';
  dom.furniturePlacementPanel.innerHTML = `
    <div class="furniture-placement-panel-head">选择家具 · ${escapeHtml(FURNITURE_CATEGORY_LABELS[category])}</div>
    <div class="furniture-list-grid">${listHtml}</div>
  `;
  positionFurniturePlacementPanel();
}

function positionFurniturePlacementPanel(): void {
  if (dom.furniturePlacementPanel.hidden) {
    return;
  }
  const anchorRect = dom.furnitureCategoryMenu.getBoundingClientRect();
  const panelWidth = Math.max(320, Math.min(760, Math.round(anchorRect.width)));
  const left = Math.max(8, Math.min(window.innerWidth - panelWidth - 8, Math.round(anchorRect.left)));
  const bottom = Math.max(68, Math.round(window.innerHeight - anchorRect.top + 6));
  dom.furniturePlacementPanel.style.left = `${left}px`;
  dom.furniturePlacementPanel.style.width = `${panelWidth}px`;
  dom.furniturePlacementPanel.style.bottom = `${bottom}px`;
}

function renderSettingsModePanel(): void {
  if (state.viewMode !== 'settings' || !state.settingsMode) {
    dom.settingsModePanel.hidden = true;
    dom.settingsModeContent.innerHTML = '';
    dom.houseFloatingOverlay.hidden = true;
    dom.houseFloatingContent.innerHTML = '';
    delete dom.houseFloatingWindow.dataset.floatingMode;
    return;
  }

  const editorState = getActiveScene()?.getEditorModeState() ?? null;
  const panelContent = resolveSettingsModePanelContent(state.settingsMode, editorState);
  dom.houseFloatingWindow.dataset.floatingMode = state.settingsMode;

  if (state.settingsMode === 'house') {
    dom.settingsModePanel.hidden = true;
    dom.settingsModeContent.innerHTML = '';
    if (state.houseSettingsSubMode === 'import') {
      dom.houseFloatingOverlay.hidden = false;
      dom.houseFloatingTitle.textContent = panelContent.title;
      dom.houseFloatingDescription.textContent = panelContent.description;
      dom.houseFloatingContent.innerHTML = renderHouseSettingsPanel();
    } else {
      dom.houseFloatingOverlay.hidden = true;
      dom.houseFloatingContent.innerHTML = '';
    }
    return;
  }

  if (state.settingsMode === 'furniture') {
    dom.settingsModePanel.hidden = true;
    dom.settingsModeContent.innerHTML = '';
    if (state.furnitureSettingsSubMode === 'import') {
      dom.houseFloatingOverlay.hidden = false;
      dom.houseFloatingTitle.textContent = panelContent.title;
      dom.houseFloatingDescription.textContent = panelContent.description;
      dom.houseFloatingContent.innerHTML = renderFurnitureSettingsPanel();
    } else {
      dom.houseFloatingOverlay.hidden = true;
      dom.houseFloatingContent.innerHTML = '';
    }
    return;
  }

  if (state.settingsMode === 'interaction') {
    dom.settingsModePanel.hidden = true;
    dom.settingsModeContent.innerHTML = '';
    if (state.interactionEditorModalOpen && state.interactionEditorDraft) {
      dom.houseFloatingOverlay.hidden = false;
      dom.houseFloatingTitle.textContent = panelContent.title;
      dom.houseFloatingDescription.textContent = panelContent.description;
      dom.houseFloatingContent.innerHTML = renderInteractionEditorPanel();
    } else {
      dom.houseFloatingOverlay.hidden = true;
      dom.houseFloatingContent.innerHTML = '';
    }
    return;
  }

  if (state.settingsMode === 'character') {
    dom.settingsModePanel.hidden = true;
    dom.settingsModeContent.innerHTML = '';
    dom.houseFloatingOverlay.hidden = false;
    dom.houseFloatingTitle.textContent = panelContent.title;
    dom.houseFloatingDescription.textContent = panelContent.description;
    dom.houseFloatingContent.innerHTML = renderActorSettingsPanel();
    return;
  }

  dom.houseFloatingOverlay.hidden = true;
  dom.houseFloatingContent.innerHTML = '';
  dom.settingsModePanel.hidden = false;
  dom.settingsModeTitle.textContent = panelContent.title;
  dom.settingsModeDescription.textContent = panelContent.description;
  dom.settingsModeClose.textContent = panelContent.closeLabel;
  dom.settingsModeContent.innerHTML = '';
}

function resolveSettingsModePanelContent(
  mode: TyxtSettingsMode,
  editorState: { enabled: boolean; tool: 'wall' | 'furniture' | 'interaction' | 'room_label' } | null
): { title: string; description: string; closeLabel: string } {
  if (mode === 'house') {
    return {
      title: '房屋设置',
      description: '管理房屋底板资源：查看、检查、导入并切换当前房屋；可进入“房屋名”调整标签位置。',
      closeLabel: '返回普通视图'
    };
  }

  if (mode === 'furniture') {
    const isLive = Boolean(editorState?.enabled && editorState.tool === 'furniture');
    return {
      title: state.furnitureSettingsSubMode === 'import' ? '家具导入' : '家具摆放',
      description: state.furnitureSettingsSubMode === 'import'
        ? '选择类别，上传单张精灵图并设置单格尺寸；系统按从左到右切出四方向（正/左/后/右）。'
        : isLive
          ? '选择分类与家具，左键拖拽摆放，右键删除；可切换左右朝向。'
          : '请选择“摆放家具”进入场景家具摆放。',
      closeLabel: '关闭家具面板'
    };
  }

  if (mode === 'character') {
    return {
      title: '人物设置',
      description: '为每个 Agent 指定可视化空间中的人物形象。',
      closeLabel: '关闭人物设置'
    };
  }

  if (mode === 'interaction') {
    const modeLabel = state.interactionSettingsSubMode === 'interaction_box' ? '交互框' : '动作点';
    return {
      title: `${modeLabel}编辑`,
      description: '编辑当前选中项：名称、功能与精灵图参数；保存后写入场景地图数据。',
      closeLabel: '关闭交互编辑'
    };
  }

  return {
    title: '商店设置（占位页）',
    description: '第一阶段仅提供商店面板占位，不包含购买与经济系统。',
    closeLabel: '关闭商店占位页'
  };
}

function renderActorSettingsPanel(): string {
  const agents = agentRowsForActorSettings();
  const actors = state.actorCatalog;
  const defaultId = defaultActorId();

  const rowsHtml = agents.length > 0
    ? agents.map((agent) => {
      const draftActorId = normalizeActorFolderId(state.agentActorDraftAssignments[agent.agent_id]);
      const selectedActorId = draftActorId && actorById(draftActorId) ? draftActorId : defaultId;
      const selectedActor = actorById(selectedActorId);
      const previewHtml = selectedActor?.demo_url
        ? `<img class="actor-settings-preview-image" src="${escapeHtml(resolveRuntimeAssetUrl(selectedActor.demo_url))}" alt="${escapeHtml(selectedActor.name || selectedActor.id)}" />`
        : '<div class="actor-settings-preview-empty">无预览</div>';
      return `
        <div class="actor-settings-row">
          <select class="actor-settings-agent-select" disabled aria-label="Agent名称">
            <option>${escapeHtml(agent.display_name || agent.agent_id)}</option>
          </select>
          <select
            class="actor-settings-actor-select"
            data-agent-actor-select="true"
            data-agent-id="${escapeHtml(agent.agent_id)}"
            aria-label="人物"
            ${actors.length === 0 || state.actorSettingsSaving ? 'disabled' : ''}
          >
            ${actors.map((actor) => (
              `<option value="${escapeHtml(actor.id)}" ${actor.id === selectedActorId ? 'selected' : ''}>${escapeHtml(actor.name || actor.id)}</option>`
            )).join('')}
          </select>
          <div class="actor-settings-preview">${previewHtml}</div>
        </div>
      `;
    }).join('')
    : '<div class="actor-settings-empty">暂无 Agent。</div>';

  const messageHtml = state.actorSettingsMessage
    ? `<div class="house-message tone-${escapeHtml(state.actorSettingsMessageTone || 'info')}">${escapeHtml(state.actorSettingsMessage)}</div>`
    : '';

  return `
    <div class="actor-settings-layout">
      <div class="actor-settings-toolbar">
        <button class="house-action-btn secondary" type="button" data-actor-settings-action="refresh" ${state.actorSettingsLoading ? 'disabled' : ''}>
          ${state.actorSettingsLoading ? '刷新中...' : '刷新人物列表'}
        </button>
        <button class="house-action-btn" type="button" data-actor-settings-action="save" ${state.actorSettingsSaving || actors.length === 0 ? 'disabled' : ''}>
          ${state.actorSettingsSaving ? '保存中...' : '保存'}
        </button>
      </div>
      <div class="actor-settings-head">
        <span>Agent名称</span>
        <span>人物</span>
        <span>样貌</span>
      </div>
      <div class="actor-settings-list">${rowsHtml}</div>
      ${actors.length === 0 && !state.actorSettingsLoading ? '<div class="house-message tone-error">未在人物资源目录中找到可用文件夹。</div>' : ''}
      ${messageHtml}
      <div class="house-baseline-tip">人物资源目录：public/assets/generated/actors</div>
    </div>
  `;
}

function renderHouseSettingsPanel(): string {
  const houses = state.houseCatalog;
  const listHtml = houses.length > 0
    ? houses.map((item) => {
      const isCurrent = item.id === state.houseCurrentId;
      const isSwitching = state.houseSettingCurrentId === item.id;
      return `
        <article class="house-item-card" data-current="${isCurrent ? 'true' : 'false'}">
          <div class="house-thumb-wrap">
            <img class="house-thumb-image" src="${escapeHtml(resolveRuntimeAssetUrl(item.asset_url))}" alt="${escapeHtml(item.name)}" />
          </div>
          <div class="house-item-body">
            <div class="house-item-title">${escapeHtml(item.name)}</div>
            <div class="house-item-meta">文件：${escapeHtml(item.file_name)}</div>
            <div class="house-item-meta">尺寸：${item.width} × ${item.height}</div>
            <div class="house-item-meta">比例：${item.ratio.toFixed(3)} · ${item.format.toUpperCase()} · ${formatBytes(item.file_size)}</div>
            <div class="house-item-meta">导入时间：${escapeHtml(formatDateTime(item.imported_at))}</div>
          </div>
          <div class="house-item-actions">
            <button
              class="house-action-btn"
              type="button"
              data-house-action="set-current"
              data-house-id="${escapeHtml(item.id)}"
              ${(isCurrent || isSwitching || state.houseImporting) ? 'disabled' : ''}
            >${isCurrent ? '当前房屋' : (isSwitching ? '切换中...' : '设为当前房屋')}</button>
          </div>
        </article>
      `;
    }).join('')
    : '<div class="house-empty">暂无房屋资源。</div>';

  const draft = state.houseDraft;
  const previewHtml = draft
    ? `<img class="house-preview-image" src="${escapeHtml(draft.preview_url)}" alt="房屋预览" />`
    : '<div class="house-preview-empty">请选择 PNG / WebP 图片</div>';

  const fileInfoHtml = draft
    ? `
      <div class="house-file-info-row"><span>文件名</span><strong>${escapeHtml(draft.file_name)}</strong></div>
      <div class="house-file-info-row"><span>格式</span><strong>${escapeHtml((draft.format === 'unknown' ? '未知' : draft.format.toUpperCase()))}</strong></div>
      <div class="house-file-info-row"><span>尺寸</span><strong>${draft.width > 0 && draft.height > 0 ? `${draft.width} × ${draft.height}` : '读取中/读取失败'}</strong></div>
      <div class="house-file-info-row"><span>大小</span><strong>${formatBytes(draft.file_size)}</strong></div>
      <div class="house-file-info-row"><span>比例</span><strong>${draft.width > 0 && draft.height > 0 ? draft.ratio.toFixed(3) : '--'}</strong></div>
    `
    : '<div class="house-file-info-empty">尚未选择文件。</div>';

  const checkButtonDisabled = !draft || draft.width <= 0 || draft.height <= 0 || state.houseImporting;
  const importButtonDisabled = !draft || !state.houseValidation?.passed || state.houseImporting;
  const checkResultHtml = renderHouseValidationResult();
  const messageHtml = state.houseMessage
    ? `<div class="house-message tone-${escapeHtml(state.houseMessageTone || 'info')}">${escapeHtml(state.houseMessage)}</div>`
    : '';
  const baselineText = state.houseBaselineRatio
    ? `${state.houseBaselineRatio.toFixed(3)}（容差 ±${(state.houseRatioTolerance * 100).toFixed(1)}%）`
    : '读取中';
  const dropFolderText = state.houseDropFolderPath || '(路径读取中)';

  return `
    <div class="house-manager-layout">
      <section class="house-panel-block">
        <div class="house-panel-head">
          <h4>已有房屋列表</h4>
          <div style="display:flex; gap:6px;">
            <button class="house-action-btn secondary" type="button" data-house-action="copy-drop-folder-path">
              复制文件夹路径
            </button>
            <button class="house-action-btn secondary" type="button" data-house-action="scan-drop-folder" ${state.houseCatalogLoading ? 'disabled' : ''}>
              ${state.houseCatalogLoading ? '扫描中...' : '扫描地图文件夹'}
            </button>
            <button class="house-action-btn secondary" type="button" data-house-action="refresh-list" ${state.houseCatalogLoading ? 'disabled' : ''}>
              ${state.houseCatalogLoading ? '刷新中...' : '刷新列表'}
            </button>
          </div>
        </div>
        <div class="house-baseline-tip">基准比例：${baselineText}</div>
        <div class="house-baseline-tip">地图文件夹：${escapeHtml(dropFolderText)}</div>
        ${state.houseCatalogError ? `<div class="house-message tone-error">${escapeHtml(state.houseCatalogError)}</div>` : ''}
        <div class="house-list-wrap">${listHtml}</div>
      </section>

      <section class="house-panel-block">
        <h4>新房屋导入</h4>
        <input class="house-file-input" id="house-file-input" type="file" accept="image/png,image/webp" />
        <div class="house-toolbar">
          <button class="house-action-btn" type="button" data-house-action="pick-file" ${state.houseImporting ? 'disabled' : ''}>选择图片</button>
          <button class="house-action-btn" type="button" data-house-action="validate" ${checkButtonDisabled ? 'disabled' : ''}>检查</button>
          <button class="house-action-btn" type="button" data-house-action="import" ${importButtonDisabled ? 'disabled' : ''}>
            ${state.houseImporting ? '导入中...' : '导入'}
          </button>
          <button class="house-action-btn" type="button" data-house-action="import-and-activate" ${importButtonDisabled ? 'disabled' : ''}>
            ${state.houseImporting ? '导入中...' : '导入并设为当前'}
          </button>
        </div>
        <div class="house-import-grid">
          <div class="house-preview-box">${previewHtml}</div>
          <div class="house-file-info">${fileInfoHtml}</div>
        </div>
        ${checkResultHtml}
        ${messageHtml}
      </section>
    </div>
  `;
}

function renderHouseValidationResult(): string {
  const report = state.houseValidation;
  if (!report) {
    return '<div class="house-check-report pending">点击“检查”后显示校验结果。</div>';
  }

  const reasonHtml = report.reasons.length > 0
    ? `<div class="house-check-reasons">${report.reasons.map((reason) => `<div>原因：${escapeHtml(reason)}</div>`).join('')}</div>`
    : '';
  const suggestionHtml = report.suggestions.length > 0
    ? `<div class="house-check-suggestions">${report.suggestions.map((item) => `<div>建议：${escapeHtml(item)}</div>`).join('')}</div>`
    : '';

  return `
    <div class="house-check-report ${report.passed ? 'pass' : 'fail'}">
      <div>当前尺寸：${report.width} × ${report.height}</div>
      <div>当前比例：${report.current_ratio.toFixed(3)}</div>
      <div>基准比例：${report.baseline_ratio === null ? '未知' : report.baseline_ratio.toFixed(3)}</div>
      <div>文件格式：${escapeHtml(report.format_label)}</div>
      <div>文件大小：${formatBytes(report.file_size)}</div>
      <div>结果：${report.passed ? '通过' : '不通过'}</div>
      ${report.ratio_delta_percent === null ? '' : `<div>比例偏差：${report.ratio_delta_percent.toFixed(2)}%</div>`}
      ${reasonHtml}
      ${suggestionHtml}
    </div>
  `;
}

function parseFurnitureSpriteCellSetting(): TyxtFurnitureSpriteCellSetting {
  const width = Number.parseInt(String(state.furnitureSpriteCellWidthInput || '').trim(), 10);
  const height = Number.parseInt(String(state.furnitureSpriteCellHeightInput || '').trim(), 10);
  if (!Number.isInteger(width) || width <= 0) {
    return {
      width: 0,
      height: Number.isInteger(height) && height > 0 ? height : 0,
      valid: false,
      reason: '单格宽度需为正整数像素。'
    };
  }
  if (!Number.isInteger(height) || height <= 0) {
    return {
      width,
      height: 0,
      valid: false,
      reason: '单格高度需为正整数像素。'
    };
  }
  return {
    width,
    height,
    valid: true,
    reason: null
  };
}

function resolveFurnitureSpriteCellIssue(
  draft: TyxtFurnitureDraftDirection | null,
  cell: TyxtFurnitureSpriteCellSetting
): string | null {
  if (!draft) {
    return '未选择';
  }
  if (!cell.valid) {
    return cell.reason || '单格尺寸不合法。';
  }
  if (cell.width > draft.width || cell.height > draft.height) {
    return `单格 ${cell.width}×${cell.height} 超出原图 ${draft.width}×${draft.height}`;
  }
  if (draft.height < cell.height) {
    return `精灵图高度不足一格（至少 ${cell.height}px，当前 ${draft.height}px）`;
  }
  return null;
}

function renderFurnitureDirectionCellPreview(
  draft: TyxtFurnitureDraftDirection | null,
  direction: TyxtFurnitureDirection,
  cell: TyxtFurnitureSpriteCellSetting,
  mode: 'main' | 'thumb'
): string {
  if (!draft) {
    return '<div class="furniture-direction-empty">尚未选择精灵图</div>';
  }
  const issue = resolveFurnitureSpriteCellIssue(draft, cell);
  if (issue) {
    return `<div class="furniture-direction-empty">${escapeHtml(issue)}</div>`;
  }
  const maxEdge = mode === 'main' ? 230 : 58;
  const scale = Math.min(maxEdge / cell.width, maxEdge / cell.height, 1);
  const frameWidth = Math.max(10, Math.round(cell.width * scale));
  const frameHeight = Math.max(10, Math.round(cell.height * scale));
  const imageWidth = Math.max(1, Math.round(draft.width * scale));
  const imageHeight = Math.max(1, Math.round(draft.height * scale));
  const frameIndex = FURNITURE_DIRECTION_FRAME_INDEX[direction] ?? 0;
  const availableFrameCount = Math.max(1, Math.floor(draft.width / cell.width));
  const safeFrameIndex = Math.min(frameIndex, availableFrameCount - 1);
  const offsetX = Math.round(safeFrameIndex * cell.width * scale);
  return `
    <div class="furniture-cell-crop-frame ${mode === 'thumb' ? 'thumb' : ''}" style="width:${frameWidth}px;height:${frameHeight}px;">
      <img
        class="furniture-cell-crop-image"
        src="${escapeHtml(draft.preview_url)}"
        alt="${escapeHtml(FURNITURE_DIRECTION_LABELS[direction])}预览"
        style="width:${imageWidth}px;height:${imageHeight}px;transform:translate(${-offsetX}px,0);"
      />
    </div>
  `;
}

function renderFurnitureSettingsPanel(): string {
  const categoryOptions = FURNITURE_CATEGORIES
    .map((category) => `<option value="${category}" ${state.furnitureImportCategory === category ? 'selected' : ''}>${FURNITURE_CATEGORY_LABELS[category]}</option>`)
    .join('');

  const spriteCell = parseFurnitureSpriteCellSetting();
  const directionDraft = state.furnitureSpriteSheetDraft;
  const directionPreviewHtml = renderFurnitureDirectionCellPreview(
    directionDraft,
    state.furnitureImportDirection,
    spriteCell,
    'main'
  );
  const directionPreviewIssue = resolveFurnitureSpriteCellIssue(directionDraft, spriteCell);
  const directionPreviewMeta = directionDraft
    ? directionPreviewIssue
      ? directionPreviewIssue
      : `原图 ${directionDraft.width}×${directionDraft.height}，单格 ${spriteCell.width}×${spriteCell.height}，从左到右：正/左/后/右`
    : '尚未选择精灵图';

  const importDisabled = state.furnitureImporting;

  const messageHtml = state.furnitureMessage
    ? `<div class="house-message tone-${escapeHtml(state.furnitureMessageTone || 'info')}">${escapeHtml(state.furnitureMessage)}</div>`
    : '';

  const directionStatusHtml = FURNITURE_IMPORT_DIRECTION_ORDER.map((direction) => {
    const issue = resolveFurnitureSpriteCellIssue(directionDraft, spriteCell);
    const frameIndex = (FURNITURE_DIRECTION_FRAME_INDEX[direction] ?? 0) + 1;
    const status = !directionDraft
      ? '未选择'
      : issue
        ? issue
        : `第 ${frameIndex} 格（${spriteCell.width}×${spriteCell.height}）`;
    const preview = renderFurnitureDirectionCellPreview(directionDraft, direction, spriteCell, 'thumb');
    return `
      <div class="furniture-direction-status-card ${state.furnitureImportDirection === direction ? 'is-active' : ''}">
        <div class="furniture-direction-status-head">${escapeHtml(FURNITURE_DIRECTION_LABELS[direction])} · 第${frameIndex}格</div>
        <div class="furniture-direction-status-thumb">${preview}</div>
        <div class="furniture-direction-status-text">${escapeHtml(status)}</div>
      </div>
    `;
  }).join('');

  if (state.furnitureSettingsSubMode === 'import') {
    return `
      <div class="house-manager-layout">
        <section class="house-panel-block">
          <h4>导入家具资源</h4>
          <div class="furniture-import-form-grid">
            <label class="furniture-import-field" for="furniture-import-category">
              <span>家具类别</span>
              <select id="furniture-import-category" class="furniture-import-control">
                ${categoryOptions}
              </select>
            </label>
            <label class="furniture-import-field" for="furniture-import-name">
              <span>家具名称</span>
              <input
                id="furniture-import-name"
                class="furniture-import-control"
                value="${escapeHtml(state.furnitureImportName)}"
                placeholder="例如：深蓝双人沙发"
                autocomplete="off"
              />
            </label>
          </div>
          <div class="furniture-import-form-grid sprite-cell">
            <label class="furniture-import-field" for="furniture-sprite-cell-width">
              <span>单格宽度（px）</span>
              <input
                id="furniture-sprite-cell-width"
                class="furniture-import-control"
                type="number"
                min="1"
                step="1"
                inputmode="numeric"
                value="${escapeHtml(state.furnitureSpriteCellWidthInput)}"
              />
            </label>
            <label class="furniture-import-field" for="furniture-sprite-cell-height">
              <span>单格高度（px）</span>
              <input
                id="furniture-sprite-cell-height"
                class="furniture-import-control"
                type="number"
                min="1"
                step="1"
                inputmode="numeric"
                value="${escapeHtml(state.furnitureSpriteCellHeightInput)}"
              />
            </label>
          </div>
          <div class="furniture-cell-setting-tip ${spriteCell.valid ? '' : 'error'}">
            ${escapeHtml(spriteCell.valid ? `按单格 ${spriteCell.width} × ${spriteCell.height} 像素切图；系统优先使用第1~4格作为正/左/后/右，不足时自动复用最后可用格。` : (spriteCell.reason || '单格尺寸设置不合法。'))}
          </div>
          <div class="house-toolbar">
            <button class="house-action-btn" type="button" data-furniture-action="pick-direction-file">选择精灵图</button>
            <button class="house-action-btn" type="button" data-furniture-action="import" ${importDisabled ? 'disabled' : ''}>${state.furnitureImporting ? '导入中...' : '导入家具'}</button>
          </div>
          <input class="house-file-input" id="furniture-file-input" type="file" accept="image/png,image/webp" />
          <div class="furniture-import-grid">
            <div class="furniture-direction-preview">
              <div class="furniture-direction-toolbar">
                <button class="house-action-btn secondary" type="button" data-furniture-action="prev-direction">← 左方向</button>
                <strong>${escapeHtml(FURNITURE_DIRECTION_LABELS[state.furnitureImportDirection])}</strong>
                <button class="house-action-btn secondary" type="button" data-furniture-action="next-direction">右方向 →</button>
              </div>
              <div class="furniture-direction-image-wrap">${directionPreviewHtml}</div>
              <div class="furniture-direction-meta">${escapeHtml(directionPreviewMeta)}</div>
            </div>
            <div class="furniture-direction-status-grid">${directionStatusHtml}</div>
          </div>
          ${messageHtml}
        </section>
      </div>
    `;
  }
  return '';
}

function parsePositiveIntInput(raw: string, fallback: number): number {
  const value = Number.parseInt(String(raw || '').trim(), 10);
  if (!Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  return Math.max(1, value);
}

function parsePositiveNumberInput(raw: string, fallback: number): number {
  const value = Number.parseFloat(String(raw || '').trim());
  if (!Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  return Math.max(0.1, value);
}

function renderInteractionEditorPanel(): string {
  const draft = state.interactionEditorDraft;
  if (!draft) {
    return '<div class="interaction-editor-empty">当前未选中可编辑项，请先在场景中选择动作点或交互框。</div>';
  }

  const spriteKey = normalizeInteractionSpriteAssetPath(String(draft.spriteKey || '').trim());
  const previewSpriteUrl = spriteKey ? resolveRuntimeAssetUrl(spriteKey) : '';
  const frames = parsePositiveIntInput(draft.spriteTotalFramesInput, 1);
  const frameWidth = parsePositiveIntInput(draft.spriteFrameWidthInput, 64);
  const frameHeight = parsePositiveIntInput(draft.spriteFrameHeightInput, 64);
  const fps = parsePositiveNumberInput(draft.spriteFpsInput, 8);

  const previewHtml = previewSpriteUrl
    ? `
      <div class="interaction-sprite-preview-viewport" style="width:${frameWidth}px;height:${frameHeight}px;">
        <img
          id="interaction-sprite-preview-film"
          class="interaction-sprite-preview-film"
          src="${escapeHtml(previewSpriteUrl)}"
          alt="精灵预览"
          data-frame-width="${frameWidth}"
          data-frames="${frames}"
          data-fps="${fps}"
        />
      </div>
    `
    : '<div class="interaction-sprite-preview-empty">未设置精灵图文件，无法播放预览。</div>';

  const modeLabel = draft.kind === 'action_point' ? '动作点' : '交互框';
  const messageHtml = state.interactionEditorMessage
    ? `<div class="house-message tone-${escapeHtml(state.interactionEditorMessageTone || 'info')}">${escapeHtml(state.interactionEditorMessage)}</div>`
    : '';
  const interactionNameFieldHtml = draft.kind === 'interaction_box'
    ? `
      <label class="furniture-import-field" for="interaction-edit-interaction-name">
        <span>交互功能名称</span>
        <input
          id="interaction-edit-interaction-name"
          class="furniture-import-control"
          value="${escapeHtml(draft.interactionName)}"
          autocomplete="off"
        />
      </label>
    `
    : '';

  return `
    <div class="interaction-editor-layout">
      <section class="house-panel-block">
        <h4>${modeLabel}编辑</h4>
        <div class="interaction-editor-id">当前ID：${escapeHtml(draft.id)}</div>
        <div class="furniture-import-form-grid">
          <label class="furniture-import-field" for="interaction-edit-label">
            <span>${modeLabel}名称</span>
            <input
              id="interaction-edit-label"
              class="furniture-import-control"
              value="${escapeHtml(draft.label)}"
              autocomplete="off"
            />
          </label>
          ${interactionNameFieldHtml}
        </div>
        <div class="furniture-import-form-grid">
          <label class="furniture-import-field" for="interaction-edit-interaction-type">
            <span>交互类型</span>
            <input
              id="interaction-edit-interaction-type"
              class="furniture-import-control"
              value="${escapeHtml(draft.interactionType)}"
              autocomplete="off"
              placeholder="例如：inspect / open / trigger"
            />
          </label>
          <label class="furniture-import-field" for="interaction-edit-sprite-key">
            <span>动作精灵图文件</span>
            <div class="interaction-sprite-picker-row">
              <input
                id="interaction-edit-sprite-key"
                class="furniture-import-control"
                value="${escapeHtml(draft.spriteKey)}"
                autocomplete="off"
                placeholder="/assets/furnitures/.../xxx.png"
              />
              <button
                class="house-action-btn secondary interaction-sprite-pick-btn"
                type="button"
                data-interaction-action="pick-sprite"
              >选择</button>
            </div>
            <input
              class="house-file-input"
              id="interaction-edit-sprite-file-input"
              type="file"
              accept="image/png,image/webp,image/gif,image/*"
            />
            <span class="furniture-cell-setting-tip">请填写资源管理器中的 asset_url（通常以 <code>/assets/</code> 开头）。</span>
          </label>
        </div>
        <div class="furniture-import-form-grid sprite-cell">
          <label class="furniture-import-field" for="interaction-edit-sprite-frames">
            <span>总格数</span>
            <input
              id="interaction-edit-sprite-frames"
              class="furniture-import-control"
              type="number"
              min="1"
              step="1"
              inputmode="numeric"
              value="${escapeHtml(draft.spriteTotalFramesInput)}"
            />
          </label>
          <label class="furniture-import-field" for="interaction-edit-sprite-width">
            <span>每格宽度(px)</span>
            <input
              id="interaction-edit-sprite-width"
              class="furniture-import-control"
              type="number"
              min="1"
              step="1"
              inputmode="numeric"
              value="${escapeHtml(draft.spriteFrameWidthInput)}"
            />
          </label>
          <label class="furniture-import-field" for="interaction-edit-sprite-height">
            <span>每格高度(px)</span>
            <input
              id="interaction-edit-sprite-height"
              class="furniture-import-control"
              type="number"
              min="1"
              step="1"
              inputmode="numeric"
              value="${escapeHtml(draft.spriteFrameHeightInput)}"
            />
          </label>
          <label class="furniture-import-field" for="interaction-edit-sprite-fps">
            <span>播放速度(fps)</span>
            <input
              id="interaction-edit-sprite-fps"
              class="furniture-import-control"
              type="number"
              min="0.1"
              step="0.1"
              inputmode="decimal"
              value="${escapeHtml(draft.spriteFpsInput)}"
            />
          </label>
        </div>
        <div class="interaction-sprite-preview-wrap">
          ${previewHtml}
          <div class="interaction-sprite-preview-meta">
            帧设定：${frames} 格 · ${frameWidth}×${frameHeight}px · ${fps.toFixed(1)} fps
          </div>
        </div>
        <div class="house-toolbar">
          <button class="house-action-btn" type="button" data-interaction-action="apply-meta">应用到当前项</button>
          <button class="house-action-btn secondary" type="button" data-interaction-action="close-meta">关闭</button>
        </div>
        ${messageHtml}
      </section>
    </div>
  `;
}

function stopInteractionSpritePreview(): void {
  if (interactionSpritePreviewTimer !== null) {
    window.clearInterval(interactionSpritePreviewTimer);
    interactionSpritePreviewTimer = null;
  }
}

function syncInteractionSpritePreview(): void {
  stopInteractionSpritePreview();
  if (!state.interactionEditorModalOpen || !state.interactionEditorDraft) {
    return;
  }
  const film = document.getElementById('interaction-sprite-preview-film');
  if (!(film instanceof HTMLImageElement)) {
    return;
  }
  const frameWidth = Number.parseInt(String(film.dataset.frameWidth || '0'), 10);
  const frames = Number.parseInt(String(film.dataset.frames || '1'), 10);
  const fps = Number.parseFloat(String(film.dataset.fps || '0'));
  if (!Number.isFinite(frameWidth) || frameWidth <= 0) {
    return;
  }

  let frameIndex = 0;
  const applyFrame = () => {
    film.style.transform = `translateX(${-frameIndex * frameWidth}px)`;
    frameIndex = (frameIndex + 1) % Math.max(1, frames);
  };
  applyFrame();
  if (!Number.isFinite(fps) || fps <= 0 || frames <= 1) {
    return;
  }
  const intervalMs = Math.max(40, Math.round(1000 / fps));
  interactionSpritePreviewTimer = window.setInterval(applyFrame, intervalMs);
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
    positionFurniturePlacementPanel();
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

  dom.settingsToggle.addEventListener('click', () => {
    state.settingsMenuOpen = !state.settingsMenuOpen;
    refreshPage();
  });

  dom.settingsModeClose.addEventListener('click', () => {
    setSettingsMode(null, 'menu');
  });

  dom.houseFloatingClose.addEventListener('click', () => {
    if (state.settingsMode === 'house') {
      setHouseSettingsSubMode(null, 'menu');
      return;
    }
    if (state.settingsMode === 'furniture') {
      setFurnitureSettingsSubMode(null, 'menu');
      return;
    }
    if (state.settingsMode === 'interaction') {
      closeInteractionEditorModal();
      return;
    }
    setSettingsMode(null, 'menu');
  });

  dom.houseFloatingOverlay.addEventListener('click', (event) => {
    if (event.target === dom.houseFloatingOverlay) {
      if (state.settingsMode === 'house') {
        setHouseSettingsSubMode(null, 'menu');
        return;
      }
      if (state.settingsMode === 'furniture') {
        setFurnitureSettingsSubMode(null, 'menu');
        return;
      }
      if (state.settingsMode === 'interaction') {
        closeInteractionEditorModal();
        return;
      }
      setSettingsMode(null, 'menu');
    }
  });

  dom.settingsMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-setting-action]');
    if (!button) {
      return;
    }
    const actionId = button.dataset.settingAction as TyxtSettingsActionId | undefined;
    if (!actionId || !(actionId in SETTINGS_ACTION_LABELS)) {
      return;
    }
    handleSettingsAction(actionId);
  });

  dom.houseSettingsMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-house-setting-action]');
    if (!button) {
      return;
    }
    const action = String(button.dataset.houseSettingAction || '').trim();
    if (action === 'import') {
      setHouseSettingsSubMode('import', 'menu');
      return;
    }
    if (action === 'wall') {
      setHouseSettingsSubMode('wall', 'menu');
      return;
    }
    if (action === 'label') {
      setHouseSettingsSubMode('label', 'menu');
      return;
    }
  });

  dom.furnitureSettingsMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-furniture-setting-action]');
    if (!button) {
      return;
    }
    const action = String(button.dataset.furnitureSettingAction || '').trim();
    if (action === 'import') {
      setFurnitureSettingsSubMode('import', 'menu');
      return;
    }
    if (action === 'place') {
      setFurnitureSettingsSubMode('place', 'menu');
    }
  });

  dom.interactionSettingsMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-interaction-setting-action]');
    if (!button) {
      return;
    }
    const action = String(button.dataset.interactionSettingAction || '').trim();
    if (action === 'action-point') {
      setInteractionSettingsSubMode('action_point', 'menu');
      return;
    }
    if (action === 'interaction-box') {
      setInteractionSettingsSubMode('interaction_box', 'menu');
    }
  });

  dom.furnitureCategoryMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-furniture-category]');
    if (!button) {
      return;
    }
    const category = String(button.dataset.furnitureCategory || '').trim() as TyxtFurnitureCategory;
    if (!FURNITURE_CATEGORIES.includes(category)) {
      return;
    }
    state.furnitureCategorySelected = category;
    state.furniturePlacementPanelOpen = true;
    state.furniturePlacementAssetId = null;
    applyFurniturePlacementTemplateToScene();
    refreshPage();
  });

  dom.wallShapeMenu.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-wall-shape-type]');
    if (!button) {
      return;
    }
    const wallShape = button.dataset.wallShapeType as TyxtWallShapeType | undefined;
    if (!wallShape || !(wallShape in WALL_SHAPE_LABELS)) {
      return;
    }
    state.wallShapeSelection = wallShape;
    state.modeNote = `墙壁图形已切换：${WALL_SHAPE_LABELS[wallShape]}`;
    refreshPage();
    const activeScene = getActiveScene();
    activeScene?.setWallEditorShapePreset(wallShape);
  });

  dom.wallEditorSave.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.saveWallEditorChanges();
    state.modeNote = '墙壁编辑已保存。';
    refreshPage();
  });

  dom.wallEditorExit.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.exitWallEditor({ discardUnsaved: true });
    setSettingsMode(null, 'system');
    state.modeNote = '已退出墙壁编辑。';
    refreshPage();
  });

  dom.roomLabelEditorSave.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.saveRoomLabelEditorChanges();
    state.modeNote = '房屋名编辑已保存。';
    refreshPage();
  });

  dom.roomLabelEditorExit.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.exitRoomLabelEditor({ silent: true });
    setSettingsMode(null, 'system');
    state.modeNote = '已退出房屋名编辑。';
    refreshPage();
  });

  dom.furnitureEditorSave.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.saveFurniturePlacementChanges();
    state.modeNote = '家具摆放已保存。';
    state.furnitureMessage = '家具摆放已保存。';
    state.furnitureMessageTone = 'ok';
    refreshPage();
  });

  dom.furnitureEditorExit.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.exitFurniturePlacement({ discardUnsaved: false });
    setSettingsMode(null, 'system');
    state.modeNote = '已退出家具摆放。';
    refreshPage();
  });

  dom.furnitureEditorDirectionLeft.addEventListener('click', () => {
    cycleFurniturePlacementDirection(-1);
  });

  dom.furnitureEditorDirectionRight.addEventListener('click', () => {
    cycleFurniturePlacementDirection(1);
  });

  dom.furnitureEditorScaleDown.addEventListener('click', () => {
    scaleFurniturePlacementSelection(-1);
  });

  dom.furnitureEditorScaleUp.addEventListener('click', () => {
    scaleFurniturePlacementSelection(1);
  });

  dom.interactionEditorOpen.addEventListener('click', () => {
    openInteractionEditorModal();
  });

  dom.interactionEditorSave.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.saveInteractionEditorChanges();
    state.modeNote = '交互编辑已保存。';
    state.interactionEditorMessage = '交互编辑已保存。';
    state.interactionEditorMessageTone = 'ok';
    refreshPage();
  });

  dom.interactionEditorExit.addEventListener('click', () => {
    const activeScene = getActiveScene();
    activeScene?.exitInteractionEditor({ discardUnsaved: false, silent: true });
    setSettingsMode(null, 'system');
    state.modeNote = '已退出交互编辑。';
    refreshPage();
  });

  document.addEventListener('click', (event) => {
    if (!state.settingsMenuOpen) {
      return;
    }
    if (
      state.settingsMode === 'house'
      && (state.houseSettingsSubMode === 'wall' || state.houseSettingsSubMode === 'label')
    ) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (
      dom.settingsDock.contains(target)
      || dom.settingsToggle.contains(target)
      || dom.settingsMenu.contains(target)
      || dom.houseSettingsMenu.contains(target)
      || dom.furnitureSettingsMenu.contains(target)
      || dom.interactionSettingsMenu.contains(target)
      || dom.furnitureCategoryMenu.contains(target)
      || dom.wallShapeMenu.contains(target)
      || dom.wallEditorControls.contains(target)
      || dom.roomLabelEditorControls.contains(target)
      || dom.furnitureEditorControls.contains(target)
      || dom.interactionEditorControls.contains(target)
      || dom.furniturePlacementPanel.contains(target)
      || dom.houseFloatingWindow.contains(target)
    ) {
      return;
    }
    state.settingsMenuOpen = false;
    refreshPage();
  });

  const onHousePanelClick = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const actorSettingsButton = target.closest<HTMLButtonElement>('button[data-actor-settings-action]');
    if (actorSettingsButton) {
      const action = String(actorSettingsButton.dataset.actorSettingsAction || '').trim();
      if (action === 'refresh') {
        void refreshActorSettings();
        return;
      }
      if (action === 'save') {
        void saveActorSettings();
      }
      return;
    }

    const houseActionButton = target.closest<HTMLButtonElement>('button[data-house-action]');
    if (houseActionButton) {
      const action = String(houseActionButton.dataset.houseAction || '').trim();
      if (!action) {
        return;
      }
      if (action === 'pick-file') {
        void triggerHouseFilePicker();
        return;
      }
      if (action === 'copy-drop-folder-path') {
        void copyHouseDropFolderPath();
        return;
      }
      if (action === 'validate') {
        runHouseDraftValidation();
        return;
      }
      if (action === 'refresh-list') {
        void refreshHouseCatalog();
        return;
      }
      if (action === 'scan-drop-folder') {
        void scanHouseDropFolder();
        return;
      }
      if (action === 'import') {
        void importHouseDraft(false);
        return;
      }
      if (action === 'import-and-activate') {
        void importHouseDraft(true);
        return;
      }
      if (action === 'set-current') {
        const houseId = String(houseActionButton.dataset.houseId || '').trim();
        if (houseId) {
          void setCurrentHouse(houseId);
        }
      }
      return;
    }

    const furnitureActionButton = target.closest<HTMLButtonElement>('button[data-furniture-action]');
    if (furnitureActionButton) {
      const action = String(furnitureActionButton.dataset.furnitureAction || '').trim();
      if (action === 'pick-direction-file') {
        void triggerFurnitureFilePicker();
        return;
      }
      if (action === 'prev-direction') {
        shiftFurnitureImportDirection(-1);
        return;
      }
      if (action === 'next-direction') {
        shiftFurnitureImportDirection(1);
        return;
      }
      if (action === 'import') {
        void importFurnitureDraft();
        return;
      }
      if (action === 'select-placement-asset') {
        const assetId = String(furnitureActionButton.dataset.furnitureAssetId || '').trim();
        if (!assetId) {
          return;
        }
        state.furniturePlacementAssetId = assetId;
        applyFurniturePlacementTemplateToScene();
        refreshPage();
      }
      return;
    }

    const interactionActionButton = target.closest<HTMLButtonElement>('button[data-interaction-action]');
    if (interactionActionButton) {
      const action = String(interactionActionButton.dataset.interactionAction || '').trim();
      if (action === 'pick-sprite') {
        void triggerInteractionSpriteFilePicker();
        return;
      }
      if (action === 'apply-meta') {
        applyInteractionEditorDraftToScene();
        return;
      }
      if (action === 'close-meta') {
        closeInteractionEditorModal();
      }
    }
  };

  const onHousePanelChange = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement)) {
      return;
    }
    if (target instanceof HTMLInputElement && target.id === 'house-file-input') {
      const nextFile = target.files?.[0] ?? null;
      target.value = '';
      void selectHouseDraftFile(nextFile);
      return;
    }
    if (target instanceof HTMLInputElement && target.id === 'furniture-file-input') {
      const nextFile = target.files?.[0] ?? null;
      target.value = '';
      void selectFurnitureSpriteSheetFile(nextFile);
      return;
    }
    if (target instanceof HTMLInputElement && target.id === 'interaction-edit-sprite-file-input') {
      const nextFile = target.files?.[0] ?? null;
      target.value = '';
      void selectInteractionSpriteFile(nextFile);
      return;
    }
    if (target instanceof HTMLSelectElement && target.dataset.agentActorSelect === 'true') {
      const agentId = String(target.dataset.agentId || '').trim();
      const actorId = normalizeActorFolderId(target.value);
      if (agentId && actorId && actorCatalogIdSet().has(actorId)) {
        state.agentActorDraftAssignments = {
          ...state.agentActorDraftAssignments,
          [agentId]: actorId
        };
        state.actorSettingsMessage = null;
        state.actorSettingsMessageTone = null;
        refreshPage();
      }
      return;
    }
    if (target instanceof HTMLSelectElement && target.id === 'furniture-import-category') {
      const category = target.value as TyxtFurnitureCategory;
      if (FURNITURE_CATEGORIES.includes(category)) {
        state.furnitureImportCategory = category;
        refreshPage();
      }
    }
    if (target instanceof HTMLInputElement && target.id === 'furniture-import-name') {
      state.furnitureImportName = target.value;
      return;
    }
    if (target instanceof HTMLInputElement && target.id === 'furniture-sprite-cell-width') {
      state.furnitureSpriteCellWidthInput = target.value;
      refreshPage();
      return;
    }
    if (target instanceof HTMLInputElement && target.id === 'furniture-sprite-cell-height') {
      state.furnitureSpriteCellHeightInput = target.value;
      refreshPage();
      return;
    }
    if (target instanceof HTMLInputElement && state.interactionEditorDraft) {
      if (target.id === 'interaction-edit-label') {
        state.interactionEditorDraft.label = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-interaction-name' && state.interactionEditorDraft.kind === 'interaction_box') {
        state.interactionEditorDraft.interactionName = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-interaction-type') {
        state.interactionEditorDraft.interactionType = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-sprite-key') {
        state.interactionEditorDraft.spriteKey = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-sprite-frames') {
        state.interactionEditorDraft.spriteTotalFramesInput = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-sprite-width') {
        state.interactionEditorDraft.spriteFrameWidthInput = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-sprite-height') {
        state.interactionEditorDraft.spriteFrameHeightInput = target.value;
        refreshPage();
        return;
      }
      if (target.id === 'interaction-edit-sprite-fps') {
        state.interactionEditorDraft.spriteFpsInput = target.value;
        refreshPage();
      }
    }
  };

  const onHousePanelInput = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    if (target.id === 'furniture-import-name') {
      state.furnitureImportName = target.value;
      return;
    }
    if (target.id === 'furniture-sprite-cell-width') {
      state.furnitureSpriteCellWidthInput = target.value;
      return;
    }
    if (target.id === 'furniture-sprite-cell-height') {
      state.furnitureSpriteCellHeightInput = target.value;
      return;
    }
    if (!state.interactionEditorDraft) {
      return;
    }
    if (target.id === 'interaction-edit-label') {
      state.interactionEditorDraft.label = target.value;
      return;
    }
    if (target.id === 'interaction-edit-interaction-name' && state.interactionEditorDraft.kind === 'interaction_box') {
      state.interactionEditorDraft.interactionName = target.value;
      return;
    }
    if (target.id === 'interaction-edit-interaction-type') {
      state.interactionEditorDraft.interactionType = target.value;
      return;
    }
    if (target.id === 'interaction-edit-sprite-key') {
      state.interactionEditorDraft.spriteKey = target.value;
      return;
    }
    if (target.id === 'interaction-edit-sprite-frames') {
      state.interactionEditorDraft.spriteTotalFramesInput = target.value;
      return;
    }
    if (target.id === 'interaction-edit-sprite-width') {
      state.interactionEditorDraft.spriteFrameWidthInput = target.value;
      return;
    }
    if (target.id === 'interaction-edit-sprite-height') {
      state.interactionEditorDraft.spriteFrameHeightInput = target.value;
      return;
    }
    if (target.id === 'interaction-edit-sprite-fps') {
      state.interactionEditorDraft.spriteFpsInput = target.value;
    }
  };

  const onHousePanelCompositionStart = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    if (!SETTINGS_EDITABLE_INPUT_IDS.has(target.id)) {
      return;
    }
    target.dataset.imeComposing = 'true';
    settingsComposingInputIds.add(target.id);
  };

  const onHousePanelCompositionEnd = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    if (!SETTINGS_EDITABLE_INPUT_IDS.has(target.id)) {
      return;
    }
    delete target.dataset.imeComposing;
    settingsComposingInputIds.delete(target.id);
    refreshPage();
  };

  dom.settingsModePanel.addEventListener('click', onHousePanelClick);
  dom.houseFloatingWindow.addEventListener('click', onHousePanelClick);
  dom.settingsModePanel.addEventListener('change', onHousePanelChange);
  dom.houseFloatingWindow.addEventListener('change', onHousePanelChange);
  dom.settingsModePanel.addEventListener('input', onHousePanelInput);
  dom.houseFloatingWindow.addEventListener('input', onHousePanelInput);
  dom.settingsModePanel.addEventListener('compositionstart', onHousePanelCompositionStart);
  dom.houseFloatingWindow.addEventListener('compositionstart', onHousePanelCompositionStart);
  dom.settingsModePanel.addEventListener('compositionend', onHousePanelCompositionEnd);
  dom.houseFloatingWindow.addEventListener('compositionend', onHousePanelCompositionEnd);

  dom.furniturePlacementPanel.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>('button[data-furniture-action="select-placement-asset"]');
    if (!button) {
      return;
    }
    const assetId = String(button.dataset.furnitureAssetId || '').trim();
    if (!assetId) {
      return;
    }
    state.furniturePlacementAssetId = assetId;
    applyFurniturePlacementTemplateToScene();
    refreshPage();
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

function handleSettingsAction(actionId: TyxtSettingsActionId): void {
  const label = SETTINGS_ACTION_LABELS[actionId];
  if (state.settingsMode === actionId) {
    if (actionId === 'house') {
      if (state.houseSettingsSubMode !== null) {
        setHouseSettingsSubMode(null, 'menu');
        return;
      }
      state.settingsMenuOpen = true;
      refreshPage();
      return;
    }
    if (actionId === 'furniture') {
      if (state.furnitureSettingsSubMode !== null) {
        setFurnitureSettingsSubMode(null, 'menu');
        return;
      }
      state.settingsMenuOpen = true;
      refreshPage();
      return;
    }
    if (actionId === 'interaction') {
      if (state.interactionEditorModalOpen) {
        closeInteractionEditorModal();
        return;
      }
      if (state.interactionSettingsSubMode !== null) {
        setInteractionSettingsSubMode(null, 'menu');
        return;
      }
      state.settingsMenuOpen = true;
      refreshPage();
      return;
    }
    setSettingsMode(null, 'menu');
    return;
  }

  setSettingsMode(actionId, 'menu');
  if (actionId === 'house') {
    setHouseSettingsSubMode(null, 'menu');
  } else if (actionId === 'furniture') {
    setFurnitureSettingsSubMode(null, 'menu');
  } else if (actionId === 'interaction') {
    setInteractionSettingsSubMode(null, 'menu');
  }
  console.info('[TYXT][SettingsMenuAction]', { actionId, label, viewMode: state.viewMode });
}

function setSettingsMode(nextMode: TyxtSettingsMode | null, source: 'menu' | 'scene' | 'system'): void {
  const previousMode = state.settingsMode;
  const previousViewMode = state.viewMode;
  const previousMenuOpen = state.settingsMenuOpen;

  state.settingsMode = nextMode;
  state.viewMode = nextMode ? 'settings' : 'normal';
  state.settingsMenuOpen = source === 'menu' ? nextMode !== null : false;
  if (nextMode !== 'house') {
    state.houseSettingsSubMode = null;
  } else if (previousMode !== 'house') {
    state.houseSettingsSubMode = null;
  }
  if (nextMode !== 'furniture') {
    state.furnitureSettingsSubMode = null;
  } else if (previousMode !== 'furniture') {
    state.furnitureSettingsSubMode = null;
  }
  if (nextMode !== 'interaction') {
    state.interactionSettingsSubMode = null;
    state.interactionEditorModalOpen = false;
    state.interactionEditorDraft = null;
    state.interactionEditorMessage = null;
    state.interactionEditorMessageTone = null;
  } else if (previousMode !== 'interaction') {
    state.interactionSettingsSubMode = null;
    state.interactionEditorModalOpen = false;
    state.interactionEditorDraft = null;
    state.interactionEditorMessage = null;
    state.interactionEditorMessageTone = null;
  }
  if (nextMode === 'character' && previousMode !== 'character') {
    initializeActorDraftAssignments();
    state.actorSettingsMessage = null;
    state.actorSettingsMessageTone = null;
    void refreshActorSettings({ silent: true });
  }

  if (previousMode === 'house' && (nextMode !== 'house' || state.houseSettingsSubMode !== 'import')) {
    resetHouseDraftSelection();
    state.houseValidation = null;
  }
  if (previousMode === 'furniture' && (nextMode !== 'furniture' || state.furnitureSettingsSubMode !== 'import')) {
    resetFurnitureDraftSelection();
  }
  if (previousMode === 'interaction' && nextMode !== 'interaction') {
    state.interactionEditorModalOpen = false;
    state.interactionEditorDraft = null;
  }

  if (previousMode !== nextMode) {
    state.modeNote = describeSettingsModeNote(nextMode, source);
  }

  if (
    previousMode !== state.settingsMode
    || previousViewMode !== state.viewMode
    || previousMenuOpen !== state.settingsMenuOpen
  ) {
    refreshPage();
  }

  if (nextMode === 'house' && state.houseSettingsSubMode === 'import') {
    void refreshHouseCatalog({ silent: true });
  }
  if (nextMode === 'furniture') {
    void refreshFurnitureCatalog({ silent: true });
  }
}

function setHouseSettingsSubMode(nextSubMode: TyxtHouseSettingsSubMode, source: 'menu' | 'system'): void {
  if (state.settingsMode !== 'house') {
    return;
  }

  const previousSubMode = state.houseSettingsSubMode;
  if (previousSubMode === nextSubMode) {
    return;
  }

  state.houseSettingsSubMode = nextSubMode;
  if (source === 'menu') {
    state.settingsMenuOpen = true;
  }
  if (nextSubMode !== 'import') {
    resetHouseDraftSelection();
    state.houseValidation = null;
  }

  if (nextSubMode === 'import') {
    void refreshHouseCatalog({ silent: true });
  }

  state.modeNote = describeHouseSubModeNote(nextSubMode, source);
  refreshPage();
}

function setFurnitureSettingsSubMode(nextSubMode: TyxtFurnitureSettingsSubMode, source: 'menu' | 'system'): void {
  if (state.settingsMode !== 'furniture') {
    return;
  }
  const previousSubMode = state.furnitureSettingsSubMode;
  if (previousSubMode === nextSubMode) {
    return;
  }
  state.furnitureSettingsSubMode = nextSubMode;
  if (source === 'menu') {
    state.settingsMenuOpen = true;
  }
  if (nextSubMode !== 'import') {
    resetFurnitureDraftSelection();
  }
  if (nextSubMode !== 'place') {
    state.furniturePlacementPanelOpen = false;
  }
  if (nextSubMode === 'import' || nextSubMode === 'place') {
    void refreshFurnitureCatalog({ silent: true });
  }
  if (nextSubMode === 'place') {
    state.furniturePlacementAssetId = null;
    state.furniturePlacementDirection = 'front';
  }
  state.modeNote = describeFurnitureSubModeNote(nextSubMode, source);
  applyFurniturePlacementTemplateToScene();
  refreshPage();
}

function setInteractionSettingsSubMode(nextSubMode: TyxtInteractionSettingsSubMode, source: 'menu' | 'system'): void {
  if (state.settingsMode !== 'interaction') {
    return;
  }
  const previousSubMode = state.interactionSettingsSubMode;
  if (previousSubMode === nextSubMode) {
    return;
  }
  state.interactionSettingsSubMode = nextSubMode;
  state.interactionEditorModalOpen = false;
  state.interactionEditorDraft = null;
  state.interactionEditorMessage = null;
  state.interactionEditorMessageTone = null;
  if (source === 'menu') {
    state.settingsMenuOpen = true;
  }
  state.modeNote = describeInteractionSubModeNote(nextSubMode, source);
  refreshPage();
}

function describeHouseSubModeNote(nextSubMode: TyxtHouseSettingsSubMode, source: 'menu' | 'system'): string {
  if (nextSubMode === 'import') {
    return '房屋导入面板已打开。';
  }
  if (nextSubMode === 'wall') {
    return source === 'menu' ? '墙壁设置已进入。可选择图形并在场景中编辑。' : '墙壁设置已同步。';
  }
  if (nextSubMode === 'label') {
    return source === 'menu' ? '房屋名编辑已进入。拖拽主图中的房屋名称可调整位置。' : '房屋名编辑已同步。';
  }
  return '房屋子菜单已收起。';
}

function describeFurnitureSubModeNote(nextSubMode: TyxtFurnitureSettingsSubMode, source: 'menu' | 'system'): string {
  if (nextSubMode === 'import') {
    return '家具导入面板已打开。';
  }
  if (nextSubMode === 'place') {
    return source === 'menu'
      ? '家具摆放模式已进入。请先点分类，再选具体家具。'
      : '家具摆放模式已同步。';
  }
  return '家具子菜单已收起。';
}

function describeInteractionSubModeNote(nextSubMode: TyxtInteractionSettingsSubMode, source: 'menu' | 'system'): string {
  if (nextSubMode === 'action_point') {
    return source === 'menu'
      ? '交互设置：动作点模式已进入。可拖拽位置并打开编辑窗口。'
      : '动作点模式已同步。';
  }
  if (nextSubMode === 'interaction_box') {
    return source === 'menu'
      ? '交互设置：交互框模式已进入。可拖拽位置并打开编辑窗口。'
      : '交互框模式已同步。';
  }
  return '交互子菜单已收起。';
}

function describeSettingsModeNote(nextMode: TyxtSettingsMode | null, source: 'menu' | 'scene' | 'system'): string {
  if (!nextMode) {
    if (source === 'scene') {
      return '场景编辑已回到普通视图。';
    }
    return '已退出设置模式。';
  }

  if (nextMode === 'house') {
    return '设置菜单：房屋。请选择“房屋导入”“墙壁设置”或“房屋名”。';
  }
  if (nextMode === 'furniture') {
    return source === 'scene'
      ? '场景工具切换：家具。'
      : '设置菜单：家具。请选择“导入家具”或“摆放家具”。';
  }
  if (nextMode === 'character') {
    return '设置菜单：人物设置已打开。';
  }
  if (nextMode === 'interaction') {
    return source === 'scene'
      ? '场景工具切换：交互。'
      : '设置菜单：交互。请选择“动作点”或“交互框”。';
  }
  return '设置菜单：商店占位页已打开。';
}

function isEditorLinkedSettingsMode(_mode: TyxtSettingsMode | null): _mode is 'interaction' {
  return false;
}

function getSceneInteractionEditorSnapshot(): TyxtInteractionEditorSnapshot | null {
  const activeScene = getActiveScene();
  if (!activeScene) {
    return null;
  }
  return activeScene.getInteractionEditorSnapshot() as TyxtInteractionEditorSnapshot;
}

function openInteractionEditorModal(): void {
  if (state.settingsMode !== 'interaction' || state.interactionSettingsSubMode === null) {
    return;
  }
  const snapshot = getSceneInteractionEditorSnapshot();
  if (!snapshot) {
    state.interactionEditorMessage = '场景尚未就绪，暂时无法编辑。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }

  if (state.interactionSettingsSubMode === 'action_point') {
    const target = snapshot.actionPoints.find((item) => item.id === snapshot.selectedActionPointId)
      ?? snapshot.actionPoints[0]
      ?? null;
    if (!target) {
      state.interactionEditorMessage = '当前没有可编辑的动作点。';
      state.interactionEditorMessageTone = 'error';
      refreshPage();
      return;
    }
    state.interactionEditorDraft = {
      kind: 'action_point',
      id: target.id,
      label: target.label || target.id,
      interactionType: target.interaction_type || 'inspect',
      spriteKey: normalizeInteractionSpriteAssetPath(String(target.sprite_key || '')),
      spriteTotalFramesInput: String(target.sprite_total_frames ?? 1),
      spriteFrameWidthInput: String(target.sprite_frame_width ?? 64),
      spriteFrameHeightInput: String(target.sprite_frame_height ?? 64),
      spriteFpsInput: String(target.sprite_fps ?? 8)
    };
  } else {
    const target = snapshot.interactionBoxes.find((item) => item.id === snapshot.selectedInteractionBoxId)
      ?? snapshot.interactionBoxes[0]
      ?? null;
    if (!target) {
      state.interactionEditorMessage = '当前没有可编辑的交互框。';
      state.interactionEditorMessageTone = 'error';
      refreshPage();
      return;
    }
    state.interactionEditorDraft = {
      kind: 'interaction_box',
      id: target.id,
      label: target.label || target.id,
      interactionName: target.interaction_name || '默认交互',
      interactionType: target.interaction_type || 'inspect',
      spriteKey: normalizeInteractionSpriteAssetPath(String(target.sprite_key || '')),
      spriteTotalFramesInput: String(target.sprite_total_frames ?? 1),
      spriteFrameWidthInput: String(target.sprite_frame_width ?? 64),
      spriteFrameHeightInput: String(target.sprite_frame_height ?? 64),
      spriteFpsInput: String(target.sprite_fps ?? 8)
    };
  }

  state.interactionEditorModalOpen = true;
  state.interactionEditorMessage = null;
  state.interactionEditorMessageTone = null;
  refreshPage();
}

function closeInteractionEditorModal(): void {
  state.interactionEditorModalOpen = false;
  state.interactionEditorDraft = null;
  state.interactionEditorMessage = null;
  state.interactionEditorMessageTone = null;
  stopInteractionSpritePreview();
  refreshPage();
}

function applyInteractionEditorDraftToScene(): void {
  const activeScene = getActiveScene();
  const draft = state.interactionEditorDraft;
  if (!activeScene || !draft) {
    state.interactionEditorMessage = '场景或编辑草稿不可用，请重试。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }

  const rawSpriteKey = String(draft.spriteKey || '').trim();
  const spriteKey = normalizeInteractionSpriteAssetPath(rawSpriteKey);
  if (rawSpriteKey && !spriteKey) {
    state.interactionEditorMessage = '动作精灵图路径不可用，请填写资源管理器中的 asset_url（例如 /assets/...）。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }
  const spriteTotalFrames = parsePositiveIntInput(draft.spriteTotalFramesInput, 1);
  const spriteFrameWidth = parsePositiveIntInput(draft.spriteFrameWidthInput, 64);
  const spriteFrameHeight = parsePositiveIntInput(draft.spriteFrameHeightInput, 64);
  const spriteFps = parsePositiveNumberInput(draft.spriteFpsInput, 8);
  const normalizedLabel = draft.label.trim() || draft.id;
  const normalizedInteractionType = draft.interactionType.trim() || 'inspect';

  const applied = draft.kind === 'action_point'
    ? activeScene.updateSelectedInteractionPointMeta({
      label: normalizedLabel,
      interaction_type: normalizedInteractionType,
      sprite_key: spriteKey,
      sprite_total_frames: spriteTotalFrames,
      sprite_frame_width: spriteFrameWidth,
      sprite_frame_height: spriteFrameHeight,
      sprite_fps: spriteFps
    }, { persist: false })
    : activeScene.updateSelectedInteractionBoxMeta({
      label: normalizedLabel,
      interaction_name: draft.interactionName.trim() || '默认交互',
      interaction_type: normalizedInteractionType,
      sprite_key: spriteKey,
      sprite_total_frames: spriteTotalFrames,
      sprite_frame_width: spriteFrameWidth,
      sprite_frame_height: spriteFrameHeight,
      sprite_fps: spriteFps
    }, { persist: false });

  if (!applied) {
    state.interactionEditorMessage = '未能应用到当前选中项，请先在场景中选中目标后再编辑。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }

  state.interactionEditorMessage = '参数已应用到当前项，点击右下角“保存”即可持久化。';
  state.interactionEditorMessageTone = 'ok';
  state.modeNote = '交互参数已更新，等待保存。';
  refreshPage();
}

async function refreshHouseCatalog(options: { silent?: boolean } = {}): Promise<void> {
  if (state.houseCatalogLoading) {
    return;
  }
  state.houseCatalogLoading = true;
  state.houseCatalogError = null;
  if (!options.silent) {
    refreshPage();
  }

  try {
    const response = await fetch(`/api/tyxt/houses?t=${Date.now()}`, { cache: 'no-store' });
    const payload = await response.json() as TyxtHouseCatalogPayload;
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || `houses ${response.status}`));
    }
    applyHouseCatalogPayload(payload);
    if (hasDropScanActivities(payload.drop_scan_report)) {
      state.houseMessage = summarizeDropScanReport(payload.drop_scan_report);
      state.houseMessageTone = payload.drop_scan_report?.failed ? 'error' : 'ok';
    }
    if (!state.houseCurrentId) {
      state.houseMessage = null;
      state.houseMessageTone = null;
    }
  } catch (error) {
    state.houseCatalogError = `房屋列表加载失败：${error instanceof Error ? error.message : String(error)}`;
  } finally {
    state.houseCatalogLoading = false;
    refreshPage();
  }
}

async function scanHouseDropFolder(): Promise<void> {
  if (state.houseCatalogLoading) {
    return;
  }
  state.houseCatalogLoading = true;
  state.houseCatalogError = null;
  state.houseMessage = '正在扫描地图文件夹...';
  state.houseMessageTone = 'info';
  refreshPage();

  try {
    const response = await fetch('/api/tyxt/houses/scan-drop-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: '{}'
    });
    const payload = await response.json() as TyxtHouseCatalogPayload;
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || `scan-drop-folder ${response.status}`));
    }
    applyHouseCatalogPayload(payload);
    const reportSummary = summarizeDropScanReport(payload.drop_scan_report);
    state.houseMessage = reportSummary;
    state.houseMessageTone = payload.drop_scan_report?.failed ? 'error' : 'ok';
  } catch (error) {
    state.houseMessage = `扫描失败：${error instanceof Error ? error.message : String(error)}`;
    state.houseMessageTone = 'error';
  } finally {
    state.houseCatalogLoading = false;
    refreshPage();
  }
}

function applyHouseCatalogPayload(payload: TyxtHouseCatalogPayload): void {
  const rawHouses = Array.isArray(payload.houses) ? payload.houses : [];
  const nextCurrentId = String(payload.current_house_id || '').trim() || null;
  state.houseCatalog = rawHouses.map((row): TyxtHouseItem => {
    const normalizedFormat: TyxtHouseFormat = normalizeHouseFormat(String(row.format || 'png')) === 'webp' ? 'webp' : 'png';
    return {
      id: String(row.id || '').trim(),
      name: String(row.name || '').trim() || String(row.id || '').trim() || '未命名房屋',
      file_name: String(row.file_name || '').trim(),
      width: Number(row.width) || 0,
      height: Number(row.height) || 0,
      ratio: Number(row.ratio) || 0,
      format: normalizedFormat,
      file_size: Number(row.file_size) || 0,
      imported_at: String(row.imported_at || ''),
      asset_url: String(row.asset_url || ''),
      is_current: nextCurrentId !== null && String(row.id || '').trim() === nextCurrentId
    };
  }).filter((item) => !!item.id && !!item.asset_url);
  state.houseCurrentId = nextCurrentId ?? state.houseCatalog.find((item) => item.is_current)?.id ?? null;
  state.houseBaselineId = String(payload.baseline_house_id || '').trim() || null;
  state.houseBaselineRatio = Number.isFinite(Number(payload.baseline_ratio))
    ? Number(payload.baseline_ratio)
    : (state.houseCatalog[0]?.ratio ?? null);
  state.houseRatioTolerance = Number.isFinite(Number(payload.ratio_tolerance))
    ? Number(payload.ratio_tolerance)
    : HOUSE_RATIO_TOLERANCE;
  state.houseDropFolderPath = String(payload.drop_folder_path || '').trim() || null;
}

function summarizeDropScanReport(report: TyxtHouseCatalogPayload['drop_scan_report']): string {
  if (!report) {
    return '扫描完成。';
  }
  const imported = Number(report.imported) || 0;
  const skipped = Number(report.skipped) || 0;
  const failed = Number(report.failed) || 0;
  const firstNote = Array.isArray(report.notes) && report.notes.length > 0 ? String(report.notes[0]) : '';
  if (imported === 0 && skipped === 0 && failed === 0) {
    return '扫描完成：地图文件夹中没有可导入文件。';
  }
  const summary = `扫描完成：导入 ${imported}，跳过 ${skipped}，失败 ${failed}。`;
  return firstNote ? `${summary} ${firstNote}` : summary;
}

function hasDropScanActivities(report: TyxtHouseCatalogPayload['drop_scan_report']): boolean {
  if (!report) {
    return false;
  }
  const imported = Number(report.imported) || 0;
  const skipped = Number(report.skipped) || 0;
  const failed = Number(report.failed) || 0;
  return imported > 0 || skipped > 0 || failed > 0;
}

async function copyHouseDropFolderPath(): Promise<void> {
  const dropFolderPath = String(state.houseDropFolderPath || '').trim();
  if (!dropFolderPath) {
    state.houseMessage = '暂未读取到地图文件夹路径，请先刷新列表。';
    state.houseMessageTone = 'error';
    refreshPage();
    return;
  }

  try {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
      throw new Error('当前浏览器不支持剪贴板写入');
    }
    await navigator.clipboard.writeText(dropFolderPath);
    state.houseMessage = `已复制地图文件夹路径：${dropFolderPath}`;
    state.houseMessageTone = 'ok';
  } catch (error) {
    state.houseMessage = `复制失败，请手动复制路径：${dropFolderPath}（${error instanceof Error ? error.message : String(error)}）`;
    state.houseMessageTone = 'error';
  }
  refreshPage();
}

type FilePickerLikeHandle = {
  getFile: () => Promise<File>;
};

type WindowWithFilePicker = typeof window & {
  showOpenFilePicker?: (options?: {
    multiple?: boolean;
    excludeAcceptAllOption?: boolean;
    types?: Array<{
      description?: string;
      accept?: Record<string, string[]>;
    }>;
  }) => Promise<FilePickerLikeHandle[]>;
};

async function triggerHouseFilePicker(): Promise<void> {
  const pickerHost = window as WindowWithFilePicker;
  if (typeof pickerHost.showOpenFilePicker === 'function') {
    try {
      const handles = await pickerHost.showOpenFilePicker({
        multiple: false,
        excludeAcceptAllOption: false,
        types: [
          {
            description: '房屋图片（PNG / WebP）',
            accept: {
              'image/png': ['.png'],
              'image/webp': ['.webp']
            }
          }
        ]
      });
      const file = handles?.[0] ? await handles[0].getFile() : null;
      if (file) {
        await selectHouseDraftFile(file);
        return;
      }
    } catch (error) {
      const errorName = error instanceof DOMException ? error.name : '';
      if (errorName === 'AbortError') {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      state.houseMessage = `原生文件选择器打开失败，已切换到标准选择方式：${message}`;
      state.houseMessageTone = 'error';
      refreshPage();
    }
  }

  const input = document.getElementById('house-file-input') as HTMLInputElement | null;
  if (!input) {
    state.houseMessage = '未找到文件选择控件，请刷新页面后重试。';
    state.houseMessageTone = 'error';
    refreshPage();
    return;
  }
  input.click();
}

async function triggerInteractionSpriteFilePicker(): Promise<void> {
  if (!state.interactionEditorModalOpen || !state.interactionEditorDraft) {
    state.interactionEditorMessage = '请先打开动作点编辑面板，再选择精灵图。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }

  const pickerHost = window as WindowWithFilePicker;
  if (typeof pickerHost.showOpenFilePicker === 'function') {
    try {
      const handles = await pickerHost.showOpenFilePicker({
        multiple: false,
        excludeAcceptAllOption: false,
        types: [
          {
            description: '精灵图文件（PNG / WebP / GIF）',
            accept: {
              'image/png': ['.png'],
              'image/webp': ['.webp'],
              'image/gif': ['.gif']
            }
          }
        ]
      });
      const file = handles?.[0] ? await handles[0].getFile() : null;
      if (file) {
        await selectInteractionSpriteFile(file);
      }
      return;
    } catch (error) {
      const errorName = error instanceof DOMException ? error.name : '';
      if (errorName === 'AbortError') {
        return;
      }
    }
  }

  const input = document.getElementById('interaction-edit-sprite-file-input') as HTMLInputElement | null;
  if (!input) {
    state.interactionEditorMessage = '未找到精灵图文件选择控件，请刷新页面后重试。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }
  input.click();
}

async function selectInteractionSpriteFile(nextFile: File | null): Promise<void> {
  if (!nextFile) {
    return;
  }
  if (!state.interactionEditorModalOpen || !state.interactionEditorDraft) {
    return;
  }
  const mimeType = String(nextFile.type || '').toLowerCase();
  if (mimeType && !mimeType.startsWith('image/')) {
    state.interactionEditorMessage = '请选择图片文件（PNG / WebP / GIF）。';
    state.interactionEditorMessageTone = 'error';
    refreshPage();
    return;
  }

  try {
    const knownAssetPath = await resolveKnownInteractionSpriteAssetPathForFile(nextFile);
    if (knownAssetPath) {
      state.interactionEditorDraft.spriteKey = knownAssetPath;
      state.interactionEditorMessage = `已选择精灵图：${nextFile.name}（已使用资源路径）`;
      state.interactionEditorMessageTone = 'ok';
      refreshPage();
      return;
    }

    const base64 = await readFileAsBase64(nextFile);
    const safeMimeType = mimeType && mimeType.startsWith('image/') ? mimeType : 'image/png';
    state.interactionEditorDraft.spriteKey = `data:${safeMimeType};base64,${base64}`;
    state.interactionEditorMessage = `已选择精灵图：${nextFile.name}`;
    state.interactionEditorMessageTone = 'ok';
  } catch (error) {
    state.interactionEditorMessage = `读取精灵图失败：${error instanceof Error ? error.message : String(error)}`;
    state.interactionEditorMessageTone = 'error';
  }
  refreshPage();
}

async function setCurrentHouse(houseId: string): Promise<void> {
  const normalizedHouseId = String(houseId || '').trim();
  if (!normalizedHouseId || state.houseImporting || state.houseSettingCurrentId) {
    return;
  }
  state.houseSettingCurrentId = normalizedHouseId;
  state.houseMessage = null;
  state.houseMessageTone = null;
  refreshPage();

  try {
    const payload = await fetchJsonWithTimeout<TyxtHouseCatalogPayload>('/api/tyxt/houses/set-current', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ house_id: normalizedHouseId })
    }, 12_000);
    if (!payload.ok) {
      throw new Error(String(payload.error || 'set-current failed'));
    }
    applyHouseCatalogPayload(payload);
    state.houseMessage = '已切换当前房屋，场景底板已更新。';
    state.houseMessageTone = 'ok';
    state.modeNote = `房屋切换：${normalizedHouseId}`;
  } catch (error) {
    state.houseMessage = `切换失败：${error instanceof Error ? error.message : String(error)}`;
    state.houseMessageTone = 'error';
  } finally {
    state.houseSettingCurrentId = null;
    refreshPage();
  }
}

async function selectHouseDraftFile(nextFile: File | null): Promise<void> {
  if (!nextFile) {
    return;
  }
  resetHouseDraftSelection();
  let previewUrl = '';
  try {
    previewUrl = URL.createObjectURL(nextFile);
    const provisionalFormat = normalizeHouseFormat(nextFile.type || nextFile.name);
    state.houseDraft = {
      file: nextFile,
      preview_url: previewUrl,
      file_name: nextFile.name,
      mime_type: nextFile.type,
      file_size: nextFile.size,
      width: 0,
      height: 0,
      ratio: 0,
      format: provisionalFormat
    };
    state.houseValidation = null;
    state.houseMessage = '已加载预览，正在读取图片尺寸...';
    state.houseMessageTone = 'info';
    refreshPage();

    const dimensions = await readImageDimensions(previewUrl);
    state.houseDraft = {
      file: nextFile,
      preview_url: previewUrl,
      file_name: nextFile.name,
      mime_type: nextFile.type,
      file_size: nextFile.size,
      width: dimensions.width,
      height: dimensions.height,
      ratio: dimensions.width > 0 && dimensions.height > 0 ? dimensions.width / dimensions.height : 0,
      format: provisionalFormat
    };
    state.houseValidation = null;
    state.houseMessage = null;
    state.houseMessageTone = null;
    refreshPage();
  } catch (error) {
    if (!state.houseDraft && previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    state.houseValidation = null;
    state.houseMessage = `图片预览已加载，但读取尺寸失败：${error instanceof Error ? error.message : String(error)}`;
    state.houseMessageTone = 'error';
    refreshPage();
  }
}

function runHouseDraftValidation(): void {
  if (!state.houseDraft) {
    return;
  }
  const baselineRatio = state.houseBaselineRatio;
  const report = validateHouseDraft(state.houseDraft, baselineRatio, state.houseRatioTolerance);
  state.houseValidation = report;
  state.houseMessage = report.passed ? '检查通过，可导入。' : '检查未通过，请按建议修正图片后重试。';
  state.houseMessageTone = report.passed ? 'ok' : 'error';
  refreshPage();
}

function validateHouseDraft(
  draft: TyxtHouseUploadDraft,
  baselineRatio: number | null,
  tolerance: number
): TyxtHouseValidationReport {
  const normalizedMime = String(draft.mime_type || '').trim().toLowerCase();
  const mimeSupported = !normalizedMime || HOUSE_ALLOWED_MIME_TYPES.has(normalizedMime);
  const formatLabel = draft.format === 'unknown' ? draft.mime_type || '未知格式' : draft.format.toUpperCase();
  const formatPass = (draft.format === 'png' || draft.format === 'webp') && mimeSupported;
  const fileSizePass = draft.file_size > 0 && draft.file_size <= HOUSE_MAX_FILE_BYTES;
  const dimensionsReadable = draft.width > 0 && draft.height > 0;
  const minSizePass = dimensionsReadable && draft.width >= HOUSE_MIN_WIDTH && draft.height >= HOUSE_MIN_HEIGHT;
  const normalizedBaseline = Number.isFinite(Number(baselineRatio)) ? Number(baselineRatio) : null;
  const ratioDelta = normalizedBaseline && normalizedBaseline > 0
    ? Math.abs(draft.ratio - normalizedBaseline) / normalizedBaseline
    : null;
  const ratioPass = ratioDelta === null ? true : ratioDelta <= tolerance;

  const reasons: string[] = [];
  const suggestions: string[] = [];

  if (!formatPass) {
    reasons.push('仅支持 PNG / WebP 图片格式。');
    suggestions.push('请导出为 PNG 或 WebP 后再导入。');
  }
  if (!fileSizePass) {
    reasons.push('文件大小超过 5MB 或文件为空。');
    suggestions.push('请压缩图片到 5MB 以内。');
  }
  if (!dimensionsReadable) {
    reasons.push('无法读取图片尺寸信息。');
    suggestions.push('请确认图片文件未损坏，并重新导出为 PNG / WebP 后重试。');
  } else if (!minSizePass) {
    reasons.push(`图片尺寸过小，最低要求 ${HOUSE_MIN_WIDTH} × ${HOUSE_MIN_HEIGHT}。`);
    suggestions.push('请使用更高分辨率图片导入。');
  }
  if (normalizedBaseline !== null && normalizedBaseline > 0 && !ratioPass) {
    reasons.push('图片比例与当前默认房屋基准图不一致。');
    suggestions.push('请裁切或导出为与基准图相同比例的 PNG / WebP 图片。');
  }

  return {
    passed: reasons.length === 0,
    file_name: draft.file_name,
    format_label: formatLabel,
    format_pass: formatPass,
    file_size: draft.file_size,
    file_size_pass: fileSizePass,
    width: draft.width,
    height: draft.height,
    min_size_pass: minSizePass,
    current_ratio: draft.ratio,
    baseline_ratio: normalizedBaseline,
    ratio_pass: ratioPass,
    ratio_delta_percent: ratioDelta === null ? null : ratioDelta * 100,
    reasons,
    suggestions
  };
}

async function importHouseDraft(makeCurrent: boolean): Promise<void> {
  const draft = state.houseDraft;
  if (!draft || !state.houseValidation?.passed || state.houseImporting) {
    return;
  }

  state.houseImporting = true;
  state.houseMessage = null;
  state.houseMessageTone = null;
  refreshPage();

  try {
    const dataBase64 = await readFileAsBase64(draft.file);
    const payload = await fetchJsonWithTimeout<TyxtHouseCatalogPayload>('/api/tyxt/houses/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        file_name: draft.file_name,
        mime_type: draft.mime_type,
        data_base64: dataBase64,
        name: deriveHouseNameFromFile(draft.file_name),
        make_current: makeCurrent
      })
    }, 15_000);
    if (!payload.ok) {
      throw new Error(String(payload.error || 'house import failed'));
    }

    applyHouseCatalogPayload(payload);
    resetHouseDraftSelection();
    state.houseValidation = null;
    state.houseMessage = makeCurrent ? '导入成功，已设为当前房屋。' : '导入成功，房屋列表已刷新。';
    state.houseMessageTone = 'ok';
    state.modeNote = makeCurrent ? '房屋导入并切换完成' : '房屋导入完成';
  } catch (error) {
    state.houseMessage = `导入失败：${error instanceof Error ? error.message : String(error)}`;
    state.houseMessageTone = 'error';
  } finally {
    state.houseImporting = false;
    refreshPage();
  }
}

async function fetchJsonWithTimeout<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number
): Promise<T> {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), Math.max(1500, timeoutMs));
  try {
    const response = await fetch(input, {
      ...init,
      signal: controller.signal
    });
    const payload = await response.json() as T;
    if (!response.ok) {
      const payloadRecord = (typeof payload === 'object' && payload !== null)
        ? payload as Record<string, unknown>
        : null;
      const errorText = payloadRecord && 'error' in payloadRecord
        ? String(payloadRecord.error || `HTTP ${response.status}`)
        : `HTTP ${response.status}`;
      throw new Error(errorText);
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('请求超时，请重试。');
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

function resetHouseDraftSelection(): void {
  if (state.houseDraft?.preview_url) {
    URL.revokeObjectURL(state.houseDraft.preview_url);
  }
  state.houseDraft = null;
}

async function refreshFurnitureCatalog(options: { silent?: boolean } = {}): Promise<void> {
  if (state.furnitureCatalogLoading) {
    return;
  }
  state.furnitureCatalogLoading = true;
  state.furnitureCatalogError = null;
  if (!options.silent) {
    refreshPage();
  }
  try {
    const response = await fetch(`/api/tyxt/furniture/catalog?t=${Date.now()}`, { cache: 'no-store' });
    const payload = await response.json() as TyxtFurnitureCatalogPayload;
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || `furniture catalog ${response.status}`));
    }
    const raw = Array.isArray(payload.assets) ? payload.assets : [];
    state.furnitureCatalog = raw.filter((item) => !!item?.id);
    if (state.furniturePlacementAssetId) {
      const stillExists = state.furnitureCatalog.some((item) => item.id === state.furniturePlacementAssetId);
      if (!stillExists) {
        state.furniturePlacementAssetId = null;
      }
    }
    applyFurniturePlacementTemplateToScene();
  } catch (error) {
    state.furnitureCatalogError = `家具列表加载失败：${error instanceof Error ? error.message : String(error)}`;
  } finally {
    state.furnitureCatalogLoading = false;
    refreshPage();
  }
}

async function saveActorSettings(): Promise<void> {
  if (state.actorSettingsSaving) {
    return;
  }
  const validActorIds = actorCatalogIdSet();
  if (validActorIds.size === 0) {
    state.actorSettingsMessage = '未找到可用人物资源，无法保存。';
    state.actorSettingsMessageTone = 'error';
    refreshPage();
    return;
  }

  const assignments: Record<string, string> = {};
  const fallbackActorId = defaultActorId();
  for (const agent of agentRowsForActorSettings()) {
    const draftActorId = normalizeActorFolderId(state.agentActorDraftAssignments[agent.agent_id]);
    assignments[agent.agent_id] = draftActorId && validActorIds.has(draftActorId) ? draftActorId : fallbackActorId;
  }

  state.actorSettingsSaving = true;
  state.actorSettingsMessage = null;
  state.actorSettingsMessageTone = null;
  refreshPage();
  try {
    const payload = await fetchJsonWithTimeout<TyxtActorSettingsPayload>('/api/tyxt/agent-actors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ assignments })
    }, 10_000);
    if (!payload.ok) {
      throw new Error(String(payload.error || 'agent-actors save failed'));
    }
    state.actorCatalog = Array.isArray(payload.actors)
      ? payload.actors
        .map((actor) => ({
          id: normalizeActorFolderId(actor.id),
          name: String(actor.name || actor.id || '').trim(),
          demo_url: String(actor.demo_url || '').trim()
        }))
        .filter((actor) => Boolean(actor.id))
      : state.actorCatalog;
    state.agentActorAssignments = normalizeActorAssignments(payload.assignments);
    initializeActorDraftAssignments();
    state.actorSettingsMessage = '人物设置已保存。';
    state.actorSettingsMessageTone = 'ok';
    state.modeNote = '人物设置已保存。';
  } catch (error) {
    state.actorSettingsMessage = `保存失败：${error instanceof Error ? error.message : String(error)}`;
    state.actorSettingsMessageTone = 'error';
  } finally {
    state.actorSettingsSaving = false;
    refreshPage();
  }
}

function resetFurnitureDraftSelection(): void {
  if (state.furnitureSpriteSheetDraft?.preview_url) {
    URL.revokeObjectURL(state.furnitureSpriteSheetDraft.preview_url);
  }
  state.furnitureSpriteSheetDraft = null;
  state.furnitureDraftByDirection = {};
}

function shiftFurnitureImportDirection(step: number): void {
  const currentIndex = FURNITURE_IMPORT_DIRECTION_ORDER.indexOf(state.furnitureImportDirection);
  const nextIndex = (currentIndex + step + FURNITURE_IMPORT_DIRECTION_ORDER.length) % FURNITURE_IMPORT_DIRECTION_ORDER.length;
  state.furnitureImportDirection = FURNITURE_IMPORT_DIRECTION_ORDER[nextIndex];
  refreshPage();
}

async function triggerFurnitureFilePicker(): Promise<void> {
  const pickerHost = window as WindowWithFilePicker;
  if (typeof pickerHost.showOpenFilePicker === 'function') {
    try {
      const handles = await pickerHost.showOpenFilePicker({
        multiple: false,
        excludeAcceptAllOption: false,
        types: [
          {
            description: '家具图片（PNG / WebP）',
            accept: {
              'image/png': ['.png'],
              'image/webp': ['.webp']
            }
          }
        ]
      });
      const file = handles?.[0] ? await handles[0].getFile() : null;
      if (file) {
        await selectFurnitureSpriteSheetFile(file);
      }
      return;
    } catch (error) {
      const errorName = error instanceof DOMException ? error.name : '';
      if (errorName === 'AbortError') {
        return;
      }
    }
  }
  const input = document.getElementById('furniture-file-input') as HTMLInputElement | null;
  input?.click();
}

async function selectFurnitureSpriteSheetFile(nextFile: File | null): Promise<void> {
  if (!nextFile) {
    return;
  }
  let previewUrl = '';
  try {
    previewUrl = URL.createObjectURL(nextFile);
    const dimensions = await readImageDimensions(previewUrl);
    const format = normalizeFurnitureFormat(nextFile.type || nextFile.name);
    const draft: TyxtFurnitureDraftDirection = {
      file: nextFile,
      preview_url: previewUrl,
      file_name: nextFile.name,
      mime_type: nextFile.type,
      file_size: nextFile.size,
      width: dimensions.width,
      height: dimensions.height,
      format
    };
    if (state.furnitureSpriteSheetDraft?.preview_url) {
      URL.revokeObjectURL(state.furnitureSpriteSheetDraft.preview_url);
    }
    state.furnitureSpriteSheetDraft = draft;
    state.furnitureDraftByDirection = {};
    state.furnitureMessage = `精灵图已选择：${draft.width}×${draft.height}，${formatBytes(draft.file_size)}。`;
    state.furnitureMessageTone = 'info';
  } catch (error) {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    state.furnitureMessage = `读取家具图片失败：${error instanceof Error ? error.message : String(error)}`;
    state.furnitureMessageTone = 'error';
  }
  refreshPage();
}

function normalizeFurnitureFormat(input: string): TyxtFurnitureFormat | 'unknown' {
  const value = String(input || '').trim().toLowerCase();
  if (value === 'image/png' || value.endsWith('.png') || value === 'png') {
    return 'png';
  }
  if (value === 'image/webp' || value.endsWith('.webp') || value === 'webp') {
    return 'webp';
  }
  return 'unknown';
}

function validateFurnitureDraftDirection(
  draft: TyxtFurnitureDraftDirection,
  spriteCell: TyxtFurnitureSpriteCellSetting
): string | null {
  const mime = String(draft.mime_type || '').toLowerCase().trim();
  if (!(draft.format === 'png' || draft.format === 'webp')) {
    return '仅支持 PNG / WebP。';
  }
  if (mime && !FURNITURE_ALLOWED_MIME_TYPES.has(mime)) {
    return '图片 MIME 类型不受支持。';
  }
  if (draft.file_size <= 0 || draft.file_size > FURNITURE_MAX_FILE_BYTES) {
    return '文件大小必须在 0~5MB。';
  }
  if (draft.width < FURNITURE_MIN_WIDTH || draft.height < FURNITURE_MIN_HEIGHT) {
    return `尺寸过小（最低 ${FURNITURE_MIN_WIDTH}×${FURNITURE_MIN_HEIGHT}）。`;
  }
  if (!spriteCell.valid) {
    return spriteCell.reason || '精灵单格尺寸不合法。';
  }
  if (spriteCell.width > draft.width || spriteCell.height > draft.height) {
    return `单格 ${spriteCell.width}×${spriteCell.height} 超出原图 ${draft.width}×${draft.height}。`;
  }
  return null;
}

async function importFurnitureDraft(): Promise<void> {
  if (state.furnitureImporting) {
    return;
  }
  const spriteCell = parseFurnitureSpriteCellSetting();
  if (!spriteCell.valid) {
    state.furnitureMessage = spriteCell.reason || '请先设置合法的精灵单格尺寸。';
    state.furnitureMessageTone = 'error';
    refreshPage();
    return;
  }
  const name = state.furnitureImportName.trim();
  if (!name) {
    state.furnitureMessage = '请输入家具名称。';
    state.furnitureMessageTone = 'error';
    refreshPage();
    return;
  }
  const spriteSheetDraft = state.furnitureSpriteSheetDraft;
  if (!spriteSheetDraft) {
    state.furnitureMessage = '请先选择精灵图。';
    state.furnitureMessageTone = 'error';
    refreshPage();
    return;
  }
  const errorText = validateFurnitureDraftDirection(spriteSheetDraft, spriteCell);
  if (errorText) {
    state.furnitureMessage = `精灵图不合法：${errorText}`;
    state.furnitureMessageTone = 'error';
    refreshPage();
    return;
  }
  state.furnitureImporting = true;
  state.furnitureMessage = null;
  state.furnitureMessageTone = null;
  refreshPage();
  try {
    const spriteSheetBase64 = await readFileAsBase64(spriteSheetDraft.file);
    const response = await fetch('/api/tyxt/furniture/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        category: state.furnitureImportCategory,
        name,
        sprite_cell: {
          width: spriteCell.width,
          height: spriteCell.height
        },
        sprite_sheet: {
          file_name: spriteSheetDraft.file_name,
          mime_type: spriteSheetDraft.mime_type,
          data_base64: spriteSheetBase64
        }
      })
    });
    const payload = await response.json() as TyxtFurnitureCatalogPayload;
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || `furniture import ${response.status}`));
    }
    await refreshFurnitureCatalog({ silent: true });
    resetFurnitureDraftSelection();
    state.furnitureImportName = '';
    state.furnitureMessage = '家具导入成功。';
    state.furnitureMessageTone = 'ok';
  } catch (error) {
    state.furnitureMessage = `家具导入失败：${error instanceof Error ? error.message : String(error)}`;
    state.furnitureMessageTone = 'error';
  } finally {
    state.furnitureImporting = false;
    refreshPage();
  }
}

function cycleFurniturePlacementDirection(step: number): void {
  const activeScene = getActiveScene();
  if (activeScene?.rotateSelectedFurnitureFacing(step)) {
    state.modeNote = step < 0 ? '已切换选中家具朝向：左向。' : '已切换选中家具朝向：右向。';
    refreshPage();
    return;
  }
  const index = FURNITURE_PLACEMENT_TURN_ORDER.indexOf(state.furniturePlacementDirection);
  const normalizedIndex = index === -1 ? 0 : index;
  const nextIndex = (normalizedIndex + step + FURNITURE_PLACEMENT_TURN_ORDER.length) % FURNITURE_PLACEMENT_TURN_ORDER.length;
  state.furniturePlacementDirection = FURNITURE_PLACEMENT_TURN_ORDER[nextIndex];
  applyFurniturePlacementTemplateToScene();
  state.modeNote = step < 0 ? '已切换摆放模板朝向：左向。' : '已切换摆放模板朝向：右向。';
  refreshPage();
}

function scaleFurniturePlacementSelection(step: number): void {
  const activeScene = getActiveScene();
  const factor = step < 0 ? 0.9 : 1.1;
  if (activeScene?.scaleSelectedFurnitureSize(factor)) {
    state.modeNote = step < 0 ? '已缩小选中家具尺寸。' : '已放大选中家具尺寸。';
    refreshPage();
    return;
  }
  state.modeNote = '请先在场景中点选一个家具后再调整尺寸。';
  refreshPage();
}

function applyFurniturePlacementTemplateToScene(): void {
  const activeScene = getActiveScene();
  if (!activeScene) {
    return;
  }
  const selected = state.furnitureCatalog.find((item) => item.id === state.furniturePlacementAssetId) ?? null;
  if (!selected) {
    activeScene.setFurniturePlacementTemplate(null);
    return;
  }
  const directionAsset = selected.directions[state.furniturePlacementDirection] ?? selected.directions.front;
  const frameWidth = Number(directionAsset.frame_width) > 0 ? Number(directionAsset.frame_width) : directionAsset.width;
  const frameHeight = Number(directionAsset.frame_height) > 0 ? Number(directionAsset.frame_height) : directionAsset.height;
  activeScene.setFurniturePlacementTemplate({
    assetId: selected.id,
    label: selected.name,
    category: selected.category,
    direction: state.furniturePlacementDirection,
    width: frameWidth,
    height: frameHeight,
    spriteKey: resolveRuntimeAssetUrl(directionAsset.asset_url),
    directions: {
      front: resolveRuntimeAssetUrl(selected.directions.front.asset_url),
      left: resolveRuntimeAssetUrl(selected.directions.left.asset_url),
      right: resolveRuntimeAssetUrl(selected.directions.right.asset_url),
      back: resolveRuntimeAssetUrl(selected.directions.back.asset_url)
    }
  });
}

function normalizeInteractionSpriteAssetPath(rawAssetPath: string): string {
  const raw = String(rawAssetPath || '').trim();
  if (!raw) {
    return '';
  }
  const normalized = raw.replace(/\\/g, '/');
  if (normalized.startsWith('data:') || normalized.startsWith('blob:')) {
    return normalized;
  }
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return '';
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
  if (normalized.startsWith('//')) {
    return `${window.location.protocol}${normalized}`;
  }
  if (normalized.startsWith('/')) {
    return normalized;
  }
  if (normalized.startsWith('./')) {
    return normalizeInteractionSpriteAssetPath(normalized.slice(2));
  }
  if (normalized.startsWith('assets/')) {
    return `/${normalized}`;
  }
  if (normalized.startsWith('api/')) {
    return `/${normalized}`;
  }
  if (normalized.includes('/')) {
    return normalized;
  }
  return '';
}

function safeInteractionSpriteFileName(value: string): string {
  const fileName = String(value || '').replace(/\\/g, '/').split('/').pop()?.trim() ?? '';
  if (!/^[a-zA-Z0-9._-]+\.(png|webp|gif)$/i.test(fileName)) {
    return '';
  }
  return fileName;
}

async function resolveKnownInteractionSpriteAssetPathForFile(file: File): Promise<string | null> {
  const fileName = safeInteractionSpriteFileName(file.name);
  if (!fileName) {
    return null;
  }

  const actorIds: string[] = [];
  const appendActorId = (value: string | null | undefined): void => {
    const actorId = normalizeActorFolderId(value);
    if (actorId && !actorIds.includes(actorId)) {
      actorIds.push(actorId);
    }
  };
  const primaryAgent = state.data ? resolvePrimarySceneAgent(state.data) : null;
  appendActorId(effectiveActorIdForAgent(primaryAgent?.agent_id));
  appendActorId(effectiveActorIdForAgent(state.selectedAgentId));
  appendActorId(defaultActorId());
  for (const actor of state.actorCatalog) {
    appendActorId(actor.id);
  }

  for (const actorId of actorIds) {
    const candidate = `/assets/generated/actors/${actorId}/sheets/${fileName}`;
    try {
      const response = await fetch(candidate, { method: 'HEAD', cache: 'no-store' });
      if (response.ok) {
        return candidate;
      }
    } catch {
      // Fall back to inline data below.
    }
  }
  return null;
}

function resolveRuntimeAssetUrl(rawAssetUrl: string): string {
  const raw = String(rawAssetUrl || '').trim();
  if (!raw) {
    return raw;
  }
  if (/^(https?:\/\/|data:|blob:)/i.test(raw)) {
    return raw;
  }
  const normalized = raw.replace(/\\/g, '/');
  const baseUrl = String((import.meta as ImportMeta & { env?: { BASE_URL?: string } }).env?.BASE_URL || '/');
  const basePrefix = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
  const relative = normalized.replace(/^\/+/, '');
  return `${basePrefix}${relative}`;
}

function normalizeHouseFormat(input: string): TyxtHouseFormat | 'unknown' {
  const value = String(input || '').trim().toLowerCase();
  if (value === 'image/png' || value.endsWith('.png') || value === 'png') {
    return 'png';
  }
  if (value === 'image/webp' || value.endsWith('.webp') || value === 'webp') {
    return 'webp';
  }
  return 'unknown';
}

function deriveHouseNameFromFile(fileName: string): string {
  const normalized = String(fileName || '').trim().replace(/\.[^.]+$/, '');
  return normalized || `house-${Date.now()}`;
}

function readImageDimensions(previewUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve({
        width: image.naturalWidth || 0,
        height: image.naturalHeight || 0
      });
    };
    image.onerror = () => {
      reject(new Error('无法解析图片尺寸'));
    };
    image.src = previewUrl;
  });
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const raw = typeof reader.result === 'string' ? reader.result : '';
      const commaIndex = raw.indexOf(',');
      if (commaIndex < 0) {
        reject(new Error('文件编码失败'));
        return;
      }
      resolve(raw.slice(commaIndex + 1));
    };
    reader.onerror = () => {
      reject(new Error('读取文件失败'));
    };
    reader.readAsDataURL(file);
  });
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
    state.sceneEditorHudVisible = false;
    state.sceneEditorHudText = '';
    renderSceneEditorHud();
    return;
  }

  activeScene.setLocale('zh');
  activeScene.setDebugVisualsVisible(false);

  if (!state.sceneBound) {
    bindSceneEvents(activeScene);
    state.sceneBound = true;
    state.spawnedAgentIds.clear();
  }
  if (!sceneMapProjectSyncStarted) {
    sceneMapProjectSyncStarted = true;
    void syncProjectSceneMap(activeScene);
  }

  const snapshot = buildLegacySceneSnapshot(data);
  activeScene.applyTelemetrySnapshot(snapshot);
  const isHouseWallSubMode = state.settingsMode === 'house' && state.houseSettingsSubMode === 'wall';
  const isHouseLabelSubMode = state.settingsMode === 'house' && state.houseSettingsSubMode === 'label';
  if (isHouseWallSubMode) {
    activeScene.exitRoomLabelEditor({ silent: true });
    // 先进入墙壁编辑，再应用 settingsMode，避免 house 模式先触发一次 editor=false 的瞬态回调，
    // 导致外层状态机误把 wall 子模式清空。
    activeScene.enterWallEditor({
      shape: state.wallShapeSelection,
      silent: true
    });
  }
  if (isHouseLabelSubMode) {
    activeScene.exitWallEditor({
      discardUnsaved: false,
      silent: true
    });
    activeScene.enterRoomLabelEditor({ silent: true });
  }
  activeScene.applySettingsMode(state.settingsMode, { silent: true });
  if (!isHouseWallSubMode) {
    activeScene.exitWallEditor({
      discardUnsaved: false,
      silent: true
    });
  }
  if (!isHouseLabelSubMode) {
    activeScene.exitRoomLabelEditor({ silent: true });
  }
  const isFurnitureSettingsMode = state.settingsMode === 'furniture';
  const isFurniturePlacementMode = isFurnitureSettingsMode && state.furnitureSettingsSubMode === 'place';
  if (isFurniturePlacementMode) {
    activeScene.enterFurniturePlacement({ silent: true });
    applyFurniturePlacementTemplateToScene();
  } else if (isFurnitureSettingsMode) {
    activeScene.exitFurniturePlacement({ discardUnsaved: false, silent: true });
  }
  const isInteractionSettingsMode = state.settingsMode === 'interaction';
  const interactionMode = state.interactionSettingsSubMode;
  if (isInteractionSettingsMode && interactionMode !== null) {
    activeScene.enterInteractionEditor({
      mode: interactionMode,
      silent: true
    });
  } else if (isInteractionSettingsMode) {
    activeScene.exitInteractionEditor({
      discardUnsaved: false,
      silent: true
    });
  } else {
    activeScene.exitInteractionEditor({
      discardUnsaved: false,
      silent: true
    });
  }
  const currentHouse = state.houseCatalog.find((item) => item.id === state.houseCurrentId) ?? null;
  activeScene.applyHouseBackdrop(currentHouse
    ? {
      houseId: currentHouse.id,
      assetUrl: resolveRuntimeAssetUrl(currentHouse.asset_url)
    }
    : null);
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

  activeScene.events.on('scene-editor-mode-changed', (eventPayload: SceneEditorModeChangedPayload | null) => {
    const editorEnabled = Boolean(eventPayload?.enabled);
    const editorTool = eventPayload?.tool;
    if (state.settingsMode === 'house' && state.houseSettingsSubMode === 'wall') {
      if (!editorEnabled || editorTool !== 'wall') {
        setHouseSettingsSubMode(null, 'system');
      }
    }
    if (state.settingsMode === 'house' && state.houseSettingsSubMode === 'label') {
      if (!editorEnabled || editorTool !== 'room_label') {
        setHouseSettingsSubMode(null, 'system');
      }
    }
    if (state.settingsMode === 'furniture' && state.furnitureSettingsSubMode === 'place') {
      if (!editorEnabled || editorTool !== 'furniture') {
        setFurnitureSettingsSubMode(null, 'system');
      }
    }
    if (state.settingsMode === 'interaction' && state.interactionSettingsSubMode !== null) {
      if (!editorEnabled || editorTool !== 'interaction') {
        setInteractionSettingsSubMode(null, 'system');
      }
    }

    const suggestedMode = eventPayload?.suggestedSettingsMode ?? null;
    if (suggestedMode === 'house') {
      if (state.settingsMode !== suggestedMode || state.viewMode !== 'settings') {
        setSettingsMode(suggestedMode, 'scene');
      }
      return;
    }
    if (suggestedMode === 'furniture') {
      if (state.settingsMode !== suggestedMode || state.viewMode !== 'settings') {
        setSettingsMode(suggestedMode, 'scene');
      }
      return;
    }
    if (suggestedMode === 'interaction') {
      if (state.settingsMode !== suggestedMode || state.viewMode !== 'settings') {
        setSettingsMode(suggestedMode, 'scene');
      }
      return;
    }

    if (isEditorLinkedSettingsMode(state.settingsMode)) {
      setSettingsMode(null, 'scene');
    }
  });

  activeScene.events.on('scene-editor-hud-changed', (eventPayload: SceneEditorHudChangedPayload | null) => {
    const nextVisible = Boolean(eventPayload?.visible);
    const nextText = nextVisible ? String(eventPayload?.text || '') : '';
    if (state.sceneEditorHudVisible === nextVisible && state.sceneEditorHudText === nextText) {
      return;
    }
    state.sceneEditorHudVisible = nextVisible;
    state.sceneEditorHudText = nextText;
    renderSceneEditorHud();
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
  activeScene.setGeneratedActorVariantFolders(state.actorCatalog.map((actor) => actor.id));
  const primaryActorId = effectiveActorIdForAgent(primaryAgent?.agent_id);
  if (primaryActorId) {
    activeScene.setActorVariant(primaryActorId);
  }

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

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '--';
  }
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

function formatBytes(bytes: number): string {
  const normalized = Number(bytes);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    return '0 B';
  }
  if (normalized < 1024) {
    return `${Math.round(normalized)} B`;
  }
  if (normalized < 1024 * 1024) {
    return `${(normalized / 1024).toFixed(1)} KB`;
  }
  return `${(normalized / (1024 * 1024)).toFixed(2)} MB`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

bindDomEvents();
void refreshAgentRegistry();
void refreshActorSettings({ silent: true });
void refreshHeaderStatus();
void refreshHouseCatalog({ silent: true });
void refreshFurnitureCatalog({ silent: true });
refreshPage();

window.setInterval(() => {
  state.tick += 1;
  refreshPage();
}, DATA_REFRESH_MS);

window.setInterval(() => {
  void refreshAgentRegistry();
}, 20_000);

window.setInterval(() => {
  void refreshActorSettings({ silent: true });
}, ACTOR_SETTINGS_REFRESH_MS);

window.setInterval(() => {
  void refreshHeaderStatus();
}, HEADER_STATUS_REFRESH_MS);













