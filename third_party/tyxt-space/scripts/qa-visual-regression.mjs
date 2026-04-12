import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import pixelmatch from 'pixelmatch';
import sharp from 'sharp';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const qaDir = path.join(root, 'tmp/qa');
const baselineDir = path.join(qaDir, 'baseline');
const currentDir = path.join(qaDir, 'current');
const diffDir = path.join(qaDir, 'diff');
const reportPath = path.join(qaDir, 'visual-regression-report.json');
const lockPath = path.join(qaDir, '.visual-regression.lock');

const targetUrl = process.env.TARGET_URL ?? 'http://localhost:5173/?mock=1';
const failRatio = Number(process.env.DIFF_FAIL_RATIO ?? '0.02');
const threshold = Number(process.env.PIXELMATCH_THRESHOLD ?? '0.12');
const updateBaseline = process.argv.includes('--update-baseline') || process.env.UPDATE_BASELINE === '1';

const scenarios = [
  {
    id: 'desktop-state-mapping',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2
  },
  {
    id: 'desktop-state-interaction',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    tapScenePoint: { x: 300, y: 268 },
    waitAfterTapMs: 1400
  },
  {
    id: 'desktop-document-kind-menu',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    resourceButtonId: 'document',
    waitAfterActionMs: 700
  },
  {
    id: 'desktop-document-modal-simplified',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    resourceButtonId: 'document',
    kindChipIndex: 0,
    waitAfterActionMs: 900
  },
  {
    id: 'desktop-agent-modal',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    resourceButtonId: 'agent',
    waitAfterActionMs: 800
  },
  {
    id: 'desktop-log-modal-scrolled',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    resourceButtonId: 'log',
    bodyScrollTop: 220,
    waitAfterActionMs: 900
  },
  {
    id: 'desktop-memory-label-hover',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'memory',
    hoverRoomLabel: true,
    waitAfterActionMs: 500
  },
  {
    id: 'desktop-memory-kind-menu-from-label',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'memory',
    clickRoomLabel: true,
    waitAfterActionMs: 800
  },
  {
    id: 'desktop-document-kind-menu-from-label',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'document',
    clickRoomLabel: true,
    waitAfterActionMs: 800
  },
  {
    id: 'desktop-break-room-kind-menu-from-label',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'break_room',
    clickRoomLabel: true,
    waitAfterActionMs: 800
  },
  {
    id: 'desktop-actor-capy-claw',
    viewport: { width: 1000, height: 488 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 2,
    clickSelector: '#toggle-actor-skin',
    waitAfterActionMs: 500
  },
  {
    id: 'mobile-state-mapping',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2
  },
  {
    id: 'mobile-state-interaction',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    tapScenePoint: { x: 300, y: 268 },
    waitAfterTapMs: 1400
  },
  {
    id: 'mobile-document-kind-menu',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    resourceButtonId: 'document',
    waitAfterActionMs: 800
  },
  {
    id: 'mobile-memory-kind-menu-from-label',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'memory',
    clickRoomLabel: true,
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-document-kind-menu-from-label',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'document',
    clickRoomLabel: true,
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-break-room-kind-menu-from-label',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    roomLabelResourceId: 'break_room',
    clickRoomLabel: true,
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-images-preview',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    resourceButtonId: 'images',
    previewSelector: '#asset-modal-items button[data-preview-path]',
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-document-preview',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    resourceButtonId: 'document',
    kindChipIndex: 0,
    previewSelector: '#asset-modal-items button[data-preview-path]',
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-log-preview',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    resourceButtonId: 'log',
    previewSelector: '#asset-modal-items button[data-preview-path]',
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-json-preview',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    resourceButtonId: 'break_room',
    kindChipIndex: 3,
    previewSelector: '#asset-modal-items button[data-preview-path]',
    waitAfterActionMs: 900
  },
  {
    id: 'mobile-actor-kitty-claw',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    clickSelector: '#toggle-actor-skin',
    clickSelectorTimes: 2,
    waitAfterActionMs: 500
  }
];

async function ensureDirs() {
  await fs.mkdir(qaDir, { recursive: true });
  await fs.mkdir(baselineDir, { recursive: true });
  await fs.mkdir(currentDir, { recursive: true });
  await fs.mkdir(diffDir, { recursive: true });
}

async function acquireRunLock() {
  try {
    const handle = await fs.open(lockPath, 'wx');
    await handle.writeFile(JSON.stringify({
      pid: process.pid,
      createdAt: new Date().toISOString(),
      updateBaseline
    }, null, 2));
    return async () => {
      await handle.close();
      await fs.rm(lockPath, { force: true });
    };
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'EEXIST') {
      throw new Error(`Visual regression run already in progress (${lockPath})`);
    }
    throw error;
  }
}

async function assertTargetReachable() {
  try {
    const response = await fetch(targetUrl, { method: 'GET' });
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot reach ${targetUrl}. Start dev server first (npm run dev). Reason: ${reason}`
    );
  }
}

async function sceneToClientPoint(page, scenePoint) {
  return page.evaluate(({ sceneX, sceneY }) => {
    const canvas = document.querySelector('canvas');
    if (!canvas) {
      throw new Error('canvas not found');
    }

    const rect = canvas.getBoundingClientRect();
    return {
      x: rect.left + (rect.width * sceneX) / 1920,
      y: rect.top + (rect.height * sceneY) / 1080
    };
  }, { sceneX: scenePoint.x, sceneY: scenePoint.y });
}

async function roomLabelToClientPoint(page, resourceId) {
  return page.evaluate((targetResourceId) => {
    const debug = window.__clawlibraryDebug;
    const scene = debug?.getScene?.();
    const label = scene?.roomTitleLabels?.get(targetResourceId);
    const canvas = document.querySelector('canvas');
    if (!label || !canvas) {
      throw new Error(`room label not found: ${targetResourceId}`);
    }
    const rect = canvas.getBoundingClientRect();
    return {
      x: rect.left + (rect.width * label.x) / 1920,
      y: rect.top + (rect.height * label.y) / 1080
    };
  }, resourceId);
}

async function dispatchClick(page, selector) {
  await page.evaluate((targetSelector) => {
    const node = document.querySelector(targetSelector);
    if (!(node instanceof HTMLElement)) {
      throw new Error(`selector not found: ${targetSelector}`);
    }
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }, selector);
}

async function setScrollTop(page, selector, scrollTop) {
  await page.evaluate(({ targetSelector, value }) => {
    const node = document.querySelector(targetSelector);
    if (!(node instanceof HTMLElement)) {
      throw new Error(`selector not found: ${targetSelector}`);
    }
    node.scrollTop = value;
  }, { targetSelector: selector, value: scrollTop });
}

async function captureScenario(browser, scenario) {
  const context = await browser.newContext({
    viewport: scenario.viewport,
    isMobile: scenario.isMobile,
    hasTouch: scenario.hasTouch,
    deviceScaleFactor: scenario.deviceScaleFactor
  });

  const page = await context.newPage();
  const outputPath = path.join(currentDir, `${scenario.id}.png`);

  try {
    await page.goto(scenario.targetUrl ?? targetUrl, { waitUntil: 'networkidle', timeout: 25000 });
    await page.waitForFunction(
      () => Boolean(document.querySelector('canvas'))
        && Boolean(document.querySelector('#resource-menu button[data-resource-id="document"]')),
      { timeout: 10000 }
    );
    await page.waitForTimeout(450);

    if (scenario.tapScenePoint) {
      const point = await sceneToClientPoint(page, scenario.tapScenePoint);
      if (scenario.hasTouch) {
        await page.touchscreen.tap(point.x, point.y);
      } else {
        await page.mouse.click(point.x, point.y);
      }
      await page.waitForTimeout(scenario.waitAfterTapMs ?? 1000);
    }

    if (scenario.resourceButtonId) {
      await dispatchClick(page, `#resource-menu button[data-resource-id="${scenario.resourceButtonId}"]`);
      await page.waitForTimeout(scenario.waitAfterActionMs ?? 500);
    }

    if (scenario.clickSelector) {
      const clickTimes = scenario.clickSelectorTimes ?? 1;
      for (let index = 0; index < clickTimes; index += 1) {
        await dispatchClick(page, scenario.clickSelector);
        await page.waitForTimeout(scenario.waitAfterActionMs ?? 350);
      }
    }

    if (typeof scenario.kindChipIndex === 'number') {
      await dispatchClick(page, `#gateway-category-menu button[data-kind-id]:nth-of-type(${scenario.kindChipIndex + 1})`);
      await page.waitForTimeout(scenario.waitAfterActionMs ?? 500);
    }

    if (typeof scenario.bodyScrollTop === 'number') {
      await setScrollTop(page, '.asset-modal-body', scenario.bodyScrollTop);
      await page.waitForTimeout(250);
    }

    if (scenario.roomLabelResourceId) {
      const point = await roomLabelToClientPoint(page, scenario.roomLabelResourceId);
      if (scenario.hoverRoomLabel) {
        await page.mouse.move(point.x, point.y);
        await page.waitForTimeout(scenario.waitAfterActionMs ?? 400);
      }
      if (scenario.clickRoomLabel) {
        if (scenario.hasTouch) {
          await page.touchscreen.tap(point.x, point.y);
        } else {
          await page.mouse.click(point.x, point.y);
        }
        await page.waitForTimeout(scenario.waitAfterActionMs ?? 500);
      }
    }

    if (scenario.previewSelector) {
      await dispatchClick(page, scenario.previewSelector);
      await page.waitForTimeout(scenario.waitAfterActionMs ?? 700);
    }

    await page.screenshot({ path: outputPath, fullPage: true, type: 'png' });
  } finally {
    await context.close();
  }

  return outputPath;
}

async function readImageRaw(filePath) {
  const { data, info } = await sharp(filePath)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  return {
    data,
    width: info.width,
    height: info.height
  };
}

async function compareScenario(id) {
  const baselinePath = path.join(baselineDir, `${id}.png`);
  const currentPath = path.join(currentDir, `${id}.png`);
  const diffPath = path.join(diffDir, `${id}.png`);

  let baselineExists = true;
  try {
    await fs.access(baselinePath);
  } catch {
    baselineExists = false;
  }

  if (!baselineExists || updateBaseline) {
    await fs.copyFile(currentPath, baselinePath);
    return {
      id,
      baselinePath,
      currentPath,
      diffPath,
      mismatchedPixels: 0,
      diffRatio: 0,
      pass: true,
      baselineUpdated: true,
      note: baselineExists ? 'baseline refreshed' : 'baseline created'
    };
  }

  const baseline = await readImageRaw(baselinePath);
  const current = await readImageRaw(currentPath);

  if (baseline.width !== current.width || baseline.height !== current.height) {
    return {
      id,
      baselinePath,
      currentPath,
      diffPath,
      mismatchedPixels: null,
      diffRatio: 1,
      pass: false,
      baselineUpdated: false,
      note: `dimension mismatch: baseline ${baseline.width}x${baseline.height}, current ${current.width}x${current.height}`
    };
  }

  const diffRaw = new Uint8ClampedArray(current.width * current.height * 4);
  const mismatchedPixels = pixelmatch(
    current.data,
    baseline.data,
    diffRaw,
    current.width,
    current.height,
    { threshold }
  );

  const diffRatio = mismatchedPixels / (current.width * current.height);

  await sharp(Buffer.from(diffRaw), {
    raw: {
      width: current.width,
      height: current.height,
      channels: 4
    }
  })
    .png()
    .toFile(diffPath);

  return {
    id,
    baselinePath,
    currentPath,
    diffPath,
    mismatchedPixels,
    diffRatio,
    pass: diffRatio <= failRatio,
    baselineUpdated: false,
    note: 'compared'
  };
}

async function main() {
  await ensureDirs();
  const releaseLock = await acquireRunLock();
  await assertTargetReachable();

  const executablePath = process.env.CHROME_PATH;
  const browser = await chromium.launch({
    headless: process.env.HEADLESS === '0' ? false : true,
    ...(executablePath ? { executablePath } : {})
  });

  const report = {
    targetUrl,
    failRatio,
    threshold,
    updateBaseline,
    generatedAt: new Date().toISOString(),
    scenarios: []
  };

  try {
    try {
      for (const scenario of scenarios) {
        await captureScenario(browser, scenario);
        const result = await compareScenario(scenario.id);
        report.scenarios.push(result);
      }
    } finally {
      await browser.close();
    }

    report.pass = report.scenarios.every((item) => item.pass);
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
  } finally {
    await releaseLock();
  }

  const header = report.pass ? '✅ Visual regression passed.' : '❌ Visual regression failed.';
  console.log(header);
  console.log(`- report: ${path.relative(root, reportPath)}`);
  console.log(`- baseline dir: ${path.relative(root, baselineDir)}`);
  console.log(`- current dir: ${path.relative(root, currentDir)}`);
  console.log(`- diff dir: ${path.relative(root, diffDir)}`);

  for (const scenario of report.scenarios) {
    const ratio = typeof scenario.diffRatio === 'number' ? scenario.diffRatio.toFixed(4) : 'n/a';
    const mark = scenario.pass ? 'PASS' : 'FAIL';
    const baselineMark = scenario.baselineUpdated ? ' (baseline updated)' : '';
    console.log(`- [${mark}] ${scenario.id}: ratio=${ratio}${baselineMark}`);
    if (scenario.note) {
      console.log(`  note: ${scenario.note}`);
    }
  }

  if (!report.pass) {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error('Visual regression run crashed.');
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
