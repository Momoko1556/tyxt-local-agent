import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');

const mapLogicPath = path.join(root, 'src/data/map.logic.json');
const assetManifestPath = path.join(root, 'src/data/asset.manifest.json');
const sceneArtPath = path.join(root, 'src/data/scene-art.manifest.json');
const themePackPath = path.join(root, 'src/data/themes/default/theme-pack.json');
const workOutputPath = path.join(root, 'src/data/work-output.protocol.json');

const mapLogic = JSON.parse(fs.readFileSync(mapLogicPath, 'utf8'));
const manifest = JSON.parse(fs.readFileSync(assetManifestPath, 'utf8'));
const sceneArt = JSON.parse(fs.readFileSync(sceneArtPath, 'utf8'));
const themePack = JSON.parse(fs.readFileSync(themePackPath, 'utf8'));
const workOutput = JSON.parse(fs.readFileSync(workOutputPath, 'utf8'));

const issues = [];
const allowedRenderLayers = new Set(['floor', 'back_walls', 'mid_props', 'actor', 'fg_occluder', 'fx_overlay']);
const allowedAssetLayers = new Set(['ground', 'mid', 'fg_occluder', ...allowedRenderLayers]);
const publicRoot = path.join(root, 'public');

if (!Array.isArray(mapLogic.walkGraph?.nodes) || mapLogic.walkGraph.nodes.length < 2) {
  issues.push('walkGraph.nodes must have at least 2 nodes');
}

if (!Array.isArray(mapLogic.walkGraph?.edges) || mapLogic.walkGraph.edges.length < 1) {
  issues.push('walkGraph.edges must have at least 1 edge');
}

if (mapLogic.renderLayers) {
  if (!Array.isArray(mapLogic.renderLayers) || mapLogic.renderLayers.length < 4) {
    issues.push('renderLayers must contain at least 4 layer definitions when present');
  }

  const seenRenderLayers = new Set();
  for (const layer of mapLogic.renderLayers ?? []) {
    if (!allowedRenderLayers.has(layer.id)) {
      issues.push(`render layer ${layer.id} is not recognized`);
    }
    if (seenRenderLayers.has(layer.id)) {
      issues.push(`render layer ${layer.id} is duplicated`);
    }
    seenRenderLayers.add(layer.id);
    if (typeof layer.depth !== 'number') {
      issues.push(`render layer ${layer.id} must include numeric depth`);
    }
  }
}

if (mapLogic.walkableZones) {
  if (!Array.isArray(mapLogic.walkableZones) || mapLogic.walkableZones.length < 1) {
    issues.push('walkableZones must include at least 1 polygon when present');
  }
  for (const zone of mapLogic.walkableZones ?? []) {
    if (!Array.isArray(zone.points) || zone.points.length < 3) {
      issues.push(`walkable zone ${zone.id} must contain at least 3 points`);
    }
  }
}

const nodeIds = new Set((mapLogic.walkGraph?.nodes ?? []).map((node) => node.id));
for (const edge of mapLogic.walkGraph?.edges ?? []) {
  const [fromId, toId] = edge;
  if (!nodeIds.has(fromId) || !nodeIds.has(toId)) {
    issues.push(`edge references missing node: ${fromId}-${toId}`);
  }
}

const roomIds = new Set((mapLogic.rooms ?? []).map((room) => room.id));

if (!Array.isArray(mapLogic.workZones) || mapLogic.workZones.length < 1) {
  issues.push('map.logic workZones must include at least 1 inherited work area');
}

const zoneTypes = new Set();
for (const zone of mapLogic.workZones ?? []) {
  zoneTypes.add(zone.type);
  if (!roomIds.has(zone.roomId)) {
    issues.push(`work zone ${zone.id} references unknown roomId ${zone.roomId}`);
  }
  if (typeof zone.radius !== 'number' || zone.radius < 12) {
    issues.push(`work zone ${zone.id} radius must be >= 12`);
  }
}

for (const asset of manifest.assets ?? []) {
  if (!roomIds.has(asset.roomId)) {
    issues.push(`asset ${asset.id} references unknown roomId ${asset.roomId}`);
  }

  if (!allowedAssetLayers.has(asset.layer)) {
    issues.push(`asset ${asset.id} uses unsupported layer ${asset.layer}`);
  }

  if (!Array.isArray(asset.hitPolygon) || asset.hitPolygon.length < 3) {
    issues.push(`asset ${asset.id} hitPolygon must contain at least 3 points`);
  }

  if (asset.footpoint) {
    if (typeof asset.footpoint.x !== 'number' || typeof asset.footpoint.y !== 'number') {
      issues.push(`asset ${asset.id} footpoint must include numeric x/y`);
    }
  }

  if (asset.occupancyBox) {
    if (!Array.isArray(asset.occupancyBox) || asset.occupancyBox.length !== 4) {
      issues.push(`asset ${asset.id} occupancyBox must be [x1, y1, x2, y2]`);
    }
  }

  if (asset.visibleBBox) {
    if (!Array.isArray(asset.visibleBBox) || asset.visibleBBox.length !== 4) {
      issues.push(`asset ${asset.id} visibleBBox must be [x1, y1, x2, y2]`);
    }
  }

  if (asset.displaySize) {
    if (typeof asset.displaySize.width !== 'number' || typeof asset.displaySize.height !== 'number') {
      issues.push(`asset ${asset.id} displaySize must contain numeric width/height`);
    }
  }

  if (asset.depthBand && typeof asset.depthBand !== 'number') {
    issues.push(`asset ${asset.id} depthBand must be numeric`);
  }
}

if (!Array.isArray(sceneArt.roomSlices)) {
  issues.push('scene-art manifest must define roomSlices array');
}

if ((sceneArt.roomSlices?.length ?? 0) < 1 && (sceneArt.conceptRefs?.length ?? 0) < 1) {
  issues.push('scene-art manifest must include at least 1 room slice or 1 concept/background reference');
}

for (const slice of sceneArt.roomSlices ?? []) {
  if (!roomIds.has(slice.roomId)) {
    issues.push(`scene-art slice ${slice.id} references unknown roomId ${slice.roomId}`);
  }

  if (!Array.isArray(slice.replacesLayers) || slice.replacesLayers.length < 1) {
    issues.push(`scene-art slice ${slice.id} must define replacesLayers`);
  }

  for (const layerId of slice.replacesLayers ?? []) {
    if (!allowedRenderLayers.has(layerId)) {
      issues.push(`scene-art slice ${slice.id} uses unsupported render layer ${layerId}`);
    }
  }

  if (!Array.isArray(slice.layers) || slice.layers.length < 1) {
    issues.push(`scene-art slice ${slice.id} must include at least 1 layer`);
  }

  for (const layer of slice.layers ?? []) {
    if (!allowedRenderLayers.has(layer.renderLayer)) {
      issues.push(`scene-art layer ${layer.id} uses unsupported render layer ${layer.renderLayer}`);
    }
    if (!layer.path || typeof layer.path !== 'string') {
      issues.push(`scene-art layer ${layer.id} must include a public asset path`);
      continue;
    }

    const assetPath = path.join(publicRoot, layer.path.replace(/^\/+/, ''));
    if (!fs.existsSync(assetPath)) {
      issues.push(`scene-art layer ${layer.id} asset missing: ${layer.path}`);
    }
  }
}

if (sceneArt.actor) {
  const actorVariants = Array.isArray(sceneArt.actor.variants) ? sceneArt.actor.variants : [];
  const actorModeSets = actorVariants.length > 0
    ? actorVariants.map((variant) => ({
        label: `variant ${variant.id}`,
        modes: variant.modes ?? []
      }))
    : [{
        label: 'base actor',
        modes: sceneArt.actor.modes ?? []
      }];

  if (actorModeSets.every((entry) => !Array.isArray(entry.modes) || entry.modes.length < 2)) {
    issues.push('scene-art actor must include at least 2 visual modes');
  }

  for (const entry of actorModeSets) {
    const actorModes = new Set((entry.modes ?? []).map((mode) => mode.mode));
    if (!actorModes.has('idle') || !actorModes.has('working')) {
      issues.push(`scene-art ${entry.label} must include idle and working modes`);
    }

    for (const mode of entry.modes ?? []) {
      const assetPath = path.join(publicRoot, String(mode.path ?? '').replace(/^\/+/, ''));
      if (!mode.path || !fs.existsSync(assetPath)) {
        issues.push(`scene-art actor texture missing for ${entry.label} mode ${mode.mode}: ${mode.path}`);
      }
      if (mode.kind === 'spritesheet') {
        if (!mode.frameWidth || !mode.frameHeight || !mode.frameCount) {
          issues.push(`scene-art actor spritesheet mode ${mode.mode} in ${entry.label} must define frameWidth/frameHeight/frameCount`);
        }
      }
    }
  }
}

const revealTargets = new Set((manifest.assets ?? []).map((asset) => asset.id));
for (const rule of manifest.growthRules ?? []) {
  for (const target of rule.reveal ?? []) {
    if (!revealTargets.has(target)) {
      issues.push(`growth rule references unknown asset: ${target}`);
    }
  }
}

if (!Array.isArray(themePack.themes) || themePack.themes.length < 2) {
  issues.push('theme-pack must include at least 2 themes for replacement testing');
}

if (!Array.isArray(workOutput.outputCategories) || workOutput.outputCategories.length < 5) {
  issues.push('work-output protocol must include at least 5 output categories');
}

if (!Array.isArray(workOutput.interfaces) || workOutput.interfaces.length < 3) {
  issues.push('work-output protocol must include at least 3 interfaces');
}

if (!Array.isArray(workOutput.states) || workOutput.states.length < 5) {
  issues.push('work-output protocol must include state profiles');
}

const outputCategoryIds = new Set((workOutput.outputCategories ?? []).map((item) => item.id));
const interfaceIds = new Set((workOutput.interfaces ?? []).map((item) => item.id));

for (const profile of workOutput.states ?? []) {
  if (!Array.isArray(profile.zoneTypes) || profile.zoneTypes.length === 0) {
    issues.push(`state profile ${profile.id} must include zoneTypes`);
  }
  for (const zoneType of profile.zoneTypes ?? []) {
    if (!zoneTypes.has(zoneType)) {
      issues.push(`state profile ${profile.id} references unmapped zone type ${zoneType}`);
    }
  }

  if (!Array.isArray(profile.interfaceIds) || profile.interfaceIds.length === 0) {
    issues.push(`state profile ${profile.id} must include interfaceIds`);
  }
  for (const interfaceId of profile.interfaceIds ?? []) {
    if (!interfaceIds.has(interfaceId)) {
      issues.push(`state profile ${profile.id} references unknown interface ${interfaceId}`);
    }
  }

  if (!Array.isArray(profile.outputCategoryIds) || profile.outputCategoryIds.length === 0) {
    issues.push(`state profile ${profile.id} must include outputCategoryIds`);
  }
  for (const categoryId of profile.outputCategoryIds ?? []) {
    if (!outputCategoryIds.has(categoryId)) {
      issues.push(`state profile ${profile.id} references unknown output category ${categoryId}`);
    }
  }

  if (!Array.isArray(profile.detailTemplates) || profile.detailTemplates.length === 0) {
    issues.push(`state profile ${profile.id} must include detailTemplates`);
  }
}

if (issues.length > 0) {
  console.error('Protocol validation failed:');
  for (const issue of issues) {
    console.error(`- ${issue}`);
  }
  process.exit(1);
}

console.log('Protocol validation passed.');
