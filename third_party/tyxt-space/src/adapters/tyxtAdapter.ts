import type {
  OpenClawSnapshot,
  ResourcePartitionId,
  ResourceTelemetryStatus,
  OpenClawAccessEvent
} from '../core/types';

export type TyxtRoomId =
  | 'main_hall'
  | 'study'
  | 'workshop'
  | 'theater'
  | 'observatory'
  | 'message_wall'
  | 'gallery';

export type TyxtStatus = 'online' | 'offline' | 'partial' | 'ready' | 'running' | 'standby';

export type TyxtRoomNav = {
  id: TyxtRoomId;
  name: string;
  icon: string;
  enabled: boolean;
};

export type TyxtAgent = {
  agent_id: string;
  display_name: string;
  status: 'online' | 'busy' | 'idle' | 'offline';
  mood: 'calm' | 'focused' | 'curious' | 'tired';
  current_room: TyxtRoomId;
};

export type TyxtRegistryAgent = {
  agent_id: string;
  display_name: string;
  agent_title?: string;
  agent_name?: string;
  enabled: boolean;
};

export type TyxtAgentRegistry = {
  agents: TyxtRegistryAgent[];
  default_agent_id: string | null;
  source: string;
  loaded_at: string;
};

export type TyxtSystemStatus = {
  backend: TyxtStatus;
  memory: TyxtStatus;
  tools: TyxtStatus;
  idle_work: TyxtStatus;
};

export type TyxtEvent = {
  id: string;
  title: string;
  detail: string;
  room_id: TyxtRoomId;
  occurred_at: string;
};

export type TyxtMessage = {
  id: string;
  author: string;
  content: string;
  created_at: string;
};

export type TyxtInteractivePoint = {
  id: string;
  label: string;
  detail: string;
  target_room: TyxtRoomId;
};

export type TyxtRoomProfile = {
  title: string;
  description: string;
  status_hint: string;
  interactive_points: TyxtInteractivePoint[];
};

export type TyxtQuickActionId =
  | 'open_chat'
  | 'open_group_chat'
  | 'open_theater'
  | 'view_memory'
  | 'open_tools'
  | 'open_settings';

export type TyxtQuickAction = {
  id: TyxtQuickActionId;
  label: string;
  hint: string;
};

export type TyxtHomeData = {
  space: {
    id: TyxtRoomId;
    name: string;
    description: string;
  };
  rooms: TyxtRoomNav[];
  agents: TyxtAgent[];
  system_status: TyxtSystemStatus;
  events: TyxtEvent[];
  messages: TyxtMessage[];
  room_profiles: Record<TyxtRoomId, TyxtRoomProfile>;
  quick_actions: TyxtQuickAction[];
  selected_agent_id: string | null;
  connection_mode: 'local_mock' | 'legacy_bridge';
  updated_at: string;
};

type TyxtRoomDef = TyxtRoomNav & {
  description: string;
  legacy_resource: ResourcePartitionId;
};

const LEGACY_RESOURCE_IDS: ResourcePartitionId[] = [
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
];

const ROOM_DEFS: TyxtRoomDef[] = [
  {
    id: 'main_hall',
    name: '主厅',
    icon: 'home',
    enabled: true,
    description: '主厅区，集中展示休闲区信息。',
    legacy_resource: 'agent'
  },
  {
    id: 'study',
    name: '书房',
    icon: 'book',
    enabled: true,
    description: '书房区，用于查看工作区信息。',
    legacy_resource: 'break_room'
  },
  {
    id: 'workshop',
    name: '工坊',
    icon: 'tool',
    enabled: true,
    description: '工坊区，查看共享文件夹及记忆库状态。',
    legacy_resource: 'memory'
  },
  {
    id: 'theater',
    name: '剧场',
    icon: 'mask',
    enabled: true,
    description: '剧场区，查看创想区剧场信息。',
    legacy_resource: 'images'
  },
  {
    id: 'observatory',
    name: '档案室',
    icon: 'eye',
    enabled: true,
    description: '档案室区，查看记忆条和用户画像。',
    legacy_resource: 'log'
  },
  {
    id: 'message_wall',
    name: '卧室',
    icon: 'message',
    enabled: true,
    description: '卧室区，查看反刍层和深度思考层报告。',
    legacy_resource: 'document'
  },
  {
    id: 'gallery',
    name: '展厅',
    icon: 'image',
    enabled: true,
    description: '展厅区，查看主人简介和Agent简介。',
    legacy_resource: 'mcp'
  }
];

const LEGACY_TO_TYXT_ROOM: Record<ResourcePartitionId, TyxtRoomId> = {
  document: 'message_wall',
  images: 'theater',
  memory: 'workshop',
  skills: 'workshop',
  gateway: 'main_hall',
  log: 'observatory',
  mcp: 'gallery',
  schedule: 'observatory',
  alarm: 'theater',
  agent: 'main_hall',
  task_queues: 'main_hall',
  break_room: 'study'
};

const ROOM_PROFILES: Record<TyxtRoomId, TyxtRoomProfile> = {
  main_hall: {
    title: '主厅 / Main Hall',
    description: 'TYXT 可视化空间主入口：集中展示休闲区信息。',
    status_hint: '主厅信标稳定，空间路由可用。',
    interactive_points: [
      { id: 'hall-private-chat', label: '私聊', detail: '显示私聊对话框信息。', target_room: 'main_hall' },
      { id: 'hall-group-chat', label: '群聊', detail: '显示群聊对话框信息。', target_room: 'main_hall' }
    ]
  },
  study: {
    title: '书房 / Study',
    description: '用于查看工作区信息。',
    status_hint: '项目信息已加载，可查看近期项目报告。',
    interactive_points: [
      { id: 'study-projects', label: '项目', detail: '查看当前项目数量与项目清单。', target_room: 'study' }
    ]
  },
  workshop: {
    title: '工坊 / Workshop',
    description: '查看共享文件夹及记忆库状态。',
    status_hint: '共享文件夹及记忆库已就绪。',
    interactive_points: [
      { id: 'workshop-shared-files', label: '共享文件', detail: '查看共享文件夹文档清单。', target_room: 'workshop' },
      { id: 'workshop-memory-db', label: '记忆库', detail: '查看 ChromaDB 数据库数量。', target_room: 'workshop' }
    ]
  },
  theater: {
    title: '剧场 / Theater',
    description: '可查看创想区剧场信息。',
    status_hint: '剧场剧目已就绪，等待用户进入演绎。',
    interactive_points: [
      { id: 'theater-shows', label: '剧目', detail: '查看创想区配置下的剧场列表。', target_room: 'theater' }
    ]
  },
  observatory: {
    title: '档案室 / Archive',
    description: '查看记忆条和用户画像。',
    status_hint: '档案索引稳定，可查看近期记录。',
    interactive_points: [
      { id: 'archive-memory-strips', label: '记忆条', detail: '查看记忆条总条数。', target_room: 'observatory' },
      { id: 'archive-user-profiles', label: '用户画像', detail: '查看用户画像条数。', target_room: 'observatory' }
    ]
  },
  message_wall: {
    title: '卧室 / Bedroom',
    description: '查看反刍层和深度思考层报告。',
    status_hint: 'Agent在梦中整理数据。',
    interactive_points: [
      { id: 'bedroom-rumination-log', label: '反刍层', detail: '查看最近一次反刍层日志。', target_room: 'message_wall' },
      { id: 'bedroom-deepthink-log', label: '深度思考层', detail: '查看最近一次深度思考层报告。', target_room: 'message_wall' }
    ]
  },
  gallery: {
    title: '展厅 / Gallery',
    description: '查看主人简介和Agent简介。',
    status_hint: '展厅主人与Agent的风采。',
    interactive_points: [
      { id: 'gallery-owner-intro', label: '主人简介', detail: '展示主人简介（照片框 + 文字框）。', target_room: 'gallery' },
      { id: 'gallery-agent-intro', label: 'Agent简介', detail: '展示 Agent 简介（照片框 + 文字框）。', target_room: 'gallery' }
    ]
  }
};

const QUICK_ACTIONS: TyxtQuickAction[] = [
  { id: 'open_chat', label: '进入私聊', hint: '进入 TYXT 私聊界面' },
  { id: 'open_group_chat', label: '进入群聊', hint: '进入 TYXT 群聊界面' },
  { id: 'open_theater', label: '打开剧场模式', hint: '进入 TYXT 剧场模式' },
  { id: 'view_memory', label: '查看记忆', hint: '切换到书房记忆区' },
  { id: 'open_tools', label: '打开工具/共享文件夹', hint: '切换到工坊能力区' },
  { id: 'open_settings', label: '打开设置', hint: '系统设置入口（占位）' }
];

export function mapTyxtRoomToLegacyResource(roomId: TyxtRoomId): ResourcePartitionId {
  const matched = ROOM_DEFS.find((room) => room.id === roomId);
  return matched?.legacy_resource ?? 'gateway';
}

export function mapLegacyResourceToTyxtRoom(resourceId: ResourcePartitionId): TyxtRoomId {
  return LEGACY_TO_TYXT_ROOM[resourceId] ?? 'main_hall';
}

export function getTyxtRoomProfile(roomId: TyxtRoomId): TyxtRoomProfile {
  return ROOM_PROFILES[roomId];
}

function normalizeTyxtRegistryAgent(raw: unknown): TyxtRegistryAgent | null {
  const row = typeof raw === 'object' && raw !== null ? raw as Record<string, unknown> : {};
  const agentId = String(row.agent_id ?? '').trim();
  if (!agentId) {
    return null;
  }

  const enabled = row.enabled !== false;
  const displayName = String(row.agent_name ?? row.display_name ?? row.agent_title ?? agentId).trim() || agentId;
  const agentTitle = String(row.agent_title ?? '').trim();
  const agentName = String(row.agent_name ?? '').trim();

  return {
    agent_id: agentId,
    display_name: displayName,
    agent_title: agentTitle,
    agent_name: agentName,
    enabled
  };
}

function normalizeTyxtAgentRegistryPayload(payload: unknown): TyxtAgentRegistry | null {
  const raw = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : {};
  const rawAgents = Array.isArray(raw.agents) ? raw.agents : [];
  const dedupe = new Set<string>();
  const agents: TyxtRegistryAgent[] = [];

  for (const item of rawAgents) {
    const normalized = normalizeTyxtRegistryAgent(item);
    if (!normalized || !normalized.enabled || dedupe.has(normalized.agent_id)) {
      continue;
    }
    dedupe.add(normalized.agent_id);
    agents.push(normalized);
  }

  if (agents.length === 0) {
    return null;
  }

  const defaultCandidate = String(raw.default_agent_id ?? '').trim();
  const defaultAgentId = agents.some((agent) => agent.agent_id === defaultCandidate)
    ? defaultCandidate
    : agents[0].agent_id;

  return {
    agents,
    default_agent_id: defaultAgentId,
    source: String(raw.source ?? 'project_registry').trim() || 'project_registry',
    loaded_at: String(raw.loaded_at ?? new Date().toISOString())
  };
}

export async function loadTyxtAgentRegistry(signal?: AbortSignal): Promise<TyxtAgentRegistry | null> {
  try {
    const response = await fetch(`/api/tyxt/agents-registry?t=${Date.now()}`, {
      method: 'GET',
      cache: 'no-store',
      signal
    });
    if (!response.ok) {
      return null;
    }
    const payload = await response.json() as unknown;
    return normalizeTyxtAgentRegistryPayload(payload);
  } catch {
    return null;
  }
}

function roomName(roomId: TyxtRoomId): string {
  return ROOM_DEFS.find((room) => room.id === roomId)?.name ?? '主厅';
}

function statusCycle(seed: number): TyxtSystemStatus {
  if (seed % 8 === 0) {
    return {
      backend: 'partial',
      memory: 'ready',
      tools: 'partial',
      idle_work: 'running'
    };
  }
  return {
    backend: 'online',
    memory: 'ready',
    tools: seed % 3 === 0 ? 'partial' : 'online',
    idle_work: seed % 2 === 0 ? 'running' : 'standby'
  };
}

function defaultMessages(nowIso: string): TyxtMessage[] {
  return [
    {
      id: 'msg-local-1',
      author: '本地系统',
      content: '留言墙功能正在原型阶段，当前为只读展示。',
      created_at: nowIso
    },
    {
      id: 'msg-remote-1',
      author: '远程 Agent 占位',
      content: '后续阶段将接入远程留言同步能力。',
      created_at: nowIso
    }
  ];
}

function defaultEvents(activeRoomId: TyxtRoomId, nowIso: string): TyxtEvent[] {
  return [
    {
      id: 'evt-room-route',
      title: '房间路由更新',
      detail: `当前焦点切换到「${roomName(activeRoomId)}」。`,
      room_id: activeRoomId,
      occurred_at: nowIso
    },
    {
      id: 'evt-health',
      title: '系统巡检完成',
      detail: '后端与待机作业状态已刷新。',
      room_id: 'observatory',
      occurred_at: nowIso
    },
    {
      id: 'evt-memory',
      title: '记忆索引同步',
      detail: '书房记忆索引完成一次轻量整理。',
      room_id: 'study',
      occurred_at: nowIso
    }
  ];
}

export function createTyxtMockHomeData(options: {
  activeRoomId: TyxtRoomId;
  selectedAgentId?: string | null;
  tick?: number;
  agentRegistry?: TyxtAgentRegistry | null;
}): TyxtHomeData {
  const tick = options.tick ?? 0;
  const nowIso = new Date().toISOString();
  const agentRoomByTick: TyxtRoomId[] = ['main_hall', 'workshop', 'observatory', 'study'];

  const fallbackAgents: TyxtRegistryAgent[] = [
    { agent_id: 'moyuan', display_name: 'Main Agent', enabled: true },
    { agent_id: 'agent-b', display_name: 'Agent-B', enabled: true },
    { agent_id: 'agent-c', display_name: 'Agent-C', enabled: true }
  ];

  const registryEnabledAgents = (options.agentRegistry?.agents ?? []).filter((agent) => agent.enabled !== false);
  const defaultAgentFromRegistry = String(options.agentRegistry?.default_agent_id ?? '').trim();

  const seedAgents = registryEnabledAgents.length > 0
    ? [...registryEnabledAgents]
    : fallbackAgents;

  if (defaultAgentFromRegistry) {
    seedAgents.sort((a, b) => {
      if (a.agent_id === defaultAgentFromRegistry) return -1;
      if (b.agent_id === defaultAgentFromRegistry) return 1;
      return 0;
    });
  }

  const agents: TyxtAgent[] = seedAgents.slice(0, 8).map((agent, index) => {
    const roomIndex = (tick + index) % agentRoomByTick.length;
    const status: TyxtAgent['status'] = (tick + index * 2) % 11 === 0 ? 'busy' : 'online';
    const moodPool: TyxtAgent['mood'][] = ['calm', 'focused', 'curious', 'tired'];

    return {
      agent_id: agent.agent_id,
      display_name: agent.display_name,
      status,
      mood: moodPool[(tick + index) % moodPool.length],
      current_room: index === 0 ? options.activeRoomId : agentRoomByTick[roomIndex]
    };
  });

  const preferredSelected = options.selectedAgentId
    ?? defaultAgentFromRegistry
    ?? agents[0]?.agent_id
    ?? null;

  const selectedAgentId = preferredSelected && agents.some((agent) => agent.agent_id === preferredSelected)
    ? preferredSelected
    : agents[0]?.agent_id ?? null;

  return {
    space: {
      id: options.activeRoomId,
      name: roomName(options.activeRoomId),
      description: ROOM_DEFS.find((room) => room.id === options.activeRoomId)?.description ?? ''
    },
    rooms: ROOM_DEFS.map((room) => ({
      id: room.id,
      name: room.name,
      icon: room.icon,
      enabled: room.enabled
    })),
    agents,
    system_status: statusCycle(tick),
    events: defaultEvents(options.activeRoomId, nowIso),
    messages: defaultMessages(nowIso),
    room_profiles: ROOM_PROFILES,
    quick_actions: QUICK_ACTIONS,
    selected_agent_id: selectedAgentId,
    connection_mode: 'local_mock',
    updated_at: nowIso
  };
}

export function mapOpenClawSnapshotToTyxtData(snapshot: OpenClawSnapshot, options?: {
  activeRoomId?: TyxtRoomId;
  selectedAgentId?: string | null;
}): TyxtHomeData {
  const fallbackRoom = options?.activeRoomId ?? mapLegacyResourceToTyxtRoom(snapshot.focus.resourceId);
  const nowIso = snapshot.generatedAt;

  const roomSignals = new Map<TyxtRoomId, { status: ResourceTelemetryStatus; count: number }>();
  for (const resource of snapshot.resources) {
    const roomId = mapLegacyResourceToTyxtRoom(resource.id);
    const existing = roomSignals.get(roomId);
    if (!existing) {
      roomSignals.set(roomId, { status: resource.status, count: resource.itemCount });
      continue;
    }

    const nextStatus = mergeTelemetryStatus(existing.status, resource.status);
    roomSignals.set(roomId, {
      status: nextStatus,
      count: existing.count + resource.itemCount
    });
  }

  const hasAlertSignal = [...roomSignals.values()].some((signal) => signal.status === 'alert');

  const agents: TyxtAgent[] = (snapshot.activeAgents ?? []).map((agent, index) => ({
    agent_id: agent.id,
    display_name: agent.label || `Agent-${index + 1}`,
    status: agent.status === 'running' ? 'busy' : agent.status === 'offline' ? 'offline' : 'online',
    mood: index % 2 === 0 ? 'focused' : 'calm',
    current_room: fallbackRoom
  }));

  const selectedAgentId = options?.selectedAgentId && agents.some((agent) => agent.agent_id === options.selectedAgentId)
    ? options.selectedAgentId
    : agents[0]?.agent_id ?? null;

  const backendStatus = snapshot.mode === 'live' ? 'online' : 'partial';

  const events: TyxtEvent[] = snapshot.recentEvents.slice(0, 6).map((event) => ({
    id: event.id,
    title: event.label,
    detail: event.detail,
    room_id: mapLegacyResourceToTyxtRoom(event.resourceId),
    occurred_at: event.occurredAt
  }));

  return {
    space: {
      id: fallbackRoom,
      name: roomName(fallbackRoom),
      description: ROOM_DEFS.find((room) => room.id === fallbackRoom)?.description ?? ''
    },
    rooms: ROOM_DEFS.map((room) => ({
      id: room.id,
      name: room.name,
      icon: room.icon,
      enabled: room.enabled
    })),
    agents,
    system_status: {
      backend: backendStatus,
      memory: 'ready',
      tools: hasAlertSignal ? 'partial' : 'online',
      idle_work: 'running'
    },
    events,
    messages: defaultMessages(nowIso),
    room_profiles: ROOM_PROFILES,
    quick_actions: QUICK_ACTIONS,
    selected_agent_id: selectedAgentId,
    connection_mode: snapshot.mode === 'live' ? 'legacy_bridge' : 'local_mock',
    updated_at: nowIso
  };
}

function mergeTelemetryStatus(a: ResourceTelemetryStatus, b: ResourceTelemetryStatus): ResourceTelemetryStatus {
  if (a === 'alert' || b === 'alert') return 'alert';
  if (a === 'active' || b === 'active') return 'active';
  if (a === 'offline' && b === 'offline') return 'offline';
  return 'idle';
}

function telemetryStatusForRoom(roomId: TyxtRoomId, data: TyxtHomeData): ResourceTelemetryStatus {
  if (roomId === data.space.id) {
    return 'active';
  }
  if (roomId === 'observatory' && data.system_status.backend !== 'online') {
    return 'alert';
  }
  if (roomId === 'message_wall') {
    return 'idle';
  }
  return 'idle';
}

export function buildLegacySceneSnapshot(data: TyxtHomeData): OpenClawSnapshot {
  const nowIso = data.updated_at;
  const focusLegacyResource = mapTyxtRoomToLegacyResource(data.space.id);

  const resources = LEGACY_RESOURCE_IDS.map((resourceId, index) => {
    const roomId = mapLegacyResourceToTyxtRoom(resourceId);
    const roomProfile = ROOM_PROFILES[roomId];
    const roomStatus = telemetryStatusForRoom(roomId, data);
    const isFocus = resourceId === focusLegacyResource;

    return {
      id: resourceId,
      label: roomName(roomId),
      status: isFocus ? 'active' : roomStatus,
      itemCount: 4 + ((index + data.events.length) % 9),
      lastAccessAt: nowIso,
      summary: roomProfile.description,
      detail: roomProfile.status_hint,
      source: `tyxt/${roomId}`,
      items: []
    };
  });

  const recentEvents: OpenClawAccessEvent[] = data.events.map((event, index) => ({
    id: `legacy-${event.id}-${index}`,
    resourceId: mapTyxtRoomToLegacyResource(event.room_id),
    label: event.title,
    occurredAt: event.occurred_at,
    detail: event.detail,
    status: event.room_id === data.space.id ? 'active' : 'idle',
    source: `tyxt/event/${event.room_id}`
  }));

  return {
    mode: 'mock',
    generatedAt: nowIso,
    resources,
    recentEvents,
    focus: {
      resourceId: focusLegacyResource,
      label: data.space.name,
      occurredAt: nowIso,
      detail: ROOM_PROFILES[data.space.id].status_hint,
      reason: 'tyxt-space-focus'
    },
    activeAgents: data.agents
      .filter((agent) => agent.status !== 'offline')
      .map((agent) => ({
        id: agent.agent_id,
        label: agent.display_name,
        status: agent.status
      })),
    activeProcesses: [],
    mainActorContext: {
      tokens: 52000 + data.events.length * 1300,
      maxTokens: 200000,
      remaining: 0.62
    }
  };
}

export function listTyxtInteractiveHotspots(roomId: TyxtRoomId): TyxtInteractivePoint[] {
  return ROOM_PROFILES[roomId].interactive_points;
}







