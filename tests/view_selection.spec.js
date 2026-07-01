const { test, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_URL = 'http://127.0.0.1:8765';
const EVENT_PATH = 'SentryClips/2026-03-27_14-37-34';

test.use({
  browserName: 'chromium',
  channel: 'chrome',
  viewport: { width: 1600, height: 1100 },
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  runCommand('docker', ['compose', 'up', '-d', '--build', 'app']);
});

test('manual camera switch survives active playback', async ({ page }) => {
  await page.goto(`${APP_URL}/events/${EVENT_PATH}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__SENTRYMANAGER_TEST_API), null, { timeout: 15000 });
  await page.waitForFunction(() => {
    const api = window.__SENTRYMANAGER_TEST_API;
    const state = api?.getSnapshotState?.();
    return Boolean(state) && state.playerCurrentTime > 0.25;
  }, null, { timeout: 15000 });

  const initialTime = await page.evaluate(() => window.__SENTRYMANAGER_TEST_API.getSnapshotState().playerCurrentTime);

  await page.locator('[data-camera-target="back"]').click();

  await page.waitForFunction(({ initialTime }) => {
    const state = window.__SENTRYMANAGER_TEST_API.getSnapshotState();
    return state.activeLayout === 'single'
      && state.activeCameraKey === 'back'
      && state.playerCurrentTime > initialTime + 0.5;
  }, { initialTime }, { timeout: 15000 });
});

test('manual layout switch survives active playback', async ({ page }) => {
  await page.goto(`${APP_URL}/events/${EVENT_PATH}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__SENTRYMANAGER_TEST_API), null, { timeout: 15000 });
  await page.waitForFunction(() => {
    const api = window.__SENTRYMANAGER_TEST_API;
    const state = api?.getSnapshotState?.();
    return Boolean(state) && state.playerCurrentTime > 0.25;
  }, null, { timeout: 15000 });

  const initialTime = await page.evaluate(() => window.__SENTRYMANAGER_TEST_API.getSnapshotState().playerCurrentTime);

  await page.locator('[data-layout-option="double"]').click();

  await page.waitForFunction(({ initialTime }) => {
    const state = window.__SENTRYMANAGER_TEST_API.getSnapshotState();
    return state.activeLayout === 'double'
      && state.activeCameraKey === 'front'
      && state.playerCurrentTime > initialTime + 0.5;
  }, { initialTime }, { timeout: 15000 });
});

function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
    ...options,
  });
  if (result.status === 0) {
    return {
      stdout: result.stdout || '',
      stderr: result.stderr || '',
    };
  }

  const output = [result.stdout, result.stderr].filter(Boolean).join('\n').trim();
  throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}${output ? `\n${output}` : ''}`);
}