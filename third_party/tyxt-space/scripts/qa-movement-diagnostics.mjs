import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const TARGET_URL = process.env.CLAWLIBRARY_QA_URL || 'http://127.0.0.1:5173/?mock=1';
const OUTPUT_PATH = path.resolve('tmp/qa/movement-diagnostics.json');

const exploratoryPoints = [
  { id: 'document-center', x: 650, y: 820 },
  { id: 'gateway-near', x: 830, y: 430 },
  { id: 'mcp-near', x: 1080, y: 430 },
  { id: 'queue-near', x: 1735, y: 430 },
  { id: 'break-center', x: 1560, y: 875 },
  { id: 'hall-near-edge', x: 980, y: 520 }
];

const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  const report = await page.evaluate(async ({ exploratoryPoints }) => {
    const debug = window.__clawlibraryDebug;
    if (!debug) {
      throw new Error('__clawlibraryDebug not found. Run against a dev build.');
    }

    const scene = debug.getScene();
    const start = { x: scene.lobster.x, y: scene.lobster.y };
    const workzoneRoutes = scene.protocols.mapLogic.workZones.map((zone) => {
      const route = scene.computeMaskRoute({ x: start.x, y: start.y }, zone.anchor) || [];
      return {
        id: zone.id,
        anchor: { x: Math.round(zone.anchor.x), y: Math.round(zone.anchor.y) },
        routeLength: route.length,
        first: route[0] ? { x: Math.round(route[0].x), y: Math.round(route[0].y) } : null,
        last: route.at(-1) ? { x: Math.round(route.at(-1).x), y: Math.round(route.at(-1).y) } : null
      };
    });

    const exploratory = exploratoryPoints.map((point) => {
      const resolved = scene.resolveRequestedWalkTarget(point);
      const route = resolved ? (scene.computeMaskRoute(start, resolved) || []) : [];
      return {
        id: point.id,
        target: { x: point.x, y: point.y },
        walkable: scene.isWalkablePoint(point),
        resolved: resolved ? { x: Math.round(resolved.x), y: Math.round(resolved.y) } : null,
        routeLength: route.length,
        last: route.at(-1) ? { x: Math.round(route.at(-1).x), y: Math.round(route.at(-1).y) } : null
      };
    });

    return {
      generatedAt: new Date().toISOString(),
      start: { x: Math.round(start.x), y: Math.round(start.y) },
      workzoneRoutes,
      exploratory
    };
  }, { exploratoryPoints });

  await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
  await fs.writeFile(OUTPUT_PATH, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`Movement diagnostics written to ${path.relative(process.cwd(), OUTPUT_PATH)}`);
} finally {
  await browser.close();
}
