import Phaser from 'phaser';
import type {
  ActorDirection,
  ActorVariantDef,
  AssetDef,
  GrowthState,
  InterfaceDef,
  LobsterStateId,
  OpenClawAccessEvent,
  OpenClawResourceTelemetry,
  OpenClawSnapshot,
  OutputCategoryDef,
  Point,
  ResourcePartitionId,
  ResourceTelemetryStatus,
  SceneGlobalLayerDef,
  RoomArtSlice,
  RoomBounds,
  RoomSliceLayerDef,
  ThemePack,
  WorkMode,
  WorkOutputEvent,
  WorkStateProfile,
  WorkStatus,
  WorkZone,
  WorkZoneType
} from '../../core/types';
import { pointInPolygon } from '../../core/geometry';
import { computeVisibleAssetIds } from '../systems/growth';
import { loadProtocols } from '../systems/protocolStore';
import { configureTouch } from '../systems/touchController';
import type { UiLocale } from '../../ui/locale';
import { resourceLabel } from '../../ui/locale';
import { PARTITION_COLORS } from '../../ui/palette';
import {
  SCENE_MAP_LOCAL_JSON_HINT,
  buildSceneMapExportText,
  cloneSceneMapData,
  createSceneEntityId,
  hasStoredSceneMapData,
  loadSceneMapData,
  normalizeSceneMapData,
  saveSceneMapData,
  type FurnitureItem,
  type InteractionBox,
  type InteractionPoint as SceneInteractionPoint,
  type SceneMapData,
  type SceneMapRect,
  type WallBlock,
  type WallShapeType
} from '../data/sceneMapData';

const INITIAL_GROWTH: GrowthState = {
  assetsCount: 0,
  skillsCount: 0,
  textOutputs: 0
};

const CAMERA_FRAME_MARGIN = 18;
const CAMERA_CONTENT_OVERSCAN = 16;
const CAMERA_ZOOM_MIN = 0.85;
const CAMERA_ZOOM_MAX = 1.3;

const PROP_SHADOW_OFFSET = { x: 4, y: 4 } as const;
const PROP_SHADOW_ALPHA = 0.16;
const ENABLE_PRIMARY_AGENT_POSE_FX = false;
const ENABLE_PRIMARY_AGENT_THOUGHT_BUBBLE = false;
const PRIMARY_AGENT_BUBBLE_GAP_PX = 18;
const EDITOR_WALL_MIN_SIZE = 10;
const INTERACTION_POINT_RADIUS = 16;
const DEFAULT_FURNITURE_SIZE = { width: 92, height: 68 } as const;
const FURNITURE_INTERACTION_TYPES = ['inspect', 'use', 'read', 'view', 'status'] as const;
const FURNITURE_EDITOR_TOP_SLACK_RATIO = 0.5;
const FURNITURE_RESIZE_MIN_SIZE = 16;
const FURNITURE_RESIZE_MAX_SIZE = 1600;
const FURNITURE_COLLISION_FADE_ALPHA = 0.48;
const FURNITURE_NORMAL_ALPHA = 1;
const FURNITURE_COLLISION_FADE_LERP = 0.24;
const FURNITURE_ALPHA_OVERLAP_THRESHOLD = 24;
const FURNITURE_ALPHA_OVERLAP_SAMPLE_STEP = 1;
const PATROL_STUCK_DISTANCE_THRESHOLD = 2;
const PATROL_STUCK_TIMEOUT_MS = 2800;
const PATROL_STUCK_MAX_RECOVERY_ATTEMPTS = 3;
const PATROL_ACTION_TARGET_MAX_OFFSET = 128;
const PATROL_ACTION_CAPTURE_RADIUS_MIN = 56;
const PATROL_ACTION_CAPTURE_RADIUS_MAX = 160;
const WALL_EDITOR_DEFAULT_SIZE = { width: 120, height: 80 } as const;
const WALL_EDITOR_HANDLE_RADIUS = 8;
const WALL_EDITOR_ROTATE_HANDLE_OFFSET = 34;
const WALKABLE_CELL_SAFETY_OFFSET_RATIO = 0.28;

type RenderedAsset = {
  def: AssetDef;
  body: Phaser.GameObjects.Rectangle;
  pulseTween: Phaser.Tweens.Tween | null;
};

type RenderedSliceLayer = {
  slice: RoomArtSlice;
  layer: RoomSliceLayerDef;
  shadowImage: Phaser.GameObjects.Image | null;
  image: Phaser.GameObjects.Image;
};

type RenderedGlobalLayer = {
  layer: SceneGlobalLayerDef;
  shadowImage: Phaser.GameObjects.Image | null;
  image: Phaser.GameObjects.Image;
};

type ZoneState = 'idle' | 'moving' | 'working' | 'done';

type RouteContext = {
  resourceId: ResourcePartitionId;
  detail: string;
  source?: string;
  status?: ResourceTelemetryStatus;
};

type ResourceSelectEvent = {
  resourceId: ResourcePartitionId;
  anchor?: Point;
};

type AgentActorKind = 'subagent' | 'exec-process';

type AgentActor = {
  id: string;
  label: string;
  kind: AgentActorKind;
  container: Phaser.GameObjects.Container;
  body: Phaser.GameObjects.Sprite | Phaser.GameObjects.Arc | null;
  route: Point[];
  activeZoneId: ResourcePartitionId | null;
  focusZoneId: ResourcePartitionId | null;
  workCursor: number;
  nameTag: Phaser.GameObjects.Text | null;
  /** Thought bubble showing last milestone/status */
  thoughtBubble: Phaser.GameObjects.Text | null;
  /** Current visual mode — only used for subagents (exec-processes stay static) */
  visualMode: WorkMode;
  /** Timestamp (ms) when working animation should end and revert to idle */
  workingUntil: number;
  /** Timestamp (ms) until which the actor lingers at its destination before picking a new one */
  lingerUntil: number;
  facing: ActorDirection;
};

type SceneEditorTool = 'wall' | 'furniture' | 'interaction' | 'room_label';

type SceneSettingsMode = 'house' | 'furniture' | 'character' | 'shop' | 'interaction' | null;
type InteractionEditorMode = 'action_point' | 'interaction_box';

type SceneToastTone = 'info' | 'success' | 'warn';
type FurnitureFacing = 'front' | 'left' | 'right' | 'back';
const FURNITURE_FACING_TURN_ORDER: FurnitureFacing[] = ['front', 'right', 'back', 'left'];
type FurniturePlacementTemplate = {
  assetId: string;
  label: string;
  category: string;
  direction: FurnitureFacing;
  width: number;
  height: number;
  spriteKey: string;
  directions: Record<FurnitureFacing, string>;
};
type SpriteAlphaMask = {
  width: number;
  height: number;
  data: Uint8ClampedArray;
};
type WallEditorHandleKind = 'move' | 'resize-nw' | 'resize-ne' | 'resize-sw' | 'resize-se' | 'rotate' | 'delete';
type WallEditorDragState = {
  kind: WallEditorHandleKind;
  wallId: string;
  startPoint: Point;
  startWall: WallBlock;
  startAngle?: number;
};

type InteractionPointDragState = {
  id: string;
  startPoint: Point;
  startPosition: { x: number; y: number };
};

type InteractionBoxDragState = {
  id: string;
  startPoint: Point;
  startRect: SceneMapRect;
};

type RoomLabelDragState = {
  roomId: ResourcePartitionId;
  startPoint: Point;
  startAnchor: Point;
  moved: boolean;
};

export type InteractionEditorSnapshot = {
  mode: InteractionEditorMode;
  selectedActionPointId: string | null;
  selectedInteractionBoxId: string | null;
  actionPoints: SceneInteractionPoint[];
  interactionBoxes: InteractionBox[];
};

export class LibraryScene extends Phaser.Scene {
  private readonly protocols = loadProtocols();
  private sceneMapData: SceneMapData = loadSceneMapData();
  private growthState: GrowthState = { ...INITIAL_GROWTH };
  private currentThemeIndex = 0;

  private lobster!: Phaser.GameObjects.Container;
  private lobsterBody: Phaser.GameObjects.Sprite | Phaser.GameObjects.Arc | null = null;
  private lobsterRoute: Point[] = [];
  private lobsterContextBar: Phaser.GameObjects.Graphics | null = null;
  private lobsterContextRemaining: number | null = 1; // 0–1, starts full; null = no data
  private lobsterNameTag: Phaser.GameObjects.Text | null = null;
  private agentActors: AgentActor[] = [];

  private roomLayer!: Phaser.GameObjects.Graphics;
  private wallBlockLayer!: Phaser.GameObjects.Graphics;
  private zoneLayer!: Phaser.GameObjects.Graphics;
  private furnitureSpriteLayer!: Phaser.GameObjects.Layer;
  private furnitureLayer!: Phaser.GameObjects.Graphics;
  private interactionPointLayer!: Phaser.GameObjects.Graphics;
  private interactionPointLabelLayer!: Phaser.GameObjects.Layer;
  private interactionBoxLayer!: Phaser.GameObjects.Graphics;
  private interactionBoxLabelLayer!: Phaser.GameObjects.Layer;
  private editorPreviewLayer!: Phaser.GameObjects.Graphics;
  private occluderLayer!: Phaser.GameObjects.Graphics;
  private hitLayer!: Phaser.GameObjects.Graphics;
  private editorHudText: Phaser.GameObjects.Text | null = null;
  private editorHudOverlayVisible = false;
  private editorHudOverlayText = '';
  private interactionToastText: Phaser.GameObjects.Text | null = null;
  private interactionToastUntil = 0;
  private floorBackdropImage: Phaser.GameObjects.Image | null = null;
  private floorBackdropFrame = { width: 1609, height: 1072 };
  private renderedGlobalLayers: RenderedGlobalLayer[] = [];
  private walkableMaskData: Uint8ClampedArray | null = null;
  private walkableMaskWidth = 0;
  private walkableMaskHeight = 0;
  private walkableMaskColorMode: 'red' | 'blue' | 'opaque' = 'red';
  private walkableGrid: Uint8Array | null = null;
  private walkableGridCols = 0;
  private walkableGridRows = 0;
  private readonly walkableGridStep = 8;
  private reachableWalkableGrid: Uint8Array | null = null;

  private workStatusText!: Phaser.GameObjects.Text;
  private lobsterThoughtText!: Phaser.GameObjects.Text;

  private renderLayerDepths = new Map<string, number>();
  private queuedTextureKeys = new Set<string>();
  private renderedAssets: RenderedAsset[] = [];
  private renderedRoomSlices: RenderedSliceLayer[] = [];
  private roomTitleBackplates = new Map<ResourcePartitionId, Phaser.GameObjects.Graphics>();
  private roomTitleLabels = new Map<ResourcePartitionId, Phaser.GameObjects.Text>();
  private zoneLabels = new Map<ResourcePartitionId, Phaser.GameObjects.Text>();
  private zoneState = new Map<ResourcePartitionId, ZoneState>();
  private stateCursorByZoneType = new Map<WorkZoneType, number>();
  private readonly hiddenRoomLabelIds = new Set<ResourcePartitionId>(['task_queues', 'schedule', 'alarm']);
  private telemetryResources = new Map<ResourcePartitionId, OpenClawResourceTelemetry>();
  private telemetryQueue: OpenClawAccessEvent[] = [];
  private processedEventIds = new Set<string>();

  private workMode: WorkMode = 'idle';
  private patrolCooldownUntil = 0;
  private patrolTargetMode: ActorVariantDef['modes'][number] | null = null;
  private currentActionMode: ActorVariantDef['modes'][number] | null = null;
  private lastCompletedActionAnchor: Point | null = null;
  private suppressedActionAnchor: Point | null = null;
  private suppressedActionAnchorUntil = 0;
  private lastMainVisualKey: string | null = null;
  private activeZoneId: ResourcePartitionId | null = null;
  private lastReachedZoneId: ResourcePartitionId | null = null;
  private outputCursor = 0;
  private pendingStateProfile: WorkStateProfile | null = null;
  private pendingRouteContext: RouteContext | null = null;

  private liveMode: OpenClawSnapshot['mode'] = 'mock';
  private focusResourceId: ResourcePartitionId = 'break_room';
  private focusDetail = 'warming up TYXT hub';
  private lastTelemetryAt: string | null = null;
  private locale: UiLocale = 'en';
  private debugVisualsVisible = false;
  private hoveredRoomId: ResourcePartitionId | null = null;
  private actorVariantId: string | null = null;
  private generatedActorVariantFolders: string[] = [];
  private generatedActorVariantCache = new Map<string, ActorVariantDef>();
  private actorFacing: ActorDirection = 'down';
  private celebrationUntil = 0;
  private actorVisualCursorByContext = new Map<string, number>();
  private actorVisualSelectionByContext = new Map<string, { textureKey: string; holdUntil: number }>();
  private hoveredFurnitureId: string | null = null;
  private highlightedFurnitureId: string | null = null;
  private highlightedFurnitureUntil = 0;
  private hoveredInteractionPointId: string | null = null;
  private hoveredInteractionBoxId: string | null = null;
  private settingsMode: SceneSettingsMode = null;
  private houseOverlaySuppressed = false;
  private activeHouseBackgroundSignature: string | null = null;
  private houseTextureKeyBySignature = new Map<string, string>();
  private editorModeEnabled = false;
  private editorTool: SceneEditorTool = 'wall';
  private editorPointerPoint: Point | null = null;
  private selectedWallBlockId: string | null = null;
  private wallEditorShapePreset: WallShapeType = 'rectangle';
  private wallEditorDragState: WallEditorDragState | null = null;
  private wallEditorSessionActive = false;
  private wallEditorDirty = false;
  private wallEditorBaseline: WallBlock[] | null = null;
  private selectedFurnitureId: string | null = null;
  private furnitureDragState: { id: string; startPoint: Point; startRect: SceneMapRect } | null = null;
  private furniturePlacementTemplate: FurniturePlacementTemplate | null = null;
  private selectedRoomLabelId: ResourcePartitionId | null = null;
  private roomLabelDragState: RoomLabelDragState | null = null;
  private roomLabelEditorSessionActive = false;
  private interactionEditorMode: InteractionEditorMode = 'action_point';
  private interactionEditorSessionActive = false;
  private selectedInteractionPointId: string | null = null;
  private selectedInteractionBoxId: string | null = null;
  private interactionPointDragState: InteractionPointDragState | null = null;
  private interactionBoxDragState: InteractionBoxDragState | null = null;
  private editorInteractionTypeCursor = 0;
  private furnitureTextureByUrl = new Map<string, string>();
  private furnitureSpriteById = new Map<string, Phaser.GameObjects.Image>();
  private spriteAlphaMaskCache = new Map<string, SpriteAlphaMask>();
  private inlineActionAssetHashByValue = new Map<string, string>();
  private sceneMapProjectPersistPromise: Promise<void> | null = null;
  private sceneMapProjectPersistPending: SceneMapData | null = null;
  private sceneMapProjectPersistWarned = false;
  private sceneMapRevision = 0;
  private patrolLastProgressAt = 0;
  private patrolLastProgressPoint: Point | null = null;
  private patrolStuckRecoveryAttempts = 0;

  private lastOutput: WorkOutputEvent = {
    stateId: 'idle',
    stateLabel: 'Standby',
    outputCategoryId: 'document',
    outputCategoryLabel: 'Document',
    interfaceId: 'gateway',
    interfaceLabel: 'Gateway Switchboard',
    interfaceEndpoint: 'tyxt/local-gateway.json',
    content: 'waiting for next task signal'
  };

  constructor() {
    super('LibraryScene');
  }

  preload(): void {
    this.preloadSceneArt();
  }

  create(): void {
    configureTouch(this);
    if (typeof window !== 'undefined') {
      (window as Window & { __tyxtSpaceScene?: LibraryScene }).__tyxtSpaceScene = this;
    }
    this.applyStageCameraFit();
    this.cameras.main.roundPixels = true;
    this.scale.on('resize', () => this.applyStageCameraFit());

    this.initializeRenderLayerDepths();

    this.spawnSceneBaseArt();

    this.roomLayer = this.add.graphics();
    this.roomLayer.setDepth(this.getRenderLayerDepth('floor'));

    this.wallBlockLayer = this.add.graphics();
    this.wallBlockLayer.setDepth(this.getRenderLayerDepth('back_walls') + 0.2);

    this.zoneLayer = this.add.graphics();
    this.zoneLayer.setDepth(this.getRenderLayerDepth('mid_props') + 3);

  this.hitLayer = this.add.graphics();
  this.hitLayer.setDepth(this.getRenderLayerDepth('mid_props') + 9);

  this.furnitureSpriteLayer = this.add.layer();
  this.furnitureSpriteLayer.setDepth(this.getRenderLayerDepth('mid_props') + 8.75);

  this.furnitureLayer = this.add.graphics();
  this.furnitureLayer.setDepth(this.getRenderLayerDepth('mid_props') + 8.8);

    this.interactionPointLayer = this.add.graphics();
    this.interactionPointLayer.setDepth(this.getRenderLayerDepth('mid_props') + 8.9);

    this.interactionPointLabelLayer = this.add.layer();
    this.interactionPointLabelLayer.setDepth(this.getRenderLayerDepth('fx_overlay') + 11);

    this.interactionBoxLayer = this.add.graphics();
    this.interactionBoxLayer.setDepth(this.getRenderLayerDepth('mid_props') + 8.95);

    this.interactionBoxLabelLayer = this.add.layer();
    this.interactionBoxLabelLayer.setDepth(this.getRenderLayerDepth('fx_overlay') + 11.1);

    this.occluderLayer = this.add.graphics();
    this.occluderLayer.setDepth(this.getRenderLayerDepth('fg_occluder'));

    this.editorPreviewLayer = this.add.graphics();
    this.editorPreviewLayer.setDepth(this.getRenderLayerDepth('fx_overlay') + 19);

    this.workStatusText = this.add.text(30, 20, '', {
      color: '#d7e2ff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
      fontSize: '16px',
      lineSpacing: 3
    });
    this.workStatusText.setDepth(this.getRenderLayerDepth('fx_overlay') + 10);
    this.workStatusText.setVisible(false);

    this.lobsterThoughtText = this.add.text(0, 0, '', {
      color: '#f3fff9',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
      fontSize: '12px',
      lineSpacing: 3,
      align: 'center',
      backgroundColor: 'rgba(9, 24, 22, 0.82)',
      padding: { left: 10, right: 10, top: 7, bottom: 7 }
    });
    this.lobsterThoughtText.setOrigin(0.5, 1);
    this.lobsterThoughtText.setDepth(this.getRenderLayerDepth('fx_overlay') + 12);
    this.lobsterThoughtText.setStroke('#04100f', 3);
    this.lobsterThoughtText.setVisible(ENABLE_PRIMARY_AGENT_THOUGHT_BUBBLE);

    this.initializeSceneInteractionUi();

    this.drawRooms();
    this.syncWorkZonesFromInteractionPoints();
    this.spawnRoomSlices();
    this.initializeWalkableMask();
    this.spawnAssets();
    this.createActorAnimations();
    this.spawnLobster();
    this.snapWorkZonesToReachableWalkable({ x: this.lobster.x, y: this.lobster.y });
    this.initializeRoomLabels();
    this.initializeWorkZones();
    this.drawOccluders();
    this.drawSceneMapLayers();
    this.applyDebugVisualLayerVisibility();

    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      this.handlePointerDown(pointer.worldX, pointer.worldY, pointer);
    });
    this.input.on('pointerup', (pointer: Phaser.Input.Pointer) => {
      this.handlePointerUp(pointer.worldX, pointer.worldY, pointer);
    });
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      this.handlePointerMove(pointer.worldX, pointer.worldY);
    });
    this.input.mouse?.disableContextMenu();
    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      this.handleEditorKeyDown(event);
    });

    this.events.on('set-growth', (next: GrowthState) => {
      this.growthState = next;
      this.applyGrowthState();
    });

    this.events.on('cycle-theme', () => {
      this.currentThemeIndex = (this.currentThemeIndex + 1) % this.protocols.themePack.themes.length;
      this.drawRooms();
      this.applyGlobalLayerTheme();
      this.applyRoomSliceTheme();
      this.syncRoomLabels();
      this.drawWorkZones();
      this.drawOccluders();
      this.drawSceneMapLayers();
      this.syncWorkStatus();
    });

    this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
      resourceId: 'document',
      detailOverride: 'waiting for next task signal'
    });

    this.applyGrowthState();
    this.syncRoomLabels();
    this.updateResourceAnimations();
    this.updateLobsterVisual('idle');
    this.syncWorkStatus();
  }

  private applyStageCameraFit(): void {
    const camera = this.cameras.main;
    const focusBounds = this.resolveStageFocusBounds();

    const viewportWidth = camera.width;
    const viewportHeight = camera.height;
    const usableWidth = Math.max(320, viewportWidth - CAMERA_FRAME_MARGIN * 2);
    const usableHeight = Math.max(240, viewportHeight - CAMERA_FRAME_MARGIN * 2);

    const zoomX = usableWidth / focusBounds.width;
    const zoomY = usableHeight / focusBounds.height;
    const zoom = Phaser.Math.Clamp(Math.min(zoomX, zoomY), CAMERA_ZOOM_MIN, CAMERA_ZOOM_MAX);

    camera.setZoom(zoom);

    const visibleWidth = viewportWidth / zoom;
    const centerX = focusBounds.centerX;
    const topAlignedY = focusBounds.y - CAMERA_FRAME_MARGIN / zoom;

    camera.setScroll(centerX - visibleWidth / 2, topAlignedY);
  }

  private resolveStageFocusBounds(): Phaser.Geom.Rectangle {
    if (this.floorBackdropImage) {
      return new Phaser.Geom.Rectangle(
        Math.max(0, this.floorBackdropImage.x - this.floorBackdropImage.displayWidth / 2 - CAMERA_CONTENT_OVERSCAN),
        Math.max(0, this.floorBackdropImage.y - this.floorBackdropImage.displayHeight / 2 - CAMERA_CONTENT_OVERSCAN),
        Math.max(1, this.floorBackdropImage.displayWidth + CAMERA_CONTENT_OVERSCAN * 2),
        Math.max(1, this.floorBackdropImage.displayHeight + CAMERA_CONTENT_OVERSCAN * 2)
      );
    }

    const floorSpec = this.resolveFloorBackdropSpec();
    if (floorSpec) {
      return new Phaser.Geom.Rectangle(
        Math.max(0, floorSpec.anchor.x - floorSpec.displaySize.width / 2 - CAMERA_CONTENT_OVERSCAN),
        Math.max(0, floorSpec.anchor.y - floorSpec.displaySize.height / 2 - CAMERA_CONTENT_OVERSCAN),
        Math.max(1, floorSpec.displaySize.width + CAMERA_CONTENT_OVERSCAN * 2),
        Math.max(1, floorSpec.displaySize.height + CAMERA_CONTENT_OVERSCAN * 2)
      );
    }

    const globalLayers = this.activeSceneGlobalLayers();
    if (globalLayers.length > 0) {
      const floorLayer = globalLayers.find((layer) => layer.renderLayer === 'floor') ?? globalLayers[0];
      const left = floorLayer.anchor.x - floorLayer.displaySize.width / 2;
      const top = floorLayer.anchor.y - floorLayer.displaySize.height / 2;
      return new Phaser.Geom.Rectangle(
        Math.max(0, left - CAMERA_CONTENT_OVERSCAN),
        Math.max(0, top - CAMERA_CONTENT_OVERSCAN),
        Math.max(1, floorLayer.displaySize.width + CAMERA_CONTENT_OVERSCAN * 2),
        Math.max(1, floorLayer.displaySize.height + CAMERA_CONTENT_OVERSCAN * 2)
      );
    }

    const rooms = this.protocols.mapLogic.rooms;
    if (!rooms || rooms.length === 0) {
      const fallbackWidth = this.sceneMapData.base_width - CAMERA_CONTENT_OVERSCAN * 2;
      const fallbackHeight = this.sceneMapData.base_height - CAMERA_CONTENT_OVERSCAN * 2;
      return new Phaser.Geom.Rectangle(
        CAMERA_CONTENT_OVERSCAN,
        CAMERA_CONTENT_OVERSCAN,
        fallbackWidth,
        fallbackHeight
      );
    }

    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    for (const room of rooms) {
      const [x, y, width, height] = room.bounds;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + width);
      maxY = Math.max(maxY, y + height);
    }

    const focusX = Math.max(0, minX - CAMERA_CONTENT_OVERSCAN);
    const focusY = Math.max(0, minY - CAMERA_CONTENT_OVERSCAN);
    const focusWidth = Math.max(1, (maxX - minX) + CAMERA_CONTENT_OVERSCAN * 2);
    const focusHeight = Math.max(1, (maxY - minY) + CAMERA_CONTENT_OVERSCAN * 2);

    return new Phaser.Geom.Rectangle(focusX, focusY, focusWidth, focusHeight);
  }

  update(_time: number, delta: number): void {
    this.advanceLobster(delta);
    this.monitorPatrolStuckState();
    this.updateFurnitureCollisionFade();
    this.positionThoughtBubble();
    for (const actor of this.agentActors) {
      this.advanceAgentActor(actor, delta);
    }
    this.tickSceneInteractionUi();
    this.maybeProcessTelemetryQueue();
  }

  public getGrowthState(): GrowthState {
    return this.growthState;
  }

  public getWorkStatus(): WorkStatus {
    const zone = this.activeZoneId ? this.zoneLabel(this.activeZoneId) : this.lastReachedZoneId ? this.zoneLabel(this.lastReachedZoneId) : null;
    return {
      mode: this.workMode,
      zone,
      stateId: this.lastOutput.stateId,
      stateLabel: this.lastOutput.stateLabel,
      outputCategory: this.lastOutput.outputCategoryLabel,
      interfaceTarget: `${this.lastOutput.interfaceLabel} · ${this.lastOutput.interfaceEndpoint}`,
      detail: this.lastOutput.content
    };
  }

  public getSceneMapDataSnapshot(): SceneMapData {
    return cloneSceneMapData(this.sceneMapData);
  }

  public getSceneMapRevision(): number {
    return this.sceneMapRevision;
  }

  public hasStoredSceneMapData(): boolean {
    return hasStoredSceneMapData();
  }

  public applySceneMapData(
    nextData: unknown,
    options: { persistLocal?: boolean; silent?: boolean } = {}
  ): void {
    const normalized = normalizeSceneMapData(nextData);
    this.sceneMapData = options.persistLocal === false
      ? normalized
      : saveSceneMapData(normalized);
    this.sceneMapRevision += 1;
    this.selectedFurnitureId = this.sceneMapData.furnitures.some((item) => item.id === this.selectedFurnitureId)
      ? this.selectedFurnitureId
      : null;
    this.selectedInteractionPointId = this.sceneMapData.interaction_points.some((item) => item.id === this.selectedInteractionPointId)
      ? this.selectedInteractionPointId
      : null;
    this.selectedInteractionBoxId = this.sceneMapData.interaction_boxes.some((item) => item.id === this.selectedInteractionBoxId)
      ? this.selectedInteractionBoxId
      : null;
    this.syncWorkZonesFromInteractionPoints();
    this.initializeWalkableMask();
    this.drawRooms();
    this.drawSceneMapLayers();
    this.drawWorkZones();
    this.resetPatrolProgressTracking();
    if (!options.silent) {
      this.showSceneToast('项目场景地图已加载。', 'success', 1600);
    }
  }

  public applyTelemetrySnapshot(snapshot: OpenClawSnapshot): void {
    this.liveMode = snapshot.mode;
    this.lastTelemetryAt = snapshot.generatedAt;
    this.focusResourceId = snapshot.focus.resourceId;
    this.focusDetail = snapshot.focus.detail;

    // Update context bar if data available
    if (snapshot.mainActorContext) {
      const remaining = snapshot.mainActorContext.remaining;
      if (this.lobsterContextRemaining !== remaining) {
        this.lobsterContextRemaining = remaining;
        this.drawContextBar(remaining);
      }
    } else if (this.lobsterContextRemaining !== null) {
      // No context data available — reset bar to avoid stale state
      this.lobsterContextRemaining = null;
      this.drawContextBar(null);
    }

    this.telemetryResources.clear();
    for (const resource of snapshot.resources) {
      this.telemetryResources.set(resource.id, resource);
    }

    const hasLiveWorkSignal = snapshot.resources.some((resource) => resource.status === 'alert' || resource.status === 'active');
    if (!hasLiveWorkSignal) {
      this.telemetryQueue = [];
    } else {
      this.telemetryQueue = this.telemetryQueue.filter((event) => event.status === 'alert' || event.status === 'active');
    }

    for (const event of snapshot.recentEvents) {
      if (event.status !== 'alert' && event.status !== 'active') {
        continue;
      }
      if (this.processedEventIds.has(event.id)) {
        continue;
      }
      this.processedEventIds.add(event.id);
      this.telemetryQueue.push(event);
    }

    if (this.processedEventIds.size > 64) {
      const recentIds = new Set(this.telemetryQueue.slice(-24).map((item) => item.id));
      for (const id of [...this.processedEventIds]) {
        if (!recentIds.has(id)) {
          this.processedEventIds.delete(id);
        }
      }
    }

    this.drawRooms();
    this.syncRoomLabels();
    this.drawWorkZones();
    this.updateResourceAnimations();
    this.syncWorkStatus();
    this.maybeProcessTelemetryQueue();
  }

  public spawnAgentActor(runId: string, label: string, kind: AgentActorKind = 'subagent'): void {
    if (this.agentActors.some((actor) => actor.id === runId)) {
      return;
    }
    const nodes = this.protocols.mapLogic.walkGraph.nodes;
    if (nodes.length === 0) {
      return;
    }

    // exec-processes spawn inside the break_room (bottom-right room — Run Dock / Documents Archive)
    // subagents pick any node far from the primary actor
    let startNode = nodes[0];
    if (kind === 'exec-process') {
      const breakRoom = this.protocols.mapLogic.rooms.find((r) => r.id === 'break_room');
      if (breakRoom) {
        const [rx, ry, rw, rh] = breakRoom.bounds;
        const roomNodes = nodes.filter((n) => n.x >= rx && n.x <= rx + rw && n.y >= ry && n.y <= ry + rh);
        startNode = roomNodes[Math.floor(Math.random() * roomNodes.length)] ?? nodes[0];
      }
    } else {
      const usableNodes = nodes.filter((node) => {
        const dx = node.x - this.lobster.x;
        const dy = node.y - this.lobster.y;
        return Math.hypot(dx, dy) > 80;
      });
      startNode = usableNodes[Math.floor(Math.random() * usableNodes.length)] ?? nodes[0];
    }

    const children: Phaser.GameObjects.GameObject[] = [];
    const actor = this.protocols.sceneArt.actor;
    const variant = this.resolveActorVariant();
    const idleVisual = this.resolveActorMode('idle', {
      position: { x: startNode.x, y: startNode.y },
      direction: 'down'
    });

    // Subtle shadow
    if (actor?.shadow) {
      const shadow = this.add.ellipse(0, actor.shadow.offsetY, actor.shadow.width * 0.85, actor.shadow.height * 0.85, 0x081018, actor.shadow.alpha * 0.7);
      children.push(shadow);
    }

    // Visual style: subagents = natural (no tint), exec-processes = warm amber tint (smaller, slower)
    const isExecProcess = kind === 'exec-process';
    const scaleFactor = isExecProcess ? 0.72 : 0.88;
    const tintColor = isExecProcess ? 0xffd080 : null; // no tint for subagents
    const fallbackColor = isExecProcess ? 0xe8a830 : 0x4fa8e8;
    const nameTagColor = isExecProcess ? '#ffe4a0' : '#d7e2ff';
    const nameTagBg = isExecProcess ? 'rgba(28, 18, 4, 0.76)' : 'rgba(4, 12, 28, 0.72)';
    const nameTagPrefix = isExecProcess ? '⚙ ' : '';

    let body: Phaser.GameObjects.Sprite | Phaser.GameObjects.Arc | null = null;
    if (actor && variant && idleVisual) {
      const sprite = this.add.sprite(actor.anchorOffset?.x ?? 0, actor.anchorOffset?.y ?? 0, idleVisual.textureKey);
      const modeDisplay = this.resolveModeDisplaySize(idleVisual, actor.displaySize, scaleFactor);
      sprite.setDisplaySize(Math.round(modeDisplay.width), Math.round(modeDisplay.height));
      if (tintColor) sprite.setTint(tintColor);
      children.push(sprite);
      body = sprite;
    } else {
      const fallback = this.add.circle(0, 0, isExecProcess ? 11 : 14, fallbackColor, 1);
      fallback.setStrokeStyle(2, isExecProcess ? 0x2a1800 : 0x0a1a2e, 0.8);
      children.push(fallback);
      body = fallback;
    }

    const container = this.add.container(startNode.x, startNode.y, children);
    container.setDepth(this.layerToDepth('actor', startNode.y) - 0.5);
    container.setAlpha(0);
    this.tweens.add({ targets: container, alpha: 1, duration: 600, ease: 'Sine.Out' });

    // Floating name tag
    const shortLabel = `${nameTagPrefix}${label.slice(0, 14)}`;
    const nameTag = this.add.text(startNode.x, startNode.y - 36, shortLabel, {
      color: nameTagColor,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '13px',
      backgroundColor: nameTagBg,
      padding: { left: 5, right: 5, top: 3, bottom: 3 }
    });
    nameTag.setOrigin(0.5, 1);
    nameTag.setDepth(this.layerToDepth('fx_overlay') + 11);

    // Thought bubble — shows last milestone/status, styled like the main capy's thought bubble
    const thoughtBubble = this.add.text(startNode.x, startNode.y - 52, '', {
      color: '#f3fff9',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '10px',
      lineSpacing: 2,
      align: 'center',
      backgroundColor: 'rgba(9, 24, 22, 0.82)',
      padding: { left: 6, right: 6, top: 4, bottom: 4 },
      wordWrap: { width: 140 }
    });
    thoughtBubble.setOrigin(0.5, 1);
    thoughtBubble.setDepth(this.layerToDepth('fx_overlay') + 12);
    thoughtBubble.setStroke('#04100f', 2);
    thoughtBubble.setVisible(false); // hidden until first status update

    const agentActor: AgentActor = {
      id: runId,
      label,
      kind,
      container,
      body,
      route: [],
      activeZoneId: null,
      focusZoneId: null,
      workCursor: Math.floor(Math.random() * 100),
      nameTag,
      thoughtBubble,
      visualMode: 'idle',
      workingUntil: 0,
      lingerUntil: 0,
      facing: 'down'
    };

    // Set initial animation for subagents
    if (kind === 'subagent') {
      this.updateAgentActorVisual(agentActor, 'idle');
    }

    this.agentActors.push(agentActor);
  }

  public setAgentActorFocus(runId: string, focusZoneId: ResourcePartitionId | null): void {
    const actor = this.agentActors.find((a) => a.id === runId);
    if (!actor) return;
    if (actor.focusZoneId === focusZoneId) return;
    actor.focusZoneId = focusZoneId;
    // Clear current route so next tick picks up the new focus zone
    actor.route = [];
    actor.activeZoneId = null;
  }

  /** Update the thought bubble text for a sub-agent or exec-process */
  public setAgentActorStatus(runId: string, statusText: string): void {
    const actor = this.agentActors.find((a) => a.id === runId);
    if (!actor || !actor.thoughtBubble) return;
    if (statusText) {
      actor.thoughtBubble.setText(statusText);
      actor.thoughtBubble.setVisible(true);
    } else {
      actor.thoughtBubble.setVisible(false);
    }
  }

  public setPrimaryAgentLabel(label: string): void {
    if (!this.lobsterNameTag) {
      return;
    }
    const normalizedLabel = label.trim().slice(0, 20) || '默认Agent';
    this.lobsterNameTag.setText(normalizedLabel);
    this.positionThoughtBubble();
  }

  public despawnAgentActor(runId: string): void {
    const index = this.agentActors.findIndex((actor) => actor.id === runId);
    if (index === -1) {
      return;
    }
    const actor = this.agentActors[index];
    this.tweens.add({
      targets: actor.container,
      alpha: 0,
      duration: 400,
      ease: 'Sine.In',
      onComplete: () => {
        actor.container.destroy();
      }
    });
    actor.nameTag?.destroy();
    actor.thoughtBubble?.destroy();
    this.agentActors.splice(index, 1);
  }

  // Rooms considered "bottom floor" — exec-processes wander freely inside these
  private readonly BOTTOM_ROOM_IDS: ReadonlyArray<string> = ['document', 'agent', 'break_room'];

  private advanceAgentActor(actor: AgentActor, deltaMs: number): void {
    // Update name tag and thought bubble positions
    if (actor.nameTag) {
      const bounds = actor.container.getBounds();
      actor.nameTag.setPosition(actor.container.x, bounds.top - 4);
      if (actor.thoughtBubble) {
        actor.thoughtBubble.setPosition(actor.container.x, bounds.top - 4 - actor.nameTag.height - 2);
      }
    }

    if (actor.route.length === 0) {
      // Linger at destination before picking a new route (prevents jitter + frozen loops)
      const now = Date.now();
      if (actor.lingerUntil > 0 && now < actor.lingerUntil) {
        // Still lingering — update visual but don't pick new route
        if (actor.kind === 'subagent') {
          const targetMode: WorkMode = actor.workingUntil > 0 && now < actor.workingUntil ? 'working' : 'idle';
          if (actor.visualMode !== targetMode) {
            actor.visualMode = targetMode;
            this.updateAgentActorVisual(actor, targetMode);
          }
        }
        return;
      }

      // Subagent visual: if working timer expired, revert to idle
      if (actor.kind === 'subagent') {
        const targetMode: WorkMode = actor.workingUntil > 0 && now < actor.workingUntil ? 'working' : 'idle';
        if (actor.visualMode !== targetMode) {
          actor.visualMode = targetMode;
          this.updateAgentActorVisual(actor, targetMode);
        }
      }

      // If we have a focusZoneId and we're already in that zone, linger longer (don't re-route to same spot)
      if (actor.focusZoneId && actor.focusZoneId === actor.activeZoneId) {
        actor.lingerUntil = now + 4000 + Math.random() * 3000; // 4-7s idle at focus zone
        actor.activeZoneId = null;
        return;
      }

      // Pick next zone to wander to — exclude zones claimed by primary or other agents
      const claimedZones = new Set<string>();
      if (this.activeZoneId) {
        claimedZones.add(this.activeZoneId);
      }
      if (this.lastReachedZoneId) {
        claimedZones.add(this.lastReachedZoneId);
      }
      for (const other of this.agentActors) {
        if (other.id !== actor.id && other.activeZoneId) {
          claimedZones.add(other.activeZoneId);
        }
      }

      // exec-processes roam only inside the bottom-floor rooms (break_room / document / agent)
      // subagents roam wherever their focusZoneId points, or all zones
      const candidateZones = actor.kind === 'exec-process'
        ? this.protocols.mapLogic.workZones.filter(
            (zone) => this.BOTTOM_ROOM_IDS.includes(zone.id) && !claimedZones.has(zone.id)
          )
        : this.protocols.mapLogic.workZones.filter((zone) => !claimedZones.has(zone.id));

      const allZones = candidateZones.length > 0
        ? candidateZones
        : (actor.kind === 'exec-process'
            ? this.protocols.mapLogic.workZones.filter((zone) => this.BOTTOM_ROOM_IDS.includes(zone.id))
            : this.protocols.mapLogic.workZones);

      if (allZones.length === 0) {
        return;
      }

      // subagents: if they have a focusZoneId, always route there first
      const focusZone = actor.focusZoneId
        ? (allZones.find((z) => z.id === actor.focusZoneId) ?? allZones[actor.workCursor % allZones.length])
        : allZones[actor.workCursor % allZones.length];

      const zone = focusZone;
      actor.workCursor += 1;
      actor.activeZoneId = zone.id;

      const maskRoute = this.computeMaskRoute({ x: actor.container.x, y: actor.container.y }, zone.anchor);
      actor.route = maskRoute ?? [];

      if (actor.route.length === 0) {
        actor.activeZoneId = null;
      }
      return;
    }

    const target = actor.route[0];
    // exec-processes: slow drift (they're background tasks). subagents: calm walk.
    const speedPerMs = actor.kind === 'exec-process' ? 0.055 : 0.098;
    const step = speedPerMs * deltaMs;
    const dx = target.x - actor.container.x;
    const dy = target.y - actor.container.y;
    const distance = Math.hypot(dx, dy);
    if (distance > 0.001) {
      actor.facing = this.resolveDirectionFromVector(dx, dy, actor.facing);
    }

    if (actor.body instanceof Phaser.GameObjects.Sprite) {
      actor.body.setFlipX(this.variantUsesDirectionalWalk() ? false : dx < 0);
    }

    // Subagent: switch to moving animation while walking
    if (actor.kind === 'subagent' && actor.visualMode !== 'moving') {
      actor.visualMode = 'moving';
      this.updateAgentActorVisual(actor, 'moving');
    }

    if (distance <= step) {
      actor.container.x = target.x;
      actor.container.y = target.y;
      actor.container.setDepth(this.layerToDepth('actor', actor.container.y) - 0.5);
      actor.route.shift();

      if (actor.route.length === 0) {
        // Arrived — set linger timer so they stay put for a while
        const lingerMs = actor.focusZoneId
          ? 5000 + Math.random() * 5000   // 5-10s at focus zone
          : 2000 + Math.random() * 3000;  // 2-5s wandering
        actor.lingerUntil = Date.now() + lingerMs;

        // Subagent plays working animation briefly, then idle
        if (actor.kind === 'subagent') {
          actor.visualMode = 'working';
          actor.workingUntil = Date.now() + 1400;
          this.updateAgentActorVisual(actor, 'working');
        }
      }
    } else {
      actor.container.x += (dx / distance) * step;
      actor.container.y += (dy / distance) * step;
      actor.container.setDepth(this.layerToDepth('actor', actor.container.y) - 0.5);
    }
  }

  public setLocale(nextLocale: UiLocale): void {
    this.locale = nextLocale;
    this.syncRoomLabels();
    this.drawWorkZones();
  }

  public setDebugVisualsVisible(visible: boolean): void {
    this.debugVisualsVisible = visible;
    this.applyDebugVisualLayerVisibility();
    this.drawSceneMapLayers();
  }

  public applySettingsMode(nextMode: SceneSettingsMode, options: { silent?: boolean } = {}): void {
    this.settingsMode = nextMode;
    this.houseOverlaySuppressed = nextMode === 'house';
    if (nextMode === 'furniture') {
      this.setEditorMode(true, 'furniture', { silent: options.silent });
      return;
    }

    if (nextMode === 'house') {
      if (this.editorModeEnabled && this.editorTool === 'wall' && this.wallEditorSessionActive) {
        this.setEditorMode(true, 'wall', { silent: true });
        return;
      }
      if (this.editorModeEnabled && this.editorTool === 'room_label' && this.roomLabelEditorSessionActive) {
        this.setEditorMode(true, 'room_label', { silent: true });
        return;
      }
      if (this.wallEditorSessionActive && !this.roomLabelEditorSessionActive) {
        this.setEditorMode(true, 'wall', { silent: true });
        return;
      }
      if (this.roomLabelEditorSessionActive && !this.wallEditorSessionActive) {
        this.setEditorMode(true, 'room_label', { silent: true });
        return;
      }
    }

    if (nextMode === 'interaction' && this.interactionEditorSessionActive) {
      this.setEditorMode(true, 'interaction', { silent: true });
      return;
    }

    // House/character/shop and null keep scene editor state off in phase-one settings flow.
    this.setEditorMode(false, this.editorTool, { silent: options.silent });
  }

  public applyHouseBackdrop(backdrop: { houseId: string; assetUrl: string } | null): void {
    const floorImage = this.resolveSceneFloorImage();
    if (!floorImage) {
      return;
    }

    if (!backdrop || !backdrop.houseId || !backdrop.assetUrl) {
      floorImage.setTexture('__WHITE');
      floorImage.setTint(0x0a1016);
      floorImage.setDisplaySize(this.floorBackdropFrame.width, this.floorBackdropFrame.height);
      this.activeHouseBackgroundSignature = null;
      this.applyStageCameraFit();
      this.refreshWalkableMaskAfterBackdropChange();
      return;
    }

    const normalizedAssetUrl = this.resolveRuntimeAssetUrl(backdrop.assetUrl);
    const signature = `${backdrop.houseId}|${normalizedAssetUrl}`;
    const cachedTextureKey = this.houseTextureKeyBySignature.get(signature) ?? null;
    if (cachedTextureKey && this.textures.exists(cachedTextureKey)) {
      if (
        this.activeHouseBackgroundSignature === signature
        && floorImage.texture?.key === cachedTextureKey
      ) {
        return;
      }
      floorImage.setTexture(cachedTextureKey);
      floorImage.clearTint();
      this.fitFloorBackdropToTexture(floorImage, cachedTextureKey);
      this.applyStageCameraFit();
      this.activeHouseBackgroundSignature = signature;
      this.refreshWalkableMaskAfterBackdropChange();
      return;
    }

    const textureKey = this.textureKeyForHouseSignature(signature, backdrop.houseId);
    if (this.textures.exists(textureKey)) {
      floorImage.setTexture(textureKey);
      floorImage.clearTint();
      this.fitFloorBackdropToTexture(floorImage, textureKey);
      this.applyStageCameraFit();
      this.activeHouseBackgroundSignature = signature;
      this.houseTextureKeyBySignature.set(signature, textureKey);
      this.refreshWalkableMaskAfterBackdropChange();
      return;
    }

    if (this.queuedTextureKeys.has(textureKey)) {
      return;
    }

    const candidateUrls = this.resolveRuntimeAssetUrlCandidates(normalizedAssetUrl);
    this.loadImageTextureWithFallback(textureKey, candidateUrls, {
      onLoaded: (loadedTextureKey) => {
        this.queuedTextureKeys.delete(textureKey);
        if (!this.textures.exists(loadedTextureKey)) {
          return;
        }
        floorImage.setTexture(loadedTextureKey);
        floorImage.clearTint();
        this.fitFloorBackdropToTexture(floorImage, loadedTextureKey);
        this.applyStageCameraFit();
        this.activeHouseBackgroundSignature = signature;
        this.houseTextureKeyBySignature.set(signature, loadedTextureKey);
        this.refreshWalkableMaskAfterBackdropChange();
      },
      onFailed: () => {
        this.queuedTextureKeys.delete(textureKey);
        this.showSceneToast('房屋底板加载失败，已保留当前底板。', 'warn', 1200);
      }
    });
  }

  private refreshWalkableMaskAfterBackdropChange(): void {
    this.initializeWalkableMask();
    this.drawWorkZones();
    this.resetPatrolProgressTracking();
  }

  private resolveRuntimeAssetUrlCandidates(rawAssetUrl: string): string[] {
    const raw = String(rawAssetUrl || '').trim();
    if (!raw) {
      return [];
    }
    if (/^(https?:\/\/|data:|blob:)/i.test(raw)) {
      return [raw];
    }

    const normalized = raw.replace(/\\/g, '/');
    const relative = normalized.replace(/^\/+/, '');
    const baseUrl = String((import.meta as ImportMeta & { env?: { BASE_URL?: string } }).env?.BASE_URL || '/');
    const basePrefix = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
    const withBase = `${basePrefix}${relative}`;
    const rootAbsolute = `/${relative}`;
    const dotRelative = `./${relative}`;

    const candidates = [normalized, withBase, rootAbsolute, dotRelative];
    const deduped: string[] = [];
    const seen = new Set<string>();
    for (const candidate of candidates) {
      const clean = String(candidate || '').trim();
      if (!clean || seen.has(clean)) {
        continue;
      }
      seen.add(clean);
      deduped.push(clean);
    }
    return deduped;
  }

  private resolveRuntimeAssetUrl(rawAssetUrl: string): string {
    return this.resolveRuntimeAssetUrlCandidates(rawAssetUrl)[0] || String(rawAssetUrl || '').trim();
  }

  private loadImageTextureWithFallback(
    primaryTextureKey: string,
    candidateUrls: string[],
    handlers: {
      onLoaded: (textureKey: string) => void;
      onFailed: () => void;
    }
  ): void {
    const queue = candidateUrls.filter((url) => String(url || '').trim().length > 0);
    if (queue.length === 0) {
      handlers.onFailed();
      return;
    }

    const tryLoadAt = (index: number): void => {
      if (index >= queue.length) {
        handlers.onFailed();
        return;
      }
      const url = queue[index];
      const textureKey = index === 0 ? primaryTextureKey : `${primaryTextureKey}-alt-${index}`;
      if (this.textures.exists(textureKey)) {
        handlers.onLoaded(textureKey);
        return;
      }
      this.queuedTextureKeys.add(textureKey);
      const image = new Image();
      const done = (ok: boolean): void => {
        image.onload = null;
        image.onerror = null;
        this.queuedTextureKeys.delete(textureKey);
        if (ok) {
          if (this.textures.exists(textureKey)) {
            this.textures.remove(textureKey);
          }
          const added = this.textures.addImage(textureKey, image);
          if (added) {
            handlers.onLoaded(textureKey);
            return;
          }
        }
        tryLoadAt(index + 1);
      };
      image.onload = () => done(true);
      image.onerror = () => done(false);
      const cacheBust = `${url.includes('?') ? '&' : '?'}t=${Date.now()}`;
      image.src = `${url}${cacheBust}`;
    };

    tryLoadAt(0);
  }

  private fitFloorBackdropToTexture(floorImage: Phaser.GameObjects.Image, textureKey: string): void {
    const texture = this.textures.get(textureKey);
    const source = texture?.getSourceImage() as { width?: number; height?: number } | null;
    const sourceWidth = Number(source?.width) || 0;
    const sourceHeight = Number(source?.height) || 0;
    if (sourceWidth <= 0 || sourceHeight <= 0) {
      floorImage.setDisplaySize(this.floorBackdropFrame.width, this.floorBackdropFrame.height);
      return;
    }

    const frameWidth = Math.max(1, this.floorBackdropFrame.width);
    const frameHeight = Math.max(1, this.floorBackdropFrame.height);
    const sourceRatio = sourceWidth / sourceHeight;
    const frameRatio = frameWidth / frameHeight;

    let displayWidth = frameWidth;
    let displayHeight = frameHeight;
    if (sourceRatio > frameRatio) {
      displayHeight = frameWidth / sourceRatio;
    } else {
      displayWidth = frameHeight * sourceRatio;
    }
    floorImage.setDisplaySize(displayWidth, displayHeight);
  }

  public getEditorModeState(): { enabled: boolean; tool: SceneEditorTool } {
    return {
      enabled: this.editorModeEnabled,
      tool: this.editorTool
    };
  }

  public setWallEditorShapePreset(shape: WallShapeType): void {
    this.wallEditorShapePreset = shape;
    if (this.editorModeEnabled && this.editorTool === 'wall') {
      this.showSceneToast(`墙壁图形：${this.wallShapeLabel(shape)}`, 'info', 900);
    }
  }

  public enterWallEditor(options: { shape?: WallShapeType; silent?: boolean } = {}): void {
    if (options.shape) {
      this.wallEditorShapePreset = options.shape;
    }
    if (!this.wallEditorSessionActive) {
      this.wallEditorBaseline = this.cloneWallBlocks(this.sceneMapData.wall_blocks);
      this.wallEditorDirty = false;
      this.wallEditorSessionActive = true;
      this.selectedWallBlockId = null;
    }
    this.setEditorMode(true, 'wall', { silent: true });
    if (!options.silent) {
      this.showSceneToast('墙壁编辑已开启。左键选中/拖拽，右键删除。', 'success', 1500);
    }
  }

  public saveWallEditorChanges(): void {
    if (!this.editorModeEnabled || this.editorTool !== 'wall') {
      return;
    }
    this.persistSceneMap('墙壁设置保存');
    this.wallEditorBaseline = this.cloneWallBlocks(this.sceneMapData.wall_blocks);
    this.wallEditorDirty = false;
    this.showSceneToast('墙壁设置已保存。', 'success', 1300);
  }

  public exitWallEditor(options: { discardUnsaved?: boolean; silent?: boolean } = {}): void {
    if (!this.wallEditorSessionActive && !(this.editorModeEnabled && this.editorTool === 'wall')) {
      return;
    }
    const discardUnsaved = options.discardUnsaved === true;
    if (discardUnsaved && this.wallEditorDirty && this.wallEditorBaseline) {
      this.sceneMapData.wall_blocks = this.cloneWallBlocks(this.wallEditorBaseline);
      this.initializeWalkableMask();
      this.drawRooms();
      this.drawSceneMapLayers();
      this.drawWorkZones();
    }

    this.wallEditorSessionActive = false;
    this.wallEditorDirty = false;
    this.wallEditorBaseline = null;
    this.selectedWallBlockId = null;
    this.wallEditorDragState = null;
    this.setEditorMode(false, 'wall', { silent: true });
    if (!options.silent) {
      this.showSceneToast('墙壁编辑已退出。', 'info', 1200);
    }
  }

  public enterFurniturePlacement(options: { silent?: boolean } = {}): void {
    this.setEditorMode(true, 'furniture', { silent: true });
    if (!options.silent) {
      this.showSceneToast('家具摆放已开启。左键拖拽，右键删除。', 'success', 1300);
    }
  }

  public exitFurniturePlacement(options: { discardUnsaved?: boolean; silent?: boolean } = {}): void {
    this.furnitureDragState = null;
    const wasFurnitureMode = this.editorModeEnabled && this.editorTool === 'furniture';
    if (wasFurnitureMode) {
      this.setEditorMode(false, 'furniture', { silent: true });
    }
    if (!options.silent && wasFurnitureMode) {
      this.showSceneToast('家具摆放已退出。', 'info', 1200);
    }
  }

  public saveFurniturePlacementChanges(): void {
    this.persistSceneMap('家具摆放保存');
    this.showSceneToast('家具摆放已保存。', 'success', 1200);
  }

  public enterRoomLabelEditor(options: { silent?: boolean } = {}): void {
    if (!this.roomLabelEditorSessionActive) {
      this.roomLabelDragState = null;
      this.selectedRoomLabelId = null;
    }
    this.roomLabelEditorSessionActive = true;
    this.setEditorMode(true, 'room_label', { silent: true });
    if (!options.silent) {
      this.showSceneToast('房屋名编辑已开启。拖拽房屋名称即可调整位置。', 'success', 1400);
    }
  }

  public saveRoomLabelEditorChanges(): void {
    this.persistSceneMap('房屋名编辑保存');
    this.showSceneToast('房屋名编辑已保存。', 'success', 1200);
  }

  public exitRoomLabelEditor(options: { silent?: boolean } = {}): void {
    this.roomLabelDragState = null;
    const wasRoomLabelMode = this.editorModeEnabled && this.editorTool === 'room_label';
    this.roomLabelEditorSessionActive = false;
    this.selectedRoomLabelId = null;
    if (wasRoomLabelMode) {
      this.setEditorMode(false, 'room_label', { silent: true });
      this.syncRoomLabels();
    }
    if (!options.silent && wasRoomLabelMode) {
      this.showSceneToast('房屋名编辑已退出。', 'info', 1200);
    }
  }

  public enterInteractionEditor(options: { mode?: InteractionEditorMode; silent?: boolean } = {}): void {
    if (options.mode) {
      this.interactionEditorMode = options.mode;
    }
    this.interactionEditorSessionActive = true;
    this.ensureInteractionSelection();
    this.setEditorMode(true, 'interaction', { silent: true });
    if (!options.silent) {
      const modeLabel = this.interactionEditorMode === 'action_point' ? '动作点' : '交互框';
      this.showSceneToast(`${modeLabel}编辑已开启。左键拖拽，右键删除。`, 'success', 1500);
    }
  }

  public setInteractionEditorMode(nextMode: InteractionEditorMode): void {
    if (this.interactionEditorMode === nextMode) {
      return;
    }
    this.interactionEditorMode = nextMode;
    this.ensureInteractionSelection();
    this.drawSceneMapLayers();
    if (this.editorModeEnabled && this.editorTool === 'interaction') {
      const label = nextMode === 'action_point' ? '动作点' : '交互框';
      this.showSceneToast(`交互编辑切换：${label}`, 'info', 900);
    }
  }

  public saveInteractionEditorChanges(): void {
    this.persistSceneMap('交互编辑保存');
    this.showSceneToast('交互编辑已保存。', 'success', 1200);
  }

  public exitInteractionEditor(options: { discardUnsaved?: boolean; silent?: boolean } = {}): void {
    const wasInteractionMode = this.editorModeEnabled && this.editorTool === 'interaction';
    this.interactionEditorSessionActive = false;
    this.interactionPointDragState = null;
    this.interactionBoxDragState = null;
    this.selectedInteractionPointId = null;
    this.selectedInteractionBoxId = null;
    if (wasInteractionMode) {
      this.setEditorMode(false, 'interaction', { silent: true });
    }
    if (!options.silent && wasInteractionMode) {
      this.showSceneToast('已退出交互编辑。', 'info', 1200);
    }
  }

  public getInteractionEditorSnapshot(): InteractionEditorSnapshot {
    return {
      mode: this.interactionEditorMode,
      selectedActionPointId: this.selectedInteractionPointId,
      selectedInteractionBoxId: this.selectedInteractionBoxId,
      actionPoints: this.sceneMapData.interaction_points.map((item) => ({ ...item })),
      interactionBoxes: this.sceneMapData.interaction_boxes.map((item) => ({ ...item }))
    };
  }

  public updateSelectedInteractionPointMeta(
    patch: Partial<Pick<
      SceneInteractionPoint,
      'label' | 'interaction_type' | 'sprite_key' | 'sprite_total_frames' | 'sprite_frame_width' | 'sprite_frame_height' | 'sprite_fps'
    >>,
    options: { persist?: boolean } = {}
  ): boolean {
    if (!this.selectedInteractionPointId) {
      return false;
    }
    const target = this.sceneMapData.interaction_points.find((item) => item.id === this.selectedInteractionPointId);
    if (!target) {
      return false;
    }
    if (typeof patch.label === 'string') {
      target.label = patch.label.trim() || target.label;
    }
    if (typeof patch.interaction_type === 'string') {
      target.interaction_type = patch.interaction_type.trim() || target.interaction_type;
    }
    if (typeof patch.sprite_key === 'string') {
      target.sprite_key = patch.sprite_key.trim() || undefined;
    }
    if (typeof patch.sprite_total_frames === 'number' && Number.isFinite(patch.sprite_total_frames)) {
      target.sprite_total_frames = Math.max(1, Math.round(patch.sprite_total_frames));
    }
    if (typeof patch.sprite_frame_width === 'number' && Number.isFinite(patch.sprite_frame_width)) {
      target.sprite_frame_width = Math.max(1, Math.round(patch.sprite_frame_width));
    }
    if (typeof patch.sprite_frame_height === 'number' && Number.isFinite(patch.sprite_frame_height)) {
      target.sprite_frame_height = Math.max(1, Math.round(patch.sprite_frame_height));
    }
    if (typeof patch.sprite_fps === 'number' && Number.isFinite(patch.sprite_fps)) {
      target.sprite_fps = Math.max(1, patch.sprite_fps);
    }
    if (options.persist) {
      this.persistSceneMap(`更新动作点 ${target.id}`);
    } else {
      this.drawSceneMapLayers();
    }
    return true;
  }

  private ensureInteractionSelection(): void {
    if (this.interactionEditorMode === 'action_point') {
      const exists = this.selectedInteractionPointId
        ? this.sceneMapData.interaction_points.some((item) => item.id === this.selectedInteractionPointId)
        : false;
      if (!exists) {
        this.selectedInteractionPointId = this.sceneMapData.interaction_points[0]?.id ?? null;
      }
      this.selectedInteractionBoxId = null;
      this.hoveredInteractionBoxId = null;
      return;
    }

    const exists = this.selectedInteractionBoxId
      ? this.sceneMapData.interaction_boxes.some((item) => item.id === this.selectedInteractionBoxId)
      : false;
    if (!exists) {
      this.selectedInteractionBoxId = this.sceneMapData.interaction_boxes[0]?.id ?? null;
    }
    this.selectedInteractionPointId = null;
    this.hoveredInteractionPointId = null;
  }

  public updateSelectedInteractionBoxMeta(
    patch: Partial<Pick<
      InteractionBox,
      'label' | 'interaction_name' | 'interaction_type' | 'sprite_key' | 'sprite_total_frames' | 'sprite_frame_width' | 'sprite_frame_height' | 'sprite_fps'
    >>,
    options: { persist?: boolean } = {}
  ): boolean {
    if (!this.selectedInteractionBoxId) {
      return false;
    }
    const target = this.sceneMapData.interaction_boxes.find((item) => item.id === this.selectedInteractionBoxId);
    if (!target) {
      return false;
    }
    if (typeof patch.label === 'string') {
      target.label = patch.label.trim() || target.label;
    }
    if (typeof patch.interaction_name === 'string') {
      target.interaction_name = patch.interaction_name.trim() || target.interaction_name;
    }
    if (typeof patch.interaction_type === 'string') {
      target.interaction_type = patch.interaction_type.trim() || target.interaction_type;
    }
    if (typeof patch.sprite_key === 'string') {
      target.sprite_key = patch.sprite_key.trim() || undefined;
    }
    if (typeof patch.sprite_total_frames === 'number' && Number.isFinite(patch.sprite_total_frames)) {
      target.sprite_total_frames = Math.max(1, Math.round(patch.sprite_total_frames));
    }
    if (typeof patch.sprite_frame_width === 'number' && Number.isFinite(patch.sprite_frame_width)) {
      target.sprite_frame_width = Math.max(1, Math.round(patch.sprite_frame_width));
    }
    if (typeof patch.sprite_frame_height === 'number' && Number.isFinite(patch.sprite_frame_height)) {
      target.sprite_frame_height = Math.max(1, Math.round(patch.sprite_frame_height));
    }
    if (typeof patch.sprite_fps === 'number' && Number.isFinite(patch.sprite_fps)) {
      target.sprite_fps = Math.max(1, patch.sprite_fps);
    }
    if (options.persist) {
      this.persistSceneMap(`更新交互框 ${target.id}`);
    } else {
      this.drawSceneMapLayers();
    }
    return true;
  }

  public setFurniturePlacementTemplate(template: FurniturePlacementTemplate | null): void {
    this.furniturePlacementTemplate = template;
    if (template && this.editorModeEnabled && this.editorTool === 'furniture') {
      this.showSceneToast(`摆放模板：${template.label}（${template.direction}）`, 'info', 700);
    }
  }

  public rotateSelectedFurnitureFacing(step: number): boolean {
    if (!(this.editorModeEnabled && this.editorTool === 'furniture')) {
      return false;
    }
    if (!this.selectedFurnitureId) {
      return false;
    }
    const selectedFurniture = this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId) ?? null;
    if (!selectedFurniture) {
      return false;
    }
    const current = this.normalizeFurnitureFacing(selectedFurniture.direction);
    const next = this.shiftFurnitureFacing(current, step);
    if (next === current && !selectedFurniture.sprite_directions) {
      return false;
    }
    selectedFurniture.direction = next;
    const nextSprite = this.resolveFurnitureSpriteForFacing(selectedFurniture, next);
    if (nextSprite) {
      selectedFurniture.sprite_key = nextSprite;
    }
    this.persistSceneMap(`切换家具朝向 ${selectedFurniture.id} -> ${next}`);
    return true;
  }

  public scaleSelectedFurnitureSize(factor: number): boolean {
    if (!(this.editorModeEnabled && this.editorTool === 'furniture')) {
      return false;
    }
    if (!Number.isFinite(factor) || factor <= 0) {
      return false;
    }
    if (!this.selectedFurnitureId) {
      return false;
    }
    const selectedFurniture = this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId) ?? null;
    if (!selectedFurniture) {
      return false;
    }
    const currentWidth = Math.max(8, Math.round(selectedFurniture.width));
    const currentHeight = Math.max(8, Math.round(selectedFurniture.height));
    const maxWidth = Math.max(
      FURNITURE_RESIZE_MIN_SIZE,
      Math.min(FURNITURE_RESIZE_MAX_SIZE, Math.round(this.sceneMapData.base_width))
    );
    const maxHeight = Math.max(
      FURNITURE_RESIZE_MIN_SIZE,
      Math.min(FURNITURE_RESIZE_MAX_SIZE, Math.round(this.sceneMapData.base_height))
    );
    const nextWidth = Math.round(Phaser.Math.Clamp(currentWidth * factor, FURNITURE_RESIZE_MIN_SIZE, maxWidth));
    const nextHeight = Math.round(Phaser.Math.Clamp(currentHeight * factor, FURNITURE_RESIZE_MIN_SIZE, maxHeight));
    if (nextWidth === currentWidth && nextHeight === currentHeight) {
      return false;
    }
    const centerX = selectedFurniture.x + (currentWidth / 2);
    const centerY = selectedFurniture.y + (currentHeight / 2);
    const clamped = this.clampFurniturePosition(
      Math.round(centerX - nextWidth / 2),
      Math.round(centerY - nextHeight / 2),
      nextWidth,
      nextHeight
    );
    selectedFurniture.width = nextWidth;
    selectedFurniture.height = nextHeight;
    selectedFurniture.x = clamped.x;
    selectedFurniture.y = clamped.y;
    selectedFurniture.z_index = selectedFurniture.y + selectedFurniture.height;
    this.persistSceneMap(`调整家具尺寸 ${selectedFurniture.id} -> ${nextWidth}×${nextHeight}`);
    return true;
  }

  public getActorVariants(): Array<{ id: string; label: string }> {
    return this.resolveActorVariants().map((variant) => ({
      id: variant.id,
      label: variant.label
    }));
  }

  public getActorVariantId(): string | null {
    return this.resolveActorVariant()?.id ?? null;
  }

  public getActorVariantLabel(): string {
    return this.resolveActorVariant()?.label ?? 'Actor';
  }

  public setGeneratedActorVariantFolders(folderIds: string[]): void {
    const nextFolders = Array.from(new Set(
      folderIds
        .map((folderId) => this.normalizeGeneratedActorFolderId(folderId))
        .filter((folderId): folderId is string => Boolean(folderId))
    ));
    if (
      nextFolders.length === this.generatedActorVariantFolders.length
      && nextFolders.every((folderId, index) => folderId === this.generatedActorVariantFolders[index])
    ) {
      return;
    }
    this.generatedActorVariantFolders = nextFolders;
    this.generatedActorVariantCache.clear();
  }

  public setActorVariant(nextVariantId: string): void {
    const variant = this.resolveActorVariants().find((entry) => entry.id === nextVariantId);
    if (!variant) {
      return;
    }
    if (this.actorVariantId === variant.id) {
      return;
    }
    this.ensureActorVariantTexturesReady(variant, () => {
      this.applyActorVariant(variant);
    });
  }

  private preloadSceneArt(): void {
    for (const layer of this.activeSceneGlobalLayers()) {
      this.loadTextureAsset(layer);
    }

    for (const slice of this.protocols.sceneArt.roomSlices) {
      for (const layer of slice.layers) {
        this.loadTextureAsset(layer);
      }
    }

    for (const variant of this.resolveActorVariants()) {
      for (const mode of variant.modes ?? []) {
        this.loadTextureAsset(mode);
      }
    }

    for (const ref of this.protocols.sceneArt.conceptRefs ?? []) {
      this.loadTextureAsset({
        textureKey: ref.id,
        path: ref.path,
        kind: 'image'
      });
    }
  }

  private loadTextureAsset(asset: {
    textureKey: string;
    path: string;
    kind?: 'image' | 'svg' | 'spritesheet';
    frameWidth?: number;
    frameHeight?: number;
    frameCount?: number;
    margin?: number;
    spacing?: number;
  }): void {
    if (this.textures.exists(asset.textureKey) || this.queuedTextureKeys.has(asset.textureKey)) {
      return;
    }
    this.queuedTextureKeys.add(asset.textureKey);

    const inferredKind = asset.kind ?? (asset.path.toLowerCase().endsWith('.svg') ? 'svg' : 'image');
    if (inferredKind === 'svg') {
      this.load.svg(asset.textureKey, asset.path);
      return;
    }

    if (inferredKind === 'spritesheet') {
      this.load.spritesheet(asset.textureKey, asset.path, {
        frameWidth: asset.frameWidth ?? 1,
        frameHeight: asset.frameHeight ?? 1,
        endFrame: Math.max(0, (asset.frameCount ?? 1) - 1),
        margin: asset.margin ?? 0,
        spacing: asset.spacing ?? 0
      });
      return;
    }

    this.load.image(asset.textureKey, asset.path);
  }

  private spawnSceneBaseArt(): void {
    this.floorBackdropImage?.destroy();
    this.floorBackdropImage = null;
    for (const rendered of this.renderedGlobalLayers) {
      rendered.shadowImage?.destroy();
      rendered.image.destroy();
    }
    this.renderedGlobalLayers = [];

    const floorSpec = this.resolveFloorBackdropSpec();
    if (floorSpec) {
      this.floorBackdropFrame = {
        width: Math.max(1, floorSpec.displaySize.width),
        height: Math.max(1, floorSpec.displaySize.height)
      };
      this.floorBackdropImage = this.add.image(floorSpec.anchor.x, floorSpec.anchor.y, '__WHITE');
      this.floorBackdropImage.setDisplaySize(this.floorBackdropFrame.width, this.floorBackdropFrame.height);
      this.floorBackdropImage.setTint(0x0a1016);
      this.floorBackdropImage.setAlpha(1);
      this.floorBackdropImage.setDepth(this.layerToDepth('floor', floorSpec.anchor.y) - 0.5);
    }

    const globalLayers = this.activeSceneGlobalLayers();

    for (const layer of globalLayers) {
      const baseDepth = this.layerToDepth(layer.renderLayer, layer.anchor.y) - (layer.renderLayer === 'floor' ? 0.5 : 0.1);
      const shadowImage = this.createLayerShadowImage(layer.textureKey, layer.renderLayer, layer.anchor, layer.displaySize, baseDepth);
      const image = this.add.image(layer.anchor.x, layer.anchor.y, layer.textureKey);
      image.setDisplaySize(layer.displaySize.width, layer.displaySize.height);
      image.setAlpha(layer.alpha ?? 1);
      image.setDepth(baseDepth);
      this.renderedGlobalLayers.push({ layer, shadowImage, image });
    }
    this.applyGlobalLayerTheme();
  }

  private applyGlobalLayerTheme(): void {
    const theme = this.getTheme();
    for (const rendered of this.renderedGlobalLayers) {
      rendered.shadowImage?.setTintFill(0x000000);
      if (rendered.layer.tintWithTheme) {
        rendered.image.setTint(theme.tint);
      } else {
        rendered.image.clearTint();
      }
    }
  }

  private hasSceneBaseArt(): boolean {
    return Boolean(this.floorBackdropImage) || this.renderedGlobalLayers.length > 0;
  }

  private activeSceneGlobalLayers(): SceneGlobalLayerDef[] {
    const layers = this.protocols.sceneArt.globalLayers ?? [];
    return layers.filter((layer) => layer.renderLayer !== 'floor');
  }

  private resolveFloorBackdropSpec(): { anchor: Point; displaySize: { width: number; height: number } } | null {
    const globalLayers = this.protocols.sceneArt.globalLayers ?? [];
    const floorLayer = globalLayers.find((layer) => layer.renderLayer === 'floor') ?? null;
    if (floorLayer?.anchor && floorLayer?.displaySize) {
      return {
        anchor: {
          x: Number(floorLayer.anchor.x) || (this.sceneMapData.base_width / 2),
          y: Number(floorLayer.anchor.y) || (this.sceneMapData.base_height / 2)
        },
        displaySize: {
          width: Math.max(1, Number(floorLayer.displaySize.width) || this.sceneMapData.base_width),
          height: Math.max(1, Number(floorLayer.displaySize.height) || this.sceneMapData.base_height)
        }
      };
    }
    return {
      anchor: {
        x: this.sceneMapData.base_width / 2,
        y: this.sceneMapData.base_height / 2
      },
      displaySize: {
        width: this.sceneMapData.base_width,
        height: this.sceneMapData.base_height
      }
    };
  }

  private resolveSceneFloorImage(): Phaser.GameObjects.Image | null {
    return this.floorBackdropImage;
  }

  private textureKeyForHouseSignature(signature: string, houseId: string): string {
    const safeHouseId = houseId
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 36) || 'house';
    let hash = 0;
    for (let i = 0; i < signature.length; i += 1) {
      hash = ((hash * 31) + signature.charCodeAt(i)) >>> 0;
    }
    return `tyxt-house-floor-${safeHouseId}-${hash.toString(16)}`;
  }

  private cssColor(color: number, alpha: number): string {
    const rgb = Phaser.Display.Color.IntegerToRGB(color);
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
  }

  private initializeWalkableMask(): void {
    const sourceWidth = Math.max(1, Math.round(this.sceneMapData.base_width));
    const sourceHeight = Math.max(1, Math.round(this.sceneMapData.base_height));
    const canvas = document.createElement('canvas');
    canvas.width = sourceWidth;
    canvas.height = sourceHeight;
    const context = canvas.getContext('2d');
    if (!context) {
      this.walkableMaskData = null;
      this.walkableMaskWidth = 0;
      this.walkableMaskHeight = 0;
      this.walkableMaskColorMode = 'red';
      return;
    }

    context.clearRect(0, 0, sourceWidth, sourceHeight);
    context.fillStyle = '#ff0000';
    this.fillWalkableMainBackdropOnCanvas(context);

    context.globalCompositeOperation = 'destination-out';
    context.fillStyle = '#000000';
    for (const wallBlock of this.sceneMapData.wall_blocks) {
      this.fillWallBlockOnCanvas(context, wallBlock);
    }
    // Furniture no longer blocks primary-agent movement.
    // This avoids oversized transparent sprite bounds causing false path obstruction.
    context.globalCompositeOperation = 'source-over';

    const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
    this.walkableMaskData = imageData.data;
    this.walkableMaskWidth = canvas.width;
    this.walkableMaskHeight = canvas.height;
    this.detectWalkableMaskColorMode();
    this.initializeWalkableGrid();
    this.snapRuntimeAnchorsToWalkable();
  }

  private fillWalkableMainBackdropOnCanvas(context: CanvasRenderingContext2D): void {
    const rect = this.resolveWalkableMainBackdropRect();
    context.beginPath();
    context.rect(rect.x, rect.y, rect.width, rect.height);
    context.closePath();
    context.fill();
  }

  private resolveWalkableMainBackdropRect(): SceneMapRect {
    if (this.floorBackdropImage) {
      const width = Number(this.floorBackdropImage.displayWidth) || 0;
      const height = Number(this.floorBackdropImage.displayHeight) || 0;
      if (width > 0 && height > 0) {
        return {
          x: this.floorBackdropImage.x - width / 2,
          y: this.floorBackdropImage.y - height / 2,
          width,
          height
        };
      }
    }

    const floorSpec = this.resolveFloorBackdropSpec();
    if (floorSpec) {
      return {
        x: floorSpec.anchor.x - floorSpec.displaySize.width / 2,
        y: floorSpec.anchor.y - floorSpec.displaySize.height / 2,
        width: floorSpec.displaySize.width,
        height: floorSpec.displaySize.height
      };
    }

    return {
      x: 0,
      y: 0,
      width: this.sceneMapData.base_width,
      height: this.sceneMapData.base_height
    };
  }

  private cloneWallBlocks(blocks: WallBlock[]): WallBlock[] {
    return blocks.map((block) => ({
      ...block,
      shape: block.shape || 'rectangle',
      rotation: Number(block.rotation) || 0
    }));
  }

  private wallShapeLabel(shape: WallShapeType): string {
    if (shape === 'square') return '正方形';
    if (shape === 'rectangle') return '长方形';
    if (shape === 'triangle') return '三角形';
    if (shape === 'circle') return '圆形';
    return '梯形';
  }

  private wallBlockCenter(block: WallBlock): Point {
    return {
      x: block.x + block.width / 2,
      y: block.y + block.height / 2
    };
  }

  private wallBlockShapeSize(block: WallBlock): { width: number; height: number } {
    if (block.shape === 'square') {
      const side = Math.max(block.width, block.height);
      return { width: side, height: side };
    }
    return {
      width: Math.max(EDITOR_WALL_MIN_SIZE, block.width),
      height: Math.max(EDITOR_WALL_MIN_SIZE, block.height)
    };
  }

  private rotateLocalPoint(point: Point, rad: number): Point {
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    return {
      x: point.x * cos - point.y * sin,
      y: point.x * sin + point.y * cos
    };
  }

  private wallBlockLocalPolygon(block: WallBlock): Point[] {
    const size = this.wallBlockShapeSize(block);
    const halfW = size.width / 2;
    const halfH = size.height / 2;

    if (block.shape === 'triangle') {
      return [
        { x: 0, y: -halfH },
        { x: halfW, y: halfH },
        { x: -halfW, y: halfH }
      ];
    }

    if (block.shape === 'trapezoid') {
      const topHalfW = halfW * 0.6;
      return [
        { x: -topHalfW, y: -halfH },
        { x: topHalfW, y: -halfH },
        { x: halfW, y: halfH },
        { x: -halfW, y: halfH }
      ];
    }

    if (block.shape === 'circle') {
      const points: Point[] = [];
      const segments = 28;
      for (let i = 0; i < segments; i += 1) {
        const t = (Math.PI * 2 * i) / segments;
        points.push({
          x: Math.cos(t) * halfW,
          y: Math.sin(t) * halfH
        });
      }
      return points;
    }

    return [
      { x: -halfW, y: -halfH },
      { x: halfW, y: -halfH },
      { x: halfW, y: halfH },
      { x: -halfW, y: halfH }
    ];
  }

  private wallBlockPolygon(block: WallBlock): Point[] {
    const center = this.wallBlockCenter(block);
    const localPoints = this.wallBlockLocalPolygon(block);
    const rad = Phaser.Math.DegToRad(Number(block.rotation) || 0);
    return localPoints.map((point) => {
      const rotated = this.rotateLocalPoint(point, rad);
      return {
        x: center.x + rotated.x,
        y: center.y + rotated.y
      };
    });
  }

  private wallBlockBounds(block: WallBlock): SceneMapRect {
    const polygon = this.wallBlockPolygon(block);
    if (polygon.length === 0) {
      return {
        x: block.x,
        y: block.y,
        width: block.width,
        height: block.height
      };
    }
    let minX = polygon[0].x;
    let maxX = polygon[0].x;
    let minY = polygon[0].y;
    let maxY = polygon[0].y;
    for (const point of polygon) {
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    }
    return {
      x: minX,
      y: minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY)
    };
  }

  private pointInWallBlock(point: Point, block: WallBlock): boolean {
    const polygon = this.wallBlockPolygon(block);
    return polygon.length >= 3 ? pointInPolygon(point, polygon) : false;
  }

  private fillWallBlockOnCanvas(context: CanvasRenderingContext2D, block: WallBlock): void {
    const polygon = this.wallBlockPolygon(block);
    if (polygon.length < 3) {
      return;
    }
    context.beginPath();
    context.moveTo(polygon[0].x, polygon[0].y);
    for (let i = 1; i < polygon.length; i += 1) {
      context.lineTo(polygon[i].x, polygon[i].y);
    }
    context.closePath();
    context.fill();
  }

  private drawWallBlockOnGraphics(
    graphics: Phaser.GameObjects.Graphics,
    block: WallBlock,
    options: { fillColor: number; fillAlpha: number; strokeColor?: number; strokeAlpha?: number; strokeWidth?: number }
  ): void {
    const polygon = this.wallBlockPolygon(block);
    if (polygon.length < 3) {
      return;
    }
    graphics.fillStyle(options.fillColor, options.fillAlpha);
    graphics.fillPoints(polygon, true);
    graphics.lineStyle(options.strokeWidth ?? 1.2, options.strokeColor ?? 0xf2fbff, options.strokeAlpha ?? 0.8);
    graphics.strokePoints(polygon, true, true);
  }

  private detectWalkableMaskColorMode(): void {
    if (!this.walkableMaskData) {
      this.walkableMaskColorMode = 'red';
      return;
    }

    let opaque = 0;
    let red = 0;
    let blue = 0;
    for (let index = 0; index < this.walkableMaskData.length; index += 4) {
      const r = this.walkableMaskData[index];
      const g = this.walkableMaskData[index + 1];
      const b = this.walkableMaskData[index + 2];
      const a = this.walkableMaskData[index + 3];
      if (a <= 8) {
        continue;
      }
      opaque += 1;
      const redDominant = r >= g + 12 && r >= b + 12;
      const blueDominant = b >= r + 12 && b >= g + 12;
      if (redDominant) {
        red += 1;
      }
      if (blueDominant) {
        blue += 1;
      }
    }

    if (opaque === 0) {
      this.walkableMaskColorMode = 'red';
      return;
    }

    const redRatio = red / opaque;
    const blueRatio = blue / opaque;
    if (redRatio >= 0.25) {
      this.walkableMaskColorMode = 'red';
    } else if (blueRatio >= 0.25) {
      this.walkableMaskColorMode = 'blue';
    } else {
      this.walkableMaskColorMode = 'opaque';
    }
  }

  private isWalkableMaskPixel(r: number, g: number, b: number, a: number): boolean {
    if (a <= 8) {
      return false;
    }
    const redDominant = r >= g + 12 && r >= b + 12;
    const blueDominant = b >= r + 12 && b >= g + 12;
    if (this.walkableMaskColorMode === 'red') {
      return redDominant;
    }
    if (this.walkableMaskColorMode === 'blue') {
      return blueDominant;
    }
    return true;
  }

  private initializeWalkableGrid(): void {
    const baseWidth = this.sceneMapData.base_width;
    const baseHeight = this.sceneMapData.base_height;
    this.walkableGridCols = Math.ceil(baseWidth / this.walkableGridStep);
    this.walkableGridRows = Math.ceil(baseHeight / this.walkableGridStep);
    this.walkableGrid = new Uint8Array(this.walkableGridCols * this.walkableGridRows);

    for (let row = 0; row < this.walkableGridRows; row += 1) {
      for (let col = 0; col < this.walkableGridCols; col += 1) {
        const samplePoint = {
          x: Math.min(baseWidth - 1, col * this.walkableGridStep + this.walkableGridStep / 2),
          y: Math.min(baseHeight - 1, row * this.walkableGridStep + this.walkableGridStep / 2)
        };
        if (this.isWalkableGridSample(samplePoint)) {
          this.walkableGrid[row * this.walkableGridCols + col] = 1;
        }
      }
    }
    this.reachableWalkableGrid = null;
  }

  private isWalkableGridSample(center: Point): boolean {
    const baseWidth = this.sceneMapData.base_width;
    const baseHeight = this.sceneMapData.base_height;
    const offset = this.walkableGridStep * WALKABLE_CELL_SAFETY_OFFSET_RATIO;
    const sample = (delta: Point): boolean => {
      const point = {
        x: Phaser.Math.Clamp(center.x + delta.x, 0, Math.max(0, baseWidth - 1)),
        y: Phaser.Math.Clamp(center.y + delta.y, 0, Math.max(0, baseHeight - 1))
      };
      return Boolean(this.isWalkableByMask(point));
    };

    // Center must be walkable; cardinal samples are tolerant so narrow corridors do not get over-pruned.
    if (!sample({ x: 0, y: 0 })) {
      return false;
    }
    const cardinals: Point[] = [
      { x: offset, y: 0 },
      { x: -offset, y: 0 },
      { x: 0, y: offset },
      { x: 0, y: -offset }
    ];
    let walkableCount = 0;
    for (const delta of cardinals) {
      if (sample(delta)) {
        walkableCount += 1;
      }
    }
    return walkableCount >= 3;
  }

  private scenePointToBaseArtPixel(point: Point): { x: number; y: number } | null {
    const baseWidth = Math.max(1, this.sceneMapData.base_width);
    const baseHeight = Math.max(1, this.sceneMapData.base_height);
    if (!this.walkableMaskWidth || !this.walkableMaskHeight) {
      return null;
    }
    const normalizedX = point.x / baseWidth;
    const normalizedY = point.y / baseHeight;
    if (normalizedX < 0 || normalizedX > 1 || normalizedY < 0 || normalizedY > 1) {
      return null;
    }

    return {
      x: Math.max(0, Math.min(this.walkableMaskWidth - 1, Math.round(normalizedX * (this.walkableMaskWidth - 1)))),
      y: Math.max(0, Math.min(this.walkableMaskHeight - 1, Math.round(normalizedY * (this.walkableMaskHeight - 1))))
    };
  }

  private baseArtPixelToScenePoint(pixel: { x: number; y: number }): Point | null {
    const baseWidth = Math.max(1, this.sceneMapData.base_width);
    const baseHeight = Math.max(1, this.sceneMapData.base_height);
    if (!this.walkableMaskWidth || !this.walkableMaskHeight) {
      return null;
    }
    return {
      x: (pixel.x / Math.max(1, this.walkableMaskWidth - 1)) * baseWidth,
      y: (pixel.y / Math.max(1, this.walkableMaskHeight - 1)) * baseHeight
    };
  }

  private isWalkableByMask(point: Point): boolean | null {
    if (!this.walkableMaskData || !this.walkableMaskWidth || !this.walkableMaskHeight) {
      return null;
    }
    const pixel = this.scenePointToBaseArtPixel(point);
    if (!pixel) {
      return false;
    }
    const index = (pixel.y * this.walkableMaskWidth + pixel.x) * 4;
    const r = this.walkableMaskData[index];
    const g = this.walkableMaskData[index + 1];
    const b = this.walkableMaskData[index + 2];
    const a = this.walkableMaskData[index + 3];
    return this.isWalkableMaskPixel(r, g, b, a);
  }

  private findNearestWalkablePoint(point: Point, maxSceneRadius = 140): Point | null {
    if (!this.walkableMaskData || !this.walkableMaskWidth || !this.walkableMaskHeight) {
      return null;
    }
    const origin = this.scenePointToBaseArtPixel(point);
    if (!origin) {
      return null;
    }

    const baseWidth = Math.max(1, this.sceneMapData.base_width);
    const scale = this.walkableMaskWidth / baseWidth;
    const maxRadius = Math.max(6, Math.round(maxSceneRadius * scale));
    let best: { x: number; y: number; dist: number } | null = null;

    for (let dy = -maxRadius; dy <= maxRadius; dy += 1) {
      const py = origin.y + dy;
      if (py < 0 || py >= this.walkableMaskHeight) {
        continue;
      }
      for (let dx = -maxRadius; dx <= maxRadius; dx += 1) {
        const px = origin.x + dx;
        if (px < 0 || px >= this.walkableMaskWidth) {
          continue;
        }
        const dist = dx * dx + dy * dy;
        if (dist > maxRadius * maxRadius || (best && dist >= best.dist)) {
          continue;
        }
        const index = (py * this.walkableMaskWidth + px) * 4;
        const r = this.walkableMaskData[index];
        const g = this.walkableMaskData[index + 1];
        const b = this.walkableMaskData[index + 2];
        const a = this.walkableMaskData[index + 3];
        if (this.isWalkableMaskPixel(r, g, b, a)) {
          best = { x: px, y: py, dist };
        }
      }
    }

    return best ? this.baseArtPixelToScenePoint(best) : null;
  }

  private resolveRequestedWalkTarget(point: Point, snapRadius = 72): Point | null {
    if (this.isWalkablePoint(point)) {
      return point;
    }
    const snapped = this.findNearestWalkablePoint(point, snapRadius);
    if (!snapped) {
      return null;
    }
    const distance = Math.hypot(snapped.x - point.x, snapped.y - point.y);
    return distance <= snapRadius ? snapped : null;
  }

  private syncWorkZonesFromInteractionPoints(options: { refreshWorkZoneLayer?: boolean } = {}): void {
    const interactionPointByRoomId = new Map<string, SceneInteractionPoint>();
    for (const point of this.sceneMapData.interaction_points) {
      const roomId = String(point.room_id || '').trim();
      if (!roomId) {
        continue;
      }
      const existing = interactionPointByRoomId.get(roomId);
      if (!existing) {
        interactionPointByRoomId.set(roomId, point);
        continue;
      }
      const existingIsWorkZone = String(existing.type || '').trim().toLowerCase() === 'work_zone';
      const nextIsWorkZone = String(point.type || '').trim().toLowerCase() === 'work_zone';
      if (!existingIsWorkZone && nextIsWorkZone) {
        interactionPointByRoomId.set(roomId, point);
      }
    }

    let changed = false;
    for (const zone of this.protocols.mapLogic.workZones) {
      const point = interactionPointByRoomId.get(zone.id);
      if (!point) {
        continue;
      }
      const nextAnchor = {
        x: Math.round(point.anchor_x ?? point.x),
        y: Math.round(point.anchor_y ?? point.y)
      };
      if (zone.anchor.x !== nextAnchor.x || zone.anchor.y !== nextAnchor.y) {
        zone.anchor = nextAnchor;
        changed = true;
      }
    }

    if (changed && options.refreshWorkZoneLayer) {
      this.drawWorkZones();
    }
  }

  private snapRuntimeAnchorsToWalkable(): void {
    for (const node of this.protocols.mapLogic.walkGraph.nodes) {
      const snapped = this.findNearestWalkablePoint({ x: node.x, y: node.y }, 120);
      if (snapped) {
        node.x = Math.round(snapped.x);
        node.y = Math.round(snapped.y);
      }
    }

    for (const zone of this.protocols.mapLogic.workZones) {
      const snapped = this.findNearestWalkablePoint(zone.anchor, 120);
      if (snapped) {
        zone.anchor = { x: Math.round(snapped.x), y: Math.round(snapped.y) };
      }
    }

    for (const interactionPoint of this.sceneMapData.interaction_points) {
      const snapped = this.findNearestWalkablePoint(
        { x: interactionPoint.anchor_x ?? interactionPoint.x, y: interactionPoint.anchor_y ?? interactionPoint.y },
        120
      );
      if (snapped) {
        interactionPoint.anchor_x = Math.round(snapped.x);
        interactionPoint.anchor_y = Math.round(snapped.y);
      }
    }
  }

  private gridIndex(col: number, row: number): number {
    return row * this.walkableGridCols + col;
  }

  private isWalkableCell(col: number, row: number): boolean {
    if (!this.walkableGrid || col < 0 || row < 0 || col >= this.walkableGridCols || row >= this.walkableGridRows) {
      return false;
    }
    return this.walkableGrid[this.gridIndex(col, row)] === 1;
  }

  private isReachableWalkableCell(col: number, row: number): boolean {
    if (!this.reachableWalkableGrid || col < 0 || row < 0 || col >= this.walkableGridCols || row >= this.walkableGridRows) {
      return false;
    }
    return this.reachableWalkableGrid[this.gridIndex(col, row)] === 1;
  }

  private scenePointToGrid(point: Point): { col: number; row: number } {
    return {
      col: Math.max(0, Math.min(this.walkableGridCols - 1, Math.floor(point.x / this.walkableGridStep))),
      row: Math.max(0, Math.min(this.walkableGridRows - 1, Math.floor(point.y / this.walkableGridStep)))
    };
  }

  private findNearestWalkableCell(point: Point, maxSceneRadius = 80): { col: number; row: number } | null {
    if (!this.walkableGrid) {
      return null;
    }
    const origin = this.scenePointToGrid(point);
    const maxRadius = Math.max(1, Math.ceil(maxSceneRadius / this.walkableGridStep));
    let best: { col: number; row: number; dist: number } | null = null;
    for (let dy = -maxRadius; dy <= maxRadius; dy += 1) {
      for (let dx = -maxRadius; dx <= maxRadius; dx += 1) {
        const col = origin.col + dx;
        const row = origin.row + dy;
        if (!this.isWalkableCell(col, row)) {
          continue;
        }
        const dist = dx * dx + dy * dy;
        if (best && dist >= best.dist) {
          continue;
        }
        best = { col, row, dist };
      }
    }
    return best ? { col: best.col, row: best.row } : null;
  }

  private findNearestExistingWalkableCell(point: Point): { col: number; row: number } | null {
    if (!this.walkableGrid || this.walkableGridCols <= 0 || this.walkableGridRows <= 0) {
      return null;
    }
    const origin = this.scenePointToGrid(point);
    let best: { col: number; row: number; dist: number } | null = null;
    for (let row = 0; row < this.walkableGridRows; row += 1) {
      for (let col = 0; col < this.walkableGridCols; col += 1) {
        if (this.walkableGrid[this.gridIndex(col, row)] !== 1) {
          continue;
        }
        const dx = col - origin.col;
        const dy = row - origin.row;
        const dist = dx * dx + dy * dy;
        if (best && dist >= best.dist) {
          continue;
        }
        best = { col, row, dist };
      }
    }
    return best ? { col: best.col, row: best.row } : null;
  }

  private resolvePatrolWalkableOrigin(origin: Point): Point | null {
    const direct = this.resolveRequestedWalkTarget(origin, 360);
    if (direct) {
      return direct;
    }
    const nearestCell = this.findNearestWalkableCell(origin, Math.max(this.sceneMapData.base_width, this.sceneMapData.base_height))
      ?? this.findNearestExistingWalkableCell(origin);
    if (nearestCell) {
      return this.gridToScenePoint(nearestCell.col, nearestCell.row);
    }
    return this.findNearestWalkablePoint(origin, Math.max(this.sceneMapData.base_width, this.sceneMapData.base_height));
  }

  private pickRandomWalkablePatrolTarget(origin: Point, minDistance = 140): Point | null {
    if (!this.walkableGrid || this.walkableGridCols <= 0 || this.walkableGridRows <= 0) {
      return this.resolvePatrolWalkableOrigin(origin);
    }

    const total = this.walkableGrid.length;
    let fallback: { point: Point; distance: number } | null = null;
    for (let attempt = 0; attempt < 220; attempt += 1) {
      const index = Phaser.Math.Between(0, total - 1);
      if (this.walkableGrid[index] !== 1) {
        continue;
      }
      const col = index % this.walkableGridCols;
      const row = Math.floor(index / this.walkableGridCols);
      const point = this.gridToScenePoint(col, row);
      const distance = Phaser.Math.Distance.Between(origin.x, origin.y, point.x, point.y);
      if (!fallback || distance > fallback.distance) {
        fallback = { point, distance };
      }
      if (distance < minDistance) {
        continue;
      }
      if (this.lastCompletedActionAnchor && this.sameAnchorPoint(point, this.lastCompletedActionAnchor, 64)) {
        continue;
      }
      return point;
    }

    if (fallback && fallback.distance >= 36) {
      if (!this.lastCompletedActionAnchor || !this.sameAnchorPoint(fallback.point, this.lastCompletedActionAnchor, 64)) {
        return fallback.point;
      }
    }
    return this.resolvePatrolWalkableOrigin(origin);
  }

  private gridToScenePoint(col: number, row: number): Point {
    return {
      x: Math.min(this.sceneMapData.base_width - 1, col * this.walkableGridStep + this.walkableGridStep / 2),
      y: Math.min(this.sceneMapData.base_height - 1, row * this.walkableGridStep + this.walkableGridStep / 2)
    };
  }

  private initializeReachableWalkableGrid(origin: Point): void {
    if (!this.walkableGrid) {
      this.reachableWalkableGrid = null;
      return;
    }
    this.reachableWalkableGrid = new Uint8Array(this.walkableGrid.length);
    const startPoint = this.resolvePatrolWalkableOrigin(origin);
    if (!startPoint) {
      return;
    }
    const start = this.findNearestWalkableCell(startPoint, Math.max(this.walkableGridStep * 2, 48))
      ?? this.findNearestExistingWalkableCell(startPoint);
    if (!start) {
      return;
    }
    const queue: Array<{ col: number; row: number }> = [];
    this.reachableWalkableGrid[this.gridIndex(start.col, start.row)] = 1;
    queue.push(start);

    const neighbors = [
      [1, 0], [-1, 0], [0, 1], [0, -1],
      [1, 1], [1, -1], [-1, 1], [-1, -1]
    ] as const;

    while (queue.length > 0) {
      const current = queue.shift();
      if (!current) {
        continue;
      }
      for (const [dx, dy] of neighbors) {
        const nextCol = current.col + dx;
        const nextRow = current.row + dy;
        if (!this.isWalkableCell(nextCol, nextRow) || this.isReachableWalkableCell(nextCol, nextRow)) {
          continue;
        }
        if (dx !== 0 && dy !== 0) {
          if (!this.isWalkableCell(current.col + dx, current.row) || !this.isWalkableCell(current.col, current.row + dy)) {
            continue;
          }
        }
        this.reachableWalkableGrid[this.gridIndex(nextCol, nextRow)] = 1;
        queue.push({ col: nextCol, row: nextRow });
      }
    }
  }

  private snapWorkZonesToReachableWalkable(origin: Point): void {
    this.initializeReachableWalkableGrid(origin);
    if (!this.reachableWalkableGrid) {
      return;
    }

    for (const zone of this.protocols.mapLogic.workZones) {
      if (this.isWalkablePoint(zone.anchor)) {
        continue;
      }
      const snapped = this.findNearestWalkablePoint(zone.anchor, 220);
      if (snapped) {
        zone.anchor = { x: Math.round(snapped.x), y: Math.round(snapped.y) };
      }
    }
  }

  private simplifyRoute(points: Point[]): Point[] {
    if (points.length <= 2) {
      return points;
    }
    const simplified: Point[] = [points[0]];
    for (let index = 1; index < points.length - 1; index += 1) {
      const prev = simplified[simplified.length - 1];
      const current = points[index];
      const next = points[index + 1];
      const dx1 = Math.sign(current.x - prev.x);
      const dy1 = Math.sign(current.y - prev.y);
      const dx2 = Math.sign(next.x - current.x);
      const dy2 = Math.sign(next.y - current.y);
      if (dx1 !== dx2 || dy1 !== dy2) {
        simplified.push(current);
      }
    }
    simplified.push(points[points.length - 1]);
    return simplified;
  }

  private computeMaskRoute(from: Point, to: Point): Point[] | null {
    if (!this.walkableGrid || this.walkableGridCols === 0 || this.walkableGridRows === 0) {
      return null;
    }
    const startPoint = this.isWalkablePoint(from) ? from : this.findNearestWalkablePoint(from, 140);
    const endPoint = this.isWalkablePoint(to) ? to : this.findNearestWalkablePoint(to, 140);
    if (!startPoint || !endPoint) {
      return null;
    }

    const start = this.findNearestWalkableCell(startPoint, 80) ?? this.scenePointToGrid(startPoint);
    const end = this.findNearestWalkableCell(endPoint, 80) ?? this.scenePointToGrid(endPoint);
    const startKey = `${start.col},${start.row}`;
    const endKey = `${end.col},${end.row}`;
    const open = [startKey];
    const cameFrom = new Map<string, string>();
    const gScore = new Map<string, number>([[startKey, 0]]);
    const fScore = new Map<string, number>([[startKey, Math.hypot(end.col - start.col, end.row - start.row)]]);

    const neighborOffsets = [
      [1, 0], [-1, 0], [0, 1], [0, -1],
      [1, 1], [1, -1], [-1, 1], [-1, -1]
    ] as const;

    const parseKey = (key: string) => {
      const [col, row] = key.split(',').map(Number);
      return { col, row };
    };

    while (open.length > 0) {
      open.sort((left, right) => (fScore.get(left) ?? Infinity) - (fScore.get(right) ?? Infinity));
      const currentKey = open.shift();
      if (!currentKey) {
        break;
      }
      if (currentKey === endKey) {
        const reversed: Point[] = [endPoint];
        let cursor: string | undefined = currentKey;
        while (cursor) {
          const { col, row } = parseKey(cursor);
          reversed.push(this.gridToScenePoint(col, row));
          cursor = cameFrom.get(cursor);
        }
        reversed.push(startPoint);
        return this.simplifyRoute(reversed.reverse());
      }

      const current = parseKey(currentKey);
      for (const [dx, dy] of neighborOffsets) {
        const nextCol = current.col + dx;
        const nextRow = current.row + dy;
        if (!this.isWalkableCell(nextCol, nextRow)) {
          continue;
        }
        if (dx !== 0 && dy !== 0) {
          if (!this.isWalkableCell(current.col + dx, current.row) || !this.isWalkableCell(current.col, current.row + dy)) {
            continue;
          }
        }
        const nextKey = `${nextCol},${nextRow}`;
        const stepCost = dx !== 0 && dy !== 0 ? 1.414 : 1;
        const tentative = (gScore.get(currentKey) ?? Infinity) + stepCost;
        if (tentative >= (gScore.get(nextKey) ?? Infinity)) {
          continue;
        }
        cameFrom.set(nextKey, currentKey);
        gScore.set(nextKey, tentative);
        fScore.set(nextKey, tentative + Math.hypot(end.col - nextCol, end.row - nextRow));
        if (!open.includes(nextKey)) {
          open.push(nextKey);
        }
      }
    }

    return null;
  }

  private drawRooms(): void {
    const theme = this.getTheme();
    this.roomLayer.clear();
    const hasBaseArt = this.hasSceneBaseArt();

    const slicedFloorRooms = new Set(
      this.protocols.sceneArt.roomSlices
        .filter((slice) => slice.replacesLayers.includes('floor'))
        .map((slice) => slice.roomId)
    );

    for (const room of this.protocols.mapLogic.rooms) {
      const [x, y, width, height] = room.bounds;
      const resource = this.telemetryResources.get(room.id);
      const accent = PARTITION_COLORS[room.id];
      const isFocus = this.focusResourceId === room.id;
      const status = resource?.status ?? (room.id === 'break_room' ? 'idle' : 'offline');
      const suppressStatusRoomOverlay = room.id === 'alarm' || room.id === 'gateway';
      const fillAlpha = hasBaseArt ? 0 : (slicedFloorRooms.has(room.id) ? 0.14 : 0.92);

      this.roomLayer.fillStyle(theme.roomFill, fillAlpha);
      this.roomLayer.fillRect(x, y, width, height);

      const overlayAlpha = hasBaseArt
        ? (
            status === 'alert' && !suppressStatusRoomOverlay
              ? 0.1
              : status === 'active' && !suppressStatusRoomOverlay
                ? 0.05
                : isFocus
                  ? 0.035
                  : 0
          )
        : (
            status === 'alert' && !suppressStatusRoomOverlay
              ? 0.2
              : status === 'active' && !suppressStatusRoomOverlay
                ? 0.12
                : room.id === 'break_room'
                  ? 0.08
                  : 0.04
          );
      this.roomLayer.fillStyle(accent, overlayAlpha);
      if (overlayAlpha > 0) {
        this.roomLayer.fillRect(x, y, width, height);
      }

      const strokeColor = status === 'alert' && !suppressStatusRoomOverlay ? 0xffa0ad : isFocus ? accent : theme.roomStroke;
      const strokeWidth = isFocus ? 4 : hasBaseArt ? 1.1 : 2;
      const strokeAlpha = hasBaseArt
        ? (
            isFocus
              ? 0.72
              : status === 'alert' && !suppressStatusRoomOverlay
                ? 0.32
                : status === 'active' && !suppressStatusRoomOverlay
                  ? 0.16
                  : 0.06
          )
        : 0.96;
      if (!hasBaseArt || isFocus || ((status === 'active' || status === 'alert') && !suppressStatusRoomOverlay)) {
        this.roomLayer.lineStyle(strokeWidth, strokeColor, strokeAlpha);
        this.roomLayer.strokeRect(x, y, width, height);
      }
    }

    if (this.sceneMapData.floor_regions.length > 0) {
      this.roomLayer.lineStyle(1, 0xffffff, this.debugVisualsVisible ? 0.16 : 0.05);
      this.roomLayer.fillStyle(0xffffff, this.debugVisualsVisible ? 0.05 : 0.015);
      for (const floorRegion of this.sceneMapData.floor_regions) {
        if (floorRegion.polygon && floorRegion.polygon.length >= 3) {
          this.roomLayer.beginPath();
          this.roomLayer.moveTo(floorRegion.polygon[0].x, floorRegion.polygon[0].y);
          for (let index = 1; index < floorRegion.polygon.length; index += 1) {
            this.roomLayer.lineTo(floorRegion.polygon[index].x, floorRegion.polygon[index].y);
          }
          this.roomLayer.closePath();
          this.roomLayer.fillPath();
          this.roomLayer.strokePath();
          continue;
        }
        if (floorRegion.rect) {
          this.roomLayer.fillRect(
            floorRegion.rect.x,
            floorRegion.rect.y,
            floorRegion.rect.width,
            floorRegion.rect.height
          );
          this.roomLayer.strokeRect(
            floorRegion.rect.x,
            floorRegion.rect.y,
            floorRegion.rect.width,
            floorRegion.rect.height
          );
        }
      }
    }
    this.applyDebugVisualLayerVisibility();
  }

  private initializeRoomLabels(): void {
    for (const room of this.protocols.mapLogic.rooms) {
      if (this.hiddenRoomLabelIds.has(room.id)) {
        continue;
      }
      const anchor = this.resolveRoomLabelAnchor(room);
      const titleX = anchor.x;
      const titleY = anchor.y;
      const labelColor = this.cssColor(PARTITION_COLORS[room.id], 1);
      const backplate = this.add.graphics();
      backplate.setDepth(this.getRenderLayerDepth('mid_props') + 3.5);
      this.roomTitleBackplates.set(room.id, backplate);

      const title = this.add.text(titleX, titleY, resourceLabel(room.id, this.locale), {
        color: labelColor,
        fontFamily: this.displayFontFamily(),
        fontSize: '24px',
        fontStyle: '400',
        align: 'center'
      });
      title.setOrigin(0.5, 0);
      title.setPadding(10, 1, 10, 0);
      title.setStroke('#05100e', 4);
      title.setShadow(0, 0, '#010403', 4, false, true);
      title.setDepth(this.getRenderLayerDepth('mid_props') + 4);
      title.setInteractive({ useHandCursor: true });
      title.on('pointerover', () => {
        this.hoveredRoomId = room.id;
        this.syncRoomLabels();
      });
      title.on('pointerout', () => {
        if (this.hoveredRoomId === room.id) {
          this.hoveredRoomId = null;
          this.syncRoomLabels();
        }
      });
      title.on('pointerdown', (pointer: Phaser.Input.Pointer, _localX: number, _localY: number, event: Phaser.Types.Input.EventData) => {
        event.stopPropagation();
        if (this.editorModeEnabled && this.editorTool === 'room_label') {
          const startAnchor = this.resolveRoomLabelAnchor(room);
          this.selectedRoomLabelId = room.id;
          this.roomLabelDragState = {
            roomId: room.id,
            startPoint: { x: pointer.worldX, y: pointer.worldY },
            startAnchor,
            moved: false
          };
          this.syncRoomLabels();
          return;
        }
        this.emitResourceSelection(room.id, { x: title.x, y: title.y + title.displayHeight / 2 });
      });
      this.roomTitleLabels.set(room.id, title);
    }
  }

  private syncRoomLabels(): void {
    for (const room of this.protocols.mapLogic.rooms) {
      if (this.hiddenRoomLabelIds.has(room.id)) {
        continue;
      }
      const backplate = this.roomTitleBackplates.get(room.id);
      const title = this.roomTitleLabels.get(room.id);
      const telemetry = this.telemetryResources.get(room.id);
      const isFocus = this.focusResourceId === room.id;

      if (title) {
        const anchor = this.resolveRoomLabelAnchor(room);
        const isHovered = this.hoveredRoomId === room.id;
        const isSelected = this.editorModeEnabled && this.editorTool === 'room_label' && this.selectedRoomLabelId === room.id;
        title.setPosition(anchor.x, anchor.y);
        title.setText(resourceLabel(room.id, this.locale));
        title.setFontFamily(this.displayFontFamily());
        title.setColor(
          isHovered
            ? '#f6fff9'
            : telemetry?.status === 'offline'
            ? '#8ca197'
            : telemetry?.status === 'alert'
              ? '#ffd5de'
              : isFocus
                ? '#ffffff'
                : this.cssColor(PARTITION_COLORS[room.id], 1)
        );
        title.setScale((isHovered || isSelected) ? 1.045 : 1);
        title.setDepth(this.getRenderLayerDepth('mid_props') + ((isHovered || isSelected) ? 5 : 4));
        title.setShadow(
          0,
          0,
          (isHovered || isSelected) ? this.cssColor(PARTITION_COLORS[room.id], 0.72) : '#010403',
          (isHovered || isSelected) ? 8 : 4,
          false,
          true
        );
        if (backplate) {
          const fillColor = isSelected
            ? PARTITION_COLORS[room.id]
            : isHovered
            ? PARTITION_COLORS[room.id]
            : telemetry?.status === 'alert'
              ? 0x4e191f
              : isFocus
                ? PARTITION_COLORS[room.id]
                : 0x102622;
          const fillAlpha = isSelected
            ? 0.44
            : isHovered
            ? 0.34
            : telemetry?.status === 'alert'
              ? 0.62
              : isFocus
                ? 0.22
                : room.id === 'memory' || room.id === 'document'
                  ? 0.5
                  : 0.34;
          this.drawRoomTitleBackplate(backplate, title, fillColor, fillAlpha);
        }
      }
    }
  }

  private drawRoomTitleBackplate(
    backplate: Phaser.GameObjects.Graphics,
    title: Phaser.GameObjects.Text,
    fillColor: number,
    fillAlpha: number
  ): void {
    const bounds = title.getBounds();
    const padX = 6;
    const padY = 3;
    backplate.clear();
    backplate.fillStyle(fillColor, fillAlpha);
    backplate.fillRoundedRect(bounds.x - padX, bounds.y - padY, bounds.width + padX * 2, bounds.height + padY * 2, 12);
    backplate.lineStyle(1, 0xffffff, 0.05);
    backplate.strokeRoundedRect(bounds.x - padX, bounds.y - padY, bounds.width + padX * 2, bounds.height + padY * 2, 12);
    backplate.setDepth(title.depth - 0.1);
    backplate.setAlpha(1);
    backplate.setVisible(true);
  }

  private resolveRoomLabelAnchor(room: RoomBounds): Point {
    const storedAnchor = this.getSceneMapRoomLabelAnchor(room.id);
    if (storedAnchor) {
      return this.clampRoomLabelAnchor(storedAnchor);
    }
    const [x, y, width] = room.bounds;
    return this.clampRoomLabelAnchor(room.labelAnchor ?? { x: x + width / 2, y: y + 18 });
  }

  private getSceneMapRoomLabelAnchor(roomId: ResourcePartitionId): Point | null {
    const stored = this.sceneMapData.room_label_anchors[roomId];
    if (!stored) {
      return null;
    }
    const x = Number(stored.x);
    const y = Number(stored.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return null;
    }
    return { x, y };
  }

  private setSceneMapRoomLabelAnchor(roomId: ResourcePartitionId, anchor: Point): void {
    const nextAnchor = this.clampRoomLabelAnchor(anchor);
    this.sceneMapData.room_label_anchors[roomId] = nextAnchor;
  }

  private clampRoomLabelAnchor(anchor: Point): Point {
    const maxX = Math.max(0, this.sceneMapData.base_width);
    const maxY = Math.max(0, this.sceneMapData.base_height);
    return {
      x: Math.round(Phaser.Math.Clamp(anchor.x, 0, maxX)),
      y: Math.round(Phaser.Math.Clamp(anchor.y, 0, maxY))
    };
  }

  private emitResourceSelection(resourceId: ResourcePartitionId, anchor?: Point): void {
    const payload: ResourceSelectEvent = { resourceId };
    if (anchor) {
      payload.anchor = anchor;
    }
    this.events.emit('select-resource', payload);
  }

  private spawnRoomSlices(): void {
    for (const renderedLayer of this.renderedRoomSlices) {
      renderedLayer.shadowImage?.destroy();
      renderedLayer.image.destroy();
    }
    this.renderedRoomSlices = [];

    for (const slice of this.protocols.sceneArt.roomSlices) {
      for (const layer of slice.layers) {
        const baseDepth = this.layerToDepth(layer.renderLayer, layer.anchor.y);
        const shadowImage = this.createLayerShadowImage(layer.textureKey, layer.renderLayer, layer.anchor, layer.displaySize, baseDepth);
        const image = this.add.image(layer.anchor.x, layer.anchor.y, layer.textureKey);
        image.setDisplaySize(layer.displaySize.width, layer.displaySize.height);
        image.setAlpha(layer.alpha ?? 1);
        image.setDepth(baseDepth);
        this.renderedRoomSlices.push({ slice, layer, shadowImage, image });
      }
    }

    this.applyRoomSliceTheme();
  }

  private applyRoomSliceTheme(): void {
    const theme = this.getTheme();
    for (const renderedLayer of this.renderedRoomSlices) {
      renderedLayer.shadowImage?.setTintFill(0x000000);
      if (renderedLayer.layer.tintWithTheme) {
        renderedLayer.image.setTint(theme.tint);
      } else {
        renderedLayer.image.clearTint();
      }
    }
  }

  private createLayerShadowImage(
    textureKey: string,
    renderLayer: SceneGlobalLayerDef['renderLayer'] | RoomSliceLayerDef['renderLayer'],
    anchor: Point,
    displaySize: { width: number; height: number },
    baseDepth: number
  ): Phaser.GameObjects.Image | null {
    if (renderLayer !== 'mid_props') {
      return null;
    }
    if (!this.textures.exists(textureKey)) {
      return null;
    }
    const shadow = this.add.image(anchor.x + PROP_SHADOW_OFFSET.x, anchor.y + PROP_SHADOW_OFFSET.y, textureKey);
    shadow.setDisplaySize(displaySize.width, displaySize.height);
    shadow.setTintFill(0x000000);
    shadow.setAlpha(PROP_SHADOW_ALPHA);
    shadow.setDepth(baseDepth - 0.08);
    return shadow;
  }

  private drawOccluders(): void {
    this.occluderLayer.clear();
    const theme = this.getTheme();
    this.occluderLayer.fillStyle(theme.tint, 0.36);

    for (const occluder of this.protocols.mapLogic.occluders) {
      if (this.isOccluderHandledBySlice(occluder.x, occluder.y, occluder.width, occluder.height)) {
        continue;
      }
      this.occluderLayer.fillRect(occluder.x, occluder.y, occluder.width, occluder.height);
    }
  }

  private initializeWorkZones(): void {
    for (const zone of this.protocols.mapLogic.workZones) {
      this.zoneState.set(zone.id, 'idle');
      const label = this.add.text(zone.anchor.x, zone.anchor.y + zone.radius + 8, `${zone.label}\nidle`, {
        color: '#9eb8ff',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
        fontSize: '11px',
        align: 'center'
      });
      label.setOrigin(0.5, 0);
      label.setDepth(this.getRenderLayerDepth('mid_props') + 6);
      this.zoneLabels.set(zone.id, label);
    }
    this.drawWorkZones();
  }

  private drawWorkZones(): void {
    this.zoneLayer.clear();

    for (const zone of this.protocols.mapLogic.workZones) {
      const state = this.zoneState.get(zone.id) ?? 'idle';
      const resource = this.telemetryResources.get(zone.id);
      const baseColor = PARTITION_COLORS[zone.id];

      if (state === 'working') {
        this.zoneLayer.fillStyle(baseColor, 0.56);
        this.zoneLayer.lineStyle(3, 0xffffff, 0.96);
      } else if (state === 'moving') {
        this.zoneLayer.fillStyle(baseColor, 0.38);
        this.zoneLayer.lineStyle(2, 0xf3f6ff, 0.92);
      } else if (state === 'done') {
        this.zoneLayer.fillStyle(baseColor, 0.28);
        this.zoneLayer.lineStyle(2, 0xcbffea, 0.95);
      } else if (resource?.status === 'alert') {
        this.zoneLayer.fillStyle(baseColor, 0.34);
        this.zoneLayer.lineStyle(2, 0xffd5dc, 0.98);
      } else if (resource?.status === 'active') {
        this.zoneLayer.fillStyle(baseColor, 0.22);
        this.zoneLayer.lineStyle(2, baseColor, 0.94);
      } else {
        this.zoneLayer.fillStyle(baseColor, 0.14);
        this.zoneLayer.lineStyle(2, baseColor, 0.84);
      }

      this.zoneLayer.fillCircle(zone.anchor.x, zone.anchor.y, zone.radius);
      this.zoneLayer.strokeCircle(zone.anchor.x, zone.anchor.y, zone.radius);

      const label = this.zoneLabels.get(zone.id);
      if (label) {
        const statusText =
          state === 'working'
            ? 'accessing'
            : state === 'moving'
              ? 'routing'
              : resource?.status === 'alert'
                ? 'alert'
                : resource?.status === 'active'
                  ? `live · ${resource.itemCount}`
                  : zone.id === 'break_room'
                    ? 'rest'
                    : 'idle';
        if (this.hasSceneBaseArt()) {
          label.setText('');
          label.setVisible(false);
        } else {
          label.setVisible(true);
          label.setText(`${resourceLabel(zone.id, this.locale)}\n${statusText}`);
          label.setColor(state === 'working' ? '#ffffff' : resource?.status === 'alert' ? '#ffd8e0' : '#9eb8ff');
        }
      }
    }
    this.applyDebugVisualLayerVisibility();
  }

  private applyDebugVisualLayerVisibility(): void {
    const wallEditorActive = this.editorModeEnabled && this.editorTool === 'wall';
    const overlaySuppressed = wallEditorActive || this.houseOverlaySuppressed;
    this.roomLayer.setVisible(this.debugVisualsVisible);
    this.wallBlockLayer.setVisible(true);
    this.zoneLayer.setVisible(this.debugVisualsVisible);
    this.furnitureSpriteLayer.setVisible(!overlaySuppressed);
    this.furnitureLayer.setVisible(!overlaySuppressed);
    this.interactionPointLayer.setVisible(!overlaySuppressed);
    this.interactionPointLabelLayer.setVisible(!overlaySuppressed);
    this.interactionBoxLayer.setVisible(!overlaySuppressed);
    this.interactionBoxLabelLayer.setVisible(!overlaySuppressed);
    this.occluderLayer.setVisible(this.debugVisualsVisible);
    this.editorPreviewLayer.setVisible(this.editorModeEnabled);
  }

  private initializeSceneInteractionUi(): void {
    this.editorHudText = this.add.text(14, 14, '', {
      color: '#d9f0ff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
      fontSize: '16px',
      lineSpacing: 4,
      backgroundColor: 'rgba(8, 17, 28, 0.68)',
      padding: { left: 10, right: 10, top: 8, bottom: 8 }
    });
    this.editorHudText.setOrigin(0, 1);
    this.editorHudText.setScrollFactor(0);
    this.editorHudText.setDepth(this.getRenderLayerDepth('fx_overlay') + 22);
    this.editorHudText.setVisible(false);
    this.positionEditorHudText();

    this.interactionToastText = this.add.text(14, 92, '', {
      color: '#f8fcff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
      fontSize: '12px',
      lineSpacing: 2,
      backgroundColor: 'rgba(15, 28, 18, 0.76)',
      padding: { left: 8, right: 8, top: 5, bottom: 5 }
    });
    this.interactionToastText.setScrollFactor(0);
    this.interactionToastText.setDepth(this.getRenderLayerDepth('fx_overlay') + 23);
    this.interactionToastText.setVisible(false);
  }

  private positionEditorHudText(): void {
    if (!this.editorHudText) {
      return;
    }
    const camera = this.cameras.main;
    const zoom = Math.max(0.001, camera.zoom || 1);
    const margin = 6 / zoom;
    const bottomY = (camera.height / zoom) - margin;
    const leftX = 10 / zoom;
    this.editorHudText.setPosition(leftX, Math.max(80, bottomY));
  }

  private tickSceneInteractionUi(): void {
    const now = Date.now();
    if (this.highlightedFurnitureId && now >= this.highlightedFurnitureUntil) {
      this.highlightedFurnitureId = null;
      this.drawFurnitureLayer();
    }

    if (this.interactionToastText && this.interactionToastText.visible && now >= this.interactionToastUntil) {
      this.interactionToastText.setVisible(false);
    }

    this.syncEditorHudText();
    this.renderEditorWallPreview();
  }

  private syncEditorHudText(): void {
    if (!this.editorModeEnabled) {
      if (this.editorHudText) {
        this.editorHudText.setVisible(false);
      }
      this.emitEditorHudOverlay(false, '');
      return;
    }

    const selectedFurniture = this.selectedFurnitureId
      ? this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId) ?? null
      : null;
    const selectedWall = this.selectedWallBlockId
      ? this.sceneMapData.wall_blocks.find((item) => item.id === this.selectedWallBlockId) ?? null
      : null;
    const selectedRoomLabel = this.selectedRoomLabelId
      ? this.protocols.mapLogic.rooms.find((item) => item.id === this.selectedRoomLabelId) ?? null
      : null;
    const toolText = this.editorTool === 'wall'
      ? '墙壁编辑'
      : this.editorTool === 'furniture'
        ? '家具编辑'
        : this.editorTool === 'interaction'
          ? '互动点编辑'
          : '房屋名编辑';
    const currentSelectionHint = this.editorTool === 'wall'
      ? selectedWall
        ? '当前：已选中墙体，可直接拖拽或调节点。'
        : `当前：未选中墙体，待放置形状=${this.wallShapeLabel(this.wallEditorShapePreset)}。`
      : this.editorTool === 'furniture'
        ? selectedFurniture
          ? `当前：已选中家具（${selectedFurniture.label}）。`
          : '当前：未选中家具，左键可放置新家具。'
        : this.editorTool === 'interaction'
          ? '当前：互动点模式，左键新增、右键删除。'
          : selectedRoomLabel
            ? `当前：已选中房屋名（${resourceLabel(selectedRoomLabel.id, this.locale)}）。`
            : '当前：请点住房屋名并拖拽移动。';
    const toolHint = this.editorTool === 'wall'
      ? '左键选中/拖拽/缩放/旋转，右键删除，Delete删除选中，S保存并退出'
      : this.editorTool === 'furniture'
        ? '左键放置/拖拽家具，右键删除，Delete删除选中；底部按钮可放大/缩小'
        : this.editorTool === 'interaction'
          ? '左键放置互动点，右键删除互动点'
          : '拖拽房屋名称文字调整位置，松开后自动保存';
    const abilityHint = this.editorTool === 'furniture'
      ? '快捷键：B切换阻挡，I切换可互动，T切换互动类型'
      : this.editorTool === 'wall'
        ? '在底部菜单切换墙体形状（正方/长方/三角/圆/梯形）'
        : this.editorTool === 'interaction'
          ? '使用 Shift+E 可快速退出编辑模式'
          : '可从房屋子菜单切换回“房屋导入”或“墙壁设置”';

    const nextHudText = [
      `编辑模式: ${toolText}`,
      '模式切换：1墙体 2家具 3互动点 4房屋名 | Shift+E退出',
      toolHint,
      abilityHint,
      currentSelectionHint
    ].join('\n');
    if (this.editorHudText) {
      this.editorHudText.setVisible(false);
      this.editorHudText.setText(nextHudText);
    }
    this.emitEditorHudOverlay(true, nextHudText);
  }

  private emitEditorHudOverlay(visible: boolean, text: string): void {
    const nextText = visible ? text : '';
    if (this.editorHudOverlayVisible === visible && this.editorHudOverlayText === nextText) {
      return;
    }
    this.editorHudOverlayVisible = visible;
    this.editorHudOverlayText = nextText;
    this.events.emit('scene-editor-hud-changed', {
      visible,
      text: nextText
    });
  }

  private showSceneToast(message: string, tone: SceneToastTone = 'info', durationMs = 2200): void {
    if (!this.interactionToastText) {
      return;
    }
    const color = tone === 'success'
      ? '#d8ffe5'
      : tone === 'warn'
        ? '#ffe2d6'
        : '#f8fcff';
    const backgroundColor = tone === 'success'
      ? 'rgba(16, 46, 24, 0.82)'
      : tone === 'warn'
        ? 'rgba(56, 24, 11, 0.84)'
        : 'rgba(15, 28, 18, 0.76)';
    this.interactionToastText.setStyle({ color, backgroundColor });
    this.interactionToastText.setText(message);
    this.interactionToastText.setVisible(true);
    this.interactionToastUntil = Date.now() + durationMs;
  }

  private drawSceneMapLayers(): void {
    this.drawWallBlockLayer();
    this.drawFurnitureLayer();
    this.drawInteractionPointLayer();
    this.drawInteractionBoxLayer();
    this.renderEditorWallPreview();
    this.syncEditorHudText();
  }

  private drawWallBlockLayer(): void {
    this.wallBlockLayer.clear();
    const isWallEditor = this.editorModeEnabled && this.editorTool === 'wall';
    const isHighVisibility = isWallEditor || this.debugVisualsVisible;
    if (!isHighVisibility) {
      return;
    }

    for (const wallBlock of this.sceneMapData.wall_blocks) {
      const color = this.resolveSceneMapRoomColor(wallBlock.room_id);
      const isSelected = this.selectedWallBlockId === wallBlock.id;
      this.drawWallBlockOnGraphics(this.wallBlockLayer, wallBlock, {
        fillColor: color,
        fillAlpha: isSelected ? 0.42 : 0.26,
        strokeColor: isSelected ? 0xfff0c8 : 0xf2fbff,
        strokeAlpha: isSelected ? 0.98 : 0.8,
        strokeWidth: isSelected ? 2 : 1.2
      });
    }

    if (isWallEditor && this.selectedWallBlockId) {
      const selected = this.sceneMapData.wall_blocks.find((item) => item.id === this.selectedWallBlockId) ?? null;
      if (selected) {
        this.drawWallBlockEditorHandles(selected);
      }
    }
  }

  private wallEditorHandlesForBlock(block: WallBlock): Array<{ kind: WallEditorHandleKind; x: number; y: number; radius: number }> {
    const bounds = this.wallBlockBounds(block);
    const centerX = bounds.x + bounds.width / 2;
    const right = bounds.x + bounds.width;
    const bottom = bounds.y + bounds.height;
    const top = bounds.y;
    const left = bounds.x;

    return [
      { kind: 'resize-nw', x: left, y: top, radius: WALL_EDITOR_HANDLE_RADIUS },
      { kind: 'resize-ne', x: right, y: top, radius: WALL_EDITOR_HANDLE_RADIUS },
      { kind: 'resize-sw', x: left, y: bottom, radius: WALL_EDITOR_HANDLE_RADIUS },
      { kind: 'resize-se', x: right, y: bottom, radius: WALL_EDITOR_HANDLE_RADIUS },
      { kind: 'rotate', x: centerX, y: top - WALL_EDITOR_ROTATE_HANDLE_OFFSET, radius: WALL_EDITOR_HANDLE_RADIUS },
      { kind: 'delete', x: right + 16, y: top - 10, radius: WALL_EDITOR_HANDLE_RADIUS }
    ];
  }

  private drawWallBlockEditorHandles(block: WallBlock): void {
    const bounds = this.wallBlockBounds(block);
    this.wallBlockLayer.lineStyle(1, 0xf8e6a9, 0.9);
    this.wallBlockLayer.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height);

    const handles = this.wallEditorHandlesForBlock(block);
    for (const handle of handles) {
      const isDelete = handle.kind === 'delete';
      const isRotate = handle.kind === 'rotate';
      const fillColor = isDelete ? 0xff7d7d : isRotate ? 0xffcf7a : 0x8fd5ff;
      this.wallBlockLayer.fillStyle(fillColor, 0.95);
      this.wallBlockLayer.fillCircle(handle.x, handle.y, handle.radius);
      this.wallBlockLayer.lineStyle(1, 0x0b1520, 0.85);
      this.wallBlockLayer.strokeCircle(handle.x, handle.y, handle.radius);
    }
  }

  private findWallEditorHandleByPoint(point: Point, block: WallBlock): { kind: WallEditorHandleKind; x: number; y: number; radius: number } | null {
    const handles = this.wallEditorHandlesForBlock(block);
    for (const handle of handles) {
      const dx = point.x - handle.x;
      const dy = point.y - handle.y;
      if ((dx * dx) + (dy * dy) <= (handle.radius + 3) * (handle.radius + 3)) {
        return handle;
      }
    }
    return null;
  }

  private drawFurnitureLayer(): void {
    this.furnitureLayer.clear();
    if ((this.editorModeEnabled && this.editorTool === 'wall') || this.houseOverlaySuppressed) {
      this.furnitureSpriteLayer.removeAll(true);
      this.furnitureSpriteById.clear();
      return;
    }
    const sortedFurnitures = [...this.sceneMapData.furnitures].sort((left, right) => {
      if (left.z_index !== right.z_index) {
        return left.z_index - right.z_index;
      }
      return left.id.localeCompare(right.id);
    });

    this.syncFurnitureSpriteLayer(sortedFurnitures);
    // 外框改为不渲染，仅保留家具贴图本体，避免出现“外面那个方框”。
  }

  private syncFurnitureSpriteLayer(sortedFurnitures: FurnitureItem[]): void {
    this.furnitureSpriteLayer.removeAll(true);
    this.furnitureSpriteById.clear();
    for (const furniture of sortedFurnitures) {
      const spriteUrl = this.resolveRuntimeAssetUrl(String(furniture.sprite_key || '').trim());
      if (!spriteUrl) {
        continue;
      }
      const textureKey = this.ensureFurnitureTexture(spriteUrl);
      if (!textureKey || !this.textures.exists(textureKey)) {
        continue;
      }
      const image = this.add.image(furniture.x + furniture.width / 2, furniture.y + furniture.height / 2, textureKey);
      image.setDisplaySize(Math.max(8, furniture.width), Math.max(8, furniture.height));
      image.setDepth(this.layerToDepth('mid_props', furniture.y + furniture.height) + 0.02);
      image.setAlpha(FURNITURE_NORMAL_ALPHA);
      this.furnitureSpriteLayer.add(image);
      this.furnitureSpriteById.set(furniture.id, image);
    }
    this.updateFurnitureCollisionFade();
  }

  private updateFurnitureCollisionFade(): void {
    if (this.furnitureSpriteById.size === 0) {
      return;
    }

    const shouldHideByCollision = Boolean(this.lobster)
      && !this.houseOverlaySuppressed
      && !(this.editorModeEnabled && this.editorTool === 'wall');

    if (!shouldHideByCollision) {
      for (const sprite of this.furnitureSpriteById.values()) {
        if (!sprite.active) {
          continue;
        }
        if (Math.abs(sprite.alpha - FURNITURE_NORMAL_ALPHA) <= 0.01) {
          sprite.setAlpha(FURNITURE_NORMAL_ALPHA);
        } else {
          sprite.setAlpha(Phaser.Math.Linear(sprite.alpha, FURNITURE_NORMAL_ALPHA, FURNITURE_COLLISION_FADE_LERP));
        }
      }
      return;
    }

    const actorSprite = this.lobsterBody instanceof Phaser.GameObjects.Sprite ? this.lobsterBody : null;
    if (!actorSprite?.active) {
      for (const sprite of this.furnitureSpriteById.values()) {
        sprite.setAlpha(FURNITURE_NORMAL_ALPHA);
      }
      return;
    }

    for (const sprite of this.furnitureSpriteById.values()) {
      if (!sprite.active) {
        continue;
      }
      const isTouching = this.spritesHaveOpaquePixelOverlap(actorSprite, sprite);
      const targetAlpha = isTouching ? FURNITURE_COLLISION_FADE_ALPHA : FURNITURE_NORMAL_ALPHA;
      if (Math.abs(sprite.alpha - targetAlpha) <= 0.01) {
        sprite.setAlpha(targetAlpha);
      } else {
        sprite.setAlpha(Phaser.Math.Linear(sprite.alpha, targetAlpha, FURNITURE_COLLISION_FADE_LERP));
      }
    }
  }

  private spritesHaveOpaquePixelOverlap(
    actorSprite: Phaser.GameObjects.Sprite,
    furnitureSprite: Phaser.GameObjects.Image
  ): boolean {
    const actorMask = this.getAlphaMaskForSprite(actorSprite);
    const furnitureMask = this.getAlphaMaskForSprite(furnitureSprite);
    if (!actorMask || !furnitureMask) {
      return Phaser.Geom.Intersects.RectangleToRectangle(actorSprite.getBounds(), furnitureSprite.getBounds());
    }

    const actorBounds = actorSprite.getBounds();
    const furnitureBounds = furnitureSprite.getBounds();
    const left = Math.max(actorBounds.x, furnitureBounds.x);
    const top = Math.max(actorBounds.y, furnitureBounds.y);
    const right = Math.min(actorBounds.x + actorBounds.width, furnitureBounds.x + furnitureBounds.width);
    const bottom = Math.min(actorBounds.y + actorBounds.height, furnitureBounds.y + furnitureBounds.height);
    if (right <= left || bottom <= top) {
      return false;
    }

    const centerX = (left + right) / 2;
    const centerY = (top + bottom) / 2;
    if (
      this.isSpriteOpaqueAtWorldPoint(actorSprite, actorMask, centerX, centerY)
      && this.isSpriteOpaqueAtWorldPoint(furnitureSprite, furnitureMask, centerX, centerY)
    ) {
      return true;
    }

    const overlapWidth = right - left;
    const overlapHeight = bottom - top;
    const step = Math.max(
      1,
      Math.min(
        FURNITURE_ALPHA_OVERLAP_SAMPLE_STEP,
        Math.floor(Math.min(overlapWidth, overlapHeight) / 2) || 1
      )
    );
    const startX = left + Math.min(step / 2, overlapWidth / 2);
    const startY = top + Math.min(step / 2, overlapHeight / 2);
    for (let y = startY; y <= bottom; y += step) {
      for (let x = startX; x <= right; x += step) {
        if (
          this.isSpriteOpaqueAtWorldPoint(actorSprite, actorMask, x, y)
          && this.isSpriteOpaqueAtWorldPoint(furnitureSprite, furnitureMask, x, y)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  private getAlphaMaskForSprite(target: Phaser.GameObjects.Image | Phaser.GameObjects.Sprite): SpriteAlphaMask | null {
    const frame = target.frame;
    const sourceImage = frame?.source?.image as CanvasImageSource | undefined;
    const width = Math.max(1, Math.round(frame?.cutWidth || frame?.width || target.width || 1));
    const height = Math.max(1, Math.round(frame?.cutHeight || frame?.height || target.height || 1));
    if (!frame || !sourceImage) {
      return null;
    }

    const cacheKey = [
      target.texture.key,
      String(frame.name),
      Math.round(frame.cutX),
      Math.round(frame.cutY),
      width,
      height
    ].join(':');
    const cached = this.spriteAlphaMaskCache.get(cacheKey);
    if (cached) {
      return cached;
    }

    try {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) {
        return null;
      }
      context.clearRect(0, 0, width, height);
      context.drawImage(
        sourceImage,
        frame.cutX,
        frame.cutY,
        width,
        height,
        0,
        0,
        width,
        height
      );
      const mask = {
        width,
        height,
        data: context.getImageData(0, 0, width, height).data
      };
      this.spriteAlphaMaskCache.set(cacheKey, mask);
      return mask;
    } catch {
      return null;
    }
  }

  private isSpriteOpaqueAtWorldPoint(
    target: Phaser.GameObjects.Image | Phaser.GameObjects.Sprite,
    mask: SpriteAlphaMask,
    worldX: number,
    worldY: number
  ): boolean {
    const bounds = target.getBounds();
    if (bounds.width <= 0 || bounds.height <= 0) {
      return false;
    }

    const normalizedX = (worldX - bounds.x) / bounds.width;
    const normalizedY = (worldY - bounds.y) / bounds.height;
    if (normalizedX < 0 || normalizedX > 1 || normalizedY < 0 || normalizedY > 1) {
      return false;
    }

    const flippedX = Boolean((target as { flipX?: boolean }).flipX);
    const flippedY = Boolean((target as { flipY?: boolean }).flipY);
    const maskX = Phaser.Math.Clamp(
      Math.floor((flippedX ? 1 - normalizedX : normalizedX) * mask.width),
      0,
      mask.width - 1
    );
    const maskY = Phaser.Math.Clamp(
      Math.floor((flippedY ? 1 - normalizedY : normalizedY) * mask.height),
      0,
      mask.height - 1
    );
    const alphaIndex = ((maskY * mask.width) + maskX) * 4 + 3;
    return (mask.data[alphaIndex] ?? 0) > FURNITURE_ALPHA_OVERLAP_THRESHOLD;
  }

  private ensureFurnitureTexture(assetUrl: string): string | null {
    const url = String(assetUrl || '').trim();
    if (!url) {
      return null;
    }
    const cached = this.furnitureTextureByUrl.get(url);
    if (cached && this.textures.exists(cached)) {
      return cached;
    }
    const textureKey = cached || `furniture-asset-${this.furnitureTextureByUrl.size + 1}`;
    this.furnitureTextureByUrl.set(url, textureKey);
    if (this.textures.exists(textureKey) || this.queuedTextureKeys.has(textureKey)) {
      return textureKey;
    }
    this.queuedTextureKeys.add(textureKey);
    const onFileComplete = (): void => {
      this.load.off(`filecomplete-image-${textureKey}`, onFileComplete);
      this.load.off('loaderror', onLoadError);
      this.queuedTextureKeys.delete(textureKey);
      this.drawSceneMapLayers();
    };
    const onLoadError = (file: Phaser.Loader.File): void => {
      if (file.key !== textureKey) {
        return;
      }
      this.load.off(`filecomplete-image-${textureKey}`, onFileComplete);
      this.load.off('loaderror', onLoadError);
      this.queuedTextureKeys.delete(textureKey);
    };
    this.load.on(`filecomplete-image-${textureKey}`, onFileComplete);
    this.load.on('loaderror', onLoadError);
    this.load.image(textureKey, url);
    if (!this.load.isLoading()) {
      this.load.start();
    }
    return textureKey;
  }

  private drawInteractionPointLayer(): void {
    this.interactionPointLayer.clear();
    this.interactionPointLabelLayer.removeAll(true);
    if ((this.editorModeEnabled && this.editorTool === 'wall') || this.houseOverlaySuppressed) {
      return;
    }
    const actionPointMode = this.editorModeEnabled && this.editorTool === 'interaction' && this.interactionEditorMode === 'action_point';
    const shouldRender = actionPointMode || this.debugVisualsVisible;
    if (!shouldRender) {
      return;
    }
    for (const point of this.sceneMapData.interaction_points) {
      const isHovered = this.hoveredInteractionPointId === point.id || (actionPointMode && this.selectedInteractionPointId === point.id);
      const color = this.resolveSceneMapRoomColor(point.room_id);
      const radius = isHovered ? INTERACTION_POINT_RADIUS + 4 : actionPointMode ? INTERACTION_POINT_RADIUS + 2 : INTERACTION_POINT_RADIUS;
      const fillAlpha = isHovered ? 0.62 : actionPointMode ? 0.38 : 0.24;
      const strokeAlpha = isHovered ? 0.98 : actionPointMode ? 0.88 : 0.74;
      this.interactionPointLayer.fillStyle(color, fillAlpha);
      this.interactionPointLayer.fillCircle(point.x, point.y, radius);
      this.interactionPointLayer.lineStyle(1.5, 0xf3fbff, strokeAlpha);
      this.interactionPointLayer.strokeCircle(point.x, point.y, radius);
      if (actionPointMode) {
        this.interactionPointLayer.lineStyle(1, 0x0a1218, 0.85);
        this.interactionPointLayer.strokeCircle(point.x, point.y, Math.max(4, radius - 6));
      }
    }
    if (actionPointMode) {
      for (const point of this.sceneMapData.interaction_points) {
        const text = this.add.text(point.x, point.y - (INTERACTION_POINT_RADIUS + 18), point.label, {
          color: '#e6f2ff',
          fontFamily: this.sansFontFamily(),
          fontSize: '12px',
          backgroundColor: 'rgba(8, 14, 22, 0.72)',
          padding: { left: 5, right: 5, top: 2, bottom: 2 }
        });
        text.setOrigin(0.5, 1);
        this.interactionPointLabelLayer.add(text);
      }
    }
  }

  private drawInteractionBoxLayer(): void {
    this.interactionBoxLayer.clear();
    this.interactionBoxLabelLayer.removeAll(true);
    if ((this.editorModeEnabled && this.editorTool === 'wall') || this.houseOverlaySuppressed) {
      return;
    }
    const boxMode = this.editorModeEnabled && this.editorTool === 'interaction' && this.interactionEditorMode === 'interaction_box';
    if (!boxMode) {
      return;
    }
    for (const interactionBox of this.sceneMapData.interaction_boxes) {
      const isSelected = this.selectedInteractionBoxId === interactionBox.id;
      const isHovered = this.hoveredInteractionBoxId === interactionBox.id;
      const color = this.resolveSceneMapRoomColor(interactionBox.room_id);
      this.interactionBoxLayer.fillStyle(color, isSelected ? 0.26 : isHovered ? 0.2 : 0.15);
      this.interactionBoxLayer.fillRect(interactionBox.x, interactionBox.y, interactionBox.width, interactionBox.height);
      this.interactionBoxLayer.lineStyle(isSelected ? 2 : 1.2, isSelected ? 0xf8e6a9 : 0xf3fbff, isSelected ? 0.95 : 0.75);
      this.interactionBoxLayer.strokeRect(interactionBox.x, interactionBox.y, interactionBox.width, interactionBox.height);
      const label = this.add.text(interactionBox.x + 6, interactionBox.y - 4, interactionBox.label, {
        color: '#e6f2ff',
        fontFamily: this.sansFontFamily(),
        fontSize: '12px',
        backgroundColor: 'rgba(8, 14, 22, 0.72)',
        padding: { left: 5, right: 5, top: 2, bottom: 2 }
      });
      label.setOrigin(0, 1);
      this.interactionBoxLabelLayer.add(label);
    }
  }

  private resolveSceneMapRoomColor(roomId: string): number {
    return PARTITION_COLORS[roomId as ResourcePartitionId] ?? 0x6b879d;
  }

  private renderEditorWallPreview(): void {
    this.editorPreviewLayer.clear();
    if (!this.editorModeEnabled || this.editorTool !== 'wall' || !this.editorPointerPoint || this.wallEditorDragState) {
      return;
    }

    const hitExisting = this.findWallBlockByPoint(this.editorPointerPoint);
    if (hitExisting) {
      return;
    }

    const preview = this.buildWallBlockFromShapePreset(this.editorPointerPoint, this.wallEditorShapePreset);
    this.drawWallBlockOnGraphics(this.editorPreviewLayer, preview, {
      fillColor: 0xffb77a,
      fillAlpha: 0.16,
      strokeColor: 0xffd6b2,
      strokeAlpha: 0.9,
      strokeWidth: 1.5
    });
  }

  private spawnAssets(): void {
    for (const asset of this.protocols.assetManifest.assets) {
      const colorByKind = {
        book: 0xa9d0ff,
        tool: 0x91f0cc,
        art: 0xf6c48f,
        marker: 0xc8a4ff
      } as const;

      const width = asset.displaySize?.width ?? asset.size.width;
      const height = asset.displaySize?.height ?? asset.size.height;
      const drawPoint = asset.footpoint ?? asset.anchor;
      const body = this.add.rectangle(asset.anchor.x, asset.anchor.y, width, height, colorByKind[asset.kind], 0.92);
      body.setDepth(this.layerToDepth(asset.layer, drawPoint.y, asset.depthBand));
      body.setStrokeStyle(2, 0x223050, 0.82);
      if (asset.roomId === 'break_room') {
        body.setFillStyle(0xd5b798, 0.92);
      }
      if (this.hasSceneBaseArt() || this.roomHasSliceLayer(asset.roomId, 'mid_props')) {
        body.setVisible(false);
      }
      this.renderedAssets.push({ def: asset, body, pulseTween: null });
    }
  }

  private spawnLobster(): void {
    const firstNode =
      this.protocols.mapLogic.walkGraph.nodes.find((node) => node.id === 'BR1')
      ?? this.protocols.mapLogic.walkGraph.nodes[0];
    const spawnIdleMode = this.resolveSpawnIdleMode();
    const spawnAnchor = spawnIdleMode?.triggerAnchor
      ? { x: Math.round(spawnIdleMode.triggerAnchor.x), y: Math.round(spawnIdleMode.triggerAnchor.y) }
      : null;
    const fallbackSpawnPoint = this.resolveRequestedWalkTarget({ x: firstNode.x, y: firstNode.y }, 240)
      ?? { x: firstNode.x, y: firstNode.y };
    const spawnPoint = spawnAnchor
      ? (this.resolveRequestedWalkTarget(spawnAnchor, 260) ?? spawnAnchor)
      : fallbackSpawnPoint;
    const children: Phaser.GameObjects.GameObject[] = [];
    const actor = this.protocols.sceneArt.actor;
    const variant = this.resolveActorVariant();

    if (actor?.shadow) {
      const shadow = this.add.ellipse(0, actor.shadow.offsetY, actor.shadow.width, actor.shadow.height, 0x081018, actor.shadow.alpha);
      children.push(shadow);
    }

    const idleVisual = spawnIdleMode ?? this.resolveActorMode('idle', {
      position: spawnPoint,
      direction: this.actorFacing
    });
    if (actor && variant && idleVisual) {
      const sprite = this.add.sprite(actor.anchorOffset?.x ?? 0, actor.anchorOffset?.y ?? 0, idleVisual.textureKey);
      const modeDisplay = this.resolveModeDisplaySize(idleVisual, actor.displaySize, 1.2);
      sprite.setDisplaySize(Math.round(modeDisplay.width), Math.round(modeDisplay.height));
      children.push(sprite);
      this.lobsterBody = sprite;
    } else {
      const fallback = this.add.circle(0, 0, 16, 0xff6f48, 1);
      fallback.setStrokeStyle(3, 0x2a0f05, 0.8);
      children.push(fallback);
      this.lobsterBody = fallback;
    }

    this.lobster = this.add.container(spawnPoint.x, spawnPoint.y, children);
    this.lobster.setDepth(this.layerToDepth('actor', spawnPoint.y));
    this.lastReachedZoneId = this.findRoomByPoint(spawnPoint)?.id ?? firstNode.roomId;
    this.currentActionMode = spawnIdleMode ?? null;
    this.lastCompletedActionAnchor = spawnIdleMode?.triggerAnchor
      ? { x: Math.round(spawnIdleMode.triggerAnchor.x), y: Math.round(spawnIdleMode.triggerAnchor.y) }
      : null;
    this.suppressedActionAnchor = null;
    this.suppressedActionAnchorUntil = 0;
    this.lastMainVisualKey = null;
    this.resetPatrolProgressTracking();
    this.patrolCooldownUntil = Date.now() + 1800;
    this.updateLobsterVisual('idle', spawnIdleMode ?? undefined);

    this.lobsterNameTag = this.add.text(spawnPoint.x, spawnPoint.y - 36, '默认Agent', {
      color: '#ffe4a0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
      fontSize: '13px',
      backgroundColor: 'rgba(28, 18, 4, 0.76)',
      padding: { left: 6, right: 6, top: 3, bottom: 3 }
    });
    this.lobsterNameTag.setOrigin(0.5, 1);
    this.lobsterNameTag.setDepth(this.layerToDepth('fx_overlay') + 11);

    // Context bar — independent graphics, positioned below the thought label
    this.lobsterContextBar = this.add.graphics();
    this.lobsterContextBar.setDepth(this.layerToDepth('fx_overlay', this.lobster.y) + 11);
    this.drawContextBar(1); // starts full/green
  }

  private handlePointerDown(x: number, y: number, pointer?: Phaser.Input.Pointer): void {
    const point = { x, y };
    this.editorPointerPoint = point;

    if (this.editorModeEnabled) {
      this.handleEditorPointerDown(point, pointer);
      return;
    }

    const furniture = this.findFurnitureByPoint(point);
    if (furniture) {
      this.handleFurnitureClick(furniture);
      return;
    }

    const interactionPoint = this.findInteractionPointByPoint(point);
    if (interactionPoint) {
      this.handleInteractionPointClick(interactionPoint);
      return;
    }

    // 地面点击优先触发移动，避免旧的 hitAsset / workZone 拦截导致“点地不走”。
    const moved = this.movePrimaryAgentTo(point);
    this.hitLayer.clear();
    const hitRoom = this.findRoomByPoint(point);
    if (moved && hitRoom) {
      this.emitResourceSelection(hitRoom.id, this.resolveRoomLabelAnchor(hitRoom));
      return;
    }
    if (moved) {
      return;
    }

    const hitAsset = this.findHitAsset(point);
    if (hitAsset) {
      this.emitResourceSelection(hitAsset.roomId, point);
      this.drawHitOverlay(hitAsset);
      return;
    }

    const hitZone = this.findWorkZone(point);
    if (hitZone) {
      this.emitResourceSelection(hitZone.id, hitZone.anchor);
      return;
    }

    if (hitRoom) {
      this.emitResourceSelection(hitRoom.id, this.resolveRoomLabelAnchor(hitRoom));
      return;
    }

    this.showSceneToast('该位置不可达，已保持原地。', 'warn', 1300);
  }

  private handlePointerUp(x: number, y: number, pointer?: Phaser.Input.Pointer): void {
    const point = { x, y };
    this.editorPointerPoint = point;
    if (!this.editorModeEnabled) {
      return;
    }
    this.handleEditorPointerUp(point, pointer);
  }

  private handlePointerMove(x: number, y: number): void {
    const point = { x, y };
    this.editorPointerPoint = point;

    if (this.editorModeEnabled && this.editorTool === 'wall') {
      this.handleWallEditorPointerMove(point);
      return;
    }

    if (this.editorModeEnabled && this.editorTool === 'furniture' && this.furnitureDragState) {
      const furniture = this.sceneMapData.furnitures.find((item) => item.id === this.furnitureDragState?.id);
      if (!furniture) {
        this.furnitureDragState = null;
        return;
      }
      const dx = point.x - this.furnitureDragState.startPoint.x;
      const dy = point.y - this.furnitureDragState.startPoint.y;
      const clamped = this.clampFurniturePosition(
        this.furnitureDragState.startRect.x + dx,
        this.furnitureDragState.startRect.y + dy,
        furniture.width,
        furniture.height
      );
      furniture.x = clamped.x;
      furniture.y = clamped.y;
      furniture.z_index = furniture.y + furniture.height;
      this.drawSceneMapLayers();
      return;
    }

    if (this.editorModeEnabled && this.editorTool === 'room_label') {
      if (this.roomLabelDragState) {
        const room = this.protocols.mapLogic.rooms.find((item) => item.id === this.roomLabelDragState?.roomId) ?? null;
        if (!room) {
          this.roomLabelDragState = null;
          this.selectedRoomLabelId = null;
          return;
        }
        const dx = point.x - this.roomLabelDragState.startPoint.x;
        const dy = point.y - this.roomLabelDragState.startPoint.y;
        const nextAnchor = this.clampRoomLabelAnchor({
          x: this.roomLabelDragState.startAnchor.x + dx,
          y: this.roomLabelDragState.startAnchor.y + dy
        });
        const currentAnchor = this.resolveRoomLabelAnchor(room);
        if (nextAnchor.x !== currentAnchor.x || nextAnchor.y !== currentAnchor.y) {
          this.roomLabelDragState.moved = true;
          this.setSceneMapRoomLabelAnchor(room.id, nextAnchor);
          this.syncRoomLabels();
        }
      }
      return;
    }

    if (this.editorModeEnabled && this.editorTool === 'interaction') {
      if (this.interactionEditorMode === 'action_point' && this.interactionPointDragState) {
        const actionPoint = this.sceneMapData.interaction_points.find((item) => item.id === this.interactionPointDragState?.id);
        if (!actionPoint) {
          this.interactionPointDragState = null;
          return;
        }
        const dx = point.x - this.interactionPointDragState.startPoint.x;
        const dy = point.y - this.interactionPointDragState.startPoint.y;
        const nextX = Math.round(Phaser.Math.Clamp(this.interactionPointDragState.startPosition.x + dx, 0, this.sceneMapData.base_width));
        const nextY = Math.round(Phaser.Math.Clamp(this.interactionPointDragState.startPosition.y + dy, 0, this.sceneMapData.base_height));
        actionPoint.x = nextX;
        actionPoint.y = nextY;
        actionPoint.anchor_x = nextX;
        actionPoint.anchor_y = nextY;
        this.syncWorkZonesFromInteractionPoints({ refreshWorkZoneLayer: true });
        this.drawSceneMapLayers();
        return;
      }
      if (this.interactionEditorMode === 'interaction_box' && this.interactionBoxDragState) {
        const interactionBox = this.sceneMapData.interaction_boxes.find((item) => item.id === this.interactionBoxDragState?.id);
        if (!interactionBox) {
          this.interactionBoxDragState = null;
          return;
        }
        const dx = point.x - this.interactionBoxDragState.startPoint.x;
        const dy = point.y - this.interactionBoxDragState.startPoint.y;
        const nextX = Math.round(this.interactionBoxDragState.startRect.x + dx);
        const nextY = Math.round(this.interactionBoxDragState.startRect.y + dy);
        interactionBox.x = Phaser.Math.Clamp(nextX, 0, Math.max(0, this.sceneMapData.base_width - interactionBox.width));
        interactionBox.y = Phaser.Math.Clamp(nextY, 0, Math.max(0, this.sceneMapData.base_height - interactionBox.height));
        this.drawSceneMapLayers();
        return;
      }
      if (this.interactionEditorMode === 'action_point') {
        const hoveredActionPoint = this.findInteractionPointByPoint(point);
        const nextActionPointId = hoveredActionPoint?.id ?? null;
        if (nextActionPointId !== this.hoveredInteractionPointId) {
          this.hoveredInteractionPointId = nextActionPointId;
          this.drawInteractionPointLayer();
        }
      } else {
        const hoveredInteractionBox = this.findInteractionBoxByPoint(point);
        const nextBoxId = hoveredInteractionBox?.id ?? null;
        if (nextBoxId !== this.hoveredInteractionBoxId) {
          this.hoveredInteractionBoxId = nextBoxId;
          this.drawInteractionBoxLayer();
        }
      }
      return;
    }

    const hoveredFurniture = this.findFurnitureByPoint(point);
    const hoveredInteractionPoint = this.findInteractionPointByPoint(point);
    const nextFurnitureId = hoveredFurniture?.id ?? null;
    const nextInteractionPointId = hoveredInteractionPoint?.id ?? null;
    if (nextFurnitureId !== this.hoveredFurnitureId || nextInteractionPointId !== this.hoveredInteractionPointId) {
      this.hoveredFurnitureId = nextFurnitureId;
      this.hoveredInteractionPointId = nextInteractionPointId;
      this.drawFurnitureLayer();
      this.drawInteractionPointLayer();
    }
  }

  private handleEditorKeyDown(event: KeyboardEvent): void {
    if (event.shiftKey && event.code === 'KeyE') {
      event.preventDefault();
      this.toggleEditorMode();
      return;
    }

    if (!this.editorModeEnabled) {
      return;
    }

    if (event.code === 'Digit1') {
      this.settingsMode = null;
      this.setEditorMode(true, 'wall');
      return;
    }
    if (event.code === 'Digit2') {
      this.settingsMode = 'furniture';
      this.setEditorMode(true, 'furniture');
      return;
    }
    if (event.code === 'Digit3') {
      this.settingsMode = null;
      this.setEditorMode(true, 'interaction');
      return;
    }
    if (event.code === 'Digit4') {
      this.settingsMode = 'house';
      this.roomLabelEditorSessionActive = true;
      this.setEditorMode(true, 'room_label');
      return;
    }

    if (event.code === 'KeyS') {
      event.preventDefault();
      if (this.editorTool === 'wall') {
        this.saveWallEditorChanges();
      } else {
        this.persistSceneMap('手动保存场景地图');
      }
      return;
    }

    if (event.code === 'KeyE' && !event.shiftKey) {
      event.preventDefault();
      this.exportSceneMapJson();
      return;
    }

    if (event.code === 'Escape') {
      this.wallEditorDragState = null;
      this.editorPreviewLayer.clear();
      this.showSceneToast('已取消当前编辑操作', 'info', 800);
      return;
    }

    if (event.code === 'Delete' || event.code === 'Backspace') {
      if (this.editorTool === 'wall' && this.selectedWallBlockId) {
        event.preventDefault();
        this.deleteWallBlockById(this.selectedWallBlockId);
        return;
      }
      if (this.editorTool === 'furniture' && this.selectedFurnitureId) {
        event.preventDefault();
        this.deleteFurnitureById(this.selectedFurnitureId);
      }
      return;
    }

    if (event.code === 'KeyB') {
      this.toggleSelectedFurnitureBlocking();
      return;
    }
    if (event.code === 'KeyI') {
      this.toggleSelectedFurnitureInteractive();
      return;
    }
    if (event.code === 'KeyT') {
      this.cycleSelectedFurnitureInteractionType();
      return;
    }
  }

  private toggleEditorMode(): void {
    this.setEditorMode(!this.editorModeEnabled, this.editorTool);
  }

  private setEditorMode(
    enabled: boolean,
    nextTool: SceneEditorTool,
    options: { silent?: boolean } = {}
  ): void {
    const previousEnabled = this.editorModeEnabled;
    const previousTool = this.editorTool;

    this.editorModeEnabled = enabled;
    this.editorTool = nextTool;

    if (enabled && nextTool === 'wall' && !this.wallEditorSessionActive) {
      this.wallEditorBaseline = this.cloneWallBlocks(this.sceneMapData.wall_blocks);
      this.wallEditorDirty = false;
      this.wallEditorSessionActive = true;
      this.selectedWallBlockId = null;
    }
    if (enabled && nextTool === 'room_label') {
      this.roomLabelEditorSessionActive = true;
    }

    if (!enabled) {
      this.wallEditorDragState = null;
      this.selectedWallBlockId = null;
      this.interactionPointDragState = null;
      this.interactionBoxDragState = null;
      this.roomLabelDragState = null;
      this.selectedRoomLabelId = null;
      this.editorPreviewLayer.clear();
      if (this.settingsMode === 'furniture' || this.settingsMode === 'interaction') {
        this.settingsMode = null;
      }
      if (previousTool === 'wall') {
        if (this.wallEditorDirty) {
          this.persistSceneMap('墙壁设置自动保存');
        }
        this.wallEditorSessionActive = false;
        this.wallEditorDirty = false;
        this.wallEditorBaseline = null;
      }
      if (previousTool === 'interaction') {
        this.interactionEditorSessionActive = false;
      }
      if (previousTool === 'room_label') {
        this.roomLabelEditorSessionActive = false;
      }
    }

    if (previousTool !== nextTool) {
      if (previousTool === 'room_label') {
        this.roomLabelDragState = null;
        this.selectedRoomLabelId = null;
        this.roomLabelEditorSessionActive = false;
        this.syncRoomLabels();
      }
      if (nextTool !== 'room_label') {
        this.roomLabelDragState = null;
      }
    }

    this.drawSceneMapLayers();

    if (!options.silent) {
      if (previousEnabled !== enabled) {
        this.showSceneToast(
          enabled
            ? `编辑模式已开启（数据持久化键: ${SCENE_MAP_LOCAL_JSON_HINT}）`
            : '编辑模式已关闭',
          enabled ? 'success' : 'info',
          1800
        );
      } else if (previousTool !== nextTool) {
        const label = nextTool === 'wall'
          ? '墙壁'
          : nextTool === 'furniture'
            ? '家具'
            : nextTool === 'interaction'
              ? '互动点'
              : '房屋名';
        this.showSceneToast(`编辑工具切换: ${label}`, 'info', 1000);
      }
    }

    if (previousEnabled !== enabled || previousTool !== nextTool) {
      this.emitEditorModeChanged();
    }
  }

  private emitEditorModeChanged(): void {
    const suggestedSettingsMode: SceneSettingsMode =
      this.editorModeEnabled
        ? this.editorTool === 'furniture'
            ? 'furniture'
            : this.editorTool === 'interaction'
              ? 'interaction'
              : this.editorTool === 'room_label'
                ? 'house'
              : null
        : null;
    this.events.emit('scene-editor-mode-changed', {
      enabled: this.editorModeEnabled,
      tool: this.editorTool,
      suggestedSettingsMode
    });
  }

  private handleEditorPointerDown(point: Point, pointer?: Phaser.Input.Pointer): void {
    const isRightClick = Boolean(pointer?.rightButtonDown());

    if (this.editorTool === 'wall') {
      this.handleWallEditorPointerDown(point, isRightClick);
      return;
    }

    if (this.editorTool === 'furniture') {
      if (isRightClick) {
        const removed = this.deleteFurnitureAt(point);
        if (!removed) {
          this.showSceneToast('未命中可删除的家具', 'warn', 900);
        }
        return;
      }

      const existed = this.findFurnitureByPoint(point);
      if (existed) {
        this.selectedFurnitureId = existed.id;
        this.highlightFurniture(existed.id);
        this.furnitureDragState = {
          id: existed.id,
          startPoint: point,
          startRect: { x: existed.x, y: existed.y, width: existed.width, height: existed.height }
        };
        this.showSceneToast(`选中家具: ${existed.label}`, 'info', 700);
        this.drawSceneMapLayers();
        return;
      }

      if (!this.furniturePlacementTemplate) {
        this.showSceneToast('请先在分类面板中选择具体家具。', 'warn', 1100);
        return;
      }
      this.placeFurnitureAt(point);
      return;
    }

    if (this.editorTool === 'room_label') {
      return;
    }

    if (this.interactionEditorMode === 'action_point') {
      if (isRightClick) {
        const removed = this.deleteInteractionPointAt(point, { persist: false });
        if (!removed) {
          this.showSceneToast('未命中可删除的动作点', 'warn', 900);
        }
        return;
      }
      const existed = this.findInteractionPointByPoint(point);
      if (existed) {
        this.selectedInteractionPointId = existed.id;
        this.selectedInteractionBoxId = null;
        this.interactionPointDragState = {
          id: existed.id,
          startPoint: point,
          startPosition: { x: existed.x, y: existed.y }
        };
        this.drawSceneMapLayers();
        return;
      }
      this.placeInteractionPointAt(point, { persist: false });
      const created = this.findInteractionPointByPoint(point);
      if (created) {
        this.selectedInteractionPointId = created.id;
        this.selectedInteractionBoxId = null;
      }
      this.drawSceneMapLayers();
      return;
    }

    if (isRightClick) {
      const removed = this.deleteInteractionBoxAt(point, { persist: false });
      if (!removed) {
        this.showSceneToast('未命中可删除的交互框', 'warn', 900);
      }
      return;
    }

    const hitBox = this.findInteractionBoxByPoint(point);
    if (hitBox) {
      this.selectedInteractionBoxId = hitBox.id;
      this.selectedInteractionPointId = null;
      this.interactionBoxDragState = {
        id: hitBox.id,
        startPoint: point,
        startRect: { x: hitBox.x, y: hitBox.y, width: hitBox.width, height: hitBox.height }
      };
      this.drawSceneMapLayers();
      return;
    }
    this.placeInteractionBoxAt(point, { persist: false });
    const created = this.findInteractionBoxByPoint(point);
    if (created) {
      this.selectedInteractionBoxId = created.id;
      this.selectedInteractionPointId = null;
      this.drawSceneMapLayers();
    }
  }

  private handleEditorPointerUp(point: Point, _pointer?: Phaser.Input.Pointer): void {
    if (this.editorTool === 'furniture') {
      if (this.furnitureDragState) {
        this.furnitureDragState = null;
        this.persistSceneMap('拖拽家具位置');
      }
      return;
    }
    if (this.editorTool === 'room_label') {
      if (this.roomLabelDragState) {
        const shouldPersist = this.roomLabelDragState.moved;
        this.roomLabelDragState = null;
        if (shouldPersist) {
          this.persistSceneMap('拖拽房屋名位置');
        }
      }
      return;
    }
    if (this.editorTool === 'interaction') {
      if (this.interactionPointDragState || this.interactionBoxDragState) {
        this.interactionPointDragState = null;
        this.interactionBoxDragState = null;
      }
      return;
    }
    if (this.editorTool !== 'wall') {
      return;
    }
    this.handleWallEditorPointerUp(point);
  }

  private handleWallEditorPointerDown(point: Point, isRightClick: boolean): void {
    if (isRightClick) {
      const hitWall = this.findWallBlockByPoint(point);
      if (!hitWall) {
        this.showSceneToast('未命中可删除的墙壁模块', 'warn', 900);
        return;
      }
      this.deleteWallBlockById(hitWall.id);
      return;
    }

    const selectedWall = this.selectedWallBlockId
      ? this.sceneMapData.wall_blocks.find((item) => item.id === this.selectedWallBlockId) ?? null
      : null;
    if (selectedWall) {
      const handle = this.findWallEditorHandleByPoint(point, selectedWall);
      if (handle) {
        if (handle.kind === 'delete') {
          this.deleteWallBlockById(selectedWall.id);
          return;
        }
        const center = this.wallBlockCenter(selectedWall);
        this.wallEditorDragState = {
          kind: handle.kind,
          wallId: selectedWall.id,
          startPoint: point,
          startWall: { ...selectedWall },
          startAngle: Math.atan2(point.y - center.y, point.x - center.x)
        };
        return;
      }
    }

    const hitWall = this.findWallBlockByPoint(point);
    if (hitWall) {
      this.selectedWallBlockId = hitWall.id;
      this.wallEditorDragState = {
        kind: 'move',
        wallId: hitWall.id,
        startPoint: point,
        startWall: { ...hitWall }
      };
      this.drawSceneMapLayers();
      return;
    }

    const nextWall = this.buildWallBlockFromShapePreset(point, this.wallEditorShapePreset);
    this.sceneMapData.wall_blocks.push(nextWall);
    this.selectedWallBlockId = nextWall.id;
    this.markWallEditorDirty(`新增墙壁 ${nextWall.id}`, true);
  }

  private handleWallEditorPointerMove(point: Point): void {
    if (!this.wallEditorDragState) {
      this.renderEditorWallPreview();
      return;
    }
    const index = this.sceneMapData.wall_blocks.findIndex((item) => item.id === this.wallEditorDragState?.wallId);
    if (index === -1) {
      this.wallEditorDragState = null;
      this.drawSceneMapLayers();
      return;
    }

    const drag = this.wallEditorDragState;
    const wall = this.sceneMapData.wall_blocks[index];
    const dx = point.x - drag.startPoint.x;
    const dy = point.y - drag.startPoint.y;

    if (drag.kind === 'move') {
      wall.x = Math.round(drag.startWall.x + dx);
      wall.y = Math.round(drag.startWall.y + dy);
      this.clampWallBlockInBounds(wall);
      this.drawSceneMapLayers();
      return;
    }

    if (drag.kind === 'rotate') {
      const center = this.wallBlockCenter(drag.startWall);
      const startAngle = drag.startAngle ?? 0;
      const currentAngle = Math.atan2(point.y - center.y, point.x - center.x);
      wall.rotation = Math.round((Number(drag.startWall.rotation) || 0) + Phaser.Math.RadToDeg(currentAngle - startAngle));
      this.drawSceneMapLayers();
      return;
    }

    const startLeft = drag.startWall.x;
    const startTop = drag.startWall.y;
    const startRight = drag.startWall.x + drag.startWall.width;
    const startBottom = drag.startWall.y + drag.startWall.height;

    let nextLeft = startLeft;
    let nextTop = startTop;
    let nextRight = startRight;
    let nextBottom = startBottom;

    if (drag.kind === 'resize-nw') {
      nextLeft += dx;
      nextTop += dy;
    } else if (drag.kind === 'resize-ne') {
      nextRight += dx;
      nextTop += dy;
    } else if (drag.kind === 'resize-sw') {
      nextLeft += dx;
      nextBottom += dy;
    } else if (drag.kind === 'resize-se') {
      nextRight += dx;
      nextBottom += dy;
    }

    const minSize = EDITOR_WALL_MIN_SIZE;
    if (nextRight - nextLeft < minSize) {
      if (drag.kind === 'resize-nw' || drag.kind === 'resize-sw') {
        nextLeft = nextRight - minSize;
      } else {
        nextRight = nextLeft + minSize;
      }
    }
    if (nextBottom - nextTop < minSize) {
      if (drag.kind === 'resize-nw' || drag.kind === 'resize-ne') {
        nextTop = nextBottom - minSize;
      } else {
        nextBottom = nextTop + minSize;
      }
    }

    wall.x = Math.round(nextLeft);
    wall.y = Math.round(nextTop);
    wall.width = Math.max(minSize, Math.round(nextRight - nextLeft));
    wall.height = Math.max(minSize, Math.round(nextBottom - nextTop));
    if (wall.shape === 'square' || wall.shape === 'circle') {
      const side = Math.max(wall.width, wall.height);
      wall.width = side;
      wall.height = side;
    }
    this.clampWallBlockInBounds(wall);
    this.drawSceneMapLayers();
  }

  private handleWallEditorPointerUp(_point: Point): void {
    if (!this.wallEditorDragState) {
      return;
    }
    this.wallEditorDragState = null;
    this.markWallEditorDirty('墙壁已调整', false);
  }

  private movePrimaryAgentTo(targetPoint: Point): boolean {
    if (!this.lobster) {
      return false;
    }
    const resolvedTarget = this.resolveRequestedWalkTarget(targetPoint, 260);
    if (!resolvedTarget) {
      return false;
    }

    const route = this.computeMaskRoute({ x: this.lobster.x, y: this.lobster.y }, resolvedTarget);
    if (!route || route.length === 0) {
      return false;
    }

    this.clearZoneStates();
    this.drawWorkZones();
    this.activeZoneId = null;
    this.pendingStateProfile = null;
    this.pendingRouteContext = null;
    this.patrolTargetMode = null;
    this.workMode = 'moving';
    this.currentActionMode = null;
    this.lobsterRoute = route;
    this.notePatrolProgress();
    this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
      resourceId: this.focusResourceId,
      detailOverride: 'manual ground move'
    });
    this.updateLobsterVisual('moving');
    this.syncWorkStatus();
    return true;
  }

  private handleFurnitureClick(furniture: FurnitureItem): void {
    this.selectedFurnitureId = furniture.id;
    this.highlightFurniture(furniture.id);
    const baseMessage = `家具: ${furniture.label} (${furniture.interaction_type})`;
    if (!furniture.interactive) {
      this.showSceneToast(`${baseMessage} [仅选中]`, 'info', 1400);
      return;
    }

    this.showSceneToast(`${baseMessage} 互动已触发`, 'success', 1500);
    console.info('[TYXT][FurnitureInteraction]', {
      id: furniture.id,
      interactionType: furniture.interaction_type,
      roomId: furniture.room_id
    });
    this.events.emit('scene-furniture-interaction', {
      id: furniture.id,
      roomId: furniture.room_id,
      interactionType: furniture.interaction_type
    });
  }

  private handleInteractionPointClick(interactionPoint: SceneInteractionPoint): void {
    this.showSceneToast(`互动点触发: ${interactionPoint.label} (${interactionPoint.interaction_type})`, 'success', 1500);
    console.info('[TYXT][InteractionPoint]', {
      id: interactionPoint.id,
      interactionType: interactionPoint.interaction_type,
      roomId: interactionPoint.room_id
    });
    this.events.emit('scene-interaction-point', {
      id: interactionPoint.id,
      roomId: interactionPoint.room_id,
      interactionType: interactionPoint.interaction_type
    });

    const resourceId = this.asResourcePartitionId(interactionPoint.room_id);
    this.emitResourceSelection(resourceId, {
      x: interactionPoint.anchor_x ?? interactionPoint.x,
      y: interactionPoint.anchor_y ?? interactionPoint.y
    });
  }

  private asResourcePartitionId(roomId: string): ResourcePartitionId {
    const matchedRoom = this.protocols.mapLogic.rooms.find((room) => room.id === roomId);
    return matchedRoom?.id ?? 'gateway';
  }

  private highlightFurniture(furnitureId: string): void {
    this.highlightedFurnitureId = furnitureId;
    this.highlightedFurnitureUntil = Date.now() + 900;
    this.drawFurnitureLayer();
  }

  private persistSceneMap(reason: string): void {
    this.sceneMapData = saveSceneMapData(this.sceneMapData);
    this.sceneMapRevision += 1;
    this.persistSceneMapToProjectFile();
    this.syncWorkZonesFromInteractionPoints();
    this.initializeWalkableMask();
    this.drawRooms();
    this.drawSceneMapLayers();
    this.drawWorkZones();
    this.showSceneToast(`${reason}，已保存。`, 'success', 1400);
  }

  private persistSceneMapToProjectFile(): void {
    this.sceneMapProjectPersistPending = cloneSceneMapData(this.sceneMapData);
    if (this.sceneMapProjectPersistPromise) {
      return;
    }

    const flush = async (): Promise<void> => {
      while (this.sceneMapProjectPersistPending) {
        const payload = this.sceneMapProjectPersistPending;
        this.sceneMapProjectPersistPending = null;
        const response = await fetch('/api/tyxt/scene-map', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json; charset=utf-8' },
          body: JSON.stringify({ scene_map: payload })
        });
        if (!response.ok) {
          throw new Error(`scene-map ${response.status}`);
        }
      }
    };

    this.sceneMapProjectPersistPromise = flush()
      .then(() => {
        this.sceneMapProjectPersistWarned = false;
      })
      .catch((error) => {
        console.warn('[TYXT] Failed to persist scene map project file:', error);
        if (!this.sceneMapProjectPersistWarned) {
          this.showSceneToast('项目场景文件保存失败，已保留浏览器缓存。', 'warn', 2600);
        }
        this.sceneMapProjectPersistWarned = true;
      })
      .finally(() => {
        this.sceneMapProjectPersistPromise = null;
        if (this.sceneMapProjectPersistPending) {
          this.persistSceneMapToProjectFile();
        }
      });
  }

  private exportSceneMapJson(): void {
    const exportText = buildSceneMapExportText(this.sceneMapData);
    const blob = new Blob([exportText], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `scene-map.local.${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.json`;
    link.click();
    URL.revokeObjectURL(url);
    this.showSceneToast(`已导出 JSON（建议覆盖 ${SCENE_MAP_LOCAL_JSON_HINT}）`, 'success', 2600);
  }

  private findWallBlockByPoint(point: Point): WallBlock | null {
    for (let index = this.sceneMapData.wall_blocks.length - 1; index >= 0; index -= 1) {
      const block = this.sceneMapData.wall_blocks[index];
      if (this.pointInWallBlock(point, block)) {
        return block;
      }
    }
    return null;
  }

  private markWallEditorDirty(reason: string, showToast: boolean): void {
    this.wallEditorDirty = true;
    this.initializeWalkableMask();
    this.drawRooms();
    this.drawSceneMapLayers();
    this.drawWorkZones();
    if (showToast) {
      this.showSceneToast(`${reason}（未保存）`, 'info', 1200);
    }
  }

  private clampWallBlockInBounds(block: WallBlock): void {
    const maxWidth = this.sceneMapData.base_width;
    const maxHeight = this.sceneMapData.base_height;
    block.width = Math.max(EDITOR_WALL_MIN_SIZE, Math.min(maxWidth, block.width));
    block.height = Math.max(EDITOR_WALL_MIN_SIZE, Math.min(maxHeight, block.height));
    block.x = Math.max(0, Math.min(maxWidth - block.width, block.x));
    block.y = Math.max(0, Math.min(maxHeight - block.height, block.y));
  }

  private buildWallBlockFromShapePreset(point: Point, shape: WallShapeType): WallBlock {
    const nextId = createSceneEntityId('wall', this.sceneMapData.wall_blocks.map((item) => item.id));
    let width = Number(WALL_EDITOR_DEFAULT_SIZE.width);
    let height = Number(WALL_EDITOR_DEFAULT_SIZE.height);
    if (shape === 'square' || shape === 'circle') {
      width = 96;
      height = 96;
    } else if (shape === 'triangle' || shape === 'trapezoid') {
      width = 126;
      height = 96;
    }
    const x = Math.round(point.x - width / 2);
    const y = Math.round(point.y - height / 2);
    const roomId = this.findRoomByPoint(point)?.id ?? 'gateway';
    const block: WallBlock = {
      id: nextId,
      x,
      y,
      width,
      height,
      room_id: roomId,
      shape,
      rotation: 0
    };
    this.clampWallBlockInBounds(block);
    return block;
  }

  private deleteWallBlockById(wallId: string): boolean {
    const index = this.sceneMapData.wall_blocks.findIndex((wallBlock) => wallBlock.id === wallId);
    if (index === -1) {
      return false;
    }
    const [removed] = this.sceneMapData.wall_blocks.splice(index, 1);
    if (this.selectedWallBlockId === removed.id) {
      this.selectedWallBlockId = null;
    }
    this.markWallEditorDirty(`删除墙壁 ${removed.id}`, true);
    return true;
  }

  private deleteFurnitureAt(point: Point): boolean {
    const furniture = this.findFurnitureByPoint(point);
    if (!furniture) {
      return false;
    }
    return this.deleteFurnitureById(furniture.id);
  }

  private deleteFurnitureById(furnitureId: string): boolean {
    const index = this.sceneMapData.furnitures.findIndex((item) => item.id === furnitureId);
    if (index === -1) {
      return false;
    }
    const [removed] = this.sceneMapData.furnitures.splice(index, 1);
    if (this.selectedFurnitureId === removed.id) {
      this.selectedFurnitureId = null;
    }
    this.persistSceneMap(`删除家具 ${removed.id}`);
    return true;
  }

  private deleteInteractionPointAt(point: Point, options: { persist?: boolean } = {}): boolean {
    const index = this.sceneMapData.interaction_points.findIndex((interactionPoint) => {
      const dx = interactionPoint.x - point.x;
      const dy = interactionPoint.y - point.y;
      return dx * dx + dy * dy <= (INTERACTION_POINT_RADIUS + 6) * (INTERACTION_POINT_RADIUS + 6);
    });
    if (index === -1) {
      return false;
    }
    const [removed] = this.sceneMapData.interaction_points.splice(index, 1);
    this.selectedInteractionPointId = this.selectedInteractionPointId === removed.id ? null : this.selectedInteractionPointId;
    this.ensureInteractionSelection();
    if (options.persist === false) {
      this.syncWorkZonesFromInteractionPoints({ refreshWorkZoneLayer: true });
      this.drawSceneMapLayers();
    } else {
      this.persistSceneMap(`删除互动点 ${removed.id}`);
    }
    return true;
  }

  private deleteInteractionBoxAt(point: Point, options: { persist?: boolean } = {}): boolean {
    const hitBox = this.findInteractionBoxByPoint(point);
    if (!hitBox) {
      return false;
    }
    const index = this.sceneMapData.interaction_boxes.findIndex((item) => item.id === hitBox.id);
    if (index === -1) {
      return false;
    }
    const [removed] = this.sceneMapData.interaction_boxes.splice(index, 1);
    if (this.selectedInteractionBoxId === removed.id) {
      this.selectedInteractionBoxId = null;
    }
    this.ensureInteractionSelection();
    if (options.persist === false) {
      this.drawSceneMapLayers();
    } else {
      this.persistSceneMap(`删除交互框 ${removed.id}`);
    }
    return true;
  }

  private placeFurnitureAt(point: Point): void {
    const nextId = createSceneEntityId('furniture', this.sceneMapData.furnitures.map((item) => item.id));
    const roomId = this.findRoomByPoint(point)?.id ?? 'gateway';
    const template = this.furniturePlacementTemplate;
    const width = Math.max(24, Math.round(template?.width ?? DEFAULT_FURNITURE_SIZE.width));
    const height = Math.max(24, Math.round(template?.height ?? DEFAULT_FURNITURE_SIZE.height));
    const clamped = this.clampFurniturePosition(
      Math.round(point.x - width / 2),
      Math.round(point.y - height / 2),
      width,
      height
    );
    const x = clamped.x;
    const y = clamped.y;
    const interactionType = FURNITURE_INTERACTION_TYPES[this.editorInteractionTypeCursor % FURNITURE_INTERACTION_TYPES.length];
    const spriteDirections = template?.directions
      ? {
        front: template.directions.front,
        left: template.directions.left,
        right: template.directions.right,
        back: template.directions.back
      }
      : undefined;
    const furniture: FurnitureItem = {
      id: nextId,
      type: template?.category || 'custom',
      label: template?.label || nextId,
      room_id: roomId,
      x,
      y,
      width,
      height,
      sprite_key: template?.spriteKey || '',
      blocking: true,
      interactive: true,
      interaction_type: interactionType,
      z_index: y + height,
      direction: template?.direction || 'front',
      sprite_directions: spriteDirections,
      asset_id: template?.assetId || '',
      category: template?.category || ''
    };
    this.sceneMapData.furnitures.push(furniture);
    this.selectedFurnitureId = furniture.id;
    this.persistSceneMap(`新增家具 ${nextId}`);
  }

  private clampFurniturePosition(rawX: number, rawY: number, width: number, height: number): { x: number; y: number } {
    const maxX = this.sceneMapData.base_width - width;
    const maxY = this.sceneMapData.base_height - height;
    const minY = -Math.round(height * FURNITURE_EDITOR_TOP_SLACK_RATIO);
    const x = Math.round(Math.max(0, Math.min(maxX, rawX)));
    const y = Math.round(Math.max(minY, Math.min(maxY, rawY)));
    return { x, y };
  }

  private placeInteractionPointAt(point: Point, options: { persist?: boolean } = {}): void {
    const nextId = createSceneEntityId('interaction', this.sceneMapData.interaction_points.map((item) => item.id));
    const roomId = this.findRoomByPoint(point)?.id ?? 'gateway';
    const interactionPoint: SceneInteractionPoint = {
      id: nextId,
      type: 'custom',
      label: nextId,
      room_id: roomId,
      x: Math.round(point.x),
      y: Math.round(point.y),
      anchor_x: Math.round(point.x),
      anchor_y: Math.round(point.y),
      interaction_type: 'inspect'
    };
    this.sceneMapData.interaction_points.push(interactionPoint);
    this.selectedInteractionPointId = interactionPoint.id;
    this.selectedInteractionBoxId = null;
    if (options.persist === false) {
      this.syncWorkZonesFromInteractionPoints({ refreshWorkZoneLayer: true });
      this.drawSceneMapLayers();
    } else {
      this.persistSceneMap(`新增互动点 ${nextId}`);
    }
  }

  private placeInteractionBoxAt(point: Point, options: { persist?: boolean } = {}): void {
    const nextId = createSceneEntityId('interaction-box', this.sceneMapData.interaction_boxes.map((item) => item.id));
    const width = 132;
    const height = 82;
    const roomId = this.findRoomByPoint(point)?.id ?? 'gateway';
    const x = Phaser.Math.Clamp(Math.round(point.x - width / 2), 0, Math.max(0, this.sceneMapData.base_width - width));
    const y = Phaser.Math.Clamp(Math.round(point.y - height / 2), 0, Math.max(0, this.sceneMapData.base_height - height));
    const interactionBox: InteractionBox = {
      id: nextId,
      label: nextId,
      room_id: roomId,
      x,
      y,
      width,
      height,
      interaction_name: '默认交互',
      interaction_type: 'inspect'
    };
    this.sceneMapData.interaction_boxes.push(interactionBox);
    this.selectedInteractionBoxId = interactionBox.id;
    this.selectedInteractionPointId = null;
    if (options.persist === false) {
      this.drawSceneMapLayers();
    } else {
      this.persistSceneMap(`新增交互框 ${nextId}`);
    }
  }

  private toggleSelectedFurnitureBlocking(): void {
    if (!this.selectedFurnitureId) {
      return;
    }
    const selectedFurniture = this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId);
    if (!selectedFurniture) {
      return;
    }
    selectedFurniture.blocking = !selectedFurniture.blocking;
    this.persistSceneMap(`${selectedFurniture.id} blocking=${selectedFurniture.blocking}`);
  }

  private toggleSelectedFurnitureInteractive(): void {
    if (!this.selectedFurnitureId) {
      return;
    }
    const selectedFurniture = this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId);
    if (!selectedFurniture) {
      return;
    }
    selectedFurniture.interactive = !selectedFurniture.interactive;
    this.persistSceneMap(`${selectedFurniture.id} interactive=${selectedFurniture.interactive}`);
  }

  private cycleSelectedFurnitureInteractionType(): void {
    if (!this.selectedFurnitureId) {
      return;
    }
    const selectedFurniture = this.sceneMapData.furnitures.find((item) => item.id === this.selectedFurnitureId);
    if (!selectedFurniture) {
      return;
    }
    const pool = [...FURNITURE_INTERACTION_TYPES];
    const currentIndex = pool.findIndex((entry) => entry === selectedFurniture.interaction_type);
    const nextIndex = currentIndex === -1 ? 0 : (currentIndex + 1) % pool.length;
    selectedFurniture.interaction_type = pool[nextIndex];
    this.editorInteractionTypeCursor = nextIndex;
    this.persistSceneMap(`${selectedFurniture.id} interaction_type=${selectedFurniture.interaction_type}`);
  }

  private normalizeFurnitureFacing(value: unknown): FurnitureFacing {
    const normalized = String(value ?? '').trim().toLowerCase();
    if (normalized === 'front' || normalized === 'left' || normalized === 'right' || normalized === 'back') {
      return normalized;
    }
    return 'front';
  }

  private shiftFurnitureFacing(current: FurnitureFacing, step: number): FurnitureFacing {
    const signedStep = step < 0 ? -1 : step > 0 ? 1 : 0;
    if (signedStep === 0) {
      return current;
    }
    const currentIndex = FURNITURE_FACING_TURN_ORDER.indexOf(current);
    const baseIndex = currentIndex === -1 ? 0 : currentIndex;
    const nextIndex = (baseIndex + signedStep + FURNITURE_FACING_TURN_ORDER.length) % FURNITURE_FACING_TURN_ORDER.length;
    return FURNITURE_FACING_TURN_ORDER[nextIndex];
  }

  private resolveFurnitureSpriteForFacing(furniture: FurnitureItem, facing: FurnitureFacing): string | null {
    const pool = furniture.sprite_directions;
    if (!pool) {
      return null;
    }
    const direct = String(pool[facing] || '').trim();
    if (direct) {
      return direct;
    }
    const front = String(pool.front || '').trim();
    return front || null;
  }

  private findFurnitureByPoint(point: Point): FurnitureItem | null {
    const sorted = [...this.sceneMapData.furnitures].sort((left, right) => {
      if (left.z_index !== right.z_index) {
        return right.z_index - left.z_index;
      }
      return right.id.localeCompare(left.id);
    });
    for (const furniture of sorted) {
      if (this.pointInRect(point, furniture)) {
        return furniture;
      }
    }
    return null;
  }

  private findInteractionPointByPoint(point: Point): SceneInteractionPoint | null {
    const maxDistance = INTERACTION_POINT_RADIUS + 6;
    for (const interactionPoint of this.sceneMapData.interaction_points) {
      const dx = interactionPoint.x - point.x;
      const dy = interactionPoint.y - point.y;
      if (dx * dx + dy * dy <= maxDistance * maxDistance) {
        return interactionPoint;
      }
    }
    return null;
  }

  private findInteractionBoxByPoint(point: Point): InteractionBox | null {
    for (let index = this.sceneMapData.interaction_boxes.length - 1; index >= 0; index -= 1) {
      const interactionBox = this.sceneMapData.interaction_boxes[index];
      if (this.pointInRect(point, interactionBox)) {
        return interactionBox;
      }
    }
    return null;
  }

  private pointInRect(point: Point, rect: SceneMapRect): boolean {
    return point.x >= rect.x
      && point.x <= rect.x + rect.width
      && point.y >= rect.y
      && point.y <= rect.y + rect.height;
  }

  private advanceLobster(deltaMs: number): void {
    if (this.lobsterRoute.length === 0) {
      this.resetPatrolProgressTracking();
      this.updateLobsterVisual(this.workMode === 'working' ? 'working' : 'idle');
      return;
    }

    if (this.workMode === 'moving') {
      const capturePoint = this.mainActorTriggerCenterPoint();
      if (this.suppressedActionAnchor) {
        const awayDistance = Phaser.Math.Distance.Between(
          capturePoint.x,
          capturePoint.y,
          this.suppressedActionAnchor.x,
          this.suppressedActionAnchor.y
        );
        if (awayDistance >= 104 || Date.now() >= this.suppressedActionAnchorUntil) {
          this.suppressedActionAnchor = null;
          this.suppressedActionAnchorUntil = 0;
        }
      }
      const targetedCaptureMode = this.patrolTargetMode?.triggerAnchor && this.isModeCaptureReachable(capturePoint, this.patrolTargetMode)
        ? this.patrolTargetMode
        : null;
      const captureMode = targetedCaptureMode ?? (!this.patrolTargetMode
        ? this.findCapturableActionMode(capturePoint, this.resolvePatrolActionModes())
        : null);
      if (captureMode?.triggerAnchor) {
        this.patrolTargetMode = captureMode;
        this.lobsterRoute = [];
        const zoneId = this.resolvePatrolRoomId(captureMode) ?? this.focusResourceId;
        this.startWorking(zoneId);
        return;
      }
    }

    const target = this.lobsterRoute[0];
    // Speed scales with context remaining: full HP = 0.32, near-empty = 0.098 (sub-agent speed)
    const maxSpeed = 0.32;
    const minSpeed = 0.098;
    const hp = this.lobsterContextRemaining ?? 1; // 0–1
    const speedPerMs = minSpeed + (maxSpeed - minSpeed) * hp;
    const step = speedPerMs * deltaMs;

    const dx = target.x - this.lobster.x;
    const dy = target.y - this.lobster.y;
    const distance = Math.hypot(dx, dy);
    if (distance > 0.001) {
      this.actorFacing = this.resolveDirectionFromVector(dx, dy, this.actorFacing);
    }

    if (this.lobsterBody instanceof Phaser.GameObjects.Sprite) {
      this.lobsterBody.setFlipX(this.variantUsesDirectionalWalk() ? false : dx < 0);
    }

    if (distance <= step) {
      this.lobster.x = Math.round(target.x);
      this.lobster.y = Math.round(target.y);
      this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
      this.notePatrolProgress();
      this.lobsterRoute.shift();

      if (this.lobsterRoute.length === 0 && this.workMode === 'moving') {
        if (this.patrolTargetMode?.triggerAnchor) {
          const capturePoint = this.mainActorTriggerCenterPoint();
          if (this.isModeCaptureReachable(capturePoint, this.patrolTargetMode)) {
            this.snapContainerToModeAnchor(
              this.lobster,
              this.lobsterBody instanceof Phaser.GameObjects.Sprite ? this.lobsterBody : null,
              this.patrolTargetMode
            );
            this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
            const zoneId = this.resolvePatrolRoomId(this.patrolTargetMode) ?? this.focusResourceId;
            this.startWorking(zoneId);
          } else {
            const nearbyMode = this.findCapturableActionMode(capturePoint, this.resolvePatrolActionModes());
            if (nearbyMode?.triggerAnchor) {
              this.patrolTargetMode = nearbyMode;
              this.snapContainerToModeAnchor(
                this.lobster,
                this.lobsterBody instanceof Phaser.GameObjects.Sprite ? this.lobsterBody : null,
                nearbyMode
              );
              this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
              const zoneId = this.resolvePatrolRoomId(nearbyMode) ?? this.focusResourceId;
              this.startWorking(zoneId);
              return;
            }
            const fallbackDistance = Phaser.Math.Distance.Between(
              capturePoint.x,
              capturePoint.y,
              this.patrolTargetMode.triggerAnchor.x,
              this.patrolTargetMode.triggerAnchor.y
            );
            if (fallbackDistance <= PATROL_ACTION_TARGET_MAX_OFFSET + 40) {
              this.snapContainerToModeAnchor(
                this.lobster,
                this.lobsterBody instanceof Phaser.GameObjects.Sprite ? this.lobsterBody : null,
                this.patrolTargetMode
              );
              this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
              const zoneId = this.resolvePatrolRoomId(this.patrolTargetMode) ?? this.focusResourceId;
              this.startWorking(zoneId);
              return;
            }
            this.suppressedActionAnchor = {
              x: Math.round(this.patrolTargetMode.triggerAnchor.x),
              y: Math.round(this.patrolTargetMode.triggerAnchor.y)
            };
            this.suppressedActionAnchorUntil = Date.now() + 2600;
            this.workMode = 'idle';
            this.activeZoneId = null;
            this.pendingStateProfile = null;
            this.pendingRouteContext = null;
            this.patrolTargetMode = null;
            this.currentActionMode = null;
            this.clearZoneStates();
            this.drawWorkZones();
            this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
              resourceId: this.focusResourceId,
              detailOverride: 'patrol reroute: target anchor not capturable'
            });
            this.updateLobsterVisual('idle');
            this.syncWorkStatus();
            this.maybeProcessTelemetryQueue();
          }
        } else {
          const capturePoint = this.mainActorTriggerCenterPoint();
          const captureMode = this.findCapturableActionMode(capturePoint, this.resolvePatrolActionModes());
          if (captureMode?.triggerAnchor) {
            this.patrolTargetMode = captureMode;
            const zoneId = this.resolvePatrolRoomId(captureMode) ?? this.focusResourceId;
            this.startWorking(zoneId);
            return;
          }
          this.workMode = 'idle';
          this.activeZoneId = null;
          this.pendingStateProfile = null;
          this.pendingRouteContext = null;
          this.patrolTargetMode = null;
          this.currentActionMode = null;
          this.clearZoneStates();
          this.drawWorkZones();
          this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
            resourceId: this.focusResourceId,
            detailOverride: 'patrol segment completed'
          });
          this.updateLobsterVisual('idle');
          this.syncWorkStatus();
          this.maybeProcessTelemetryQueue();
        }
      } else if (this.lobsterRoute.length === 0 && !this.activeZoneId) {
        this.workMode = 'idle';
        this.currentActionMode = null;
        this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
          resourceId: this.focusResourceId,
          detailOverride: 'manual route completed'
        });
        this.updateLobsterVisual('idle');
        this.syncWorkStatus();
        this.maybeProcessTelemetryQueue();
      }
      return;
    }

    this.lobster.x = Math.round(this.lobster.x + (dx / distance) * step);
    this.lobster.y = Math.round(this.lobster.y + (dy / distance) * step);
    this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
    this.notePatrolProgress();
    this.updateLobsterVisual('moving');
  }

  private startWorking(zoneId: ResourcePartitionId): void {
    const targetMode = this.patrolTargetMode;
    if (!targetMode?.triggerAnchor) {
      this.workMode = 'idle';
      this.activeZoneId = null;
      this.pendingStateProfile = null;
      this.pendingRouteContext = null;
      this.syncWorkStatus();
      this.maybeProcessTelemetryQueue();
      return;
    }

    const mappedZoneId = this.resolvePatrolRoomId(targetMode) ?? zoneId;

    this.clearZoneStates();
    this.zoneState.set(mappedZoneId, 'working');
    this.drawWorkZones();
    this.resetPatrolProgressTracking();

    this.workMode = 'working';
    this.activeZoneId = mappedZoneId;
    this.lastReachedZoneId = mappedZoneId;
    this.currentActionMode = targetMode;

    const zone = this.protocols.mapLogic.workZones.find((item) => item.id === mappedZoneId);
    const profile = zone ? this.pendingStateProfile ?? this.pickStateProfile(zone.type) : this.resolveStateProfile('executing');
    const routeContext = this.pendingRouteContext ?? {
      resourceId: mappedZoneId,
      detail: zone ? `accessing ${zone.label.toLowerCase()}` : 'running action'
    };

    this.lastOutput = this.materializeOutput(profile, {
      resourceId: routeContext.resourceId,
      detailOverride: routeContext.detail
    });
    this.updateLobsterVisual('working', targetMode);
    // Final correction: snap once after switching visual mode to guarantee exact anchor lock.
    this.snapContainerToModeAnchor(this.lobster, this.lobsterBody instanceof Phaser.GameObjects.Sprite ? this.lobsterBody : null, targetMode);
    this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
    this.updateResourceAnimations();
    this.syncWorkStatus();
    this.resetPrimaryAgentPoseFx();

    if (ENABLE_PRIMARY_AGENT_POSE_FX) {
      const activeTextureKey =
        this.lobsterBody instanceof Phaser.GameObjects.Sprite
          ? this.lobsterBody.texture.key.toLowerCase()
          : '';
      const isCalmPose = activeTextureKey.includes('sit') || activeTextureKey.includes('sleep');
      if (!isCalmPose) {
        this.tweens.add({
          targets: this.lobster,
          scaleX: { from: 1, to: 1.08 },
          scaleY: { from: 1, to: 1.08 },
          yoyo: true,
          duration: 260,
          repeat: mappedZoneId === 'break_room' ? 5 : 3,
          ease: 'Sine.InOut'
        });
      }

      if (/(alert|blocked|failed|error|alarm)/i.test(this.lastOutput.content)) {
        this.tweens.add({
          targets: this.lobster,
          angle: { from: -4, to: 4 },
          yoyo: true,
          repeat: 7,
          duration: 80,
          ease: 'Sine.InOut'
        });
      }
    }

    this.time.delayedCall(mappedZoneId === 'break_room' ? 2100 : 1500, () => this.finishWorking(mappedZoneId));
  }

  private finishWorking(zoneId: ResourcePartitionId): void {
    this.clearZoneStates();
    this.zoneState.set(zoneId, 'done');
    this.drawWorkZones();
    this.resetPatrolProgressTracking();

    this.activeZoneId = null;
    this.pendingStateProfile = null;
    this.pendingRouteContext = null;
    if (this.currentActionMode?.triggerAnchor) {
      this.lastCompletedActionAnchor = {
        x: Math.round(this.currentActionMode.triggerAnchor.x),
        y: Math.round(this.currentActionMode.triggerAnchor.y)
      };
      this.suppressedActionAnchor = { ...this.lastCompletedActionAnchor };
      this.suppressedActionAnchorUntil = Date.now() + 4200;
    }
    this.patrolTargetMode = null;
    this.workMode = 'idle';

    const zone = this.protocols.mapLogic.workZones.find((item) => item.id === zoneId);
    const completionProfile = zone ? this.pickStateProfile(zone.type) : this.resolveStateProfile('documenting');
    this.lastOutput = this.materializeOutput(completionProfile, {
      resourceId: zoneId,
      detailOverride: `access completed in ${this.zoneLabel(zoneId)}`
    });

    this.celebrationUntil = Date.now() + 2200;
    this.updateLobsterVisual('idle');
    this.updateResourceAnimations();
    this.syncWorkStatus();
    this.resetPrimaryAgentPoseFx();

    if (ENABLE_PRIMARY_AGENT_POSE_FX) {
      this.tweens.add({
        targets: this.lobster,
        y: { from: this.lobster.y, to: this.lobster.y - 10 },
        yoyo: true,
        duration: 180,
        repeat: 1,
        ease: 'Quad.Out'
      });
    }

    this.time.delayedCall(900, () => {
      this.clearZoneStates();
      this.drawWorkZones();
      this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
        resourceId: this.focusResourceId,
        detailOverride: 'waiting for the next access'
      });
      this.syncWorkStatus();
      this.maybeProcessTelemetryQueue();
    });
  }

  private notePatrolProgress(): void {
    if (!this.lobster) {
      return;
    }
    this.patrolLastProgressPoint = { x: Math.round(this.lobster.x), y: Math.round(this.lobster.y) };
    this.patrolLastProgressAt = Date.now();
  }

  private resetPatrolProgressTracking(): void {
    this.patrolLastProgressPoint = null;
    this.patrolLastProgressAt = 0;
    this.patrolStuckRecoveryAttempts = 0;
  }

  private isModeCaptureReachable(capturePoint: Point, mode: ActorVariantDef['modes'][number]): boolean {
    if (!mode.triggerAnchor) {
      return false;
    }
    const baseRadius = Math.max(32, mode.triggerRadius ?? 76);
    const captureRadius = Phaser.Math.Clamp(
      baseRadius + 30,
      PATROL_ACTION_CAPTURE_RADIUS_MIN,
      PATROL_ACTION_CAPTURE_RADIUS_MAX
    );
    const distance = Phaser.Math.Distance.Between(
      capturePoint.x,
      capturePoint.y,
      mode.triggerAnchor.x,
      mode.triggerAnchor.y
    );
    return distance <= captureRadius;
  }

  private monitorPatrolStuckState(): void {
    if (!this.lobster || this.workMode !== 'moving' || this.lobsterRoute.length === 0) {
      this.resetPatrolProgressTracking();
      return;
    }

    const now = Date.now();
    const current = { x: Math.round(this.lobster.x), y: Math.round(this.lobster.y) };
    if (!this.patrolLastProgressPoint) {
      this.patrolLastProgressPoint = current;
      this.patrolLastProgressAt = now;
      return;
    }
    const movedDistance = Phaser.Math.Distance.Between(
      current.x,
      current.y,
      this.patrolLastProgressPoint.x,
      this.patrolLastProgressPoint.y
    );
    if (movedDistance >= PATROL_STUCK_DISTANCE_THRESHOLD) {
      this.patrolLastProgressPoint = current;
      this.patrolLastProgressAt = now;
      this.patrolStuckRecoveryAttempts = 0;
      return;
    }
    if (now - this.patrolLastProgressAt < PATROL_STUCK_TIMEOUT_MS) {
      return;
    }

    if (this.tryRecoverStuckPatrolRoute()) {
      return;
    }
    this.recoverPrimaryAgentToSpawn('patrol stuck reset to stand-front');
  }

  private tryRecoverStuckPatrolRoute(): boolean {
    if (!this.lobster || this.patrolStuckRecoveryAttempts >= PATROL_STUCK_MAX_RECOVERY_ATTEMPTS) {
      return false;
    }
    this.patrolStuckRecoveryAttempts += 1;

    const actorOrigin = this.resolvePatrolWalkableOrigin({ x: this.lobster.x, y: this.lobster.y })
      ?? this.resolvePatrolWalkableOrigin(this.mainActorTriggerCenterPoint());
    if (!actorOrigin) {
      this.patrolLastProgressAt = Date.now();
      return this.patrolStuckRecoveryAttempts < PATROL_STUCK_MAX_RECOVERY_ATTEMPTS;
    }

    if (this.patrolTargetMode?.triggerAnchor) {
      const targetPoint = this.resolveActionAnchorPatrolTarget(this.patrolTargetMode.triggerAnchor);
      if (targetPoint) {
        const route = this.computeMaskRoute(actorOrigin, targetPoint);
        if (route && route.length > 0) {
          this.lobsterRoute = route;
          this.notePatrolProgress();
          return true;
        }
      }
    }

    const actionPlan = this.pickActionPointPatrolPlan(actorOrigin);
    if (actionPlan) {
      this.patrolTargetMode = actionPlan.mode;
      this.lobsterRoute = actionPlan.route;
      this.notePatrolProgress();
      return true;
    }

    const hasActionModes = this.resolvePatrolActionModes().some((mode) => Boolean(mode.triggerAnchor));
    if (!hasActionModes) {
      const targetPoint = this.pickRandomReachablePatrolTarget(actorOrigin);
      if (targetPoint) {
        const route = this.computeMaskRoute(actorOrigin, targetPoint);
        if (route && route.length > 0) {
          this.patrolTargetMode = null;
          this.lobsterRoute = route;
          this.notePatrolProgress();
          return true;
        }
      }
    }

    this.patrolLastProgressAt = Date.now();
    return this.patrolStuckRecoveryAttempts < PATROL_STUCK_MAX_RECOVERY_ATTEMPTS;
  }

  private recoverPrimaryAgentToSpawn(detail: string): void {
    if (!this.lobster) {
      return;
    }
    const spawnIdleMode = this.resolveSpawnIdleMode();
    const spawnAnchor = spawnIdleMode?.triggerAnchor
      ? { x: Math.round(spawnIdleMode.triggerAnchor.x), y: Math.round(spawnIdleMode.triggerAnchor.y) }
      : null;
    const fallback = this.resolvePatrolWalkableOrigin({ x: this.lobster.x, y: this.lobster.y })
      ?? { x: this.lobster.x, y: this.lobster.y };
    const spawnPoint = spawnAnchor
      ? (this.resolveRequestedWalkTarget(spawnAnchor, 260) ?? spawnAnchor)
      : fallback;

    this.lobsterRoute = [];
    this.workMode = 'idle';
    this.activeZoneId = null;
    this.pendingStateProfile = null;
    this.pendingRouteContext = null;
    this.patrolTargetMode = null;
    this.currentActionMode = spawnIdleMode ?? null;
    this.clearZoneStates();
    this.drawWorkZones();
    this.lobster.x = Math.round(spawnPoint.x);
    this.lobster.y = Math.round(spawnPoint.y);
    this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
    this.lastMainVisualKey = null;
    this.updateLobsterVisual('idle', spawnIdleMode ?? undefined);
    this.lastOutput = this.materializeOutput(this.resolveStateProfile('idle'), {
      resourceId: this.focusResourceId,
      detailOverride: detail
    });
    this.patrolCooldownUntil = Date.now() + 1200;
    this.resetPatrolProgressTracking();
    this.syncWorkStatus();
  }

  private sameAnchorPoint(left: Point | null, right: Point | null, tolerance = 18): boolean {
    if (!left || !right) {
      return false;
    }
    return Phaser.Math.Distance.Between(left.x, left.y, right.x, right.y) <= tolerance;
  }

  private findCapturableActionMode(
    capturePoint: Point,
    actionModes: ActorVariantDef['modes'][number][]
  ): ActorVariantDef['modes'][number] | null {
    const candidates = actionModes.filter((mode) => Boolean(mode.triggerAnchor));
    if (candidates.length === 0) {
      return null;
    }

    const hasAlternativeAnchor = this.lastCompletedActionAnchor
      ? candidates.some((mode) => !this.sameAnchorPoint(mode.triggerAnchor ?? null, this.lastCompletedActionAnchor))
      : false;

    const pickNearest = (allowSameAnchor: boolean): ActorVariantDef['modes'][number] | null => {
      let best: { mode: ActorVariantDef['modes'][number]; distance: number } | null = null;
      for (const mode of candidates) {
        if (!mode.triggerAnchor) {
          continue;
        }
        if (
          this.suppressedActionAnchor
          && Date.now() < this.suppressedActionAnchorUntil
          && this.sameAnchorPoint(mode.triggerAnchor, this.suppressedActionAnchor)
        ) {
          continue;
        }
        if (!allowSameAnchor && hasAlternativeAnchor && this.sameAnchorPoint(mode.triggerAnchor, this.lastCompletedActionAnchor)) {
          continue;
        }
        const baseRadius = Math.max(32, mode.triggerRadius ?? 76);
        const distance = Phaser.Math.Distance.Between(
          capturePoint.x,
          capturePoint.y,
          mode.triggerAnchor.x,
          mode.triggerAnchor.y
        );
        const captureRadius = Phaser.Math.Clamp(
          baseRadius + 24,
          PATROL_ACTION_CAPTURE_RADIUS_MIN,
          PATROL_ACTION_CAPTURE_RADIUS_MAX
        );
        if (distance > captureRadius) {
          continue;
        }
        if (!best || distance < best.distance) {
          best = { mode, distance };
        }
      }
      return best?.mode ?? null;
    };

    return pickNearest(false) ?? pickNearest(true);
  }

  private pickRandomReachablePatrolTarget(origin: Point): Point | null {
    if (!this.walkableGrid || this.walkableGridCols <= 0 || this.walkableGridRows <= 0) {
      return this.pickRandomWalkablePatrolTarget(origin);
    }

    this.initializeReachableWalkableGrid(origin);
    if (!this.reachableWalkableGrid) {
      return this.pickRandomWalkablePatrolTarget(origin);
    }

    const minDistance = 140;
    const reachableIndices: number[] = [];
    for (let index = 0; index < this.reachableWalkableGrid.length; index += 1) {
      if (this.reachableWalkableGrid[index] === 1) {
        reachableIndices.push(index);
      }
    }
    if (reachableIndices.length === 0) {
      return this.pickRandomWalkablePatrolTarget(origin);
    }
    let fallback: { point: Point; distance: number } | null = null;

    for (let attempt = 0; attempt < 140; attempt += 1) {
      const index = reachableIndices[Phaser.Math.Between(0, reachableIndices.length - 1)];
      const col = index % this.walkableGridCols;
      const row = Math.floor(index / this.walkableGridCols);
      const point = this.gridToScenePoint(col, row);
      const distance = Phaser.Math.Distance.Between(origin.x, origin.y, point.x, point.y);
      if (!fallback || distance > fallback.distance) {
        fallback = { point, distance };
      }
      if (distance < minDistance) {
        continue;
      }
      if (this.lastCompletedActionAnchor && this.sameAnchorPoint(point, this.lastCompletedActionAnchor, 64)) {
        continue;
      }
      return point;
    }

    if (fallback && fallback.distance >= 36) {
      return fallback.point;
    }
    return this.pickRandomWalkablePatrolTarget(origin, 80);
  }

  private resolveActionAnchorPatrolTarget(anchor: Point): Point | null {
    const direct = this.resolveRequestedWalkTarget(anchor, PATROL_ACTION_TARGET_MAX_OFFSET);
    if (direct) {
      return direct;
    }
    const nearest = this.findNearestWalkablePoint(anchor, PATROL_ACTION_TARGET_MAX_OFFSET);
    if (!nearest) {
      return null;
    }
    const distance = Phaser.Math.Distance.Between(anchor.x, anchor.y, nearest.x, nearest.y);
    return distance <= PATROL_ACTION_TARGET_MAX_OFFSET ? nearest : null;
  }

  private shuffledPatrolActionModes(): ActorVariantDef['modes'][number][] {
    const pool = this.resolvePatrolActionModes().filter((mode) => Boolean(mode.triggerAnchor));
    for (let index = pool.length - 1; index > 0; index -= 1) {
      const swapIndex = Phaser.Math.Between(0, index);
      const temp = pool[index];
      pool[index] = pool[swapIndex];
      pool[swapIndex] = temp;
    }
    return pool;
  }

  private pickActionPointPatrolPlan(origin: Point): {
    mode: ActorVariantDef['modes'][number];
    route: Point[];
    targetPoint: Point;
  } | null {
    const candidates = this.shuffledPatrolActionModes();
    if (candidates.length === 0) {
      return null;
    }
    const hasAlternativeAnchor = this.lastCompletedActionAnchor
      ? candidates.some((mode) => !this.sameAnchorPoint(mode.triggerAnchor ?? null, this.lastCompletedActionAnchor))
      : false;

    const tryPick = (allowSameAnchor: boolean): {
      mode: ActorVariantDef['modes'][number];
      route: Point[];
      targetPoint: Point;
    } | null => {
      for (const candidate of candidates) {
        if (!candidate.triggerAnchor) {
          continue;
        }
        if (
          this.suppressedActionAnchor
          && Date.now() < this.suppressedActionAnchorUntil
          && this.sameAnchorPoint(candidate.triggerAnchor, this.suppressedActionAnchor)
        ) {
          continue;
        }
        if (!allowSameAnchor && hasAlternativeAnchor && this.sameAnchorPoint(candidate.triggerAnchor, this.lastCompletedActionAnchor)) {
          continue;
        }
        const targetPoint = this.resolveActionAnchorPatrolTarget(candidate.triggerAnchor);
        if (!targetPoint) {
          continue;
        }
        const route = this.computeMaskRoute(origin, targetPoint);
        if (!route || route.length === 0) {
          continue;
        }
        return { mode: candidate, route, targetPoint };
      }
      return null;
    };

    return tryPick(false) ?? tryPick(true);
  }

  private scheduleDeterministicPatrol(): void {
    const now = Date.now();
    if (now < this.patrolCooldownUntil) {
      return;
    }

    const actorCenter = { x: this.lobster.x, y: this.lobster.y };
    const actorOrigin = this.resolvePatrolWalkableOrigin(actorCenter)
      ?? this.resolvePatrolWalkableOrigin(this.mainActorTriggerCenterPoint())
      ?? actorCenter;
    if (!this.isWalkablePoint(actorCenter)) {
      this.lobster.x = Math.round(actorOrigin.x);
      this.lobster.y = Math.round(actorOrigin.y);
      this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
    }
    const hasActionModes = this.resolvePatrolActionModes().some((mode) => Boolean(mode.triggerAnchor));
    const actionPlan = this.pickActionPointPatrolPlan(actorOrigin);
    const patrolTarget = actionPlan?.targetPoint ?? (!hasActionModes ? this.pickRandomReachablePatrolTarget(actorOrigin) : null);
    const route = actionPlan?.route ?? (patrolTarget ? this.computeMaskRoute(actorOrigin, patrolTarget) : null);
    if (!patrolTarget || !route || route.length === 0) {
      this.patrolCooldownUntil = now + (hasActionModes ? 560 : 1000);
      return;
    }

    const targetRoomId = actionPlan?.mode
      ? (this.resolvePatrolRoomId(actionPlan.mode) ?? this.findRoomByPoint(patrolTarget)?.id ?? this.focusResourceId)
      : (this.findRoomByPoint(patrolTarget)?.id ?? this.focusResourceId);
    this.patrolTargetMode = actionPlan?.mode ?? null;
    this.clearZoneStates();
    this.zoneState.set(targetRoomId, 'moving');
    this.drawWorkZones();
    this.activeZoneId = targetRoomId;
    this.workMode = 'moving';
    this.currentActionMode = null;
    this.pendingStateProfile = this.resolveStateProfile('executing');
    this.pendingRouteContext = {
      resourceId: targetRoomId,
      detail: `patrolling ${this.zoneLabel(targetRoomId)}`
    };
    this.lastOutput = this.materializeOutput(this.pendingStateProfile, {
      resourceId: targetRoomId,
      detailOverride: this.pendingRouteContext.detail
    });
    this.lobsterRoute = route;
    this.notePatrolProgress();
    this.patrolCooldownUntil = now + Phaser.Math.Between(1500, 2600);
    this.updateLobsterVisual('moving');
    this.syncWorkStatus();
  }

  private maybeProcessTelemetryQueue(): void {
    if (this.workMode === 'working' || this.workMode === 'moving' || this.lobsterRoute.length > 0) {
      return;
    }
    if (Date.now() < this.celebrationUntil) {
      return;
    }
    if (this.workMode === 'idle' && this.activeZoneId && !this.patrolTargetMode) {
      this.activeZoneId = null;
    }
    this.scheduleDeterministicPatrol();
  }

  private clearZoneStates(): void {
    for (const zone of this.protocols.mapLogic.workZones) {
      this.zoneState.set(zone.id, 'idle');
    }
  }

  private syncWorkStatus(): void {
    const activeZone = this.activeZoneId
      ? this.zoneLabel(this.activeZoneId)
      : this.lastReachedZoneId
        ? this.zoneLabel(this.lastReachedZoneId)
        : 'None';

    this.workStatusText.setText(
      [
        `state: ${this.lastOutput.stateLabel} · ${this.workMode}`,
        `zone: ${activeZone} · focus ${this.zoneLabel(this.focusResourceId)}`,
        `feed: ${this.liveMode} · queue ${this.telemetryQueue.length} · update ${this.formatClock(this.lastTelemetryAt)}`,
        `detail: ${this.lastOutput.content}`
      ].join('\n')
    );
    this.syncThoughtBubble();
  }

  private syncThoughtBubble(): void {
    if (!ENABLE_PRIMARY_AGENT_THOUGHT_BUBBLE) {
      this.lobsterThoughtText.setVisible(false);
      this.positionThoughtBubble();
      return;
    }
    this.lobsterThoughtText.setVisible(true);

    const lowerDetail = this.lastOutput.content.toLowerCase();
    const isAlertish = /(alert|blocked|failed|error|panic|alarm)/.test(lowerDetail);
    const isHappyMoment = Date.now() < this.celebrationUntil || /completed|done|access completed/.test(lowerDetail);

    // If we have a live focusDetail from auto-focus / snapshot, show it directly
    // instead of the generic hardcoded text. Trim to fit in the bubble.
    if (this.focusDetail && this.focusDetail.trim().length > 0 && this.focusResourceId !== 'break_room') {
      const detail = this.focusDetail.trim();
      // Split at ~28 chars on a word boundary for a two-line bubble
      const maxLen = 28;
      let line1 = detail;
      let line2 = '';
      if (detail.length > maxLen) {
        const splitIdx = detail.lastIndexOf(' ', maxLen);
        if (splitIdx > 0) {
          line1 = detail.slice(0, splitIdx);
          line2 = detail.slice(splitIdx + 1).slice(0, maxLen);
        } else {
          line1 = detail.slice(0, maxLen);
          line2 = detail.slice(maxLen, maxLen * 2);
        }
      }
      this.lobsterThoughtText.setText(line2 ? `${line1}\n${line2}` : line1);
      this.positionThoughtBubble();
      return;
    }

    let lines: string[];
    if (this.workMode === 'moving') {
      lines = this.locale === 'zh'
        ? ['出发啦', '路由切换中']
        : ['On my way', 'route engaged'];
    } else if (this.workMode === 'working' && isAlertish) {
      lines = this.locale === 'zh'
        ? ['抓狂中', '别慌我来修']
        : ['Mild panic', 'I can fix this'];
    } else if (this.workMode === 'working') {
      lines = this.locale === 'zh'
        ? ['认真工作', '处理中']
        : ['Deep focus', 'processing context'];
    } else if (isHappyMoment) {
      lines = this.locale === 'zh'
        ? ['搞定啦', '今天很开心']
        : ['Done!', 'tiny victory'];
    } else if (this.focusResourceId === 'break_room') {
      lines = this.locale === 'zh'
        ? ['静默待机', '等待下一任务']
        : ['Quiet standby', 'waiting for tasks'];
    } else if (isAlertish) {
      lines = this.locale === 'zh'
        ? ['糟糕怎么办', '先冷静一下']
        : ['Uh oh...', 'stay calm'];
    } else {
      lines = this.locale === 'zh'
        ? ['我在待命', '下一单是什么']
        : ['Standing by', 'what next?'];
    }

    this.lobsterThoughtText.setText(lines.join('\n'));
    this.positionThoughtBubble();
  }

    private positionThoughtBubble(): void {
    if (!this.lobster || !this.lobsterThoughtText) {
      return;
    }

    const bounds = this.lobster.getBounds();
    const nameTagBottom = bounds.top - 4;
    let bubbleY = bounds.top - 12;

    if (this.lobsterNameTag) {
      this.lobsterNameTag.setPosition(this.lobster.x, nameTagBottom);
      this.lobsterNameTag.setDepth(this.layerToDepth('fx_overlay') + 11);
      bubbleY = nameTagBottom - this.lobsterNameTag.height - PRIMARY_AGENT_BUBBLE_GAP_PX;
    }

    this.lobsterThoughtText.setPosition(this.lobster.x, bubbleY);
    this.lobsterThoughtText.setDepth(this.layerToDepth('fx_overlay') + 12);

    // Reposition the context bar below the thought label
    if (this.lobsterContextBar) {
      this.lobsterContextBar.setDepth(this.layerToDepth('fx_overlay', this.lobster.y) + 11);
      this.drawContextBar(this.lobsterContextRemaining);
    }
  }

  private findWorkZone(point: Point): WorkZone | null {
    for (const zone of this.protocols.mapLogic.workZones) {
      const dx = point.x - zone.anchor.x;
      const dy = point.y - zone.anchor.y;
      if (dx * dx + dy * dy <= zone.radius * zone.radius) {
        return zone;
      }
    }
    return null;
  }

  private findHitAsset(point: Point): AssetDef | null {
    if (this.hasSceneBaseArt()) {
      return null;
    }
    const visibleIds = computeVisibleAssetIds(this.protocols.assetManifest, this.growthState);

    for (const asset of this.protocols.assetManifest.assets) {
      if (!visibleIds.has(asset.id)) {
        continue;
      }
      if (pointInPolygon(point, asset.hitPolygon)) {
        return asset;
      }
    }

    return null;
  }

  private findRoomByPoint(point: Point) {
    return this.protocols.mapLogic.rooms.find((room) => {
      const [x, y, width, height] = room.bounds;
      return point.x >= x && point.x <= x + width && point.y >= y && point.y <= y + height;
    }) ?? null;
  }

  private isWalkablePoint(point: Point): boolean {
    const maskDecision = this.isWalkableByMask(point);
    if (maskDecision !== null) {
      return maskDecision;
    }
    const walkableZones = this.protocols.mapLogic.walkableZones ?? [];
    if (walkableZones.length === 0) {
      return true;
    }

    return walkableZones.some((zone) => zone.points.length >= 3 && pointInPolygon(point, zone.points));
  }

  private drawHitOverlay(asset: AssetDef): void {
    this.hitLayer.clear();
    this.hitLayer.fillStyle(PARTITION_COLORS[asset.roomId], 0.2);
    this.hitLayer.lineStyle(3, 0xe9f2ff, 0.95);

    this.hitLayer.beginPath();
    this.hitLayer.moveTo(asset.hitPolygon[0].x, asset.hitPolygon[0].y);
    for (let index = 1; index < asset.hitPolygon.length; index += 1) {
      this.hitLayer.lineTo(asset.hitPolygon[index].x, asset.hitPolygon[index].y);
    }
    this.hitLayer.closePath();
    this.hitLayer.fillPath();
    this.hitLayer.strokePath();
  }

  private applyGrowthState(): void {
    if (this.hasSceneBaseArt()) {
      for (const asset of this.renderedAssets) {
        asset.body.setVisible(false);
      }
      return;
    }

    const visibleAssetIds = computeVisibleAssetIds(this.protocols.assetManifest, this.growthState);

    for (const asset of this.renderedAssets) {
      const shouldShow = visibleAssetIds.has(asset.def.id);
      asset.body.setVisible(shouldShow);
      if (shouldShow) {
        this.tweens.add({
          targets: asset.body,
          scaleX: { from: 0.85, to: 1 },
          scaleY: { from: 0.85, to: 1 },
          alpha: { from: 0.3, to: 1 },
          duration: 260,
          ease: 'Sine.Out'
        });
      }
    }
  }

  private updateResourceAnimations(): void {
    const activeResource = this.activeZoneId;
    for (const asset of this.renderedAssets) {
      const telemetry = this.telemetryResources.get(asset.def.roomId);
      const isActive = activeResource === asset.def.roomId || telemetry?.status === 'active' || telemetry?.status === 'alert';
      if (isActive) {
        if (!asset.pulseTween) {
          asset.pulseTween = this.tweens.add({
            targets: asset.body,
            scaleX: { from: 1, to: 1.05 },
            scaleY: { from: 1, to: 1.05 },
            yoyo: true,
            duration: 620,
            repeat: -1,
            ease: 'Sine.InOut'
          });
        }
        asset.body.setStrokeStyle(3, PARTITION_COLORS[asset.def.roomId], telemetry?.status === 'alert' ? 1 : 0.95);
      } else {
        asset.pulseTween?.stop();
        asset.pulseTween = null;
        asset.body.setScale(1);
        asset.body.setStrokeStyle(2, 0x223050, 0.82);
      }
    }
  }

  private resolveStateProfile(stateId: LobsterStateId): WorkStateProfile {
    return this.protocols.workOutput.states.find((item) => item.id === stateId) ?? this.protocols.workOutput.states[0];
  }

  private pickStateProfile(zoneType: WorkZoneType): WorkStateProfile {
    const candidates = this.protocols.workOutput.states.filter((item) => item.zoneTypes.includes(zoneType) && item.id !== 'idle');
    if (candidates.length === 0) {
      return this.resolveStateProfile(zoneType === 'break_room' ? 'resting' : 'executing');
    }

    const cursor = this.stateCursorByZoneType.get(zoneType) ?? 0;
    const profile = candidates[cursor % candidates.length];
    this.stateCursorByZoneType.set(zoneType, cursor + 1);
    return profile;
  }

  private resolveCategory(categoryId: string): OutputCategoryDef {
    return this.protocols.workOutput.outputCategories.find((item) => item.id === categoryId) ?? this.protocols.workOutput.outputCategories[0];
  }

  private resolveInterface(interfaceId: string): InterfaceDef {
    return this.protocols.workOutput.interfaces.find((item) => item.id === interfaceId) ?? this.protocols.workOutput.interfaces[0];
  }

  private materializeOutput(
    profile: WorkStateProfile,
    options: {
      resourceId?: ResourcePartitionId;
      detailOverride?: string;
    } = {}
  ): WorkOutputEvent {
    const resourceId = options.resourceId;
    const categoryId =
      resourceId && profile.outputCategoryIds.includes(resourceId)
        ? resourceId
        : this.pick(profile.outputCategoryIds);
    const interfaceId =
      resourceId && profile.interfaceIds.includes(resourceId)
        ? resourceId
        : this.pick(profile.interfaceIds);

    const category = this.resolveCategory(categoryId);
    const iface = this.resolveInterface(interfaceId);
    const detail = options.detailOverride ?? `${this.pick(profile.detailTemplates)} (${this.pick(category.sampleContents)})`;

    this.outputCursor += 1;

    return {
      stateId: profile.id,
      stateLabel: profile.label,
      outputCategoryId: category.id,
      outputCategoryLabel: category.label,
      interfaceId: iface.id,
      interfaceLabel: iface.label,
      interfaceEndpoint: iface.endpoint,
      content: detail
    };
  }

  private pick<T>(list: T[]): T {
    const index = this.outputCursor % list.length;
    return list[index];
  }

  private zoneLabel(zoneId: ResourcePartitionId): string {
    return this.protocols.mapLogic.workZones.find((zone) => zone.id === zoneId)?.label ?? zoneId;
  }

  private formatClock(value: string | null): string {
    if (!value) {
      return '--:--';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '--:--';
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  private getTheme(): ThemePack['themes'][number] {
    return this.protocols.themePack.themes[this.currentThemeIndex];
  }

  private initializeRenderLayerDepths(): void {
    const defaults = {
      floor: 1,
      back_walls: 8,
      mid_props: 20,
      actor: 30,
      fg_occluder: 50,
      fx_overlay: 70
    } as const;

    for (const [layerId, depth] of Object.entries(defaults)) {
      this.renderLayerDepths.set(layerId, depth);
    }

    for (const layer of this.protocols.mapLogic.renderLayers ?? []) {
      this.renderLayerDepths.set(layer.id, layer.depth);
    }
  }

  private getRenderLayerDepth(layerId: string): number {
    return this.renderLayerDepths.get(layerId) ?? 0;
  }

  private sansFontFamily(): string {
    return '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
  }

  private displayFontFamily(): string {
    return this.locale === 'zh'
      ? this.sansFontFamily()
      : '"VT323", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  }

  private roomHasSliceLayer(roomId: ResourcePartitionId, layerId: RoomSliceLayerDef['renderLayer']): boolean {
    return this.protocols.sceneArt.roomSlices.some(
      (slice) => slice.roomId === roomId && slice.replacesLayers.includes(layerId)
    );
  }

  private layerToDepth(layer: AssetDef['layer'] | RoomSliceLayerDef['renderLayer'], footY?: number, depthBand?: number): number {
    if (layer === 'ground' || layer === 'floor') {
      return this.getRenderLayerDepth('floor');
    }
    if (layer === 'mid' || layer === 'mid_props') {
      const base = this.getRenderLayerDepth('mid_props');
      return base + (depthBand ?? 0) * 0.1 + (footY ?? 0) * 0.0001;
    }
    if (layer === 'actor') {
      const base = this.getRenderLayerDepth('actor');
      return base + (footY ?? 0) * 0.001;
    }
    if (layer === 'back_walls') {
      return this.getRenderLayerDepth('back_walls');
    }
    if (layer === 'fx_overlay') {
      return this.getRenderLayerDepth('fx_overlay');
    }
    return this.getRenderLayerDepth('fg_occluder') + (depthBand ?? 0) * 0.01;
  }

  private isOccluderHandledBySlice(x: number, y: number, width: number, height: number): boolean {
    const center = { x: x + width / 2, y: y + height / 2 };
    return this.protocols.sceneArt.roomSlices.some((slice) => {
      if (!slice.replacesLayers.includes('fg_occluder')) {
        return false;
      }
      const room = this.protocols.mapLogic.rooms.find((candidate) => candidate.id === slice.roomId);
      if (!room) {
        return false;
      }
      const [left, top, roomWidth, roomHeight] = room.bounds;
      return center.x >= left && center.x <= left + roomWidth && center.y >= top && center.y <= top + roomHeight;
    });
  }

  private applyActorVariant(variant: ActorVariantDef): void {
    if (this.actorVariantId === variant.id) {
      return;
    }
    this.actorVariantId = variant.id;
    this.actorVisualSelectionByContext.clear();
    this.lobsterRoute = [];
    this.patrolTargetMode = null;
    this.activeZoneId = null;
    this.workMode = 'idle';
    const spawnIdleMode = this.resolveSpawnIdleMode();
    this.currentActionMode = spawnIdleMode;
    this.lastCompletedActionAnchor = null;
    this.suppressedActionAnchor = null;
    this.suppressedActionAnchorUntil = 0;
    this.lastMainVisualKey = null;
    this.resetPatrolProgressTracking();
    if (spawnIdleMode) {
      this.updateLobsterVisual('idle', spawnIdleMode);
    } else {
      this.updateLobsterVisual('idle');
    }
    this.patrolCooldownUntil = Date.now() + 1800;
  }

  private normalizeGeneratedActorFolderId(value: string): string | null {
    const text = String(value || '').trim().slice(0, 80);
    if (!/^[a-zA-Z0-9._-]+$/.test(text)) {
      return null;
    }
    return text;
  }

  private rewriteGeneratedActorPath(pathValue: string, folderId: string): string {
    const normalizedPath = String(pathValue || '').trim();
    if (!normalizedPath) {
      return `/assets/generated/actors/${folderId}/sheets/stand_front-spritesheet.png`;
    }
    return normalizedPath.replace(/\/assets\/generated\/actors\/[^/]+\/sheets\//, `/assets/generated/actors/${folderId}/sheets/`);
  }

  private findGeneratedActorBaseVariant(): ActorVariantDef | null {
    const actor = this.protocols.sceneArt.actor;
    const variants = Array.isArray(actor?.variants) ? actor.variants : [];
    return variants.find((variant) => variant.id === 'tyxt-emoji')
      ?? variants.find((variant) => (variant.modes ?? []).some((mode) => String(mode.path || '').includes('/assets/generated/actors/tyxt-emoji-v1/')))
      ?? variants[0]
      ?? null;
  }

  private buildGeneratedActorVariant(folderId: string): ActorVariantDef | null {
    const normalizedFolderId = this.normalizeGeneratedActorFolderId(folderId);
    if (!normalizedFolderId) {
      return null;
    }
    const cached = this.generatedActorVariantCache.get(normalizedFolderId);
    if (cached) {
      return cached;
    }
    const baseVariant = this.findGeneratedActorBaseVariant();
    if (!baseVariant) {
      return null;
    }
    const variant: ActorVariantDef = {
      id: normalizedFolderId,
      label: normalizedFolderId,
      modes: baseVariant.modes.map((mode) => ({
        ...mode,
        textureKey: `${normalizedFolderId}:${mode.textureKey}`,
        path: this.rewriteGeneratedActorPath(mode.path, normalizedFolderId),
        stateIds: mode.stateIds ? [...mode.stateIds] : undefined,
        directions: mode.directions ? [...mode.directions] : undefined,
        triggerAnchor: mode.triggerAnchor ? { ...mode.triggerAnchor } : undefined,
        displaySize: mode.displaySize ? { ...mode.displaySize } : undefined,
        animation: mode.animation ? { ...mode.animation } : undefined
      }))
    };
    this.generatedActorVariantCache.set(normalizedFolderId, variant);
    return variant;
  }

  private actorVariantTexturesReady(variant: ActorVariantDef): boolean {
    return (variant.modes ?? []).every((mode) => {
      if (!mode.textureKey) {
        return true;
      }
      return this.textures.exists(mode.textureKey);
    });
  }

  private ensureActorVariantTexturesReady(variant: ActorVariantDef, onReady: () => void): void {
    if (this.actorVariantTexturesReady(variant)) {
      this.createActorAnimations();
      onReady();
      return;
    }
    for (const mode of variant.modes ?? []) {
      this.loadTextureAsset(mode);
    }
    this.load.once('complete', () => {
      this.createActorAnimations();
      onReady();
    });
    if (!this.load.isLoading()) {
      this.load.start();
    }
  }

  private resolveActorVariants(): ActorVariantDef[] {
    const actor = this.protocols.sceneArt.actor;
    const generatedVariants = this.generatedActorVariantFolders
      .map((folderId) => this.buildGeneratedActorVariant(folderId))
      .filter((variant): variant is ActorVariantDef => variant !== null);
    if (!actor) {
      return generatedVariants;
    }
    if (Array.isArray(actor.variants) && actor.variants.length > 0) {
      const existingIds = new Set(actor.variants.map((variant) => variant.id));
      return [
        ...actor.variants,
        ...generatedVariants.filter((variant) => !existingIds.has(variant.id))
      ];
    }
    if (Array.isArray(actor.modes) && actor.modes.length > 0) {
      return [{
        id: actor.defaultVariantId ?? actor.id,
        label: 'Default',
        modes: actor.modes
      }, ...generatedVariants];
    }
    return generatedVariants;
  }

  private resolveActorVariant(): ActorVariantDef | null {
    const variants = this.resolveActorVariants();
    if (variants.length === 0) {
      return null;
    }
    if (this.actorVariantId) {
      const matched = variants.find((variant) => variant.id === this.actorVariantId);
      if (matched) {
        return matched;
      }
    }
    const actor = this.protocols.sceneArt.actor;
    const preferredId = actor?.defaultVariantId;
    if (preferredId) {
      const matched = variants.find((variant) => variant.id === preferredId);
      if (matched) {
        this.actorVariantId = matched.id;
        return matched;
      }
    }
    this.actorVariantId = variants[0].id;
    return variants[0];
  }

  private normalizeActionAssetPath(value: string | undefined): string {
    const raw = String(value || '').trim().replace(/\\/g, '/');
    if (!raw) {
      return '';
    }
    if (/^(data:|blob:)/i.test(raw)) {
      return raw;
    }
    const publicIndex = raw.toLowerCase().lastIndexOf('/public/');
    if (publicIndex >= 0) {
      return raw.slice(publicIndex + '/public'.length).toLowerCase();
    }
    if (/^[a-zA-Z]:\//.test(raw)) {
      const assetsIndex = raw.toLowerCase().lastIndexOf('/assets/');
      return assetsIndex >= 0 ? raw.slice(assetsIndex).toLowerCase() : raw.toLowerCase();
    }
    return (raw.startsWith('/') ? raw : `/${raw}`).toLowerCase();
  }

  private actionAssetBaseName(normalizedPath: string): string {
    const value = normalizedPath.trim().toLowerCase();
    if (!value) {
      return '';
    }
    const slashIndex = value.lastIndexOf('/');
    return slashIndex >= 0 ? value.slice(slashIndex + 1) : value;
  }

  private findActorModeByActionAssetPath(
    modes: ActorVariantDef['modes'][number][],
    assetPath: string
  ): ActorVariantDef['modes'][number] | null {
    const normalizedAssetPath = this.normalizeActionAssetPath(assetPath);
    if (!normalizedAssetPath) {
      return null;
    }

    const exact = modes.find((mode) => this.normalizeActionAssetPath(mode.path) === normalizedAssetPath);
    if (exact) {
      return exact;
    }

    const assetName = this.actionAssetBaseName(normalizedAssetPath);
    if (!assetName) {
      return null;
    }
    return modes.find((mode) => {
      const modePath = this.normalizeActionAssetPath(mode.path);
      return this.actionAssetBaseName(modePath) === assetName;
    }) ?? null;
  }

  private inlineActionAssetHash(value: string): string {
    const cached = this.inlineActionAssetHashByValue.get(value);
    if (cached) {
      return cached;
    }
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
    const out = hash.toString(36);
    if (this.inlineActionAssetHashByValue.size > 32) {
      this.inlineActionAssetHashByValue.clear();
    }
    this.inlineActionAssetHashByValue.set(value, out);
    return out;
  }

  private createActorAnimationForMode(variantId: string, mode: ActorVariantDef['modes'][number]): void {
    if (mode.kind !== 'spritesheet' || !mode.frameCount || !this.textures.exists(mode.textureKey)) {
      return;
    }
    const key = this.actorAnimationKey(variantId, mode.textureKey);
    if (this.anims.exists(key)) {
      return;
    }
    this.anims.create({
      key,
      frames: this.anims.generateFrameNumbers(mode.textureKey, {
        start: 0,
        end: mode.frameCount - 1
      }),
      frameRate: mode.animation?.fps ?? 10,
      repeat: mode.animation?.repeat ?? -1
    });
  }

  private ensureInlineActorModeTextureReady(
    variantId: string,
    mode: ActorVariantDef['modes'][number]
  ): boolean {
    if (this.textures.exists(mode.textureKey)) {
      this.createActorAnimationForMode(variantId, mode);
      return true;
    }
    if (this.queuedTextureKeys.has(mode.textureKey)) {
      return false;
    }
    this.loadTextureAsset(mode);
    this.load.once('complete', () => {
      this.createActorAnimationForMode(variantId, mode);
      this.lastMainVisualKey = null;
    });
    if (!this.load.isLoading()) {
      this.load.start();
    }
    return false;
  }

  private buildInlineActorModeFromScenePoint(
    point: SceneInteractionPoint,
    fallbackMode: ActorVariantDef['modes'][number] | null,
    variantId: string
  ): ActorVariantDef['modes'][number] | null {
    const rawSpriteKey = String(point.sprite_key || '').trim();
    if (!/^(data:image\/|blob:)/i.test(rawSpriteKey)) {
      return null;
    }
    const frameWidth = Math.max(1, Math.round(point.sprite_frame_width ?? fallbackMode?.frameWidth ?? 64));
    const frameHeight = Math.max(1, Math.round(point.sprite_frame_height ?? fallbackMode?.frameHeight ?? 64));
    const frameCount = Math.max(1, Math.round(point.sprite_total_frames ?? fallbackMode?.frameCount ?? 1));
    const fps = Math.max(1, Number(point.sprite_fps ?? fallbackMode?.animation?.fps ?? 8));
    const textureKey = [
      'scene-action-inline',
      this.inlineActionAssetHash(rawSpriteKey),
      frameWidth,
      frameHeight,
      frameCount
    ].join(':');
    const mode: ActorVariantDef['modes'][number] = {
      ...(fallbackMode ?? {
        mode: 'working',
        textureKey,
        path: rawSpriteKey
      }),
      textureKey,
      path: rawSpriteKey,
      kind: 'spritesheet',
      frameWidth,
      frameHeight,
      frameCount,
      animation: {
        fps,
        repeat: -1
      },
      directions: undefined,
      displaySize: undefined
    };
    return this.ensureInlineActorModeTextureReady(variantId, mode) ? mode : null;
  }

  private modeAnchorDistanceToPoint(mode: ActorVariantDef['modes'][number], point: Point): number {
    if (!mode.triggerAnchor) {
      return Number.POSITIVE_INFINITY;
    }
    return Phaser.Math.Distance.Between(
      point.x,
      point.y,
      mode.triggerAnchor.x,
      mode.triggerAnchor.y
    );
  }

  private pickNearestAnchoredMode(
    modes: ActorVariantDef['modes'][number][],
    point: Point
  ): ActorVariantDef['modes'][number] | null {
    let best: { mode: ActorVariantDef['modes'][number]; distance: number } | null = null;
    for (const mode of modes) {
      if (!mode.triggerAnchor) {
        continue;
      }
      const distance = this.modeAnchorDistanceToPoint(mode, point);
      if (!best || distance < best.distance) {
        best = { mode, distance };
      }
    }
    return best?.mode ?? null;
  }

  private deterministicModeIndex(seed: string, length: number): number {
    if (length <= 1) {
      return 0;
    }
    let hash = 0;
    for (let index = 0; index < seed.length; index += 1) {
      hash = ((hash * 33) + seed.charCodeAt(index)) >>> 0;
    }
    return hash % length;
  }

  private resolveFallbackWorkingModeForScenePoint(
    point: SceneInteractionPoint,
    manifestModes: ActorVariantDef['modes'][number][],
    manifestModesByAssetPath: Map<string, ActorVariantDef['modes'][number]>
  ): ActorVariantDef['modes'][number] | null {
    if (manifestModes.length === 0) {
      return null;
    }

    const pointAnchor = {
      x: Math.round(point.anchor_x ?? point.x),
      y: Math.round(point.anchor_y ?? point.y)
    };
    const spritePath = this.normalizeActionAssetPath(point.sprite_key);
    if (spritePath) {
      const exact = manifestModesByAssetPath.get(spritePath);
      if (exact) {
        return exact;
      }
      const spriteName = this.actionAssetBaseName(spritePath);
      if (spriteName) {
        const byName = manifestModes.find((mode) => {
          const modePath = this.normalizeActionAssetPath(mode.path);
          return this.actionAssetBaseName(modePath) === spriteName;
        }) ?? null;
        if (byName) {
          return byName;
        }
      }
    }

    const roomId = String(point.room_id || '').trim().toLowerCase();
    const anchoredModes = manifestModes.filter((mode) => Boolean(mode.triggerAnchor));
    const sameRoomAnchoredModes = anchoredModes.filter((mode) => {
      const modeRoomId = this.resolvePatrolRoomId(mode);
      return modeRoomId && String(modeRoomId).toLowerCase() === roomId;
    });

    const nearestSameRoom = this.pickNearestAnchoredMode(sameRoomAnchoredModes, pointAnchor);
    if (nearestSameRoom) {
      return nearestSameRoom;
    }
    const nearestAnchored = this.pickNearestAnchoredMode(anchoredModes, pointAnchor);
    if (nearestAnchored) {
      return nearestAnchored;
    }

    const seed = `${point.id}|${point.label}|${point.room_id}|${pointAnchor.x}|${pointAnchor.y}`;
    return manifestModes[this.deterministicModeIndex(seed, manifestModes.length)] ?? manifestModes[0];
  }

  private findSceneActionPoint(name: string): SceneInteractionPoint | null {
    const normalizedName = name.trim().toLowerCase();
    return this.sceneMapData.interaction_points.find((point) => {
      const label = String(point.label || '').trim().toLowerCase();
      const id = String(point.id || '').trim().toLowerCase();
      return label === normalizedName || id === normalizedName;
    }) ?? null;
  }

  private isStandFrontActionPoint(point: SceneInteractionPoint): boolean {
    const label = String(point.label || '').trim().toLowerCase();
    const id = String(point.id || '').trim().toLowerCase();
    const isStandName = (value: string): boolean => (
      value.includes('stand-front')
      || value.includes('stand_front')
      || value.includes('stant-front')
      || value.includes('stant_front')
    );
    return isStandName(label) || isStandName(id);
  }

  private buildActorModeFromScenePoint(
    point: SceneInteractionPoint,
    fallbackMode: ActorVariantDef['modes'][number] | null
  ): ActorVariantDef['modes'][number] | null {
    const variant = this.resolveActorVariant();
    if (!variant) {
      return null;
    }
    const pointAssetPath = this.normalizeActionAssetPath(point.sprite_key);
    const matchedBySprite = pointAssetPath
      ? this.findActorModeByActionAssetPath(variant.modes, pointAssetPath)
      : null;
    const usesInlineSprite = /^(data:image\/|blob:)/i.test(String(point.sprite_key || '').trim());
    const inlineMode = usesInlineSprite
      ? this.buildInlineActorModeFromScenePoint(point, fallbackMode, variant.id)
      : null;
    const matchedMode = inlineMode
      ?? (usesInlineSprite ? null : matchedBySprite)
      ?? (usesInlineSprite ? null : fallbackMode);
    if (!matchedMode) {
      return null;
    }
    return {
      ...matchedMode,
      triggerAnchor: {
        x: Math.round(point.anchor_x ?? point.x),
        y: Math.round(point.anchor_y ?? point.y)
      },
      // Patrol uses action-point anchors; keep radius practical so "nearby absorb" can happen.
      triggerRadius: Math.max(48, Math.min(108, matchedMode.triggerRadius ?? 76)),
      triggerAnchorBasis: 'center'
    };
  }

  private resolveSpawnIdleMode(): ActorVariantDef['modes'][number] | null {
    const variant = this.resolveActorVariant();
    if (!variant) {
      return null;
    }
    const idleWithAnchor = variant.modes.filter((mode) => mode.mode === 'idle' && Boolean(mode.triggerAnchor));
    if (idleWithAnchor.length === 0) {
      return null;
    }
    const standFront = idleWithAnchor.find((mode) => {
      const key = String(mode.textureKey || '').toLowerCase();
      return key.includes('stand-front') || key.includes('stand_front') || key.includes('stant-front') || key.includes('stant_front');
    });
    const scenePoint = this.findSceneActionPoint('stand-front');
    const fromScenePoint = scenePoint ? this.buildActorModeFromScenePoint(scenePoint, standFront ?? idleWithAnchor[0] ?? null) : null;
    return fromScenePoint ?? standFront ?? idleWithAnchor[0] ?? null;
  }

  private resolvePatrolActionModes(): ActorVariantDef['modes'][number][] {
    const variant = this.resolveActorVariant();
    if (!variant) {
      return [];
    }
    const manifestModes = variant.modes.filter((mode) => mode.mode === 'working');
    if (manifestModes.length === 0) {
      return [];
    }
    const manifestModesByAssetPath = new Map(
      manifestModes
        .map((mode) => [this.normalizeActionAssetPath(mode.path), mode] as const)
        .filter(([path]) => Boolean(path))
    );

    const sceneModes = this.sceneMapData.interaction_points
      .map((point) => {
        if (this.isStandFrontActionPoint(point)) {
          return null;
        }
        const fallbackMode = this.resolveFallbackWorkingModeForScenePoint(point, manifestModes, manifestModesByAssetPath);
        if (!fallbackMode) {
          return null;
        }
        const built = this.buildActorModeFromScenePoint(point, fallbackMode);
        if (!built) {
          return null;
        }
        const nextMode: ActorVariantDef['modes'][number] = {
          ...built,
          mode: 'working',
          triggerRadius: Math.max(52, Math.min(112, built.triggerRadius ?? 76)),
          triggerAnchorBasis: 'center'
        };
        return nextMode;
      })
      .filter((mode): mode is ActorVariantDef['modes'][number] => mode !== null);

    return sceneModes;
  }

  private resolvePatrolRoomId(mode: ActorVariantDef['modes'][number]): ResourcePartitionId | null {
    if (!mode.triggerAnchor) {
      return null;
    }
    return this.findRoomByPoint(mode.triggerAnchor)?.id ?? null;
  }

  private actorAnimationKey(variantId: string, textureKey: string): string {
    return `actor:${variantId}:${textureKey}`;
  }

  private resetPrimaryAgentPoseFx(): void {
    if (!this.lobster) {
      return;
    }
    this.tweens.killTweensOf(this.lobster);
    this.lobster.setScale(1, 1);
    this.lobster.setAngle(0);
  }

  private spriteLeftBottomPoint(sprite: Phaser.GameObjects.Sprite | null): Point | null {
    if (!sprite) {
      return null;
    }
    const bounds = sprite.getBounds();
    return { x: bounds.left, y: bounds.bottom };
  }

  private spriteCenterPoint(sprite: Phaser.GameObjects.Sprite | null): Point | null {
    if (!sprite) {
      return null;
    }
    const bounds = sprite.getBounds();
    return { x: bounds.centerX, y: bounds.centerY };
  }

  private mainActorTriggerPoint(): Point {
    const fromSprite = this.lobsterBody instanceof Phaser.GameObjects.Sprite
      ? this.spriteLeftBottomPoint(this.lobsterBody)
      : null;
    if (fromSprite) {
      return fromSprite;
    }
    return { x: this.lobster?.x ?? 0, y: this.lobster?.y ?? 0 };
  }

  private mainActorTriggerCenterPoint(): Point {
    const fromSprite = this.lobsterBody instanceof Phaser.GameObjects.Sprite
      ? this.spriteCenterPoint(this.lobsterBody)
      : null;
    if (fromSprite) {
      return fromSprite;
    }
    return { x: this.lobster?.x ?? 0, y: this.lobster?.y ?? 0 };
  }

  private agentActorTriggerPoint(actor: AgentActor): Point {
    const fromSprite = actor.body instanceof Phaser.GameObjects.Sprite
      ? this.spriteLeftBottomPoint(actor.body)
      : null;
    if (fromSprite) {
      return fromSprite;
    }
    return { x: actor.container.x, y: actor.container.y };
  }

  private agentActorTriggerCenterPoint(actor: AgentActor): Point {
    const fromSprite = actor.body instanceof Phaser.GameObjects.Sprite
      ? this.spriteCenterPoint(actor.body)
      : null;
    if (fromSprite) {
      return fromSprite;
    }
    return { x: actor.container.x, y: actor.container.y };
  }

  private snapContainerLeftBottomToAnchor(
    container: Phaser.GameObjects.Container,
    sprite: Phaser.GameObjects.Sprite | null,
    anchor: Point
  ): void {
    if (!sprite) {
      container.x = Math.round(anchor.x);
      container.y = Math.round(anchor.y);
      return;
    }
    const bounds = sprite.getBounds();
    const deltaX = anchor.x - bounds.left;
    const deltaY = anchor.y - bounds.bottom;
    container.x = Math.round(container.x + deltaX);
    container.y = Math.round(container.y + deltaY);
  }

  private snapContainerCenterToAnchor(
    container: Phaser.GameObjects.Container,
    sprite: Phaser.GameObjects.Sprite | null,
    anchor: Point
  ): void {
    if (!sprite) {
      container.x = Math.round(anchor.x);
      container.y = Math.round(anchor.y);
      return;
    }
    container.x = Math.round(anchor.x - sprite.x);
    container.y = Math.round(anchor.y - sprite.y);
  }

  private modeTriggerAnchorBasis(mode: ActorVariantDef['modes'][number]): 'leftBottom' | 'center' {
    return mode.triggerAnchorBasis === 'center' ? 'center' : 'leftBottom';
  }

  private snapContainerToModeAnchor(
    container: Phaser.GameObjects.Container,
    sprite: Phaser.GameObjects.Sprite | null,
    mode: ActorVariantDef['modes'][number]
  ): void {
    if (!mode.triggerAnchor) {
      return;
    }
    if (this.modeTriggerAnchorBasis(mode) === 'center') {
      this.snapContainerCenterToAnchor(container, sprite, mode.triggerAnchor);
      return;
    }
    this.snapContainerLeftBottomToAnchor(container, sprite, mode.triggerAnchor);
  }

  private resolveModeDisplaySize(
    mode: ActorVariantDef['modes'][number],
    actorDisplaySize: { width: number; height: number },
    baseScale: number
  ): { width: number; height: number } {
    if (mode.kind === 'spritesheet' && mode.frameWidth && mode.frameHeight) {
      return {
        width: mode.frameWidth * baseScale,
        height: mode.frameHeight * baseScale
      };
    }
    if (mode.displaySize) {
      return {
        width: mode.displaySize.width,
        height: mode.displaySize.height
      };
    }
    return {
      width: actorDisplaySize.width * baseScale,
      height: actorDisplaySize.height * baseScale
    };
  }

  private applySpriteFrameStabilizer(
    sprite: Phaser.GameObjects.Sprite,
    mode: {
      textureKey: string;
      frameWidth?: number;
      frameHeight?: number;
      frameCount?: number;
      kind?: 'image' | 'svg' | 'spritesheet';
    },
    baseOffset: Point
  ): void {
    // Stabilizer disabled: lock anchor and avoid per-frame offset wobble.
    void mode;
    sprite.setPosition(Math.round(baseOffset.x), Math.round(baseOffset.y));
  }

  private variantUsesDirectionalWalk(): boolean {
    const variant = this.resolveActorVariant();
    if (!variant) {
      return false;
    }
    return variant.modes.some((mode) => mode.mode === 'moving' && (mode.directions?.length ?? 0) > 0);
  }

  private createActorAnimations(): void {
    for (const variant of this.resolveActorVariants()) {
      for (const mode of variant.modes ?? []) {
        this.createActorAnimationForMode(variant.id, mode);
      }
    }
  }

  private resolveDirectionFromVector(dx: number, dy: number, fallback: ActorDirection = 'down'): ActorDirection {
    if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
      return fallback;
    }

    const absX = Math.abs(dx);
    const absY = Math.abs(dy);
    const horizontalDominant = absX > absY * 1.7;
    const verticalDominant = absY > absX * 1.7;

    if (horizontalDominant) {
      return dx >= 0 ? 'right' : 'left';
    }
    if (verticalDominant) {
      return dy >= 0 ? 'down' : 'up';
    }
    if (dx >= 0 && dy >= 0) {
      return 'downright';
    }
    if (dx >= 0 && dy < 0) {
      return 'upright';
    }
    if (dx < 0 && dy >= 0) {
      return 'downleft';
    }
    return 'upleft';
  }

  private pickHotspotActorMode(
    candidates: ActorVariantDef['modes'],
    position?: Point,
    positionCenter?: Point
  ): ActorVariantDef['modes'][number] | null {
    if (!position && !positionCenter) {
      return null;
    }
    const fallbackPosition = position ?? positionCenter;
    if (!fallbackPosition) {
      return null;
    }
    const hits = candidates
      .filter((candidate) => Boolean(candidate.triggerAnchor))
      .map((candidate) => {
        const anchor = candidate.triggerAnchor as Point;
        const basis = this.modeTriggerAnchorBasis(candidate);
        const actorPoint = basis === 'center'
          ? (positionCenter ?? fallbackPosition)
          : (position ?? fallbackPosition);
        const actorRoomId = this.findRoomByPoint(actorPoint)?.id ?? null;
        const anchorRoomId = this.findRoomByPoint(anchor)?.id ?? null;
        if (actorRoomId && anchorRoomId && actorRoomId !== anchorRoomId) {
          return null;
        }
        // Proximity trigger: near the anchor is enough (not exact-point match).
        const radius = Math.max(24, candidate.triggerRadius ?? 96);
        const dist = Phaser.Math.Distance.Between(actorPoint.x, actorPoint.y, anchor.x, anchor.y);
        return { candidate, dist, radius };
      })
      .filter((entry): entry is { candidate: ActorVariantDef['modes'][number]; dist: number; radius: number } => Boolean(entry))
      .filter((entry) => entry.dist <= entry.radius);

    if (hits.length === 0) {
      return null;
    }

    hits.sort((left, right) => {
      const leftPriority = left.candidate.priority ?? 0;
      const rightPriority = right.candidate.priority ?? 0;
      if (rightPriority !== leftPriority) {
        return rightPriority - leftPriority;
      }
      return left.dist - right.dist;
    });

    return hits[0]?.candidate ?? null;
  }

  private modeTriggerRoomId(mode: ActorVariantDef['modes'][number]): ResourcePartitionId | null {
    if (!mode.triggerAnchor) {
      return null;
    }
    return this.findRoomByPoint(mode.triggerAnchor)?.id ?? null;
  }

  private pickHighestPriorityActorMode(
    candidates: ActorVariantDef['modes'][number][]
  ): ActorVariantDef['modes'][number] | null {
    if (candidates.length === 0) {
      return null;
    }
    const sorted = [...candidates].sort((left, right) => {
      const leftPriority = left.priority ?? 0;
      const rightPriority = right.priority ?? 0;
      if (rightPriority !== leftPriority) {
        return rightPriority - leftPriority;
      }
      return left.textureKey.localeCompare(right.textureKey);
    });
    return sorted[0] ?? null;
  }

  private isActorModeStateCompatible(
    candidate: ActorVariantDef['modes'][number],
    stateId: LobsterStateId
  ): boolean {
    return !candidate.stateIds || candidate.stateIds.length === 0 || candidate.stateIds.includes(stateId);
  }

  private resolveActorMode(
    mode: WorkMode,
    options: {
      position?: Point;
      positionCenter?: Point;
      direction?: ActorDirection;
      resourceId?: ResourcePartitionId;
    } = {}
  ) {
    const variant = this.resolveActorVariant();
    if (!variant) {
      return null;
    }
    const stateId = this.lastOutput.stateId;
    const candidates = variant.modes.filter((candidate) => candidate.mode === mode);
    if (candidates.length === 0) {
      return variant.modes[0] ?? null;
    }

    const exactCandidates = candidates.filter((candidate) => this.isActorModeStateCompatible(candidate, stateId));
    const usable = exactCandidates.length > 0 ? exactCandidates : candidates;

    if (mode === 'moving') {
      const direction = options.direction;
      if (direction) {
        const directional = usable.find((candidate) => candidate.directions?.includes(direction));
        if (directional) {
          return directional;
        }
      }
      const neutral = usable.find((candidate) => !candidate.directions || candidate.directions.length === 0);
      return neutral ?? usable[0];
    }

    if (mode === 'working') {
      const resourceId = options.resourceId ?? null;
      if (resourceId) {
        const strictByResource = usable.filter(
          (candidate) => Boolean(candidate.triggerAnchor) && this.modeTriggerRoomId(candidate) === resourceId
        );
        const strictResourceMatch = this.pickHighestPriorityActorMode(strictByResource);
        if (strictResourceMatch) {
          return strictResourceMatch;
        }
        const relaxedByResource = variant.modes.filter(
          (candidate) =>
            candidate.mode === 'working'
            && Boolean(candidate.triggerAnchor)
            && this.modeTriggerRoomId(candidate) === resourceId
        );
        const relaxedResourceMatch = this.pickHighestPriorityActorMode(relaxedByResource);
        if (relaxedResourceMatch) {
          return relaxedResourceMatch;
        }
      }

      // Working visuals are hotspot-only; prefer state-compatible hotspots, then relax.
      const strictHotspotPool = variant.modes.filter(
        (candidate) =>
          candidate.mode === 'working'
          && Boolean(candidate.triggerAnchor)
          && this.isActorModeStateCompatible(candidate, stateId)
      );
      const strictMatch = this.pickHotspotActorMode(strictHotspotPool, options.position, options.positionCenter);
      if (strictMatch) {
        return strictMatch;
      }
      const relaxedHotspotPool = variant.modes.filter(
        (candidate) => candidate.mode === 'working' && Boolean(candidate.triggerAnchor)
      );
      const relaxedMatch = this.pickHotspotActorMode(relaxedHotspotPool, options.position, options.positionCenter);
      if (relaxedMatch) {
        return relaxedMatch;
      }
      const fallback = usable.find((candidate) => !candidate.directions || candidate.directions.length === 0);
      return fallback ?? usable[0] ?? null;
    }

    if (mode === 'idle') {
      const strictHotspotPool = variant.modes.filter(
        (candidate) =>
          candidate.mode === 'idle'
          && Boolean(candidate.triggerAnchor)
          && this.isActorModeStateCompatible(candidate, stateId)
      );
      const hotspotMatch = this.pickHotspotActorMode(strictHotspotPool, options.position, options.positionCenter);
      if (hotspotMatch) {
        return hotspotMatch;
      }
      const relaxedHotspotPool = variant.modes.filter(
        (candidate) => candidate.mode === 'idle' && Boolean(candidate.triggerAnchor)
      );
      const relaxedMatch = this.pickHotspotActorMode(relaxedHotspotPool, options.position, options.positionCenter);
      if (relaxedMatch) {
        return relaxedMatch;
      }
    }

    const contextKey = `${variant.id}:${mode}:${stateId}`;
    const now = Date.now();
    const heldSelection = this.actorVisualSelectionByContext.get(contextKey);
    if (heldSelection) {
      const matched = usable.find((candidate) => candidate.textureKey === heldSelection.textureKey);
      if (matched && (usable.length <= 1 || now < heldSelection.holdUntil)) {
        return matched;
      }
    }

    const cursor = this.actorVisualCursorByContext.get(contextKey) ?? 0;
    const selected = usable[cursor % usable.length] ?? usable[0];
    this.actorVisualCursorByContext.set(contextKey, cursor + 1);
    this.actorVisualSelectionByContext.set(contextKey, {
      textureKey: selected.textureKey,
      holdUntil: usable.length > 1 ? now + 60_000 : Number.POSITIVE_INFINITY
    });
    return selected;
  }

  /**
   * Draw (or redraw) the context-window bar below the thought label, above the main lobster.
   * Now uses absolute scene coordinates (not relative to lobster container).
   * @param remaining — fraction 0–1 (1 = full context available, 0 = exhausted)
   */
  private drawContextBar(remaining: number | null): void {
    if (!this.lobsterContextBar) {
      return;
    }
    const actor = this.protocols.sceneArt.actor;
    const barWidth = actor ? Math.round(actor.displaySize.width * 0.72) : 44;
    const barHeight = 8; // 150% of original 5px

    // Position below the thought text label, centered on lobster X
    const lobsterX = this.lobster?.x ?? 0;
    const thoughtBottom = this.lobsterThoughtText
      ? this.lobsterThoughtText.y + 4
      : (this.lobster ? this.lobster.getBounds().top - 8 : 0);
    const barX = lobsterX - Math.round(barWidth / 2);
    const barY = thoughtBottom;

    // Interpolate color: green → lime → yellow → orange → red
    const pct = Math.max(0, Math.min(1, remaining ?? 0));
    let barColor: number;
    if (pct >= 0.70) {
      barColor = 0x44ff88; // green
    } else if (pct >= 0.45) {
      barColor = 0xaaff44; // lime
    } else if (pct >= 0.25) {
      barColor = 0xffcc00; // yellow
    } else if (pct >= 0.10) {
      barColor = 0xff8800; // orange
    } else {
      barColor = 0xff4444; // red
    }

    this.lobsterContextBar.clear();

    // Background track
    this.lobsterContextBar.fillStyle(0x000000, 0.36);
    this.lobsterContextBar.fillRoundedRect(barX - 1, barY - 1, barWidth + 2, barHeight + 2, 3);

    // Fill
    const fillWidth = Math.max(2, Math.round(barWidth * pct));
    this.lobsterContextBar.fillStyle(barColor, 0.92);
    this.lobsterContextBar.fillRoundedRect(barX, barY, fillWidth, barHeight, 2);

    // Subtle border
    this.lobsterContextBar.lineStyle(1, 0xffffff, 0.18);
    this.lobsterContextBar.strokeRoundedRect(barX, barY, barWidth, barHeight, 2);
  }

  private updateLobsterVisual(mode: WorkMode, forcedMode?: ActorVariantDef['modes'][number]): void {
    const actor = this.protocols.sceneArt.actor;
    const variant = this.resolveActorVariant();
    const actorMode = forcedMode
      ?? (mode !== 'moving' ? this.currentActionMode : null)
      ?? this.resolveActorMode(mode, {
        position: this.mainActorTriggerPoint(),
        positionCenter: this.mainActorTriggerCenterPoint(),
        direction: this.actorFacing
      });
    if (!actor || !variant || !actorMode || !(this.lobsterBody instanceof Phaser.GameObjects.Sprite)) {
      return;
    }

    const visualKey = `${mode}:${actorMode.textureKey}`;
    if (mode !== 'moving') {
      const shouldSnapToAnchor = Boolean(forcedMode) || this.lastMainVisualKey !== visualKey;
      if (actorMode.triggerAnchor && shouldSnapToAnchor) {
        this.snapContainerToModeAnchor(this.lobster, this.lobsterBody, actorMode);
        this.lobster.setDepth(this.layerToDepth('actor', this.lobster.y));
      }
    }

    const modeDisplay = this.resolveModeDisplaySize(actorMode, actor.displaySize, 1.2);
    this.lobsterBody.setDisplaySize(
      Math.round(modeDisplay.width),
      Math.round(modeDisplay.height)
    );

    const animationKey = this.actorAnimationKey(variant.id, actorMode.textureKey);
    if (actorMode.kind === 'spritesheet' && actorMode.frameCount && this.anims.exists(animationKey)) {
      if (this.lobsterBody.anims.currentAnim?.key !== animationKey) {
        this.lobsterBody.play(animationKey);
      }
      if (this.modeTriggerAnchorBasis(actorMode) === 'center') {
        this.lobsterBody.setPosition(actor.anchorOffset?.x ?? 0, actor.anchorOffset?.y ?? 0);
      } else {
        this.applySpriteFrameStabilizer(this.lobsterBody, actorMode, {
          x: actor.anchorOffset?.x ?? 0,
          y: actor.anchorOffset?.y ?? 0
        });
      }
      this.lastMainVisualKey = visualKey;
      return;
    }

    this.lobsterBody.stop();
    if (this.lobsterBody.texture.key !== actorMode.textureKey) {
      this.lobsterBody.setTexture(actorMode.textureKey);
    }
    this.lobsterBody.setFrame(0);
    if (this.modeTriggerAnchorBasis(actorMode) === 'center') {
      this.lobsterBody.setPosition(actor.anchorOffset?.x ?? 0, actor.anchorOffset?.y ?? 0);
    } else {
      this.applySpriteFrameStabilizer(this.lobsterBody, actorMode, {
        x: actor.anchorOffset?.x ?? 0,
        y: actor.anchorOffset?.y ?? 0
      });
    }
    this.lastMainVisualKey = visualKey;
  }

  /** Apply the correct animation to a subagent actor sprite, mirroring updateLobsterVisual. */
  private updateAgentActorVisual(agentActor: AgentActor, mode: WorkMode): void {
    if (!(agentActor.body instanceof Phaser.GameObjects.Sprite)) {
      return;
    }
    const actorDef = this.protocols.sceneArt.actor;
    const variant = this.resolveActorVariant();
    if (!actorDef || !variant) {
      return;
    }

    const candidates = variant.modes.filter((entry) => entry.mode === mode);
    const fallback = variant.modes.filter((entry) => entry.mode === 'idle');
    const usable = candidates.length > 0 ? candidates : fallback;

    let modeEntry = usable[0] ?? variant.modes[0];
    if (mode === 'moving') {
      modeEntry =
        usable.find((entry) => entry.directions?.includes(agentActor.facing))
        ?? usable.find((entry) => !entry.directions || entry.directions.length === 0)
        ?? modeEntry;
    } else {
      const hotspotPool = variant.modes.filter((entry) => entry.mode === mode && Boolean(entry.triggerAnchor));
      modeEntry =
        this.pickHotspotActorMode(
          hotspotPool,
          this.agentActorTriggerPoint(agentActor),
          this.agentActorTriggerCenterPoint(agentActor)
        )
        ?? variant.modes.find((entry) => entry.mode === mode && !entry.triggerAnchor && (!entry.directions || entry.directions.length === 0))
        ?? variant.modes.find((entry) => entry.mode === 'idle' && !entry.triggerAnchor && (!entry.directions || entry.directions.length === 0))
        ?? modeEntry;
    }

    if (!modeEntry) {
      return;
    }

    const scaleFactor = 0.88; // same as spawn scale
    if (mode !== 'moving' && modeEntry.triggerAnchor) {
      this.snapContainerToModeAnchor(agentActor.container, agentActor.body, modeEntry);
      agentActor.container.setDepth(this.layerToDepth('actor', agentActor.container.y) - 0.5);
    }

    const modeDisplay = this.resolveModeDisplaySize(modeEntry, actorDef.displaySize, scaleFactor);
    agentActor.body.setDisplaySize(
      Math.round(modeDisplay.width),
      Math.round(modeDisplay.height)
    );

    const animationKey = this.actorAnimationKey(variant.id, modeEntry.textureKey);
    if (modeEntry.kind === 'spritesheet' && modeEntry.frameCount && this.anims.exists(animationKey)) {
      if (agentActor.body.anims.currentAnim?.key !== animationKey) {
        agentActor.body.play(animationKey);
      }
      if (this.modeTriggerAnchorBasis(modeEntry) === 'center') {
        agentActor.body.setPosition(actorDef.anchorOffset?.x ?? 0, actorDef.anchorOffset?.y ?? 0);
      } else {
        this.applySpriteFrameStabilizer(agentActor.body, modeEntry, {
          x: actorDef.anchorOffset?.x ?? 0,
          y: actorDef.anchorOffset?.y ?? 0
        });
      }
      return;
    }

    agentActor.body.stop();
    if (agentActor.body.texture.key !== modeEntry.textureKey) {
      agentActor.body.setTexture(modeEntry.textureKey);
    }
    agentActor.body.setFrame(0);
    if (this.modeTriggerAnchorBasis(modeEntry) === 'center') {
      agentActor.body.setPosition(actorDef.anchorOffset?.x ?? 0, actorDef.anchorOffset?.y ?? 0);
    } else {
      this.applySpriteFrameStabilizer(agentActor.body, modeEntry, {
        x: actorDef.anchorOffset?.x ?? 0,
        y: actorDef.anchorOffset?.y ?? 0
      });
    }
  }
}





