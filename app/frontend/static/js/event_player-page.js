import {
    CAMERA_LAYOUT_SEQUENCE,
    decodeTelemetryBuffer,
    populateClipDurations,
} from "./event_player-media.js";
import {
    createPreloadPlayers,
    loadEventPlayerBootstrap,
    queryEventPlayerNodes,
} from "./event_player-page-bootstrap.js";
import {
    getRenderJobStatusMessage as describeRenderJobStatus,
    getSecondaryCameraKeyMapForSelection as getSecondaryCameraKeyMapForSelectionHelper,
    getVisibleCameraKeysForSelection as getVisibleCameraKeysForSelectionHelper,
    isRenderJobActive,
    normalizeDriverAssistDisplay,
    normalizeExportFormat,
    normalizePersistedTime,
} from "./event_player-page-helpers.js";
import { createEventPlayerEditingController } from "./event_player-page-editing.js";
import { createEventPlayerExportController } from "./event_player-page-export.js";
import { createEventPlayerHudController } from "./event_player-page-hud.js";
import { createEventPlayerPlaybackController } from "./event_player-page-playback.js";
import { createEventPlayerSnapshotApi } from "./event_player-page-snapshot.js";
import { createStageSafeZoneController } from "./event_player-page-stage.js";

export function initEventPlayer() {
    const bootstrap = loadEventPlayerBootstrap(document, normalizeDriverAssistDisplay);
    if (!bootstrap) {
        return;
    }

    const {
        allPlaylists,
        defaultViewKey,
        eventDriverAssistDisplay,
        eventHasAutopilotActivity,
        eventHasSteeringAngleData,
        eventMarkerTime,
        eventRouteSvgUrl,
        eventTimestampIso,
        initialRenderJob,
        initialStartTime,
        latestRenderMetadata,
        player,
        playerDownloadUrl,
        playerEditsSaveUrl,
        playerRenderUrl,
        rawSavedEdits,
    } = bootstrap;

    let activeLayout = "single";
    let activeCameraKey = hasCameraPlaylist(defaultViewKey)
        ? defaultViewKey
        : CAMERA_LAYOUT_SEQUENCE.find((cameraKey) => hasCameraPlaylist(cameraKey)) || defaultViewKey;
    let playlist = allPlaylists[activeCameraKey];
    if (!Array.isArray(playlist) || playlist.length === 0) {
        return;
    }

    const {
        addCameraMarkerButton,
        autopilotNode,
        blinkerLeftNode,
        blinkerRightNode,
        cameraButtons,
        currentTimeNode,
        downloadActionButton,
        editTrack,
        editTrackFill,
        endMarkerButton,
        eventDateNode,
        eventMarker,
        eventTimeNode,
        exportFormatButtons,
        exportFormatToggle,
        fsdPercentNode,
        routeMapNode,
        headingIndicatorNode,
        headingLabelNode,
        headingNode,
        layoutButtons,
        renderActionButton,
        renderActionIcon,
        renderStatusNode,
        scrubber,
        secondaryPlayers,
        playFromStartButton,
        setEndButton,
        setStartButton,
        speedNode,
        stageSafeZones,
        stageSurface,
        startMarkerButton,
        toggleButton,
        toggleIcon,
        totalTimeNode,
        viewFrame,
        brakeNode,
    } = queryEventPlayerNodes(document);
    const preloadPlayers = createPreloadPlayers(document);

    let activeIndex = 0;
    let pendingEventTime = null;
    let playlistReady = false;
    let isScrubbing = false;
    let lastPointerCommitAt = 0;
    let initialSeekApplied = false;
    let savedPlayerEditsHydrated = false;
    let editingController;
    let exportController;
    let playbackController;

    const durationCache = new Map();
    const telemetryCache = new Map();
    const baseEventTimestampMs = (() => {
        if (typeof eventTimestampIso !== "string" || !eventTimestampIso.trim()) {
            return null;
        }
        const parsedMs = Date.parse(eventTimestampIso);
        return Number.isFinite(parsedMs) ? parsedMs : null;
    })();

    function clipHasTelemetry(clip) {
        return Boolean(clip?.hasTelemetry);
    }

    function hasCameraPlaylist(cameraKey) {
        return Array.isArray(allPlaylists[cameraKey]) && allPlaylists[cameraKey].length > 0;
    }

    function normalizeViewSelection(selection) {
        if (!selection) {
            return null;
        }
        if (!["single", "double", "triple"].includes(selection.layout)) {
            selection.layout = "single";
        }
        selection.cameraKey = getFirstAvailableCameraKey(selection.cameraKey);
        return selection;
    }

    function getFirstAvailableCameraKey(preferredCameraKey = null) {
        if (preferredCameraKey && hasCameraPlaylist(preferredCameraKey)) {
            return preferredCameraKey;
        }
        return CAMERA_LAYOUT_SEQUENCE.find((cameraKey) => hasCameraPlaylist(cameraKey)) || preferredCameraKey || defaultViewKey;
    }

    function isCompositeView() {
        return activeLayout !== "single";
    }

    function getSecondaryCameraKeyMapForSelection(layout, cameraKey) {
        return getSecondaryCameraKeyMapForSelectionHelper(layout, cameraKey, CAMERA_LAYOUT_SEQUENCE);
    }

    function getSecondaryCameraKeyMap() {
        return getSecondaryCameraKeyMapForSelection(activeLayout, activeCameraKey);
    }

    function getVisibleCameraKeysForSelection(layout, cameraKey) {
        return getVisibleCameraKeysForSelectionHelper(
            layout,
            cameraKey,
            CAMERA_LAYOUT_SEQUENCE,
            getFirstAvailableCameraKey,
            hasCameraPlaylist,
        );
    }

    function getVisibleCameraKeys() {
        return getVisibleCameraKeysForSelection(activeLayout, activeCameraKey);
    }

    function buildPlayerEditsPayload() {
        return editingController
            ? editingController.buildPlayerEditsPayload(exportController?.getActiveExportFormat() || "4k")
            : {
                trimStartTime: 0,
                trimEndTime: 0,
                exportFormat: exportController?.getActiveExportFormat() || "4k",
                startMarkerView: {
                    layout: activeLayout,
                    cameraKey: activeCameraKey,
                },
                cameraMarkers: [],
            };
    }

    function schedulePlayerEditsPersistence() {
        exportController?.schedulePlayerEditsPersistence();
    }

    function toggleExportFormat() {
        return exportController ? exportController.toggleExportFormat() : false;
    }

    async function handleRenderAction() {
        if (!exportController) {
            return;
        }
        await exportController.handleRenderAction();
    }

    function handleDownloadAction() {
        exportController?.handleDownloadAction();
    }

    function hydrateSavedPlayerEdits(rawSavedPlayerEdits) {
        exportController?.hydrateSavedExportFormat(rawSavedPlayerEdits);
        editingController?.hydrateSavedPlayerEdits(rawSavedPlayerEdits);
    }

    const { scheduleStageSafeZoneUpdate } = createStageSafeZoneController({
        windowObject: window,
        player,
        viewFrame,
        stageSafeZones,
        secondaryPlayers,
    });

    function formatClockTime(totalSeconds) {
        const safeSeconds = Math.max(0, Math.floor(totalSeconds));
        const hours = Math.floor(safeSeconds / 3600);
        const minutes = Math.floor((safeSeconds % 3600) / 60);
        const seconds = safeSeconds % 60;
        if (hours > 0) {
            return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
        }
        return `${minutes}:${String(seconds).padStart(2, "0")}`;
    }

    function formatOverlayDateLabel(date) {
        const day = String(date.getDate()).padStart(2, "0");
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const year = String(date.getFullYear());
        return `${day}-${month}-${year}`;
    }

    function formatOverlayTimeLabel(date) {
        const hours = String(date.getHours()).padStart(2, "0");
        const minutes = String(date.getMinutes()).padStart(2, "0");
        return `${hours}:${minutes}`;
    }

    function getClipStart(index) {
        return playbackController ? playbackController.getClipStart(index) : 0;
    }

    function getTotalDuration() {
        return playbackController ? playbackController.getTotalDuration() : 0;
    }

    function getCurrentEventTime() {
        return playbackController ? playbackController.getCurrentEventTime() : 0;
    }

    function getActualPlaybackEventTime() {
        return playbackController ? playbackController.getActualPlaybackEventTime() : 0;
    }

    function ensureTrimRange(totalDuration) {
        editingController?.ensureTrimRange(totalDuration);
    }

    function syncTrimUI(totalDuration) {
        editingController?.syncTrimUI(totalDuration);
    }

    function syncCameraMarkerUI(totalDuration) {
        editingController?.syncCameraMarkerUI(totalDuration);
    }

    function getPlaybackMarkerIdAtOrBefore(eventTime) {
        return editingController ? editingController.getPlaybackMarkerIdAtOrBefore(eventTime) : null;
    }

    function syncPlaybackMarkerCheckpoint(eventTime) {
        editingController?.syncPlaybackMarkerCheckpoint(eventTime);
    }

    function maybeApplyPlaybackCameraMarker(eventTime, options = {}) {
        return editingController ? editingController.maybeApplyPlaybackCameraMarker(eventTime, options) : false;
    }

    function maybeApplyCurrentPlaybackViewMarker(eventTime, options = {}) {
        return editingController ? editingController.maybeApplyCurrentPlaybackViewMarker(eventTime, options) : false;
    }

    function noteManualViewSelectionOverride(eventTime) {
        editingController?.noteManualViewSelectionOverride(eventTime);
    }

    function getTrimStartTime() {
        return editingController ? editingController.getTrimStartTime() : 0;
    }

    function getTrimEndTime() {
        return editingController ? editingController.getTrimEndTime() : 0;
    }

    function applyStartMarkerViewSelection(options = {}) {
        return editingController ? editingController.applyStartMarkerViewSelection(options) : false;
    }

    function findClipForEventTime(eventTime) {
        return playbackController
            ? playbackController.findClipForEventTime(eventTime)
            : { index: 0, offset: 0 };
    }

    function seekToEventTime(eventTime, options = {}) {
        playbackController?.seekToEventTime(eventTime, options);
    }

    function findClipIndexBySegmentKey(cameraKey, segmentKey, fallbackIndex) {
        return playbackController
            ? playbackController.findClipIndexBySegmentKey(cameraKey, segmentKey, fallbackIndex)
            : -1;
    }

    function syncSecondaryPlayers(offset, shouldPlay) {
        playbackController?.syncSecondaryPlayers(offset, shouldPlay);
    }

    function loadClip(index, options = {}) {
        playbackController?.loadClip(index, options);
    }

    function ensureTelemetryLoaded(clip) {
        return playbackController
            ? playbackController.ensureTelemetryLoaded(clip)
            : Promise.resolve(null);
    }

    function populatePlaylistDurations(playlistToPopulate) {
        return playbackController
            ? playbackController.populatePlaylistDurations(playlistToPopulate)
            : Promise.resolve(playlistToPopulate);
    }

    function preloadTelemetryForPlaylist(playlistToPopulate) {
        playbackController?.preloadTelemetryForPlaylist(playlistToPopulate);
    }

    function applyViewSelection(nextLayout, nextCameraKey, options = {}) {
        return playbackController ? playbackController.applyViewSelection(nextLayout, nextCameraKey, options) : false;
    }

    function switchCamera(nextCameraKey) {
        playbackController?.switchCamera(nextCameraKey);
    }

    function switchLayout(nextLayout) {
        playbackController?.switchLayout(nextLayout);
    }

    const {
        syncHeadingUI,
        syncAutopilotUI,
        syncBlinkerUI,
        syncBrakeUI,
        syncSpeedUI,
        syncFsdPercentUI,
        syncRouteMapUI,
    } = createEventPlayerHudController({
        getPlaylist: () => playlist,
        getPendingEventTime: () => pendingEventTime,
        getActiveIndex: () => activeIndex,
        getPlayerCurrentTime: () => player.currentTime,
        findClipForEventTime,
        eventHasAutopilotActivity,
        eventHasSteeringAngleData,
        eventDriverAssistDisplay,
        eventRouteSvgUrl,
        speedNode,
        blinkerLeftNode,
        headingIndicatorNode,
        headingNode,
        headingLabelNode,
        autopilotNode,
        brakeNode,
        blinkerRightNode,
        fsdPercentNode,
        routeMapNode,
    });

    function syncTimelineUI() {
        const eventTime = getCurrentEventTime();
        const overlayEventTime = (typeof pendingEventTime === "number" && Number.isFinite(pendingEventTime))
            ? pendingEventTime
            : eventTime;
        const totalDuration = getTotalDuration();
        const activeClip = playlist[activeIndex] || null;

        ensureTrimRange(totalDuration);

        if (stageSurface) {
            stageSurface.dataset.hasTelemetry = clipHasTelemetry(activeClip) ? "true" : "false";
        }
        if (currentTimeNode) {
            currentTimeNode.textContent = formatClockTime(eventTime);
        }
        if (baseEventTimestampMs !== null) {
            const overlayDate = new Date(baseEventTimestampMs + (Math.max(0, overlayEventTime) * 1000));
            if (eventDateNode) {
                eventDateNode.textContent = formatOverlayDateLabel(overlayDate);
            }
            if (eventTimeNode) {
                eventTimeNode.textContent = formatOverlayTimeLabel(overlayDate);
            }
        }
        if (totalTimeNode) {
            totalTimeNode.textContent = totalDuration > 0 ? formatClockTime(totalDuration) : "--:--";
        }
        if (scrubber && totalDuration > 0 && !isScrubbing) {
            scrubber.max = String(totalDuration);
            scrubber.value = String(Math.min(eventTime, totalDuration));
        }
        if (eventMarker) {
            if (eventMarkerTime === null || totalDuration <= 0) {
                eventMarker.hidden = true;
            } else {
                const markerTime = Math.min(Math.max(eventMarkerTime, 0), totalDuration);
                eventMarker.style.left = `${(markerTime / totalDuration) * 100}%`;
                eventMarker.hidden = false;
            }
        }
        if (toggleButton) {
            const isPaused = player.paused;
            const nextLabel = isPaused ? "Play" : "Pause";
            toggleButton.setAttribute("aria-label", nextLabel);
            toggleButton.setAttribute("title", nextLabel);
            if (toggleIcon) {
                toggleIcon.src = isPaused ? toggleButton.dataset.playIcon : toggleButton.dataset.pauseIcon;
            }
        }
        if (viewFrame) {
            viewFrame.dataset.layout = activeLayout;
            viewFrame.dataset.activeCamera = activeCameraKey;
        }
        for (const button of layoutButtons) {
            const isActive = button.dataset.layoutOption === activeLayout;
            const icon = button.querySelector(".player-camera-overlay-icon");
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
            if (icon?.dataset.activeSrc && icon?.dataset.inactiveSrc) {
                icon.src = isActive ? icon.dataset.activeSrc : icon.dataset.inactiveSrc;
            }
        }
        const visibleCameraKeys = getVisibleCameraKeys();
        for (const button of cameraButtons) {
            const targetCameraKey = button.dataset.cameraTarget;
            const isActive = Boolean(targetCameraKey && visibleCameraKeys.has(targetCameraKey));
            const isAvailable = Boolean(targetCameraKey && hasCameraPlaylist(targetCameraKey));
            const icon = button.querySelector(".player-camera-overlay-icon");
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
            button.disabled = !isAvailable;
            if (icon?.dataset.activeSrc && icon?.dataset.inactiveSrc) {
                icon.src = isActive ? icon.dataset.activeSrc : icon.dataset.inactiveSrc;
            }
        }
        for (const button of exportFormatButtons) {
            const exportFormat = normalizeExportFormat(button.dataset.exportFormatOption);
            const isActive = exportFormat === (exportController?.getActiveExportFormat() || "4k");
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
        }
        exportController?.syncRenderUI();
        syncBlinkerUI(eventTime);
        syncHeadingUI(eventTime);
        syncAutopilotUI(eventTime);
        syncSpeedUI(eventTime);
        syncBrakeUI(eventTime);
        syncFsdPercentUI();
        syncTrimUI(totalDuration);
        syncCameraMarkerUI(totalDuration);
        syncRouteMapUI(eventTime);
    }

    function togglePlayback() {
        if (player.paused) {
            const playPromise = player.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
            return;
        }
        player.pause();
    }

    function playFromStartMarker() {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        const startTime = Math.min(Math.max(getTrimStartTime(), 0), totalDuration);
        const appliedViewSelection = applyStartMarkerViewSelection({ autoplay: true });
        if (appliedViewSelection) {
            return;
        }

        seekToEventTime(startTime, { autoplay: true });
    }

    editingController = createEventPlayerEditingController({
        documentObject: document,
        player,
        editTrack,
        editTrackFill,
        startMarkerButton,
        endMarkerButton,
        setStartButton,
        setEndButton,
        addCameraMarkerButton,
        layoutButtons,
        cameraButtons,
        getTotalDuration,
        getCurrentEventTime,
        getVisibleCameraKeys,
        getVisibleCameraKeysForSelection,
        getActiveLayout: () => activeLayout,
        getActiveCameraKey: () => activeCameraKey,
        hasCameraPlaylist,
        normalizeViewSelection,
        applyViewSelection,
        normalizePersistedTime,
        formatClockTime,
        onStateChanged: syncTimelineUI,
        schedulePlayerEditsPersistence,
    });
    editingController.bindEditingControls();

    playbackController = createEventPlayerPlaybackController({
        windowObject: window,
        player,
        viewFrame,
        secondaryPlayers,
        preloadPlayers,
        allPlaylists,
        hasCameraPlaylist,
        getFirstAvailableCameraKey,
        getSecondaryCameraKeyMap,
        isCompositeView,
        syncTimelineUI,
        scheduleStageSafeZoneUpdate,
        maybeApplyPlaybackCameraMarker,
        maybeApplyCurrentPlaybackViewMarker,
        syncPlaybackMarkerCheckpoint,
        getPlaybackMarkerIdAtOrBefore,
        decodeTelemetryBuffer,
        populateClipDurations,
        clipHasTelemetry,
        getActiveLayout: () => activeLayout,
        setActiveLayout: (nextLayout) => {
            activeLayout = nextLayout;
        },
        getActiveCameraKey: () => activeCameraKey,
        setActiveCameraKey: (nextCameraKey) => {
            activeCameraKey = nextCameraKey;
        },
        getPlaylist: () => playlist,
        setPlaylist: (nextPlaylist) => {
            playlist = nextPlaylist;
        },
        getActiveIndex: () => activeIndex,
        setActiveIndex: (nextIndex) => {
            activeIndex = nextIndex;
        },
        getPendingEventTime: () => pendingEventTime,
        setPendingEventTime: (nextTime) => {
            pendingEventTime = nextTime;
        },
        isPlaylistReady: () => playlistReady,
        setPlaylistReady: (nextReady) => {
            playlistReady = nextReady;
        },
        durationCache,
        telemetryCache,
    });
    playbackController.bindMediaEvents();

    exportController = createEventPlayerExportController({
        windowObject: window,
        playerEditsSaveUrl,
        playerRenderUrl,
        playerDownloadUrl,
        initialRenderJob,
        initialLatestRenderMetadata: latestRenderMetadata,
        normalizeExportFormat,
        isRenderJobActive,
        describeRenderJobStatus,
        renderStatusNode,
        renderActionButton,
        renderActionIcon,
        downloadActionButton,
        getCanRender: () => getTrimEndTime() > getTrimStartTime(),
        getPlayerEditsPayload: buildPlayerEditsPayload,
        onPlayerEditsChanged: syncTimelineUI,
    });

    if (toggleButton) {
        toggleButton.addEventListener("click", togglePlayback);
    }

    if (playFromStartButton) {
        playFromStartButton.addEventListener("click", playFromStartMarker);
    }

    for (const button of layoutButtons) {
        button.addEventListener("click", () => {
            const nextLayout = button.dataset.layoutOption;
            if (!nextLayout) {
                return;
            }
            noteManualViewSelectionOverride(getCurrentEventTime());
            switchLayout(nextLayout);
        });
    }

    for (const button of cameraButtons) {
        button.addEventListener("click", () => {
            const nextCameraKey = button.dataset.cameraTarget;
            if (!nextCameraKey) {
                return;
            }
            noteManualViewSelectionOverride(getCurrentEventTime());
            switchCamera(nextCameraKey);
        });
    }

    if (exportFormatToggle) {
        exportFormatToggle.addEventListener("click", () => {
            toggleExportFormat();
        });
    }

    if (renderActionButton) {
        renderActionButton.addEventListener("click", () => {
            handleRenderAction().catch(() => {});
        });
    }

    if (downloadActionButton) {
        downloadActionButton.addEventListener("click", handleDownloadAction);
    }

    if (viewFrame) {
        viewFrame.addEventListener("click", (event) => {
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            if (target.closest(".player-camera-overlay-button")) {
                return;
            }
            togglePlayback();
        });
    }

    if (scrubber) {
        const updateScrubTime = () => {
            if (!playlistReady) {
                return;
            }
            const nextTime = Number.parseFloat(scrubber.value);
            if (Number.isNaN(nextTime)) {
                return;
            }
            pendingEventTime = nextTime;
            syncTimelineUI();
        };

        const commitScrubTime = () => {
            if (!playlistReady) {
                return;
            }
            const nextTime = Number.parseFloat(scrubber.value);
            if (Number.isNaN(nextTime)) {
                return;
            }
            isScrubbing = false;
            const autoplay = !player.paused;
            const currentMarkerId = getPlaybackMarkerIdAtOrBefore(getActualPlaybackEventTime());
            const nextMarkerId = getPlaybackMarkerIdAtOrBefore(nextTime);
            if (currentMarkerId !== nextMarkerId && maybeApplyCurrentPlaybackViewMarker(nextTime, { autoplay })) {
                return;
            }
            seekToEventTime(nextTime);
        };

        scrubber.addEventListener("pointerdown", () => {
            isScrubbing = true;
        });
        scrubber.addEventListener("input", updateScrubTime);
        scrubber.addEventListener("change", () => {
            if (isScrubbing) {
                return;
            }
            if (performance.now() - lastPointerCommitAt < 250) {
                return;
            }
            commitScrubTime();
        });
        scrubber.addEventListener("pointerup", () => {
            lastPointerCommitAt = performance.now();
            commitScrubTime();
        });
        scrubber.addEventListener("keyup", (event) => {
            if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
                commitScrubTime();
            }
        });
        scrubber.addEventListener("blur", () => {
            if (!isScrubbing) {
                return;
            }
            commitScrubTime();
        });
    }

    window.__SENTRYMANAGER_TEST_API = createEventPlayerSnapshotApi({
        windowObject: window,
        player,
        viewFrame,
        stageSurface,
        stageSafeZones,
        getActiveLayout: () => activeLayout,
        getActiveCameraKey: () => activeCameraKey,
        getActiveIndex: () => activeIndex,
        getPlaylist: () => playlist,
        getAllPlaylists: () => allPlaylists,
        getPendingEventTime: () => pendingEventTime,
        isPlaylistReady: () => playlistReady,
        applyViewSelection,
        syncSecondaryPlayers,
        findClipIndexBySegmentKey,
        loadClip,
        ensureTelemetryLoaded,
        syncTimelineUI,
        scheduleStageSafeZoneUpdate,
    });

    populatePlaylistDurations(playlist).then(() => {
        if (!savedPlayerEditsHydrated) {
            hydrateSavedPlayerEdits(rawSavedEdits);
            exportController?.markCurrentPlayerEditsPersisted();
            savedPlayerEditsHydrated = true;
        }
        playlistReady = true;
        preloadTelemetryForPlaylist(playlist);
        if (!initialSeekApplied) {
            initialSeekApplied = true;
            seekToEventTime(initialStartTime, { autoplay: true });
            return;
        }
        syncTimelineUI();
    });

    syncTimelineUI();
    scheduleStageSafeZoneUpdate();
    exportController.startRenderPollingIfNeeded();
}