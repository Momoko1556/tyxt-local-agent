# Asset Contract v2 — OpenClaw Partitions

Date: 2026-03-06

## Goal

Define the art/runtime contract for LL3 after the project scope expanded from a single `skills` room slice to a full OpenClaw-aligned resource museum.

## Partition set

Runtime room ids must stay exactly:

- `document`
- `images`
- `memory`
- `skills`
- `gateway`
- `log`
- `mcp`
- `schedule`
- `alarm`
- `agent`
- `task_queues`
- `break_room`

## Layer contract

Every room asset package must be authored as modular layers, never as one baked final scene:

- `floor`
  - walkable base
  - rugs, floor tint, low-contrast decals only
  - no actor occlusion
- `back_walls`
  - wall backs, shelving backs, mounted panels
  - windows belong here when they are part of the structural wall set
  - may tint with theme
  - must not include baked text
  - must not include characters
- `mid_props`
  - desks, consoles, shelves, boxes, lounge furniture, displays
  - each prop is replaceable as an independent sprite/atlas entry
  - no human figures, no lobster, no baked silhouette characters
- `fg_occluder`
  - counter lips, front desk edges, door headers, screen bezels, shelf fronts
  - always alpha-preserving
  - must be exportable independently from `mid_props`
- `fx_overlay`
  - optional glows, alarm sweeps, cursor scans, active pulses
  - never merged into `floor` or `back_walls`

## Per-prop contract

Every resource-representing prop must support later increase/decrease, replacement, and animation. Minimum metadata:

- `id`
- `roomId`
- `anchor`
- `footpoint`
- `occupancyBox`
- `visibleBBox`
- `displaySize`
- `depthBand`
- `hitPolygon`
- `stateVariants`

Minimum visual states to reserve:

- `idle`
- `active`
- `grown`
- `alert`

## Occlusion rules

- No room can rely only on background illusion for foreground遮挡.
- Floors, furniture, walls/windows, and foreground遮挡 must be authored separately so runtime can recombine them.
- If a desk lip, shelf front, or counter needs to cover actor body, it belongs in `fg_occluder`.
- Actor depth is resolved by footpoint; occluders remain above actor body regardless of actor state.
- Generated room art must preserve this split so runtime can reuse current occluder logic without re-authoring the map.

## Walkable / collision contract

- Final walkable polygons must match the produced floor plan, not an abstract placeholder grid.
- Walls, counters, fixed furniture, shelving, and consoles must produce matching collision regions.
- The lobster must not:
  - walk through walls
  - walk through fixed furniture
  - cut through counter fronts
  - clip across occluder-bearing edges
- Therefore every room art batch should be accompanied by:
  - walkable corridor notes
  - collision block candidates
  - foreground occluder candidates
- Preferred production logic:
  1. generate room layers
  2. confirm visible circulation lanes in the art
  3. derive walkable polygons from those lanes
  4. derive collision boxes/polygons from wall and furniture footprints
  5. derive `fg_occluder` strips from the front-most blocking edges

## Text / character exclusion rules

- No room labels baked into art.
- No Chinese or English room names inside any generated asset.
- All room naming must stay in runtime typography so later Chinese / English switching remains possible.
- No people in room assets.
- The lobster actor is a separate asset pipeline and must never be baked into room art.

## Animation hooks

Later art exports should plug into the existing runtime hooks:

- active partition → prop pulse / screen glow / highlight sweep
- alert partition → stronger pulse / red sweep / beacon flash
- growth unlock → scale/fade reveal
- break room → soft ambient idle, not alarm-like flashing

## Nano Banana production rule

When producing real art, use `nano-banana-pro` and generate by layer/module, not one full room render.

Recommended batch order:

1. room floor slices
2. back wall slices
3. mid props by partition
4. fg occluder bands / fronts
5. fx overlays
6. lobster directional actor frames

## Naming convention

Suggested filenames:

- `ll3_<room>_floor_v001.png`
- `ll3_<room>_back_walls_v001.png`
- `ll3_<room>_fg_occluder_v001.png`
- `ll3_<room>_<prop>_idle_v001.png`
- `ll3_<room>_<prop>_active_v001.png`
- `ll3_<room>_<prop>_alert_v001.png`

## First recommended art batch

To maximize visible progress with minimal art spend:

1. `break_room`
2. `gateway`
3. `alarm`
4. `document`
5. lobster directional actor set

These rooms/states most clearly expose:

- idle fallback
- live access routing
- alert feedback
- occlusion correctness
- modular prop replacement
