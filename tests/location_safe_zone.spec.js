const { test, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_URL = 'http://127.0.0.1:8765';
const EVENT_PATH = 'SavedClips/2026-03-28_09-12-13';
const SEGMENT_KEY = '2026-03-28_09-09-48';

test.use({
  browserName: 'chromium',
  channel: 'chrome',
  viewport: { width: 1600, height: 1100 },
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  runCommand('docker', ['compose', 'up', '-d', 'app']);
});

test('location metadata appears in the top-left stage safe zone', async ({ page }) => {
  await page.goto(`${APP_URL}/events/${EVENT_PATH}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__SENTRYMANAGER_TEST_API), null, { timeout: 15000 });

  const snapshotState = await page.evaluate(async ({ segmentKey, clipTimeSeconds }) => {
    const api = window.__SENTRYMANAGER_TEST_API;
    await api.seekSnapshotFrame({
      layout: 'single',
      cameraKey: 'front',
      segmentKey,
      clipTimeSeconds,
    });
    return api.getSnapshotState();
  }, { segmentKey: SEGMENT_KEY, clipTimeSeconds: 5 });

  const locationNode = page.locator('[data-player-location]');
  const dateNode = page.locator('[data-player-event-date]');
  const timeNode = page.locator('[data-player-event-time]');
  const metaLine = page.locator('.player-meta-line');

  await expect(metaLine).toHaveCount(0);
  await expect(dateNode).toBeVisible();
  await expect(timeNode).toBeVisible();
  await expect(locationNode).toBeVisible();
  await expect(locationNode).not.toHaveText('');

  const locationText = (await locationNode.textContent()) || '';
  const dateText = (await dateNode.textContent()) || '';
  const timeText = (await timeNode.textContent()) || '';

  await page.evaluate(async ({ segmentKey, clipTimeSeconds }) => {
    const api = window.__SENTRYMANAGER_TEST_API;
    await api.seekSnapshotFrame({
      layout: 'single',
      cameraKey: 'front',
      segmentKey,
      clipTimeSeconds,
    });
  }, { segmentKey: SEGMENT_KEY, clipTimeSeconds: 55 });

  const advancedTimeText = (await timeNode.textContent()) || '';

  expect(snapshotState.safeZones.topLeft).toBeTruthy();
  expect(dateText.trim()).toMatch(/^\d{2}-\d{2}-\d{4}$/);
  expect(timeText.trim()).toMatch(/^\d{2}:\d{2}$/);
  expect(advancedTimeText.trim()).toMatch(/^\d{2}:\d{2}$/);
  expect(advancedTimeText.trim()).not.toEqual(timeText.trim());
  expect(locationText.trim().length).toBeGreaterThan(0);
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
