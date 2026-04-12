import mapLogicJson from '../../data/map.logic.json';
import assetManifestJson from '../../data/asset.manifest.json';
import sceneArtJson from '../../data/scene-art.manifest.json';
import themePackJson from '../../data/themes/default/theme-pack.json';
import workOutputJson from '../../data/work-output.protocol.json';
import type { AssetManifest, MapLogic, SceneArtManifest, ThemePack, WorkOutputProtocol } from '../../core/types';

export function loadProtocols(): {
  mapLogic: MapLogic;
  assetManifest: AssetManifest;
  sceneArt: SceneArtManifest;
  themePack: ThemePack;
  workOutput: WorkOutputProtocol;
} {
  return {
    mapLogic: mapLogicJson as unknown as MapLogic,
    assetManifest: assetManifestJson as unknown as AssetManifest,
    sceneArt: sceneArtJson as unknown as SceneArtManifest,
    themePack: themePackJson as unknown as ThemePack,
    workOutput: workOutputJson as unknown as WorkOutputProtocol
  };
}
