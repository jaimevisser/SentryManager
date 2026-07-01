function getFiniteNumberOrNull(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getStringOrNull(value) {
    return typeof value === "string" ? value : null;
}

function getObjectOrNull(value) {
    return value && typeof value === "object" ? value : null;
}

export function loadEventPlayerBootstrap(documentObject, normalizeDriverAssistDisplay) {
    const player = documentObject.querySelector("[data-event-player]");
    const playlistNode = documentObject.getElementById("event-playlist");
    if (!player || !playlistNode) {
        return null;
    }

    let playlistConfig;
    try {
        playlistConfig = JSON.parse(playlistNode.textContent || "{}");
    } catch {
        return null;
    }

    const allPlaylists = getObjectOrNull(playlistConfig?.playlists);
    const defaultViewKey = getStringOrNull(playlistConfig?.defaultViewKey);
    if (!allPlaylists || !defaultViewKey) {
        return null;
    }

    const eventFlags = getObjectOrNull(playlistConfig?.eventFlags);
    const initialStartTime = getFiniteNumberOrNull(playlistConfig?.initialStartTime);

    return {
        player,
        allPlaylists,
        defaultViewKey,
        rawSavedEdits: playlistConfig?.savedEdits,
        playerEditsSaveUrl: getStringOrNull(playlistConfig?.playerEditsSaveUrl),
        playerRenderUrl: getStringOrNull(playlistConfig?.playerRenderUrl),
        playerDownloadUrl: getStringOrNull(playlistConfig?.playerDownloadUrl),
        initialRenderJob: getObjectOrNull(playlistConfig?.activeRenderJob),
        latestRenderMetadata: getObjectOrNull(playlistConfig?.latestRender),
        eventHasAutopilotActivity: Boolean(eventFlags?.hasAutopilotActivity),
        eventHasSteeringAngleData: Boolean(eventFlags?.hasSteeringAngleData),
        eventDriverAssistDisplay: normalizeDriverAssistDisplay(eventFlags?.driverAssistDisplay),
        eventMarkerTime: getFiniteNumberOrNull(playlistConfig?.eventMarkerTime),
        eventTimestampIso: getStringOrNull(playlistConfig?.eventTimestampIso),
        initialStartTime: initialStartTime === null ? 0 : Math.max(0, initialStartTime),
    };
}

export function queryEventPlayerNodes(documentObject) {
    return {
        currentTimeNode: documentObject.querySelector("[data-player-current-time]"),
        totalTimeNode: documentObject.querySelector("[data-player-total-time]"),
        speedNode: documentObject.querySelector("[data-player-speed]"),
        blinkerLeftNode: documentObject.querySelector("[data-player-blinker-left]"),
        headingIndicatorNode: documentObject.querySelector("[data-player-heading-indicator]"),
        headingNode: documentObject.querySelector("[data-player-heading]"),
        headingLabelNode: documentObject.querySelector("[data-player-heading-label]"),
        autopilotNode: documentObject.querySelector("[data-player-autopilot]"),
        brakeNode: documentObject.querySelector("[data-player-brake]"),
        blinkerRightNode: documentObject.querySelector("[data-player-blinker-right]"),
        fsdPercentNode: documentObject.querySelector("[data-player-fsd-percent]"),
        scrubber: documentObject.querySelector("[data-player-scrub]"),
        eventMarker: documentObject.querySelector("[data-player-event-marker]"),
        editTrack: documentObject.querySelector("[data-player-edit-track]"),
        editTrackFill: documentObject.querySelector("[data-player-edit-fill]"),
        startMarkerButton: documentObject.querySelector("[data-player-start-marker]"),
        endMarkerButton: documentObject.querySelector("[data-player-end-marker]"),
        setStartButton: documentObject.querySelector("[data-player-set-start]"),
        setEndButton: documentObject.querySelector("[data-player-set-end]"),
        addCameraMarkerButton: documentObject.querySelector("[data-player-add-camera-marker]"),
        exportFormatToggle: documentObject.querySelector(".player-export-format-toggle"),
        exportFormatButtons: Array.from(documentObject.querySelectorAll("[data-export-format-option]")),
        renderActionButton: documentObject.querySelector("[data-player-render-action]"),
        renderActionIcon: documentObject.querySelector("[data-player-render-action-icon]"),
        downloadActionButton: documentObject.querySelector("[data-player-download-action]"),
        renderStatusNode: documentObject.querySelector("[data-player-render-status]"),
        toggleButton: documentObject.querySelector("[data-player-toggle]"),
        toggleIcon: documentObject.querySelector("[data-player-toggle-icon]"),
        layoutButtons: Array.from(documentObject.querySelectorAll("[data-layout-option]")),
        cameraButtons: Array.from(documentObject.querySelectorAll("[data-camera-target]")),
        stageSurface: documentObject.querySelector("[data-player-stage-surface]"),
        viewFrame: documentObject.querySelector("[data-player-view-frame]"),
        eventDateNode: documentObject.querySelector("[data-player-event-date]"),
        eventTimeNode: documentObject.querySelector("[data-player-event-time]"),
        stageSafeZones: {
            left: documentObject.querySelector('[data-player-safe-zone="left"]'),
            right: documentObject.querySelector('[data-player-safe-zone="right"]'),
            topLeft: documentObject.querySelector('[data-player-safe-zone="top-left"]'),
        },
        secondaryPlayers: {
            left: documentObject.querySelector('[data-secondary-slot="left"]'),
            right: documentObject.querySelector('[data-secondary-slot="right"]'),
        },
    };
}

export function createPreloadPlayers(documentObject) {
    const preloadPlayers = {
        master: documentObject.createElement("video"),
        left: documentObject.createElement("video"),
        right: documentObject.createElement("video"),
    };

    for (const preloadPlayer of Object.values(preloadPlayers)) {
        preloadPlayer.preload = "auto";
        preloadPlayer.muted = true;
        preloadPlayer.playsInline = true;
    }

    return preloadPlayers;
}