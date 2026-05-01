const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const FOOTAGE_ROOT = path.join(REPO_ROOT, 'data', 'TeslaCam');
const CONTAINER_FOOTAGE_ROOT = '/data/TeslaCam';
const ARTIFACT_ROOT = path.join(REPO_ROOT, 'tests', 'artifacts', 'render-snapshots');
const APP_URL = 'http://127.0.0.1:8765';
const SNAPSHOT_WIDTH = 1920;
const SNAPSHOT_HEIGHT = 1080;
const OUTPUT_PROFILE = 'hd';
const HALF_SECOND = 0.5;

const FIXTURES = [
  {
    id: 'saved-left-blinker',
    eventId: 'SavedClips/2026-03-28_09-12-13',
    segmentKey: '2026-03-28_09-09-48',
    clipTimeSeconds: 36.945,
    coverage: ['left blinker', 'speed', 'steering >= 20 deg', 'heading W'],
  },
  {
    id: 'saved-right-blinker',
    eventId: 'SavedClips/2026-03-28_09-12-13',
    segmentKey: '2026-03-28_09-08-47',
    clipTimeSeconds: 55.141,
    coverage: ['right blinker', 'speed', 'steering >= 20 deg', 'heading S'],
  },
  {
    id: 'saved-brake',
    eventId: 'SavedClips/2026-03-28_09-12-13',
    segmentKey: '2026-03-28_09-08-47',
    clipTimeSeconds: 3.051,
    coverage: ['brake', 'speed', 'steering >= 20 deg', 'heading W'],
  },
  {
    id: 'saved-fsd-blue',
    eventId: 'SavedClips/2026-03-31_06-53-21',
    segmentKey: '2026-03-31_06-43-49',
    clipTimeSeconds: 30.0,
    coverage: ['speed', 'steering wheel blue', 'FSD percent'],
  },
];

const clipDurationCache = new Map();
const frontPlaylistCache = new Map();

test.use({
  browserName: 'chromium',
  channel: 'chrome',
  viewport: { width: 2200, height: 1500 },
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  ensureCommandAvailable('docker');
  ensureCommandAvailable('ffmpeg');
  ensureCommandAvailable('ffprobe');
  runCommand('docker', ['compose', 'up', '-d', '--build', 'app']);
  fs.mkdirSync(ARTIFACT_ROOT, { recursive: true });
});

for (const fixture of FIXTURES) {
  test(fixture.id, async ({ page }) => {
    test.setTimeout(180000);

    const artifactDir = path.join(ARTIFACT_ROOT, fixture.id);
    fs.rmSync(artifactDir, { recursive: true, force: true });
    fs.mkdirSync(artifactDir, { recursive: true });

    const targetEventTime = computeFrontEventTimeSeconds(fixture.eventId, fixture.segmentKey, fixture.clipTimeSeconds);
    const trimStartTime = roundToMillis(Math.max(0, targetEventTime - HALF_SECOND));
    const trimEndTime = roundToMillis(targetEventTime + HALF_SECOND);
    const playerEdits = buildSnapshotPlayerEdits(trimStartTime, trimEndTime);

    await page.goto(`${APP_URL}/events/${fixture.eventId}`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => Boolean(window.__SENTRYMANAGER_TEST_API), null, { timeout: 15000 });

    const stageState = await page.evaluate(
      async ({ width, height, segmentKey, clipTimeSeconds }) => {
        const api = window.__SENTRYMANAGER_TEST_API;
        await api.configureSnapshotStage({ width, height, hideOverlay: true });
        return api.seekSnapshotFrame({
          layout: 'single',
          cameraKey: 'front',
          segmentKey,
          clipTimeSeconds,
        });
      },
      {
        width: SNAPSHOT_WIDTH,
        height: SNAPSHOT_HEIGHT,
        segmentKey: fixture.segmentKey,
        clipTimeSeconds: fixture.clipTimeSeconds,
      },
    );

    const stagePath = path.join(artifactDir, 'stage.png');
    await page.locator('[data-player-stage-surface]').screenshot({
      path: stagePath,
      animations: 'disabled',
    });
    normalizeImageToFrame(stagePath, SNAPSHOT_WIDTH, SNAPSHOT_HEIGHT);

    const renderMetadata = renderFixtureExport(fixture.eventId, playerEdits);
    const renderPlan = readRenderPlan(renderMetadata.renderPlanPath);
    const exportVideoPath = containerPathToHostPath(String(renderMetadata.outputPath));
    const renderedPath = path.join(artifactDir, 'rendered.png');
    const diffPath = path.join(artifactDir, 'diff.png');
    const comparisonPath = path.join(artifactDir, 'comparison.png');

    extractVideoFrame(exportVideoPath, HALF_SECOND, renderedPath);
    createDiffImage(stagePath, renderedPath, diffPath);
    createComparisonImage(stagePath, renderedPath, diffPath, comparisonPath);

    expect(stageState.stageSize).toEqual({ width: SNAPSHOT_WIDTH, height: SNAPSHOT_HEIGHT });
    expect(stageState.safeZones.left).toBeTruthy();
    expect(stageState.safeZones.right).toBeTruthy();
    expect(stageState.playerCurrentTime).toBeCloseTo(fixture.clipTimeSeconds, 2);

    const primaryFragment = renderPlan.segments?.[0]?.slots?.[0]?.fragments?.[0];
    expect(primaryFragment).toBeTruthy();
    expect(primaryFragment.sourceIn).toBeCloseTo(Math.max(0, fixture.clipTimeSeconds - HALF_SECOND), 2);
    expect(primaryFragment.sourceOut).toBeCloseTo(fixture.clipTimeSeconds + HALF_SECOND, 2);

    const leftStageCropPath = path.join(artifactDir, 'stage-left-corner.png');
    const leftRenderedCropPath = path.join(artifactDir, 'rendered-left-corner.png');
    const rightStageCropPath = path.join(artifactDir, 'stage-right-corner.png');
    const rightRenderedCropPath = path.join(artifactDir, 'rendered-right-corner.png');

    cropImage(stagePath, stageState.safeZones.left, leftStageCropPath);
    cropImage(renderedPath, stageState.safeZones.left, leftRenderedCropPath);
    cropImage(stagePath, stageState.safeZones.right, rightStageCropPath);
    cropImage(renderedPath, stageState.safeZones.right, rightRenderedCropPath);

    const frameRms = computeRmsDifference(stagePath, renderedPath);
    const leftCornerRms = computeRmsDifference(leftStageCropPath, leftRenderedCropPath);
    const rightCornerRms = computeRmsDifference(rightStageCropPath, rightRenderedCropPath);

    const metrics = {
      fixture: fixture.id,
      eventId: fixture.eventId,
      segmentKey: fixture.segmentKey,
      clipTimeSeconds: fixture.clipTimeSeconds,
      coverage: fixture.coverage,
      trimStartTime,
      trimEndTime,
      eventTimeSeconds: targetEventTime,
      stageState,
      frameRms,
      telemetryCornerRms: {
        left: leftCornerRms,
        right: rightCornerRms,
      },
      exportVideoPath,
      renderMetadata,
    };

    fs.writeFileSync(path.join(artifactDir, 'metrics.json'), `${JSON.stringify(metrics, null, 2)}\n`, 'utf-8');
    fs.writeFileSync(path.join(artifactDir, 'stage-state.json'), `${JSON.stringify(stageState, null, 2)}\n`, 'utf-8');

    console.log(`[render-snapshot] ${fixture.id} frame RMS=${frameRms.toFixed(4)} left=${leftCornerRms.toFixed(4)} right=${rightCornerRms.toFixed(4)}`);

    expect(Number.isFinite(frameRms)).toBe(true);
    expect(Number.isFinite(leftCornerRms)).toBe(true);
    expect(Number.isFinite(rightCornerRms)).toBe(true);
    expect(fs.existsSync(comparisonPath)).toBe(true);
    expect(fs.existsSync(diffPath)).toBe(true);
  });
}

function ensureCommandAvailable(command) {
  const result = spawnSync(`command -v ${command}`, {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
    shell: true,
  });
  if (result.status === 0) {
    return;
  }
  throw new Error(`Missing required command: ${command}`);
}

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

function runCommandText(command, args, options = {}) {
  const result = runCommand(command, args, options);
  return `${result.stdout}${result.stderr}`.trim();
}

function buildSnapshotPlayerEdits(trimStartTime, trimEndTime) {
  return {
    trimStartTime,
    trimEndTime,
    exportFormat: OUTPUT_PROFILE,
    startMarkerView: {
      layout: 'single',
      cameraKey: 'front',
    },
    cameraMarkers: [],
  };
}

function computeFrontEventTimeSeconds(eventId, segmentKey, clipTimeSeconds) {
  const playlist = getFrontPlaylist(eventId);
  let elapsedSeconds = 0;
  for (const clip of playlist) {
    if (clip.segmentKey === segmentKey) {
      return roundToMillis(elapsedSeconds + clipTimeSeconds);
    }
    elapsedSeconds += clip.durationSeconds;
  }
  throw new Error(`Could not find front-camera segment ${segmentKey} in ${eventId}`);
}

function getFrontPlaylist(eventId) {
  const cached = frontPlaylistCache.get(eventId);
  if (cached) {
    return cached;
  }

  const eventDir = path.join(FOOTAGE_ROOT, ...eventId.split('/'));
  const clips = fs.readdirSync(eventDir)
    .filter((fileName) => fileName.endsWith('-front.mp4'))
    .sort()
    .map((fileName) => ({
      fileName,
      filePath: path.join(eventDir, fileName),
      segmentKey: fileName.replace(/-front\.mp4$/, ''),
      durationSeconds: getClipDurationSeconds(path.join(eventDir, fileName)),
    }));

  frontPlaylistCache.set(eventId, clips);
  return clips;
}

function getClipDurationSeconds(filePath) {
  const cached = clipDurationCache.get(filePath);
  if (cached !== undefined) {
    return cached;
  }

  const output = runCommandText('ffprobe', [
    '-v',
    'error',
    '-show_entries',
    'format=duration',
    '-of',
    'default=noprint_wrappers=1:nokey=1',
    filePath,
  ]);
  const durationSeconds = Number.parseFloat(output.trim());
  if (!Number.isFinite(durationSeconds)) {
    throw new Error(`Could not parse duration for ${filePath}`);
  }
  clipDurationCache.set(filePath, durationSeconds);
  return durationSeconds;
}

function renderFixtureExport(eventId, playerEdits) {
  const script = [
    'import json, os',
    'from pathlib import Path',
    'from app.renderer.pipeline import render_event',
    'footage_root = Path("/data/TeslaCam")',
    'event_id = os.environ["SNAPSHOT_EVENT_ID"]',
    'player_edits = json.loads(os.environ["SNAPSHOT_PLAYER_EDITS"])',
    'result = render_event(',
    '    event_dir=footage_root / event_id,',
    '    footage_root=footage_root,',
    '    event_id=event_id,',
    '    player_edits=player_edits,',
    '    output_profile=os.environ["SNAPSHOT_OUTPUT_PROFILE"],',
    ')',
    'print(json.dumps(result))',
  ].join('\n');

  const output = runCommandText(
    'docker',
    [
      'compose',
      'exec',
      '-T',
      '-e',
      `SNAPSHOT_EVENT_ID=${eventId}`,
      '-e',
      `SNAPSHOT_PLAYER_EDITS=${JSON.stringify(playerEdits)}`,
      '-e',
      `SNAPSHOT_OUTPUT_PROFILE=${OUTPUT_PROFILE}`,
      'app',
      'python',
      '-c',
      script,
    ],
  );

  const jsonLine = output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .pop();
  if (!jsonLine) {
    throw new Error(`Renderer did not return metadata for ${eventId}`);
  }
  return JSON.parse(jsonLine);
}

function containerPathToHostPath(containerPath) {
  if (!containerPath.startsWith(CONTAINER_FOOTAGE_ROOT)) {
    throw new Error(`Unexpected container path: ${containerPath}`);
  }
  const relativePath = containerPath.slice(CONTAINER_FOOTAGE_ROOT.length).replace(/^\//, '');
  return path.join(FOOTAGE_ROOT, ...relativePath.split('/'));
}

function readRenderPlan(containerPath) {
  const hostPath = containerPathToHostPath(containerPath);
  return JSON.parse(fs.readFileSync(hostPath, 'utf-8'));
}

function extractVideoFrame(videoPath, timestampSeconds, outputPath) {
  runCommand('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-ss',
    String(timestampSeconds),
    '-i',
    videoPath,
    '-frames:v',
    '1',
    outputPath,
  ]);
}

function createDiffImage(stagePath, renderedPath, outputPath) {
  runCommand('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    stagePath,
    '-i',
    renderedPath,
    '-filter_complex',
    '[0:v][1:v]blend=all_mode=difference',
    '-frames:v',
    '1',
    outputPath,
  ]);
}

function createComparisonImage(stagePath, renderedPath, diffPath, outputPath) {
  runCommand('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    stagePath,
    '-i',
    renderedPath,
    '-i',
    diffPath,
    '-filter_complex',
    '[0:v][1:v][2:v]hstack=inputs=3',
    '-frames:v',
    '1',
    outputPath,
  ]);
}

function cropImage(inputPath, rect, outputPath) {
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  const x = Math.max(0, Math.round(rect.x));
  const y = Math.max(0, Math.round(rect.y));
  runCommand('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    inputPath,
    '-filter:v',
    `crop=${width}:${height}:${x}:${y}`,
    '-frames:v',
    '1',
    outputPath,
  ]);
}

function normalizeImageToFrame(imagePath, width, height) {
  const normalizedPath = `${imagePath}.normalized.png`;
  runCommand('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    imagePath,
    '-filter:v',
    `crop=${width}:${height}:0:0`,
    '-frames:v',
    '1',
    normalizedPath,
  ]);
  fs.renameSync(normalizedPath, imagePath);
}

function computeRmsDifference(leftPath, rightPath) {
  const output = runCommandText('ffmpeg', [
    '-hide_banner',
    '-i',
    leftPath,
    '-i',
    rightPath,
    '-lavfi',
    'psnr=stats_file=-:stats_version=2',
    '-f',
    'null',
    '-',
  ]);
  const match = output.match(/mse_avg:([0-9.]+)/);
  if (!match) {
    throw new Error(`Could not parse mse_avg from ffmpeg output:\n${output}`);
  }
  return Math.sqrt(Number.parseFloat(match[1]));
}

function roundToMillis(value) {
  return Math.round(value * 1000) / 1000;
}
