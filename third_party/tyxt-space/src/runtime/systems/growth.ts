import type { AssetManifest, GrowthState } from '../../core/types';

export function computeVisibleAssetIds(manifest: AssetManifest, state: GrowthState): Set<string> {
  const visibleIds = new Set<string>();

  for (const asset of manifest.assets) {
    if (!asset.startsHidden) {
      visibleIds.add(asset.id);
    }
  }

  for (const rule of manifest.growthRules) {
    if (state[rule.metric] >= rule.threshold) {
      for (const assetId of rule.reveal) {
        visibleIds.add(assetId);
      }
    }
  }

  return visibleIds;
}