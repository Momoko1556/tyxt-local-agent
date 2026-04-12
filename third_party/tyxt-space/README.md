# TYXT Space

- [中文说明 / README_cn.md](./README_cn.md)

TYXT Space is a 2D pixel-style control interface for local TYXT agent workflows.

It turns OpenClaw's generated assets, runtime activity, and assets related working state into a visual library interface that can be browsed, previewed, and monitored in real time.

Overall, it aims to feel more like a living pixel archive than a plain folder tree.

![ClawLibrary preview screenshot](./public/ClawLibrary_preview.jpg)

## Highlights

- classify, index, and manage many different asset types produced by OpenClaw
- open and preview those assets directly inside the interface
- see what OpenClaw is currently accessing, using, or processing
- connect runtime behavior to concrete asset rooms instead of raw folders
- present the whole workflow in a more approachable 2D pixel-game UI
- keep the art layer replaceable so visuals can evolve independently from the logic layer

## What It Does

TYXT Space maps resources into visual rooms such as:

- document archive
- image atelier
- memory vault
- skill forge
- interface gateway
- code lab
- scheduler
- alarm board
- runtime monitor
- queue hub
- break room

The interface is mainly designed to answer two questions:

1. What assets already exist?
2. What is OpenClaw doing with them right now?

![ClawLibrary preview animation](./public/ClawLibrary_preview-6s.gif)

## Core Features

- room routing driven by live OpenClaw activity
- asset partitions aligned to OpenClaw resource types
- direct in-panel asset browsing and preview
- actor movement linked to room state
- debug overlays for mapping and route inspection
- replaceable pixel-art scene assets

## Installation

### Easiest Setup: Send the Repo to OpenClaw

If the other person already has OpenClaw installed, the easiest path is to send the repository URL to their OpenClaw and let it install and launch the project automatically.

You can send a prompt like this:

```text
Please install and launch this repository: clone https://github.com/shengyu-meng/ClawLibrary, enter the project folder, run npm install, npm run validate, then start the dev server and tell me the final URL.
```

If you need LAN access, add a note asking OpenClaw to enable LAN access and report the LAN URL.

### Standard Local Setup

```bash
git clone https://github.com/shengyu-meng/ClawLibrary tyxt-space
cd tyxt-space
npm install
npm run validate
npm run dev
```

Then open:

- local only: `http://127.0.0.1:5173/`
- LAN mode if enabled: `http://<your-ip>:5173/`

If your OpenClaw installation is not under the default path, the recommended way is to edit:

- `clawlibrary.config.json`

If you prefer environment-variable overrides, copy and fill:

```bash
cp .env.example .env
```

and set:

- `OPENCLAW_HOME`
- `OPENCLAW_WORKSPACE`

## Development Commands

```bash
npm run dev
npm run validate
npm run typecheck
npm run build
```

Optional QA commands:

```bash
npm run qa:movement
npm run qa:visual:baseline
npm run qa:visual
```

These QA commands generate local temporary artifacts. They currently write into `tmp/qa/` and are not meant to be part of the public repository.

## Runtime Model

ClawLibrary is driven by protocol-style data plus live telemetry:

- `src/data/map.logic.json` — room layout, anchors, walk graph, work zones
- `src/data/asset.manifest.json` — logical asset definitions
- `src/data/scene-art.manifest.json` — actor and scene art bindings
- `src/data/work-output.protocol.json` — work-state mapping and output semantics
- `scripts/openclaw-telemetry.mjs` — bridge from OpenClaw state into live museum signals

## Configuration

ClawLibrary now uses `clawlibrary.config.json` at the repository root as the public-facing config entry point.

Current config surface includes:

- `debug` — whether to show room anchors, route circles, and other debug overlays
- `host` — `127.0.0.1` for local-only access, `0.0.0.0` for LAN access
- `port` — dev server port
- `locale` — `en` or `zh`
- `defaultActorVariant` — choose the default actor skin

Default config file:

```json
{
  "openclaw": {
    "home": "",
    "workspace": ""
  },
  "server": {
    "host": "127.0.0.1",
    "port": 5173
  },
  "ui": {
    "defaultLocale": "en",
    "showDebugToggle": false,
    "defaultDebugVisible": false,
    "showInfoToggle": true,
    "defaultInfoPanelVisible": true,
    "showThemeToggle": false
  },
  "actor": {
    "defaultVariantId": "capy-claw-emoji"
  },
  "telemetry": {
    "pollMs": 2500
  }
}
```

Supporting files:

- `.env.example` — optional environment-variable override example
- `scripts/clawlibrary-config.mjs` — shared config loader for config file + env overrides

## OpenClaw Path Discovery

ClawLibrary does not hardcode a single machine path.

Current lookup strategy:

- read `clawlibrary.config.json` first
- override with `OPENCLAW_HOME` if provided
- override with `OPENCLAW_WORKSPACE` if provided
- if neither config nor env is set, fall back to the standard OpenClaw layout:
  - `~/.openclaw`
  - `~/.openclaw/workspace`

That means:

- standard OpenClaw installations should work out of the box
- custom installations can be supported through config or environment-variable overrides

## Open-Source Repository Guidance

A public release should mainly keep:

- runtime code
- required public assets
- installation commands
- configuration docs
- a few polished preview assets

Internal QA captures, prompt drafts, and iteration logs are usually better removed from the public release.

## License

Code is licensed under MIT:

- `/LICENSE`

Assets are licensed under CC BY-NC-SA 4.0:

- `/LICENSE-ASSETS.md`
- Non-commercial sharing, adaptation, and redistribution are allowed with attribution.
- If you redistribute adapted assets, you must keep them under the same license.
- For commercial use of this project, replace the included art assets with your own, or obtain separate permission.

## Acknowledgements

- This project is inspired by [Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI).
- Special thanks to [@simonxxooxxoo](https://github.com/simonxxooxxoo) and [@ringhyacinth](https://github.com/ringhyacinth).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=shengyu-meng/ClawLibrary&type=Date)](https://www.star-history.com/#shengyu-meng/ClawLibrary&Date)

