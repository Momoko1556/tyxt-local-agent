import type { Point, ResourcePartitionId } from '../../core/types';
import defaultSceneMapDataJson from './scene-map.default.json';

export type SceneMapRoomId = ResourcePartitionId | string;
export type WallShapeType = 'square' | 'rectangle' | 'triangle' | 'circle' | 'trapezoid';

export type SceneMapRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type FloorRegion = {
  id: string;
  polygon?: Point[];
  rect?: SceneMapRect;
  room_id: SceneMapRoomId;
  label?: string;
};

export type WallBlock = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  room_id: SceneMapRoomId;
  shape: WallShapeType;
  rotation: number;
};

export type FurnitureItem = {
  id: string;
  type: string;
  label: string;
  room_id: SceneMapRoomId;
  x: number;
  y: number;
  width: number;
  height: number;
  sprite_key: string;
  blocking: boolean;
  interactive: boolean;
  interaction_type: string;
  z_index: number;
  direction?: 'front' | 'left' | 'right' | 'back';
  sprite_directions?: Partial<Record<'front' | 'left' | 'right' | 'back', string>>;
  asset_id?: string;
  category?: string;
};

export type InteractionPoint = {
  id: string;
  type: string;
  label: string;
  room_id: SceneMapRoomId;
  x: number;
  y: number;
  anchor_x?: number;
  anchor_y?: number;
  interaction_type: string;
  sprite_key?: string;
  sprite_total_frames?: number;
  sprite_frame_width?: number;
  sprite_frame_height?: number;
  sprite_fps?: number;
};

export type InteractionBox = {
  id: string;
  label: string;
  room_id: SceneMapRoomId;
  x: number;
  y: number;
  width: number;
  height: number;
  interaction_name: string;
  interaction_type: string;
  sprite_key?: string;
  sprite_total_frames?: number;
  sprite_frame_width?: number;
  sprite_frame_height?: number;
  sprite_fps?: number;
};

export type SceneMapData = {
  id: string;
  base_width: number;
  base_height: number;
  floor_regions: FloorRegion[];
  wall_blocks: WallBlock[];
  furnitures: FurnitureItem[];
  room_label_anchors: Partial<Record<SceneMapRoomId, Point>>;
  interaction_points: InteractionPoint[];
  interaction_boxes: InteractionBox[];
};

export const SCENE_MAP_STORAGE_KEY = 'tyxt-space-scene-map-data-v1';
export const SCENE_MAP_LOCAL_JSON_HINT = 'third_party/tyxt-space/public/data/scene-map.json';

const DEFAULT_SCENE_MAP_DATA = normalizeSceneMapData(defaultSceneMapDataJson);

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === 'object' && value !== null ? value as UnknownRecord : {};
}

function asNumber(value: unknown, fallback: number): number {
  const next = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function asText(value: unknown, fallback: string): string {
  const next = String(value ?? '').trim();
  return next.length > 0 ? next : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') {
    return value;
  }
  if (value === 'true') {
    return true;
  }
  if (value === 'false') {
    return false;
  }
  return fallback;
}

function normalizePoint(raw: unknown, fallback: Point): Point {
  const row = asRecord(raw);
  return {
    x: asNumber(row.x, fallback.x),
    y: asNumber(row.y, fallback.y)
  };
}

function normalizeRect(raw: unknown, fallback: SceneMapRect): SceneMapRect {
  const row = asRecord(raw);
  return {
    x: asNumber(row.x, fallback.x),
    y: asNumber(row.y, fallback.y),
    width: Math.max(1, asNumber(row.width, fallback.width)),
    height: Math.max(1, asNumber(row.height, fallback.height))
  };
}

function normalizeFloorRegion(raw: unknown, index: number): FloorRegion {
  const row = asRecord(raw);
  const polygon = Array.isArray(row.polygon)
    ? row.polygon.map((point, pointIndex) => normalizePoint(point, { x: pointIndex * 8, y: pointIndex * 8 }))
    : undefined;
  const rect = row.rect ? normalizeRect(row.rect, { x: 0, y: 0, width: 1, height: 1 }) : undefined;
  return {
    id: asText(row.id, `floor-region-${index + 1}`),
    polygon: polygon && polygon.length >= 3 ? polygon : undefined,
    rect,
    room_id: asText(row.room_id, 'gateway'),
    label: asText(row.label, '')
  };
}

function normalizeWallBlock(raw: unknown, index: number): WallBlock {
  const row = asRecord(raw);
  const shapeRaw = asText(row.shape, 'rectangle').toLowerCase();
  const shape: WallShapeType = (
    shapeRaw === 'square'
    || shapeRaw === 'rectangle'
    || shapeRaw === 'triangle'
    || shapeRaw === 'circle'
    || shapeRaw === 'trapezoid'
  )
    ? shapeRaw
    : 'rectangle';
  return {
    id: asText(row.id, `wall-block-${index + 1}`),
    x: asNumber(row.x, 0),
    y: asNumber(row.y, 0),
    width: Math.max(1, asNumber(row.width, 1)),
    height: Math.max(1, asNumber(row.height, 1)),
    room_id: asText(row.room_id, 'gateway'),
    shape,
    rotation: asNumber(row.rotation, 0)
  };
}

function normalizeFurnitureItem(raw: unknown, index: number): FurnitureItem {
  const row = asRecord(raw);
  const x = asNumber(row.x, 0);
  const y = asNumber(row.y, 0);
  const width = Math.max(8, asNumber(row.width, 48));
  const height = Math.max(8, asNumber(row.height, 36));
  return {
    id: asText(row.id, `furniture-${index + 1}`),
    type: asText(row.type, 'object'),
    label: asText(row.label, `Furniture ${index + 1}`),
    room_id: asText(row.room_id, 'gateway'),
    x,
    y,
    width,
    height,
    sprite_key: asText(row.sprite_key, ''),
    blocking: asBoolean(row.blocking, true),
    interactive: asBoolean(row.interactive, false),
    interaction_type: asText(row.interaction_type, 'inspect'),
    z_index: asNumber(row.z_index, y + height),
    direction: (() => {
      const direction = asText(row.direction, '').toLowerCase();
      if (direction === 'front' || direction === 'left' || direction === 'right' || direction === 'back') {
        return direction;
      }
      return undefined;
    })(),
    sprite_directions: (() => {
      const raw = asRecord(row.sprite_directions);
      const directions: Partial<Record<'front' | 'left' | 'right' | 'back', string>> = {};
      const front = asText(raw.front, '');
      const left = asText(raw.left, '');
      const right = asText(raw.right, '');
      const back = asText(raw.back, '');
      if (front) directions.front = front;
      if (left) directions.left = left;
      if (right) directions.right = right;
      if (back) directions.back = back;
      return Object.keys(directions).length > 0 ? directions : undefined;
    })(),
    asset_id: asText(row.asset_id, ''),
    category: asText(row.category, '')
  };
}

function normalizeInteractionPoint(raw: unknown, index: number): InteractionPoint {
  const row = asRecord(raw);
  const x = asNumber(row.x, 0);
  const y = asNumber(row.y, 0);
  const spriteKey = asText(row.sprite_key, '');
  const spriteTotalFrames = Math.max(1, Math.round(asNumber(row.sprite_total_frames, 1)));
  const spriteFrameWidth = Math.max(1, Math.round(asNumber(row.sprite_frame_width, 64)));
  const spriteFrameHeight = Math.max(1, Math.round(asNumber(row.sprite_frame_height, 64)));
  const spriteFps = Math.max(1, asNumber(row.sprite_fps, 8));
  return {
    id: asText(row.id, `interaction-point-${index + 1}`),
    type: asText(row.type, 'point'),
    label: asText(row.label, `Interaction ${index + 1}`),
    room_id: asText(row.room_id, 'gateway'),
    x,
    y,
    anchor_x: Number.isFinite(asNumber(row.anchor_x, Number.NaN)) ? asNumber(row.anchor_x, x) : undefined,
    anchor_y: Number.isFinite(asNumber(row.anchor_y, Number.NaN)) ? asNumber(row.anchor_y, y) : undefined,
    interaction_type: asText(row.interaction_type, 'inspect'),
    sprite_key: spriteKey || undefined,
    sprite_total_frames: spriteKey ? spriteTotalFrames : undefined,
    sprite_frame_width: spriteKey ? spriteFrameWidth : undefined,
    sprite_frame_height: spriteKey ? spriteFrameHeight : undefined,
    sprite_fps: spriteKey ? spriteFps : undefined
  };
}

function normalizeInteractionBox(raw: unknown, index: number): InteractionBox {
  const row = asRecord(raw);
  const x = asNumber(row.x, 0);
  const y = asNumber(row.y, 0);
  const width = Math.max(24, Math.round(asNumber(row.width, 128)));
  const height = Math.max(24, Math.round(asNumber(row.height, 80)));
  const spriteKey = asText(row.sprite_key, '');
  const spriteTotalFrames = Math.max(1, Math.round(asNumber(row.sprite_total_frames, 1)));
  const spriteFrameWidth = Math.max(1, Math.round(asNumber(row.sprite_frame_width, Math.max(24, width))));
  const spriteFrameHeight = Math.max(1, Math.round(asNumber(row.sprite_frame_height, Math.max(24, height))));
  const spriteFps = Math.max(1, asNumber(row.sprite_fps, 8));
  return {
    id: asText(row.id, `interaction-box-${index + 1}`),
    label: asText(row.label, `Interaction Box ${index + 1}`),
    room_id: asText(row.room_id, 'gateway'),
    x,
    y,
    width,
    height,
    interaction_name: asText(row.interaction_name, '默认交互'),
    interaction_type: asText(row.interaction_type, 'inspect'),
    sprite_key: spriteKey || undefined,
    sprite_total_frames: spriteKey ? spriteTotalFrames : undefined,
    sprite_frame_width: spriteKey ? spriteFrameWidth : undefined,
    sprite_frame_height: spriteKey ? spriteFrameHeight : undefined,
    sprite_fps: spriteKey ? spriteFps : undefined
  };
}

function normalizeRoomLabelAnchors(raw: unknown): Partial<Record<SceneMapRoomId, Point>> {
  const row = asRecord(raw);
  const normalized: Partial<Record<SceneMapRoomId, Point>> = {};
  for (const [rawRoomId, rawAnchor] of Object.entries(row)) {
    const roomId = String(rawRoomId || '').trim();
    if (!roomId) {
      continue;
    }
    const anchorRow = asRecord(rawAnchor);
    const anchorX = asNumber(anchorRow.x, Number.NaN);
    const anchorY = asNumber(anchorRow.y, Number.NaN);
    if (!Number.isFinite(anchorX) || !Number.isFinite(anchorY)) {
      continue;
    }
    normalized[roomId] = { x: anchorX, y: anchorY };
  }
  return normalized;
}

export function normalizeSceneMapData(raw: unknown): SceneMapData {
  const row = asRecord(raw);
  const floorRegionsRaw = Array.isArray(row.floor_regions) ? row.floor_regions : [];
  const wallBlocksRaw = Array.isArray(row.wall_blocks) ? row.wall_blocks : [];
  const furnituresRaw = Array.isArray(row.furnitures) ? row.furnitures : [];
  const interactionPointsRaw = Array.isArray(row.interaction_points) ? row.interaction_points : [];
  const interactionBoxesRaw = Array.isArray(row.interaction_boxes) ? row.interaction_boxes : [];

  return {
    id: asText(row.id, 'tyxt-space-scene-map'),
    base_width: Math.max(320, asNumber(row.base_width, 1920)),
    base_height: Math.max(240, asNumber(row.base_height, 1080)),
    floor_regions: floorRegionsRaw.map((entry, index) => normalizeFloorRegion(entry, index)),
    wall_blocks: wallBlocksRaw.map((entry, index) => normalizeWallBlock(entry, index)),
    furnitures: furnituresRaw.map((entry, index) => normalizeFurnitureItem(entry, index)),
    room_label_anchors: normalizeRoomLabelAnchors(row.room_label_anchors),
    interaction_points: interactionPointsRaw.map((entry, index) => normalizeInteractionPoint(entry, index)),
    interaction_boxes: interactionBoxesRaw.map((entry, index) => normalizeInteractionBox(entry, index))
  };
}

export function cloneSceneMapData(data: SceneMapData): SceneMapData {
  return normalizeSceneMapData(JSON.parse(JSON.stringify(data)) as unknown);
}

export function getDefaultSceneMapData(): SceneMapData {
  return cloneSceneMapData(DEFAULT_SCENE_MAP_DATA);
}

export function loadSceneMapData(): SceneMapData {
  if (typeof window === 'undefined') {
    return getDefaultSceneMapData();
  }

  try {
    const stored = window.localStorage.getItem(SCENE_MAP_STORAGE_KEY);
    if (!stored) {
      return getDefaultSceneMapData();
    }
    return normalizeSceneMapData(JSON.parse(stored) as unknown);
  } catch {
    return getDefaultSceneMapData();
  }
}

export function hasStoredSceneMapData(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    return Boolean(window.localStorage.getItem(SCENE_MAP_STORAGE_KEY));
  } catch {
    return false;
  }
}

export function saveSceneMapData(nextData: unknown): SceneMapData {
  const normalized = normalizeSceneMapData(nextData);
  if (typeof window === 'undefined') {
    return normalized;
  }
  try {
    window.localStorage.setItem(SCENE_MAP_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Ignore persistence failures.
  }
  return normalized;
}

export function resetSceneMapData(): SceneMapData {
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.removeItem(SCENE_MAP_STORAGE_KEY);
    } catch {
      // Ignore persistence failures.
    }
  }
  return getDefaultSceneMapData();
}

export function buildSceneMapExportText(data: SceneMapData): string {
  return `${JSON.stringify(normalizeSceneMapData(data), null, 2)}\n`;
}

export function createSceneEntityId(prefix: string, existingIds: Iterable<string>): string {
  const normalizedPrefix = asText(prefix, 'entity').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'entity';
  const used = new Set<string>();
  for (const id of existingIds) {
    used.add(String(id));
  }
  let cursor = 1;
  while (cursor < 100_000) {
    const candidate = `${normalizedPrefix}-${cursor}`;
    if (!used.has(candidate)) {
      return candidate;
    }
    cursor += 1;
  }
  return `${normalizedPrefix}-${Date.now()}`;
}
