export function createEventPlayerSnapshotApi({
    windowObject,
    player,
    viewFrame,
    stageSurface,
    stageSafeZones,
    getActiveLayout,
    getActiveCameraKey,
    getActiveIndex,
    getPlaylist,
    getAllPlaylists,
    getPendingEventTime,
    isPlaylistReady,
    applyViewSelection,
    syncSecondaryPlayers,
    findClipIndexBySegmentKey,
    loadClip,
    ensureTelemetryLoaded,
    syncTimelineUI,
    scheduleStageSafeZoneUpdate,
}) {
    const snapshotStageConfig = {
        width: null,
        height: null,
        hideOverlay: false,
    };

    function waitForCondition(predicate, timeoutMs = 5000) {
        return new Promise((resolve, reject) => {
            const startedAt = performance.now();

            function check() {
                let matched = false;
                try {
                    matched = Boolean(predicate());
                } catch {
                    matched = false;
                }

                if (matched) {
                    resolve();
                    return;
                }

                if (performance.now() - startedAt >= timeoutMs) {
                    reject(new Error("Timed out waiting for player state."));
                    return;
                }

                windowObject.requestAnimationFrame(check);
            }

            check();
        });
    }

    function waitForAnimationFrames(count = 2) {
        return new Promise((resolve) => {
            const remainingFrames = Math.max(1, count);
            let completed = 0;

            function step() {
                completed += 1;
                if (completed >= remainingFrames) {
                    resolve();
                    return;
                }
                windowObject.requestAnimationFrame(step);
            }

            windowObject.requestAnimationFrame(step);
        });
    }

    function waitForVideoFrame(videoElement, targetTimeSeconds) {
        return new Promise((resolve, reject) => {
            const timeoutId = windowObject.setTimeout(() => {
                cleanup();
                reject(new Error("Timed out waiting for video frame."));
            }, 5000);

            function cleanup() {
                windowObject.clearTimeout(timeoutId);
                videoElement.removeEventListener("seeked", handleCandidateFrame);
                videoElement.removeEventListener("loadeddata", handleCandidateFrame);
                videoElement.removeEventListener("timeupdate", handleCandidateFrame);
            }

            function finish() {
                cleanup();
                resolve();
            }

            function handleCandidateFrame() {
                if (videoElement.readyState < 2) {
                    return;
                }
                if (Math.abs(videoElement.currentTime - targetTimeSeconds) > 0.05) {
                    return;
                }

                windowObject.requestAnimationFrame(() => {
                    finish();
                });
            }

            videoElement.addEventListener("seeked", handleCandidateFrame);
            videoElement.addEventListener("loadeddata", handleCandidateFrame);
            videoElement.addEventListener("timeupdate", handleCandidateFrame);
            handleCandidateFrame();
        });
    }

    function applySnapshotStageConfig() {
        if (!stageSurface || !viewFrame) {
            return;
        }

        const width = snapshotStageConfig.width;
        const height = snapshotStageConfig.height;
        if (width && height) {
            const scale = width / 1920;
            const horizontalPadding = Math.max(0, Math.round(14 * scale));
            const doubleGap = Math.max(0, Math.round(10 * scale));
            stageSurface.style.width = `${width}px`;
            stageSurface.style.height = `${height}px`;
            stageSurface.style.maxWidth = `${width}px`;
            stageSurface.style.aspectRatio = "auto";
            stageSurface.style.margin = "0";
            viewFrame.style.padding = `0 ${horizontalPadding}px 0`;
            viewFrame.style.gap = getActiveLayout() === "triple" ? "0px" : `${doubleGap}px`;
        } else {
            stageSurface.style.removeProperty("width");
            stageSurface.style.removeProperty("height");
            stageSurface.style.removeProperty("max-width");
            stageSurface.style.removeProperty("aspect-ratio");
            stageSurface.style.removeProperty("margin");
            viewFrame.style.removeProperty("padding");
            viewFrame.style.removeProperty("gap");
        }

        const cameraOverlay = viewFrame.querySelector(".player-camera-overlay");
        if (cameraOverlay instanceof HTMLElement) {
            cameraOverlay.hidden = snapshotStageConfig.hideOverlay;
        }

        scheduleStageSafeZoneUpdate();
    }

    function getRelativeElementRect(node) {
        if (!(node instanceof HTMLElement) || !stageSurface || node.hidden) {
            return null;
        }

        const stageRect = stageSurface.getBoundingClientRect();
        const rect = node.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            return null;
        }

        return {
            x: Math.round(rect.left - stageRect.left),
            y: Math.round(rect.top - stageRect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
        };
    }

    function getSnapshotState() {
        return {
            activeCameraKey: getActiveCameraKey(),
            activeIndex: getActiveIndex(),
            activeLayout: getActiveLayout(),
            playerCurrentTime: player.currentTime,
            safeZones: {
                left: getRelativeElementRect(stageSafeZones.left),
                right: getRelativeElementRect(stageSafeZones.right),
                topLeft: getRelativeElementRect(stageSafeZones.topLeft),
            },
            stageSize: stageSurface
                ? {
                    width: stageSurface.clientWidth,
                    height: stageSurface.clientHeight,
                }
                : null,
        };
    }

    async function seekSnapshotFrame({ layout, cameraKey, segmentKey, clipTimeSeconds }) {
        const normalizedLayout = typeof layout === "string" ? layout : getActiveLayout();
        const normalizedCameraKey = typeof cameraKey === "string" ? cameraKey : getActiveCameraKey();
        const normalizedSegmentKey = typeof segmentKey === "string" ? segmentKey : null;
        const normalizedClipTime = typeof clipTimeSeconds === "number" && Number.isFinite(clipTimeSeconds)
            ? Math.max(0, clipTimeSeconds)
            : 0;

        if (!normalizedSegmentKey) {
            throw new Error("A segment key is required for snapshot capture.");
        }

        await waitForCondition(() => isPlaylistReady() && getPendingEventTime() === null && player.readyState >= 2);

        player.pause();
        syncSecondaryPlayers(player.currentTime, false);

        applyViewSelection(normalizedLayout, normalizedCameraKey, { autoplay: false });
        await waitForCondition(() => getPlaylist() === getAllPlaylists()[normalizedCameraKey]);

        const targetIndex = findClipIndexBySegmentKey(normalizedCameraKey, normalizedSegmentKey, getActiveIndex());
        if (targetIndex < 0) {
            throw new Error(`Could not find clip ${normalizedCameraKey}:${normalizedSegmentKey}.`);
        }

        const targetClip = getPlaylist()[targetIndex];
        loadClip(targetIndex, { autoplay: false, targetTime: normalizedClipTime, secondaryShouldPlay: false });
        await ensureTelemetryLoaded(targetClip);
        await waitForAnimationFrames(2);
        await waitForCondition(() => player.readyState >= 2);

        player.pause();
        if (Math.abs(player.currentTime - normalizedClipTime) > 0.02) {
            player.currentTime = normalizedClipTime;
        }

        await waitForVideoFrame(player, normalizedClipTime);
        syncTimelineUI();
        applySnapshotStageConfig();
        await waitForAnimationFrames(3);
        return getSnapshotState();
    }

    return {
        async configureSnapshotStage({ width, height, hideOverlay = true } = {}) {
            snapshotStageConfig.width = typeof width === "number" && Number.isFinite(width)
                ? Math.max(320, Math.round(width))
                : null;
            snapshotStageConfig.height = typeof height === "number" && Number.isFinite(height)
                ? Math.max(180, Math.round(height))
                : null;
            snapshotStageConfig.hideOverlay = Boolean(hideOverlay);
            applySnapshotStageConfig();
            await waitForAnimationFrames(2);
            return getSnapshotState();
        },
        seekSnapshotFrame,
        getSnapshotState,
    };
}