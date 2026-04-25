# TYXT Space v1.5.0

- [中文说明 / README_cn.md](./README_cn.md)

TYXT Space is the visual home for TYXT Local Agent. It presents the agent system as an editable 2D space where houses, furniture, characters, room labels, walls, and interaction areas can be managed from the frontend UI.

This release focuses on making the visual space data-driven and editable without relying on the old asset-pack/remap workflow.

## v1.5.0 Highlights

- House images now come from `public/assets/houses`.
- Furniture sprites now come from `public/assets/furnitures`.
- Scene data is stored in `public/data`, including house catalog, furniture catalog, scene config, scene map, and actor mapping.
- Room labels are positioned by dragging them in the frontend UI.
- Wall blocks are edited in the frontend UI and are used to subtract non-walkable areas from the main house image.
- Movement range is calculated as: visible main house image area minus wall blocks.
- Character selection is driven by `public/data/agent-actors.json` and `src/data/scene-art.manifest.json`.
- The old `public/assets/packs` and `remap.html` workflow has been removed.
- The Shop entry is reserved for future use. Shop editing is not implemented in v1.5.0.

## Main Concepts

### Houses

House images are the main visual background of the space.

Runtime location:

```text
public/assets/houses/
public/data/houses.json
public/data/scene-config.json
```

House images should be PNG or WebP. The current import checks expect a large enough image and a consistent aspect ratio with the baseline house.

### Furniture

Furniture is stored as directional sprites and placed inside the scene through the visual editor.

Runtime location:

```text
public/assets/furnitures/
public/data/furnitures.json
public/data/scene-map.json
```

Furniture entries can include front, left, right, and back sprites. Placement, direction, size, collision behavior, and interaction metadata are persisted into the scene map.

### Characters

Character visuals are separated from house and furniture data.

Runtime location:

```text
public/assets/generated/actors/
public/data/agent-actors.json
src/data/scene-art.manifest.json
```

The default actor variant is `tyxt-emoji`. Older capy/cat variants are no longer part of the runtime chain.

### Walls And Movement

Walking no longer depends on `reference-walkable.png`.

The current movement rule is:

```text
walkable area = visible main house image area - wall blocks
```

Wall blocks are edited in the frontend UI. They act as blocking geometry for movement and path recovery.

### Room Labels

Room name positions are controlled by frontend dragging. The saved positions live with scene map data instead of the removed remap workbench.

### Shop

The Shop button/entry is reserved for later product logic. It is intentionally not editable in v1.5.0.

## Development Commands

```bash
npm install
npm run validate
npm run typecheck
npm run build
npm run dev
```

Optional QA commands:

```bash
npm run qa:movement
npm run qa:visual:baseline
npm run qa:visual
```

QA output is local-only and should not be committed.

## Configuration

The public config entry is:

```text
clawlibrary.config.json
```

Default actor configuration:

```json
{
  "actor": {
    "defaultVariantId": "tyxt-emoji"
  }
}
```

Environment overrides may be placed in `.env`, which is ignored by Git.

## Public Data Files

```text
public/data/houses.json        House catalog
public/data/furnitures.json    Furniture catalog
public/data/scene-config.json  Current/baseline house selection
public/data/scene-map.json     Walls, labels, furniture, interaction data
public/data/agent-actors.json  Agent-to-actor variant mapping
```

## Privacy Notes

Do not commit local runtime data, generated logs, `.env`, or local machine configuration. The root repository `.gitignore` and this package `.gitignore` exclude those by default.

## License

Code is licensed under MIT:

- `/LICENSE`

Assets are licensed under CC BY-NC-SA 4.0:

- `/LICENSE-ASSETS.md`
- Non-commercial sharing, adaptation, and redistribution are allowed with attribution.
- If you redistribute adapted assets, you must keep them under the same license.
- For commercial use, replace the included art assets with your own or obtain separate permission.
