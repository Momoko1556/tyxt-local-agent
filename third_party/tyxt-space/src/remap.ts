import mapLogicSeed from './data/map.logic.json';
import type { MapLogic, Point, ResourcePartitionId, RoomBounds, WalkableZone, WorkZone, OccluderRect, WalkNode } from './core/types';

type EditorMode = 'rooms' | 'walkable' | 'occluders' | 'workzones' | 'graph';

type BackgroundOption = {
  id: string;
  label: string;
  src: string;
};

type DragState =
  | { kind: 'room-move'; roomId: ResourcePartitionId; offsetX: number; offsetY: number }
  | { kind: 'room-resize'; roomId: ResourcePartitionId }
  | { kind: 'label'; roomId: ResourcePartitionId }
  | { kind: 'walkable-point'; zoneId: string; pointIndex: number }
  | { kind: 'occluder-move'; occluderId: string; offsetX: number; offsetY: number }
  | { kind: 'occluder-resize'; occluderId: string }
  | { kind: 'workzone-anchor'; zoneId: ResourcePartitionId }
  | { kind: 'graph-node'; nodeId: string };

const backgrounds: BackgroundOption[] = [
  {
    id: 'default-floor',
    label: 'Default Floor',
    src: '/assets/packs/default/2026-03-09/scene-floor.png'
  },
  {
    id: 'default-objects',
    label: 'Default Objects',
    src: '/assets/packs/default/2026-03-09/scene-objects.png'
  }
];

const roomColors: Record<ResourcePartitionId, string> = {
  document: '#81a8ff',
  images: '#ffc17a',
  memory: '#a58aff',
  skills: '#7ce6c7',
  gateway: '#59d0ff',
  log: '#ff8aa5',
  mcp: '#5fe3ff',
  schedule: '#f4d06f',
  alarm: '#ff6978',
  agent: '#98f59d',
  task_queues: '#ffb16b',
  break_room: '#bec6db'
};

const sceneWidth = mapLogicSeed.meta.baseResolution.width;
const sceneHeight = mapLogicSeed.meta.baseResolution.height;
const defaultBackgroundHeight = 1072;
const handleSize = 12;
const STORAGE_KEY = 'clawlibrary-remap-workbench-v1';

const state: {
  map: MapLogic;
  mode: EditorMode;
  selectedRoomId: ResourcePartitionId | null;
  selectedWalkableId: string | null;
  selectedOccluderId: string | null;
  selectedWorkzoneId: ResourcePartitionId | null;
  selectedGraphNodeId: string | null;
  pendingGraphEdgeNodeId: string | null;
  drag: DragState | null;
  background: BackgroundOption;
  backgroundImage: HTMLImageElement | null;
} = {
  map: JSON.parse(JSON.stringify(mapLogicSeed)) as MapLogic,
  mode: 'rooms',
  selectedRoomId: (mapLogicSeed.rooms[0]?.id ?? null) as ResourcePartitionId | null,
  selectedWalkableId: mapLogicSeed.walkableZones?.[0]?.id ?? null,
  selectedOccluderId: mapLogicSeed.occluders?.[0]?.id ?? null,
  selectedWorkzoneId: (mapLogicSeed.workZones[0]?.id ?? null) as ResourcePartitionId | null,
  selectedGraphNodeId: mapLogicSeed.walkGraph.nodes[0]?.id ?? null,
  pendingGraphEdgeNodeId: null,
  drag: null,
  background: backgrounds[0],
  backgroundImage: null
};

const root = document.getElementById('root');
if (!root) {
  throw new Error('root not found');
}

root.innerHTML = `
  <aside class="sidebar">
    <div class="panel">
      <h2>Background</h2>
      <div class="row">
        <label for="bg-select">Base</label>
        <select id="bg-select"></select>
      </div>
      <div class="hint">Use this workbench to quickly remap room bounds, labels, walkable zones, graph nodes, occluders, and workzones whenever the base image changes.</div>
    </div>
    <div class="panel">
      <h2>Mode</h2>
      <div class="pill-list" id="mode-pills"></div>
    </div>
    <div class="panel">
      <h2>Selection</h2>
      <div id="selection-list"></div>
    </div>
    <div class="panel">
      <h2>Inspector</h2>
      <div id="inspector"></div>
    </div>
    <div class="panel">
      <h2>Export</h2>
      <div class="buttonbar">
        <button id="copy-json" type="button">Copy JSON</button>
        <button id="download-json" type="button">Download JSON</button>
        <button id="apply-json" type="button">Apply JSON</button>
        <button id="reset-map" type="button">Reset</button>
        <button id="clear-saved" type="button">Clear Saved</button>
      </div>
      <div class="hint" style="margin-top:10px;">
        Suggested workflow: switch to the new base image → adjust room bounds → align label anchors → sync room workzones → edit walkable zones / graph / occluders → export JSON → replace <code>src/data/map.logic.json</code>.
      </div>
      <div class="row" style="margin-top:12px;">
        <textarea id="json-preview" readonly></textarea>
      </div>
    </div>
  </aside>
  <main class="stage">
    <canvas id="canvas" width="${sceneWidth}" height="${sceneHeight}"></canvas>
  </main>
`;

const canvas = document.getElementById('canvas') as HTMLCanvasElement;
const context = canvas.getContext('2d');
if (!context) {
  throw new Error('2d context unavailable');
}
const ctx = context;

const bgSelect = document.getElementById('bg-select') as HTMLSelectElement;
const modePills = document.getElementById('mode-pills') as HTMLDivElement;
const selectionList = document.getElementById('selection-list') as HTMLDivElement;
const inspector = document.getElementById('inspector') as HTMLDivElement;
const jsonPreview = document.getElementById('json-preview') as HTMLTextAreaElement;
const copyButton = document.getElementById('copy-json') as HTMLButtonElement;
const downloadButton = document.getElementById('download-json') as HTMLButtonElement;
const applyButton = document.getElementById('apply-json') as HTMLButtonElement;
const resetButton = document.getElementById('reset-map') as HTMLButtonElement;
const clearSavedButton = document.getElementById('clear-saved') as HTMLButtonElement;

function getPointerPoint(event: MouseEvent): Point {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * sceneWidth,
    y: ((event.clientY - rect.top) / rect.height) * sceneHeight
  };
}

function fillBackground() {
  ctx.fillStyle = '#030817';
  ctx.fillRect(0, 0, sceneWidth, sceneHeight);
  if (state.backgroundImage) {
    ctx.drawImage(state.backgroundImage, 0, 0, sceneWidth, defaultBackgroundHeight);
  }
}

function drawGrid() {
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.07)';
  ctx.lineWidth = 1;
  ctx.fillStyle = 'rgba(255,255,255,0.45)';
  ctx.font = '12px Inter, sans-serif';
  for (let x = 0; x <= sceneWidth; x += 100) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, sceneHeight);
    ctx.stroke();
    ctx.fillText(String(x), x + 4, 14);
  }
  for (let y = 0; y <= sceneHeight; y += 100) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(sceneWidth, y);
    ctx.stroke();
    ctx.fillText(String(y), 4, Math.max(14, y - 4));
  }
  ctx.restore();
}

function drawRooms() {
  for (const room of state.map.rooms) {
    const [x, y, width, height] = room.bounds;
    const color = roomColors[room.id];
    ctx.save();
    ctx.fillStyle = `${color}22`;
    ctx.strokeStyle = color;
    ctx.lineWidth = room.id === state.selectedRoomId ? 3 : 2;
    ctx.strokeRect(x, y, width, height);
    ctx.fillRect(x, y, width, height);
    const label = room.labelAnchor ?? { x: x + width / 2, y: y + 20 };
    ctx.fillStyle = color;
    ctx.font = '16px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(room.id, label.x, label.y);
    ctx.beginPath();
    ctx.arc(label.x, label.y + 6, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeRect(x + width - handleSize, y + height - handleSize, handleSize, handleSize);
    ctx.restore();
  }
}

function drawWalkable() {
  for (const zone of state.map.walkableZones ?? []) {
    if (zone.points.length < 2) {
      continue;
    }
    ctx.save();
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.strokeStyle = zone.id === state.selectedWalkableId ? '#ffffff' : '#d8f3ff';
    ctx.lineWidth = zone.id === state.selectedWalkableId ? 3 : 2;
    ctx.beginPath();
    ctx.moveTo(zone.points[0].x, zone.points[0].y);
    for (let index = 1; index < zone.points.length; index += 1) {
      ctx.lineTo(zone.points[index].x, zone.points[index].y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    for (const point of zone.points) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }
}

function drawOccluders() {
  for (const occluder of state.map.occluders) {
    ctx.save();
    ctx.fillStyle = 'rgba(255, 77, 79, 0.18)';
    ctx.strokeStyle = occluder.id === state.selectedOccluderId ? '#ffd0d2' : '#ff4d4f';
    ctx.lineWidth = occluder.id === state.selectedOccluderId ? 3 : 2;
    ctx.fillRect(occluder.x, occluder.y, occluder.width, occluder.height);
    ctx.strokeRect(occluder.x, occluder.y, occluder.width, occluder.height);
    ctx.strokeRect(occluder.x + occluder.width - handleSize, occluder.y + occluder.height - handleSize, handleSize, handleSize);
    ctx.restore();
  }
}

function drawWorkzones() {
  for (const zone of state.map.workZones) {
    ctx.save();
    ctx.strokeStyle = roomColors[zone.id];
    ctx.fillStyle = `${roomColors[zone.id]}33`;
    ctx.lineWidth = zone.id === state.selectedWorkzoneId ? 3 : 2;
    ctx.beginPath();
    ctx.arc(zone.anchor.x, zone.anchor.y, zone.radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = roomColors[zone.id];
    ctx.font = '14px Inter, sans-serif';
    ctx.fillText(zone.id, zone.anchor.x + zone.radius + 4, zone.anchor.y + 4);
    ctx.restore();
  }
}

function drawGraph() {
  const nodeMap = new Map(state.map.walkGraph.nodes.map((node) => [node.id, node]));
  ctx.save();
  ctx.strokeStyle = '#ffe480';
  ctx.lineWidth = 3;
  for (const [fromId, toId] of state.map.walkGraph.edges) {
    const from = nodeMap.get(fromId);
    const to = nodeMap.get(toId);
    if (!from || !to) {
      continue;
    }
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }
  for (const node of state.map.walkGraph.nodes) {
    ctx.fillStyle = node.id === state.selectedGraphNodeId ? '#ffffff' : '#ffe480';
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.id === state.selectedGraphNodeId ? 8 : 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#fff7cc';
    ctx.font = '12px Inter, sans-serif';
    ctx.fillText(node.id, node.x + 8, node.y - 8);
  }
  ctx.restore();
}

function renderCanvas() {
  fillBackground();
  drawGrid();
  drawWalkable();
  drawGraph();
  drawOccluders();
  drawWorkzones();
  drawRooms();
}

function renderModePills() {
  const modes: EditorMode[] = ['rooms', 'walkable', 'graph', 'occluders', 'workzones'];
  modePills.innerHTML = modes.map((mode) => `
    <button class="pill ${mode === state.mode ? 'active' : ''}" data-mode="${mode}" type="button">${mode}</button>
  `).join('');
}

function renderSelectionList() {
  if (state.mode === 'rooms') {
    selectionList.innerHTML = `<div class="pill-list">${state.map.rooms.map((room) => `<button class="pill ${room.id === state.selectedRoomId ? 'active' : ''}" data-room-id="${room.id}" type="button">${room.id}</button>`).join('')}</div>`;
    return;
  }
  if (state.mode === 'walkable') {
    selectionList.innerHTML = `<div class="pill-list">${(state.map.walkableZones ?? []).map((zone) => `<button class="pill ${zone.id === state.selectedWalkableId ? 'active' : ''}" data-walkable-id="${zone.id}" type="button">${zone.id}</button>`).join('')}</div>`;
    return;
  }
  if (state.mode === 'occluders') {
    selectionList.innerHTML = `<div class="pill-list">${state.map.occluders.map((entry) => `<button class="pill ${entry.id === state.selectedOccluderId ? 'active' : ''}" data-occluder-id="${entry.id}" type="button">${entry.id}</button>`).join('')}</div>`;
    return;
  }
  if (state.mode === 'graph') {
    selectionList.innerHTML = `<div class="pill-list">${state.map.walkGraph.nodes.map((entry) => `<button class="pill ${entry.id === state.selectedGraphNodeId ? 'active' : ''}" data-graph-node-id="${entry.id}" type="button">${entry.id}</button>`).join('')}</div>`;
    return;
  }
  selectionList.innerHTML = `<div class="pill-list">${state.map.workZones.map((entry) => `<button class="pill ${entry.id === state.selectedWorkzoneId ? 'active' : ''}" data-workzone-id="${entry.id}" type="button">${entry.id}</button>`).join('')}</div>`;
}

function numberRow(label: string, key: string, value: number) {
  return `<div class="row"><label>${label}</label><input data-field="${key}" type="number" step="1" value="${Math.round(value)}" /></div>`;
}

function renderInspector() {
  if (state.mode === 'rooms') {
    const room = state.map.rooms.find((entry) => entry.id === state.selectedRoomId);
    if (!room) {
      inspector.innerHTML = '<div class="hint">Select a room.</div>';
      return;
    }
    const [x, y, width, height] = room.bounds;
    const label = room.labelAnchor ?? { x: x + width / 2, y: y + 20 };
    inspector.innerHTML = [
      `<h3>${room.id}</h3>`,
      numberRow('x', 'room.x', x),
      numberRow('y', 'room.y', y),
      numberRow('w', 'room.w', width),
      numberRow('h', 'room.h', height),
      numberRow('label x', 'room.labelX', label.x),
      numberRow('label y', 'room.labelY', label.y),
      '<div class="buttonbar"><button id="sync-room-label" type="button">Center Label</button><button id="sync-room-workzone" type="button">Sync Workzone</button></div>',
      '<div class="hint">Drag inside room to move. Drag bottom-right handle to resize. Drag label dot to move label.</div>'
    ].join('');
    return;
  }

  if (state.mode === 'walkable') {
    const zone = (state.map.walkableZones ?? []).find((entry) => entry.id === state.selectedWalkableId);
    if (!zone) {
      inspector.innerHTML = '<div class="hint">Select a walkable zone.</div>';
      return;
    }
    inspector.innerHTML = [
      `<h3>${zone.id}</h3>`,
      '<div class="buttonbar"><button id="add-walkable-zone" type="button">Add Zone</button><button id="remove-walkable-zone" type="button">Remove Zone</button><button id="add-walkable-point" type="button">Add Point</button><button id="remove-walkable-point" type="button">Remove Last</button></div>',
      '<div class="hint" style="margin-top:8px;">Drag points directly on canvas. Use Add Point to append a point at the canvas center.</div>'
    ].join('');
    return;
  }

  if (state.mode === 'occluders') {
    const occluder = state.map.occluders.find((entry) => entry.id === state.selectedOccluderId);
    if (!occluder) {
      inspector.innerHTML = '<div class="hint">Select an occluder.</div>';
      return;
    }
    inspector.innerHTML = [
      `<h3>${occluder.id}</h3>`,
      numberRow('x', 'occluder.x', occluder.x),
      numberRow('y', 'occluder.y', occluder.y),
      numberRow('w', 'occluder.w', occluder.width),
      numberRow('h', 'occluder.h', occluder.height),
      '<div class="buttonbar"><button id="add-occluder" type="button">Add Occluder</button><button id="remove-occluder" type="button">Remove Occluder</button></div>',
      '<div class="hint">Drag inside rect to move. Drag bottom-right handle to resize.</div>'
    ].join('');
    return;
  }

  if (state.mode === 'graph') {
    const node = graphNodeById(state.selectedGraphNodeId);
    if (!node) {
      inspector.innerHTML = '<div class="hint">Select a graph node.</div>';
      return;
    }
    inspector.innerHTML = [
      `<h3>${node.id}</h3>`,
      numberRow('x', 'graph.x', node.x),
      numberRow('y', 'graph.y', node.y),
      `<div class="row"><label>room</label><select data-field="graph.roomId">${state.map.rooms.map((room) => `<option value="${room.id}" ${room.id === node.roomId ? 'selected' : ''}>${room.id}</option>`).join('')}</select></div>`,
      `<div class="row"><label>pair</label><select data-field="graph.edgePeer"><option value="">none</option>${state.map.walkGraph.nodes.filter((entry) => entry.id !== node.id).map((entry) => `<option value="${entry.id}" ${entry.id === state.pendingGraphEdgeNodeId ? 'selected' : ''}>${entry.id}</option>`).join('')}</select></div>`,
      '<div class="buttonbar"><button id="add-graph-node" type="button">Add Node</button><button id="remove-graph-node" type="button">Remove Node</button><button id="toggle-graph-edge" type="button">Toggle Edge</button></div>',
      '<div class="hint" style="margin-top:8px;">Drag nodes directly on canvas. Use pair + Toggle Edge to connect/disconnect selected nodes.</div>'
    ].join('');
    return;
  }

  const zone = state.map.workZones.find((entry) => entry.id === state.selectedWorkzoneId);
  if (!zone) {
    inspector.innerHTML = '<div class="hint">Select a workzone.</div>';
    return;
  }
  inspector.innerHTML = [
    `<h3>${zone.id}</h3>`,
    numberRow('anchor x', 'workzone.x', zone.anchor.x),
    numberRow('anchor y', 'workzone.y', zone.anchor.y),
    numberRow('radius', 'workzone.r', zone.radius),
    '<div class="buttonbar"><button id="add-workzone" type="button">Add Workzone</button><button id="remove-workzone" type="button">Remove Workzone</button></div>',
    '<div class="hint">Drag the zone circle to move its anchor.</div>'
  ].join('');
}

function updateJsonPreview() {
  jsonPreview.value = JSON.stringify(state.map, null, 2);
  try {
    localStorage.setItem(STORAGE_KEY, jsonPreview.value);
  } catch {
    // ignore storage failures
  }
}

function renderAll() {
  renderModePills();
  renderSelectionList();
  renderInspector();
  updateJsonPreview();
  renderCanvas();
}

function loadBackground(option: BackgroundOption) {
  const image = new Image();
  image.onload = () => {
    state.backgroundImage = image;
    renderCanvas();
  };
  image.src = option.src;
}

function roomById(id: ResourcePartitionId | null): RoomBounds | undefined {
  return state.map.rooms.find((room) => room.id === id);
}

function walkableById(id: string | null): WalkableZone | undefined {
  return (state.map.walkableZones ?? []).find((zone) => zone.id === id);
}

function occluderById(id: string | null): OccluderRect | undefined {
  return state.map.occluders.find((entry) => entry.id === id);
}

function workzoneById(id: ResourcePartitionId | null): WorkZone | undefined {
  return state.map.workZones.find((entry) => entry.id === id);
}

function graphNodeById(id: string | null): WalkNode | undefined {
  return state.map.walkGraph.nodes.find((node) => node.id === id);
}

function hitRoom(point: Point) {
  return state.map.rooms.find((room) => {
    const [x, y, width, height] = room.bounds;
    return point.x >= x && point.x <= x + width && point.y >= y && point.y <= y + height;
  }) ?? null;
}

function hitWalkablePoint(point: Point) {
  for (const zone of state.map.walkableZones ?? []) {
    for (let index = 0; index < zone.points.length; index += 1) {
      const target = zone.points[index];
      if (Math.hypot(point.x - target.x, point.y - target.y) <= 10) {
        return { zone, pointIndex: index };
      }
    }
  }
  return null;
}

function hitOccluder(point: Point) {
  return state.map.occluders.find((entry) =>
    point.x >= entry.x && point.x <= entry.x + entry.width && point.y >= entry.y && point.y <= entry.y + entry.height
  ) ?? null;
}

function hitWorkzone(point: Point) {
  return state.map.workZones.find((zone) => Math.hypot(point.x - zone.anchor.x, point.y - zone.anchor.y) <= zone.radius) ?? null;
}

function hitGraphNode(point: Point) {
  return state.map.walkGraph.nodes.find((node) => Math.hypot(point.x - node.x, point.y - node.y) <= 10) ?? null;
}

canvas.addEventListener('mousedown', (event) => {
  const point = getPointerPoint(event);

  if (state.mode === 'rooms') {
    const room = hitRoom(point);
    if (!room) {
      return;
    }
    state.selectedRoomId = room.id;
    const [x, y, width, height] = room.bounds;
    const label = room.labelAnchor ?? { x: x + width / 2, y: y + 20 };

    if (Math.abs(point.x - (x + width)) <= handleSize && Math.abs(point.y - (y + height)) <= handleSize) {
      state.drag = { kind: 'room-resize', roomId: room.id };
    } else if (Math.hypot(point.x - label.x, point.y - (label.y + 6)) <= 12) {
      state.drag = { kind: 'label', roomId: room.id };
    } else {
      state.drag = { kind: 'room-move', roomId: room.id, offsetX: point.x - x, offsetY: point.y - y };
    }
    renderAll();
    return;
  }

  if (state.mode === 'walkable') {
    const hit = hitWalkablePoint(point);
    if (!hit) {
      return;
    }
    state.selectedWalkableId = hit.zone.id;
    state.drag = { kind: 'walkable-point', zoneId: hit.zone.id, pointIndex: hit.pointIndex };
    renderAll();
    return;
  }

  if (state.mode === 'occluders') {
    const occluder = hitOccluder(point);
    if (!occluder) {
      return;
    }
    state.selectedOccluderId = occluder.id;
    if (Math.abs(point.x - (occluder.x + occluder.width)) <= handleSize && Math.abs(point.y - (occluder.y + occluder.height)) <= handleSize) {
      state.drag = { kind: 'occluder-resize', occluderId: occluder.id };
    } else {
      state.drag = { kind: 'occluder-move', occluderId: occluder.id, offsetX: point.x - occluder.x, offsetY: point.y - occluder.y };
    }
    renderAll();
    return;
  }

  if (state.mode === 'graph') {
    const node = hitGraphNode(point);
    if (!node) {
      return;
    }
    if (event.shiftKey && state.selectedGraphNodeId && state.selectedGraphNodeId !== node.id) {
      state.pendingGraphEdgeNodeId = node.id;
    } else {
      state.selectedGraphNodeId = node.id;
    }
    state.drag = { kind: 'graph-node', nodeId: node.id };
    renderAll();
    return;
  }

  const workzone = hitWorkzone(point);
  if (workzone) {
    state.selectedWorkzoneId = workzone.id;
    state.drag = { kind: 'workzone-anchor', zoneId: workzone.id };
    renderAll();
  }
});

window.addEventListener('mousemove', (event) => {
  if (!state.drag) {
    return;
  }

  const point = getPointerPoint(event);
  if (state.drag.kind === 'room-move') {
    const room = roomById(state.drag.roomId);
    if (!room) {
      return;
    }
    const [, , width, height] = room.bounds;
    room.bounds = [Math.round(point.x - state.drag.offsetX), Math.round(point.y - state.drag.offsetY), width, height];
    renderAll();
    return;
  }
  if (state.drag.kind === 'room-resize') {
    const room = roomById(state.drag.roomId);
    if (!room) {
      return;
    }
    const [x, y] = room.bounds;
    room.bounds = [x, y, Math.max(40, Math.round(point.x - x)), Math.max(40, Math.round(point.y - y))];
    renderAll();
    return;
  }
  if (state.drag.kind === 'label') {
    const room = roomById(state.drag.roomId);
    if (!room) {
      return;
    }
    room.labelAnchor = { x: Math.round(point.x), y: Math.round(point.y - 6) };
    renderAll();
    return;
  }
  if (state.drag.kind === 'walkable-point') {
    const zone = walkableById(state.drag.zoneId);
    if (!zone) {
      return;
    }
    zone.points[state.drag.pointIndex] = { x: Math.round(point.x), y: Math.round(point.y) };
    renderAll();
    return;
  }
  if (state.drag.kind === 'occluder-move') {
    const occluder = occluderById(state.drag.occluderId);
    if (!occluder) {
      return;
    }
    occluder.x = Math.round(point.x - state.drag.offsetX);
    occluder.y = Math.round(point.y - state.drag.offsetY);
    renderAll();
    return;
  }
  if (state.drag.kind === 'occluder-resize') {
    const occluder = occluderById(state.drag.occluderId);
    if (!occluder) {
      return;
    }
    occluder.width = Math.max(10, Math.round(point.x - occluder.x));
    occluder.height = Math.max(10, Math.round(point.y - occluder.y));
    renderAll();
    return;
  }
  if (state.drag.kind === 'workzone-anchor') {
    const zone = workzoneById(state.drag.zoneId);
    if (!zone) {
      return;
    }
    zone.anchor = { x: Math.round(point.x), y: Math.round(point.y) };
    renderAll();
    return;
  }
  if (state.drag.kind === 'graph-node') {
    const node = graphNodeById(state.drag.nodeId);
    if (!node) {
      return;
    }
    node.x = Math.round(point.x);
    node.y = Math.round(point.y);
    renderAll();
  }
});

window.addEventListener('mouseup', () => {
  state.drag = null;
});

selectionList.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const roomId = target.closest('[data-room-id]')?.getAttribute('data-room-id') as ResourcePartitionId | null;
  const walkableId = target.closest('[data-walkable-id]')?.getAttribute('data-walkable-id');
  const occluderId = target.closest('[data-occluder-id]')?.getAttribute('data-occluder-id');
  const graphNodeId = target.closest('[data-graph-node-id]')?.getAttribute('data-graph-node-id');
  const workzoneId = target.closest('[data-workzone-id]')?.getAttribute('data-workzone-id') as ResourcePartitionId | null;
  if (roomId) state.selectedRoomId = roomId;
  if (walkableId) state.selectedWalkableId = walkableId;
  if (occluderId) state.selectedOccluderId = occluderId;
  if (graphNodeId) state.selectedGraphNodeId = graphNodeId;
  if (workzoneId) state.selectedWorkzoneId = workzoneId;
  renderAll();
});

modePills.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const mode = target.closest('[data-mode]')?.getAttribute('data-mode') as EditorMode | null;
  if (!mode) {
    return;
  }
  state.mode = mode;
  renderAll();
});

inspector.addEventListener('input', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) {
    return;
  }
  const field = target.dataset.field;
  if (!field) {
    return;
  }
  const value = Number(target.value);

  if (field.startsWith('room.')) {
    const room = roomById(state.selectedRoomId);
    if (!room) {
      return;
    }
    const [x, y, width, height] = room.bounds;
    const label = room.labelAnchor ?? { x: x + width / 2, y: y + 20 };
    if (field === 'room.x') room.bounds = [value, y, width, height];
    if (field === 'room.y') room.bounds = [x, value, width, height];
    if (field === 'room.w') room.bounds = [x, y, value, height];
    if (field === 'room.h') room.bounds = [x, y, width, value];
    if (field === 'room.labelX') room.labelAnchor = { x: value, y: label.y };
    if (field === 'room.labelY') room.labelAnchor = { x: label.x, y: value };
  }

  if (field.startsWith('occluder.')) {
    const occluder = occluderById(state.selectedOccluderId);
    if (!occluder) {
      return;
    }
    if (field === 'occluder.x') occluder.x = value;
    if (field === 'occluder.y') occluder.y = value;
    if (field === 'occluder.w') occluder.width = value;
    if (field === 'occluder.h') occluder.height = value;
  }

  if (field.startsWith('workzone.')) {
    const zone = workzoneById(state.selectedWorkzoneId);
    if (!zone) {
      return;
    }
    if (field === 'workzone.x') zone.anchor.x = value;
    if (field === 'workzone.y') zone.anchor.y = value;
    if (field === 'workzone.r') zone.radius = value;
  }

  if (field.startsWith('graph.')) {
    const node = graphNodeById(state.selectedGraphNodeId);
    if (!node) {
      return;
    }
    if (field === 'graph.roomId') {
      node.roomId = target.value as ResourcePartitionId;
      renderAll();
      return;
    }
    if (field === 'graph.edgePeer') {
      state.pendingGraphEdgeNodeId = target.value || null;
      renderAll();
      return;
    }
    if (Number.isNaN(value)) {
      return;
    }
    if (field === 'graph.x') node.x = value;
    if (field === 'graph.y') node.y = value;
  }

  renderAll();
});

inspector.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.id === 'add-walkable-point') {
    const zone = walkableById(state.selectedWalkableId);
    zone?.points.push({ x: sceneWidth / 2, y: sceneHeight / 2 });
    renderAll();
  }
  if (target.id === 'add-walkable-zone') {
    const id = `walkable-${(state.map.walkableZones?.length ?? 0) + 1}`;
    const nextZone: WalkableZone = {
      id,
      points: [
        { x: 700, y: 700 },
        { x: 900, y: 700 },
        { x: 900, y: 860 },
        { x: 700, y: 860 }
      ]
    };
    state.map.walkableZones = [...(state.map.walkableZones ?? []), nextZone];
    state.selectedWalkableId = id;
    renderAll();
  }
  if (target.id === 'remove-walkable-zone') {
    if (!state.selectedWalkableId) {
      return;
    }
    state.map.walkableZones = (state.map.walkableZones ?? []).filter((zone) => zone.id !== state.selectedWalkableId);
    state.selectedWalkableId = state.map.walkableZones?.[0]?.id ?? null;
    renderAll();
  }
  if (target.id === 'remove-walkable-point') {
    const zone = walkableById(state.selectedWalkableId);
    zone?.points.pop();
    renderAll();
  }
  if (target.id === 'sync-room-label') {
    const room = roomById(state.selectedRoomId);
    if (!room) {
      return;
    }
    const [x, y, width] = room.bounds;
    room.labelAnchor = { x: Math.round(x + width / 2), y: Math.round(y + 20) };
    renderAll();
  }
  if (target.id === 'sync-room-workzone') {
    const room = roomById(state.selectedRoomId);
    if (!room) {
      return;
    }
    const [x, y, width, height] = room.bounds;
    const nextAnchor = { x: Math.round(x + width / 2), y: Math.round(y + height / 2) };
    const existing = workzoneById(room.id);
    if (existing) {
      existing.anchor = nextAnchor;
      existing.roomId = room.id;
      existing.type = room.id;
      existing.label = room.label;
    } else {
      state.map.workZones.push({
        id: room.id,
        label: room.label,
        roomId: room.id,
        type: room.id,
        anchor: nextAnchor,
        radius: 24
      });
      state.selectedWorkzoneId = room.id;
    }
    renderAll();
  }
  if (target.id === 'add-occluder') {
    const id = `occluder-${state.map.occluders.length + 1}`;
    state.map.occluders.push({ id, x: 200, y: 200, width: 120, height: 24 });
    state.selectedOccluderId = id;
    renderAll();
  }
  if (target.id === 'remove-occluder') {
    if (!state.selectedOccluderId) {
      return;
    }
    state.map.occluders = state.map.occluders.filter((entry) => entry.id !== state.selectedOccluderId);
    state.selectedOccluderId = state.map.occluders[0]?.id ?? null;
    renderAll();
  }
  if (target.id === 'add-graph-node') {
    const roomId = state.selectedRoomId ?? state.map.rooms[0]?.id ?? 'document';
    const id = `N${state.map.walkGraph.nodes.length + 1}`;
    state.map.walkGraph.nodes.push({ id, x: Math.round(sceneWidth / 2), y: Math.round(sceneHeight / 2), roomId });
    state.selectedGraphNodeId = id;
    renderAll();
  }
  if (target.id === 'remove-graph-node') {
    if (!state.selectedGraphNodeId) {
      return;
    }
    state.map.walkGraph.nodes = state.map.walkGraph.nodes.filter((node) => node.id !== state.selectedGraphNodeId);
    state.map.walkGraph.edges = state.map.walkGraph.edges.filter(([fromId, toId]) => fromId !== state.selectedGraphNodeId && toId !== state.selectedGraphNodeId);
    state.selectedGraphNodeId = state.map.walkGraph.nodes[0]?.id ?? null;
    state.pendingGraphEdgeNodeId = null;
    renderAll();
  }
  if (target.id === 'toggle-graph-edge') {
    const fromId = state.selectedGraphNodeId;
    const toId = state.pendingGraphEdgeNodeId;
    if (!fromId || !toId || fromId === toId) {
      return;
    }
    const exists = state.map.walkGraph.edges.some(([a, b]) => (a === fromId && b === toId) || (a === toId && b === fromId));
    if (exists) {
      state.map.walkGraph.edges = state.map.walkGraph.edges.filter(([a, b]) => !((a === fromId && b === toId) || (a === toId && b === fromId)));
    } else {
      state.map.walkGraph.edges.push([fromId, toId]);
    }
    renderAll();
  }
  if (target.id === 'add-workzone') {
    const roomId = state.selectedRoomId ?? state.map.rooms[0]?.id ?? 'document';
    const id = roomId;
    if (state.map.workZones.some((entry) => entry.id === id)) {
      return;
    }
    state.map.workZones.push({
      id,
      label: roomId,
      roomId,
      type: roomId,
      anchor: { x: 300, y: 300 },
      radius: 24
    });
    state.selectedWorkzoneId = id;
    renderAll();
  }
  if (target.id === 'remove-workzone') {
    if (!state.selectedWorkzoneId) {
      return;
    }
    state.map.workZones = state.map.workZones.filter((entry) => entry.id !== state.selectedWorkzoneId);
    state.selectedWorkzoneId = state.map.workZones[0]?.id ?? null;
    renderAll();
  }
});

copyButton.addEventListener('click', async () => {
  await navigator.clipboard.writeText(JSON.stringify(state.map, null, 2));
});

downloadButton.addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(state.map, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'map.logic.edited.json';
  link.click();
  URL.revokeObjectURL(url);
});

resetButton.addEventListener('click', () => {
  state.map = JSON.parse(JSON.stringify(mapLogicSeed)) as MapLogic;
  renderAll();
});

applyButton.addEventListener('click', () => {
  try {
    const next = JSON.parse(jsonPreview.value) as MapLogic;
    state.map = next;
    state.selectedRoomId = next.rooms[0]?.id ?? null;
    state.selectedWalkableId = next.walkableZones?.[0]?.id ?? null;
    state.selectedOccluderId = next.occluders[0]?.id ?? null;
    state.selectedWorkzoneId = next.workZones[0]?.id ?? null;
    state.selectedGraphNodeId = next.walkGraph.nodes[0]?.id ?? null;
    renderAll();
  } catch (error) {
    alert(`Invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
});

clearSavedButton.addEventListener('click', () => {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failures
  }
});

bgSelect.innerHTML = backgrounds.map((option) => `<option value="${option.id}">${option.label}</option>`).join('');
bgSelect.addEventListener('change', () => {
  const next = backgrounds.find((entry) => entry.id === bgSelect.value);
  if (!next) {
    return;
  }
  state.background = next;
  loadBackground(next);
});

bgSelect.value = state.background.id;
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    state.map = JSON.parse(saved) as MapLogic;
    state.selectedRoomId = state.map.rooms[0]?.id ?? null;
    state.selectedWalkableId = state.map.walkableZones?.[0]?.id ?? null;
    state.selectedOccluderId = state.map.occluders[0]?.id ?? null;
    state.selectedWorkzoneId = state.map.workZones[0]?.id ?? null;
    state.selectedGraphNodeId = state.map.walkGraph.nodes[0]?.id ?? null;
  }
} catch {
  // ignore storage failures
}
loadBackground(state.background);
renderAll();
