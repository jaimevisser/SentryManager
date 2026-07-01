const { test, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_URL = 'http://127.0.0.1:8765';
const EVENT_PATH = 'SentryClips/2026-03-27_14-37-34';
const SEGMENT_KEY = '2026-03-27_14-26-59';

test.use({
  browserName: 'chromium',
  channel: 'chrome',
  viewport: { width: 1600, height: 1100 },
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  runCommand('docker', ['compose', 'up', '-d', '--build', 'app']);
});

test('trim markers can be exactly five seconds apart on long events', async ({ page }) => {
  await page.goto(`${APP_URL}/events/${EVENT_PATH}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__SENTRYMANAGER_TEST_API), null, { timeout: 15000 });

  await page.evaluate(async ({ segmentKey, clipTimeSeconds }) => {
    const api = window.__SENTRYMANAGER_TEST_API;
    await api.seekSnapshotFrame({
      layout: 'single',
      cameraKey: 'front',
      segmentKey,
      clipTimeSeconds,
    });
  }, { segmentKey: SEGMENT_KEY, clipTimeSeconds: 10 });

  await page.locator('[data-player-set-start]').click();
  await expect(page.locator('[data-player-start-marker]')).toHaveAttribute('title', 'Start marker at 0:10');

  await page.evaluate(async ({ segmentKey, clipTimeSeconds }) => {
    const api = window.__SENTRYMANAGER_TEST_API;
    await api.seekSnapshotFrame({
      layout: 'single',
      cameraKey: 'front',
      segmentKey,
      clipTimeSeconds,
    });
  }, { segmentKey: SEGMENT_KEY, clipTimeSeconds: 15 });

  await page.locator('[data-player-set-end]').click();
  await expect(page.locator('[data-player-end-marker]')).toHaveAttribute('title', 'End marker at 0:15');
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