import {
    AUTOPILOT_NONE_STATE,
    AUTOPILOT_PRESENT_MASK,
    BLINKER_LEFT_FLAG_MASK,
    BLINKER_LEFT_PRESENT_MASK,
    BLINKER_RIGHT_FLAG_MASK,
    BLINKER_RIGHT_PRESENT_MASK,
    BRAKE_FLAG_MASK,
    BRAKE_PRESENT_MASK,
    CAMERA_LAYOUT_SEQUENCE,
    HEADING_PRESENT_MASK,
    SPEED_PRESENT_MASK,
    STEERING_ANGLE_PRESENT_MASK,
    decodeTelemetryBuffer,
    populateClipDurations,
} from "./event_player-media.js";

export function initEventPlayer() {
    const player = document.querySelector("[data-event-player]");
    const playlistNode = document.getElementById("event-playlist");
    if (!player || !playlistNode) {
        return;
    }

    let playlistConfig;
    try {
        playlistConfig = JSON.parse(playlistNode.textContent || "{}");
    } catch {
        return;
    }

    const allPlaylists = playlistConfig?.playlists;
    const defaultViewKey = playlistConfig?.defaultViewKey;
    const rawEventMarkerTime = playlistConfig?.eventMarkerTime;
    const rawInitialStartTime = playlistConfig?.initialStartTime;
    const rawSavedEdits = playlistConfig?.savedEdits;
    const playerEditsSaveUrl = typeof playlistConfig?.playerEditsSaveUrl === "string"
        ? playlistConfig.playerEditsSaveUrl
        : null;
    const eventFlags = playlistConfig?.eventFlags;
    const eventHasAutopilotActivity = Boolean(eventFlags?.hasAutopilotActivity);
    const eventHasSteeringAngleData = Boolean(eventFlags?.hasSteeringAngleData);
    const rawEventFsdOnPercent = eventFlags?.fsdOnPercent;
    const eventFsdOnPercent = typeof rawEventFsdOnPercent === "number" && Number.isFinite(rawEventFsdOnPercent)
        ? Math.max(0, Math.min(100, rawEventFsdOnPercent))
        : null;
    const eventMarkerTime = typeof rawEventMarkerTime === "number" && Number.isFinite(rawEventMarkerTime)
        ? rawEventMarkerTime
        : null;
    const initialStartTime = typeof rawInitialStartTime === "number" && Number.isFinite(rawInitialStartTime)
        ? Math.max(0, rawInitialStartTime)
        : 0;
    if (!allPlaylists || typeof allPlaylists !== "object" || !defaultViewKey) {
        return;
    }

    let activeLayout = "single";
    let activeCameraKey = hasCameraPlaylist(defaultViewKey)
        ? defaultViewKey
        : CAMERA_LAYOUT_SEQUENCE.find((cameraKey) => hasCameraPlaylist(cameraKey)) || defaultViewKey;
    let playlist = allPlaylists[activeCameraKey];
    if (!Array.isArray(playlist) || playlist.length === 0) {
        return;
    }

    const currentTimeNode = document.querySelector("[data-player-current-time]");
    const totalTimeNode = document.querySelector("[data-player-total-time]");
    const speedNode = document.querySelector("[data-player-speed]");
    const blinkerLeftNode = document.querySelector("[data-player-blinker-left]");
    const headingIndicatorNode = document.querySelector("[data-player-heading-indicator]");
    const headingNode = document.querySelector("[data-player-heading]");
    const headingLabelNode = document.querySelector("[data-player-heading-label]");
    const autopilotNode = document.querySelector("[data-player-autopilot]");
    const brakeNode = document.querySelector("[data-player-brake]");
    const blinkerRightNode = document.querySelector("[data-player-blinker-right]");
    const fsdPercentNode = document.querySelector("[data-player-fsd-percent]");
    const scrubber = document.querySelector("[data-player-scrub]");
    const eventMarker = document.querySelector("[data-player-event-marker]");
    const editTrack = document.querySelector("[data-player-edit-track]");
    const editTrackFill = document.querySelector("[data-player-edit-fill]");
    const startMarkerButton = document.querySelector("[data-player-start-marker]");
    const endMarkerButton = document.querySelector("[data-player-end-marker]");
    const setStartButton = document.querySelector("[data-player-set-start]");
    const setEndButton = document.querySelector("[data-player-set-end]");
    const addCameraMarkerButton = document.querySelector("[data-player-add-camera-marker]");
    const toggleButton = document.querySelector("[data-player-toggle]");
    const toggleIcon = document.querySelector("[data-player-toggle-icon]");
    const layoutButtons = Array.from(document.querySelectorAll("[data-layout-option]"));
    const cameraButtons = Array.from(document.querySelectorAll("[data-camera-target]"));
    const cameraMarkerControlBlueprints = [...layoutButtons, ...cameraButtons].map((button) => ({
        type: button.dataset.layoutOption ? "layout" : "camera",
        value: button.dataset.layoutOption || button.dataset.cameraTarget || "",
        ariaLabel: button.getAttribute("aria-label") || "",
        icon: (() => {
            const icon = button.querySelector(".player-camera-overlay-icon");
            return {
                inactiveSrc: icon?.dataset.inactiveSrc || icon?.getAttribute("src") || "",
                activeSrc: icon?.dataset.activeSrc || icon?.dataset.inactiveSrc || icon?.getAttribute("src") || "",
                src: icon?.getAttribute("src") || "",
            };
        })(),
    }));
    const stageSurface = document.querySelector("[data-player-stage-surface]");
    const viewFrame = document.querySelector("[data-player-view-frame]");
    const stageSafeZones = {
        left: document.querySelector('[data-player-safe-zone="left"]'),
        right: document.querySelector('[data-player-safe-zone="right"]'),
    };
    const secondaryPlayers = {
        left: document.querySelector('[data-secondary-slot="left"]'),
        right: document.querySelector('[data-secondary-slot="right"]'),
    };
    const preloadPlayers = {
        master: document.createElement("video"),
        left: document.createElement("video"),
        right: document.createElement("video"),
    };
    let activeIndex = 0;
    let pendingEventTime = null;
    let playlistReady = false;
    let isScrubbing = false;
    let activeLoadToken = 0;
    let lastPointerCommitAt = 0;
    let initialSeekApplied = false;
    let stageSafeZoneUpdatePending = false;
    let trimStartTime = 0;
    let trimEndTime = 0;
    let trimInitialized = false;
    let trimEndPinnedToDuration = true;
    let activeTrimMarker = null;
    let cameraMarkers = [];
    let nextCameraMarkerId = 1;
    let activeCameraMarkerId = null;
    let startMarkerPopoverOpen = false;
    let lastPlaybackEventTime = null;
    let activePlaybackCameraMarkerId = null;
    let playerEditsSaveTimer = null;
    let playerEditsSaveInFlight = false;
    let pendingPlayerEditsSnapshot = null;
    let persistedPlayerEditsSignature = null;
    let savedPlayerEditsHydrated = false;

    const cameraMarkerNodes = new Map();
    let startMarkerViewSelection = {
        layout: activeLayout,
        cameraKey: activeCameraKey,
    };
    const startMarkerPopover = editTrack && startMarkerButton
        ? document.createElement("div")
        : null;
    const startMarkerPopoverButtons = [];

    if (startMarkerPopover && editTrack) {
        startMarkerPopover.className = "player-edit-camera-popover player-edit-start-marker-popover";
        startMarkerPopover.hidden = true;
        startMarkerPopoverButtons.push(...createViewSelectionControls(startMarkerPopover));
        editTrack.append(startMarkerPopover);
    }

    const durationCache = new Map();
    const telemetryCache = new Map();

    for (const preloadPlayer of Object.values(preloadPlayers)) {
        preloadPlayer.preload = "auto";
        preloadPlayer.muted = true;
        preloadPlayer.playsInline = true;
    }

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

    function getCameraOffsetKey(cameraKey, offset) {
        const currentIndex = CAMERA_LAYOUT_SEQUENCE.indexOf(cameraKey);
        if (currentIndex < 0) {
            return null;
        }
        const nextIndex = (currentIndex + offset + CAMERA_LAYOUT_SEQUENCE.length) % CAMERA_LAYOUT_SEQUENCE.length;
        return CAMERA_LAYOUT_SEQUENCE[nextIndex];
    }

    function getSecondaryCameraKeyMapForSelection(layout, cameraKey) {
        if (layout === "single") {
            return { left: null, right: null };
        }
        if (layout === "double") {
            return { left: getCameraOffsetKey(cameraKey, -1), right: null };
        }
        return {
            left: getCameraOffsetKey(cameraKey, -1),
            right: getCameraOffsetKey(cameraKey, 1),
        };
    }

    function getSecondaryCameraKeyMap() {
        return getSecondaryCameraKeyMapForSelection(activeLayout, activeCameraKey);
    }

    function getVisibleCameraKeysForSelection(layout, cameraKey) {
        const safeCameraKey = getFirstAvailableCameraKey(cameraKey);
        const visibleCameraKeys = new Set(safeCameraKey ? [safeCameraKey] : []);
        const secondaryCameraKeys = getSecondaryCameraKeyMapForSelection(layout, safeCameraKey);
        for (const cameraKey of Object.values(secondaryCameraKeys)) {
            if (cameraKey && hasCameraPlaylist(cameraKey)) {
                visibleCameraKeys.add(cameraKey);
            }
        }
        return visibleCameraKeys;
    }

    function getVisibleCameraKeys() {
        return getVisibleCameraKeysForSelection(activeLayout, activeCameraKey);
    }

    function findCameraMarker(markerId) {
        return cameraMarkers.find((marker) => marker.id === markerId) || null;
    }

    function normalizeCameraMarker(marker) {
        if (!marker) {
            return null;
        }

        return normalizeViewSelection(marker);
    }

    function createViewSelectionControls(popover) {
        const controlButtons = [];
        for (const blueprint of cameraMarkerControlBlueprints) {
            if (!blueprint.value) {
                continue;
            }
            const controlButton = document.createElement("button");
            controlButton.type = "button";
            controlButton.className = "player-camera-overlay-button";
            controlButton.setAttribute("aria-label", blueprint.ariaLabel);
            if (blueprint.type === "layout") {
                controlButton.dataset.viewLayoutOption = blueprint.value;
            } else {
                controlButton.dataset.viewCameraTarget = blueprint.value;
            }

            const icon = document.createElement("img");
            icon.className = "player-camera-overlay-icon";
            icon.dataset.inactiveSrc = blueprint.icon.inactiveSrc;
            icon.dataset.activeSrc = blueprint.icon.activeSrc;
            icon.src = blueprint.icon.src;
            icon.alt = "";
            icon.setAttribute("aria-hidden", "true");
            controlButton.append(icon);
            popover.append(controlButton);
            controlButtons.push(controlButton);
        }
        return controlButtons;
    }

    function normalizePersistedTime(value) {
        return Math.round(Math.max(0, value) * 1000) / 1000;
    }

    function buildPlayerEditsPayload() {
        normalizeViewSelection(startMarkerViewSelection);
        return {
            trimStartTime: normalizePersistedTime(trimStartTime),
            trimEndTime: normalizePersistedTime(trimEndTime),
            startMarkerView: {
                layout: startMarkerViewSelection.layout,
                cameraKey: startMarkerViewSelection.cameraKey,
            },
            cameraMarkers: cameraMarkers.map((marker) => ({
                id: marker.id,
                time: normalizePersistedTime(marker.time),
                layout: marker.layout,
                cameraKey: marker.cameraKey,
            })),
        };
    }

    function getPlayerEditsSignature(payload) {
        return JSON.stringify(payload);
    }

    async function flushPlayerEditsPersistence() {
        if (!playerEditsSaveUrl || playerEditsSaveInFlight || !pendingPlayerEditsSnapshot) {
            return;
        }

        const snapshot = pendingPlayerEditsSnapshot;
        pendingPlayerEditsSnapshot = null;
        playerEditsSaveInFlight = true;

        try {
            const response = await fetch(playerEditsSaveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(snapshot.payload),
            });
            const responsePayload = await response.json().catch(() => null);
            if (!response.ok) {
                throw new Error(typeof responsePayload?.error === "string" ? responsePayload.error : "Could not save player edits.");
            }
            persistedPlayerEditsSignature = snapshot.signature;
        } catch (error) {
            pendingPlayerEditsSnapshot = snapshot;
            console.error(error instanceof Error ? error.message : "Could not save player edits.");
        } finally {
            playerEditsSaveInFlight = false;
            if (pendingPlayerEditsSnapshot && pendingPlayerEditsSnapshot.signature !== snapshot.signature) {
                window.setTimeout(() => {
                    flushPlayerEditsPersistence().catch(() => {});
                }, 0);
            }
        }
    }

    function schedulePlayerEditsPersistence() {
        if (!playerEditsSaveUrl) {
            return;
        }

        const payload = buildPlayerEditsPayload();
        const signature = getPlayerEditsSignature(payload);
        if (signature === persistedPlayerEditsSignature && pendingPlayerEditsSnapshot === null && !playerEditsSaveInFlight) {
            return;
        }

        pendingPlayerEditsSnapshot = { payload, signature };
        if (playerEditsSaveTimer !== null) {
            window.clearTimeout(playerEditsSaveTimer);
        }
        playerEditsSaveTimer = window.setTimeout(() => {
            playerEditsSaveTimer = null;
            flushPlayerEditsPersistence().catch(() => {});
        }, 250);
    }

    function hydrateSavedPlayerEdits(rawSavedPlayerEdits) {
        if (!rawSavedPlayerEdits || typeof rawSavedPlayerEdits !== "object") {
            return;
        }

        const rawTrimStartTime = rawSavedPlayerEdits.trimStartTime;
        const rawTrimEndTime = rawSavedPlayerEdits.trimEndTime;
        if (typeof rawTrimStartTime === "number" && Number.isFinite(rawTrimStartTime)
            && typeof rawTrimEndTime === "number" && Number.isFinite(rawTrimEndTime)) {
            trimStartTime = Math.max(0, rawTrimStartTime);
            trimEndTime = Math.max(0, rawTrimEndTime);
            trimInitialized = true;
            trimEndPinnedToDuration = false;
        }

        const rawStartMarkerView = rawSavedPlayerEdits.startMarkerView;
        if (rawStartMarkerView && typeof rawStartMarkerView === "object") {
            if (typeof rawStartMarkerView.layout === "string") {
                startMarkerViewSelection.layout = rawStartMarkerView.layout;
            }
            if (typeof rawStartMarkerView.cameraKey === "string") {
                startMarkerViewSelection.cameraKey = rawStartMarkerView.cameraKey;
            }
            normalizeViewSelection(startMarkerViewSelection);
        }

        const rawCameraMarkers = Array.isArray(rawSavedPlayerEdits.cameraMarkers) ? rawSavedPlayerEdits.cameraMarkers : [];
        const hydratedCameraMarkers = [];
        let nextMarkerId = 1;
        for (const rawMarker of rawCameraMarkers) {
            if (!rawMarker || typeof rawMarker !== "object") {
                continue;
            }
            const markerId = typeof rawMarker.id === "number" && Number.isInteger(rawMarker.id) && rawMarker.id > 0
                ? rawMarker.id
                : nextMarkerId;
            const markerTime = typeof rawMarker.time === "number" && Number.isFinite(rawMarker.time)
                ? Math.max(0, rawMarker.time)
                : null;
            if (markerTime === null) {
                continue;
            }
            const marker = normalizeCameraMarker({
                id: markerId,
                time: markerTime,
                layout: typeof rawMarker.layout === "string" ? rawMarker.layout : "single",
                cameraKey: typeof rawMarker.cameraKey === "string" ? rawMarker.cameraKey : activeCameraKey,
            });
            if (!marker) {
                continue;
            }
            hydratedCameraMarkers.push(marker);
            nextMarkerId = Math.max(nextMarkerId, markerId + 1);
        }
        cameraMarkers = hydratedCameraMarkers;
        sortCameraMarkers();
        nextCameraMarkerId = nextMarkerId;
    }

    function sortCameraMarkers() {
        cameraMarkers = [...cameraMarkers].sort((leftMarker, rightMarker) => leftMarker.time - rightMarker.time);
    }

    function setCameraMarkerTime(markerId, nextTime) {
        const marker = findCameraMarker(markerId);
        const totalDuration = getTotalDuration();
        if (!marker || totalDuration <= 0) {
            return;
        }

        marker.time = Math.min(Math.max(nextTime, 0), totalDuration);
        sortCameraMarkers();
        syncTimelineUI();
        schedulePlayerEditsPersistence();
    }

    function removeCameraMarker(markerId) {
        const markerExists = cameraMarkers.some((marker) => marker.id === markerId);
        if (!markerExists) {
            return;
        }

        cameraMarkers = cameraMarkers.filter((marker) => marker.id !== markerId);
        if (activeCameraMarkerId === markerId) {
            activeCameraMarkerId = null;
        }
        if (activePlaybackCameraMarkerId === markerId) {
            activePlaybackCameraMarkerId = getLatestCameraMarkerAtOrBefore(getCurrentEventTime())?.id ?? null;
        }
        syncTimelineUI();
        schedulePlayerEditsPersistence();
    }

    function isCameraMarkerPointerOutsideLane(clientY) {
        if (!editTrack) {
            return false;
        }

        const rect = editTrack.getBoundingClientRect();
        const threshold = 28;
        return clientY < rect.top - threshold || clientY > rect.bottom + threshold;
    }

    function getPlaybackViewMarkers() {
        const playbackMarkers = [];
        if (trimInitialized) {
            const startMarker = normalizeViewSelection({
                id: "start",
                time: trimStartTime,
                layout: startMarkerViewSelection.layout,
                cameraKey: startMarkerViewSelection.cameraKey,
            });
            if (startMarker) {
                playbackMarkers.push(startMarker);
            }
        }
        playbackMarkers.push(...cameraMarkers.map((marker) => normalizeCameraMarker({ ...marker })));
        playbackMarkers.sort((leftMarker, rightMarker) => {
            if (Math.abs(leftMarker.time - rightMarker.time) < 0.01) {
                if (leftMarker.id === "start") {
                    return -1;
                }
                if (rightMarker.id === "start") {
                    return 1;
                }
            }
            return leftMarker.time - rightMarker.time;
        });
        return playbackMarkers;
    }

    function getLatestCameraMarkerAtOrBefore(eventTime) {
        const playbackMarkers = getPlaybackViewMarkers();
        for (let index = playbackMarkers.length - 1; index >= 0; index -= 1) {
            const marker = playbackMarkers[index];
            if (marker.time <= eventTime + 0.01) {
                return marker;
            }
        }
        return null;
    }

    function getPlaybackMarkerIdAtOrBefore(eventTime) {
        return getLatestCameraMarkerAtOrBefore(eventTime)?.id ?? null;
    }

    function getLatestCrossedCameraMarker(previousEventTime, nextEventTime) {
        if (nextEventTime < previousEventTime) {
            return null;
        }

        const playbackMarkers = getPlaybackViewMarkers();
        for (let index = playbackMarkers.length - 1; index >= 0; index -= 1) {
            const marker = playbackMarkers[index];
            if (marker.time > nextEventTime + 0.01) {
                continue;
            }
            if (marker.time <= previousEventTime + 0.01) {
                break;
            }
            return marker;
        }
        return null;
    }

    function syncPlaybackMarkerCheckpoint(eventTime) {
        lastPlaybackEventTime = eventTime;
        activePlaybackCameraMarkerId = getLatestCameraMarkerAtOrBefore(eventTime)?.id ?? null;
    }

    function doesViewSelectionMatchCurrentView(selection) {
        normalizeViewSelection(selection);
        if (selection.layout !== activeLayout) {
            return false;
        }

        const currentVisibleCameraKeys = [...getVisibleCameraKeys()].sort().join(",");
        const selectionVisibleCameraKeys = [...getVisibleCameraKeysForSelection(selection.layout, selection.cameraKey)].sort().join(",");
        return currentVisibleCameraKeys === selectionVisibleCameraKeys;
    }

    function syncOverlayButtonState(button, isActive, isDisabled = false) {
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
        button.disabled = isDisabled;
        const icon = button.querySelector(".player-camera-overlay-icon");
        if (icon?.dataset.activeSrc && icon?.dataset.inactiveSrc) {
            icon.src = isActive ? icon.dataset.activeSrc : icon.dataset.inactiveSrc;
        }
    }

    function syncViewSelectionControls(selection, controlButtons) {
        normalizeViewSelection(selection);
        const visibleCameraKeys = getVisibleCameraKeysForSelection(selection.layout, selection.cameraKey);
        for (const button of controlButtons) {
            const layoutOption = button.dataset.viewLayoutOption;
            const cameraTarget = button.dataset.viewCameraTarget;
            if (layoutOption) {
                syncOverlayButtonState(button, layoutOption === selection.layout, false);
                continue;
            }
            const isAvailable = Boolean(cameraTarget && hasCameraPlaylist(cameraTarget));
            const isActive = Boolean(cameraTarget && visibleCameraKeys.has(cameraTarget));
            syncOverlayButtonState(button, isActive, !isAvailable);
        }
    }

    function syncCameraMarkerPopover(marker, node) {
        if (!node) {
            return;
        }

        syncViewSelectionControls(marker, node.controlButtons);
    }

    function getCameraMarkerPopoverAlign(markerTime, totalDuration) {
        if (!(totalDuration > 0)) {
            return "center";
        }
        const ratio = markerTime / totalDuration;
        if (ratio <= 0.16) {
            return "start";
        }
        if (ratio >= 0.84) {
            return "end";
        }
        return "center";
    }

    function createCameraMarkerNode(marker) {
        if (!editTrack) {
            return null;
        }

        const shell = document.createElement("div");
        shell.className = "player-edit-camera-marker-shell";
        shell.dataset.markerId = String(marker.id);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "player-edit-marker player-edit-marker-camera";

        let draggedDuringPointerSequence = false;
        let pointerStartX = 0;
        let pointerStartY = 0;

        const popover = document.createElement("div");
        popover.className = "player-edit-camera-popover";
        popover.hidden = true;

        const controlButtons = createViewSelectionControls(popover);

        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (draggedDuringPointerSequence) {
                draggedDuringPointerSequence = false;
                return;
            }
            startMarkerPopoverOpen = false;
            activeCameraMarkerId = activeCameraMarkerId === marker.id ? null : marker.id;
            syncTimelineUI();
        });

        button.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
                return;
            }
            pointerStartX = event.clientX;
            pointerStartY = event.clientY;
            draggedDuringPointerSequence = false;
            shell.style.setProperty("--player-marker-drag-offset-y", "0px");
            shell.classList.remove("is-removing");
            button.setPointerCapture(event.pointerId);
        });

        button.addEventListener("pointermove", (event) => {
            if (!button.hasPointerCapture(event.pointerId)) {
                return;
            }

            const deltaX = event.clientX - pointerStartX;
            const deltaY = event.clientY - pointerStartY;
            if (!draggedDuringPointerSequence && Math.hypot(deltaX, deltaY) < 4) {
                return;
            }

            draggedDuringPointerSequence = true;
            event.preventDefault();
            shell.style.setProperty("--player-marker-drag-offset-y", `${deltaY}px`);
            shell.classList.toggle("is-removing", isCameraMarkerPointerOutsideLane(event.clientY));
            const nextTime = getEditTrackTimeFromClientX(event.clientX);
            setCameraMarkerTime(marker.id, nextTime);
        });

        const finishDragging = (event) => {
            if (!button.hasPointerCapture(event.pointerId)) {
                return;
            }

            button.releasePointerCapture(event.pointerId);
            const deltaX = event.clientX - pointerStartX;
            const deltaY = event.clientY - pointerStartY;
            shell.style.setProperty("--player-marker-drag-offset-y", "0px");

            if (Math.hypot(deltaX, deltaY) < 4) {
                shell.classList.remove("is-removing");
                return;
            }

            draggedDuringPointerSequence = true;
            event.preventDefault();
            const shouldRemoveMarker = event.type !== "pointercancel" && isCameraMarkerPointerOutsideLane(event.clientY);
            shell.classList.remove("is-removing");
            if (shouldRemoveMarker) {
                removeCameraMarker(marker.id);
                return;
            }
            const nextTime = getEditTrackTimeFromClientX(event.clientX);
            setCameraMarkerTime(marker.id, nextTime);
        };

        const cancelDragging = (event) => {
            if (!button.hasPointerCapture(event.pointerId)) {
                return;
            }

            button.releasePointerCapture(event.pointerId);
            shell.style.setProperty("--player-marker-drag-offset-y", "0px");
            shell.classList.remove("is-removing");
        };

        button.addEventListener("pointerup", finishDragging);
        button.addEventListener("pointercancel", cancelDragging);

        popover.addEventListener("click", (event) => {
            event.stopPropagation();
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            const controlButton = target.closest(".player-camera-overlay-button");
            if (!(controlButton instanceof HTMLButtonElement)) {
                return;
            }

            const markerState = findCameraMarker(marker.id);
            if (!markerState) {
                return;
            }

            const nextLayout = controlButton.dataset.viewLayoutOption;
            if (nextLayout) {
                markerState.layout = nextLayout;
                normalizeCameraMarker(markerState);
                syncTimelineUI();
                schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            markerState.cameraKey = nextCameraKey;
            normalizeCameraMarker(markerState);
            syncTimelineUI();
            schedulePlayerEditsPersistence();
        });

        shell.append(button, popover);
        editTrack.append(shell);

        const node = { shell, button, popover, controlButtons };
        cameraMarkerNodes.set(marker.id, node);
        return node;
    }

    function syncStartMarkerPopoverUI(totalDuration) {
        if (!startMarkerButton || !startMarkerPopover) {
            return;
        }

        normalizeViewSelection(startMarkerViewSelection);
        const startRatio = totalDuration > 0 ? trimStartTime / totalDuration : 0;
        startMarkerPopover.style.left = `${startRatio * 100}%`;
        startMarkerPopover.hidden = !startMarkerPopoverOpen;
        startMarkerPopover.dataset.align = getCameraMarkerPopoverAlign(trimStartTime, totalDuration);
        startMarkerButton.classList.toggle("is-open", startMarkerPopoverOpen);
        syncViewSelectionControls(startMarkerViewSelection, startMarkerPopoverButtons);
    }

    function syncCameraMarkerUI(totalDuration) {
        if (!editTrack) {
            return;
        }

        const activeIds = new Set(cameraMarkers.map((marker) => marker.id));
        for (const [markerId, node] of cameraMarkerNodes.entries()) {
            if (activeIds.has(markerId)) {
                continue;
            }
            node.shell.remove();
            cameraMarkerNodes.delete(markerId);
        }

        for (const marker of cameraMarkers) {
            normalizeCameraMarker(marker);
            const node = cameraMarkerNodes.get(marker.id) || createCameraMarkerNode(marker);
            if (!node) {
                continue;
            }

            const ratio = totalDuration > 0 ? Math.min(Math.max(marker.time / totalDuration, 0), 1) : 0;
            node.shell.style.setProperty("--player-marker-drag-offset-y", "0px");
            node.shell.classList.remove("is-removing");
            node.shell.style.left = `${ratio * 100}%`;
            node.button.setAttribute("aria-label", `Camera marker at ${formatClockTime(marker.time)}`);
            node.button.classList.toggle("is-open", activeCameraMarkerId === marker.id);
            node.popover.hidden = activeCameraMarkerId !== marker.id;
            node.popover.dataset.align = getCameraMarkerPopoverAlign(marker.time, totalDuration);
            syncCameraMarkerPopover(marker, node);
        }
    }

    function addCameraMarker(nextTime) {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        const marker = normalizeCameraMarker({
            id: nextCameraMarkerId++,
            time: Math.min(Math.max(nextTime, 0), totalDuration),
            layout: activeLayout,
            cameraKey: activeCameraKey,
        });
        cameraMarkers = [...cameraMarkers, marker];
        sortCameraMarkers();
        startMarkerPopoverOpen = false;
        activeCameraMarkerId = marker.id;
        syncTimelineUI();
        schedulePlayerEditsPersistence();
    }

    function applyViewSelection(nextLayout, nextCameraKey, options = {}) {
        const normalizedLayout = ["single", "double", "triple"].includes(nextLayout) ? nextLayout : activeLayout;
        const normalizedCameraKey = getFirstAvailableCameraKey(nextCameraKey);
        if (!normalizedCameraKey || !hasCameraPlaylist(normalizedCameraKey)) {
            return false;
        }

        const currentEventTime = typeof options.eventTime === "number" && Number.isFinite(options.eventTime)
            ? options.eventTime
            : getCurrentEventTime();
        const autoplay = typeof options.autoplay === "boolean" ? options.autoplay : !player.paused;
        const cameraChanged = normalizedCameraKey !== activeCameraKey;
        const layoutChanged = normalizedLayout !== activeLayout;
        if (!cameraChanged && !layoutChanged) {
            return false;
        }

        activeLayout = normalizedLayout;
        activeCameraKey = normalizedCameraKey;
        pendingEventTime = currentEventTime;

        if (cameraChanged) {
            playlist = allPlaylists[activeCameraKey];
            activeIndex = 0;
            playlistReady = false;
            syncTimelineUI();

            populatePlaylistDurations(playlist).then(() => {
                playlistReady = true;
                preloadTelemetryForPlaylist(playlist);
                pendingEventTime = currentEventTime;
                seekToEventTime(currentEventTime, { autoplay });
            });
            return true;
        }

        syncTimelineUI();
        if (!playlistReady) {
            return true;
        }
        seekToEventTime(currentEventTime, { autoplay });
        return true;
    }

    function applyPlaybackCameraMarker(marker, eventTime, options = {}) {
        if (!marker) {
            return false;
        }

        normalizeCameraMarker(marker);
        activePlaybackCameraMarkerId = marker.id;
        const autoplay = typeof options.autoplay === "boolean" ? options.autoplay : true;
        return applyViewSelection(marker.layout, marker.cameraKey, { eventTime, autoplay });
    }

    function maybeApplyPlaybackCameraMarker(eventTime, options = {}) {
        if (getPlaybackViewMarkers().length === 0) {
            lastPlaybackEventTime = eventTime;
            activePlaybackCameraMarkerId = null;
            return false;
        }

        if (player.paused) {
            syncPlaybackMarkerCheckpoint(eventTime);
            return false;
        }

        if (lastPlaybackEventTime === null || eventTime < lastPlaybackEventTime - 0.5) {
            syncPlaybackMarkerCheckpoint(eventTime);
            return false;
        }

        const crossedMarker = getLatestCrossedCameraMarker(lastPlaybackEventTime, eventTime);
        lastPlaybackEventTime = eventTime;
        if (!crossedMarker || crossedMarker.id === activePlaybackCameraMarkerId) {
            return false;
        }

        return applyPlaybackCameraMarker(crossedMarker, eventTime, options);
    }

    function maybeApplyCurrentPlaybackViewMarker(eventTime, options = {}) {
        const currentMarker = getLatestCameraMarkerAtOrBefore(eventTime);
        if (!currentMarker) {
            syncPlaybackMarkerCheckpoint(eventTime);
            return false;
        }

        if (currentMarker.id === activePlaybackCameraMarkerId && doesViewSelectionMatchCurrentView(currentMarker)) {
            syncPlaybackMarkerCheckpoint(eventTime);
            return false;
        }

        return applyPlaybackCameraMarker(currentMarker, eventTime, options);
    }

    function bindStartMarkerInteraction() {
        if (!startMarkerButton || !startMarkerPopover) {
            return;
        }

        let draggedDuringPointerSequence = false;
        let pointerStartX = 0;

        startMarkerButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (draggedDuringPointerSequence) {
                draggedDuringPointerSequence = false;
                return;
            }
            activeCameraMarkerId = null;
            startMarkerPopoverOpen = !startMarkerPopoverOpen;
            syncTimelineUI();
        });

        startMarkerButton.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
                return;
            }
            pointerStartX = event.clientX;
            draggedDuringPointerSequence = false;
            startMarkerButton.setPointerCapture(event.pointerId);
        });

        startMarkerButton.addEventListener("pointermove", (event) => {
            if (!startMarkerButton.hasPointerCapture(event.pointerId)) {
                return;
            }

            const deltaX = event.clientX - pointerStartX;
            if (!draggedDuringPointerSequence && Math.abs(deltaX) < 4) {
                return;
            }

            draggedDuringPointerSequence = true;
            startMarkerPopoverOpen = false;
            event.preventDefault();
            updateTrimMarkerFromPointer("start", event.clientX);
        });

        const finishDragging = (event) => {
            if (!startMarkerButton.hasPointerCapture(event.pointerId)) {
                return;
            }

            startMarkerButton.releasePointerCapture(event.pointerId);
            const deltaX = event.clientX - pointerStartX;
            if (Math.abs(deltaX) < 4) {
                return;
            }

            draggedDuringPointerSequence = true;
            startMarkerPopoverOpen = false;
            event.preventDefault();
            updateTrimMarkerFromPointer("start", event.clientX);
        };

        const cancelDragging = (event) => {
            if (!startMarkerButton.hasPointerCapture(event.pointerId)) {
                return;
            }

            startMarkerButton.releasePointerCapture(event.pointerId);
        };

        startMarkerButton.addEventListener("pointerup", finishDragging);
        startMarkerButton.addEventListener("pointercancel", cancelDragging);

        startMarkerPopover.addEventListener("click", (event) => {
            event.stopPropagation();
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            const controlButton = target.closest(".player-camera-overlay-button");
            if (!(controlButton instanceof HTMLButtonElement)) {
                return;
            }

            const nextLayout = controlButton.dataset.viewLayoutOption;
            if (nextLayout) {
                startMarkerViewSelection.layout = nextLayout;
                normalizeViewSelection(startMarkerViewSelection);
                syncTimelineUI();
                schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            startMarkerViewSelection.cameraKey = nextCameraKey;
            normalizeViewSelection(startMarkerViewSelection);
            syncTimelineUI();
            schedulePlayerEditsPersistence();
        });
    }

    function getVideoAspectRatio(videoElement) {
        if (!videoElement) {
            return null;
        }
        if (videoElement.videoWidth > 0 && videoElement.videoHeight > 0) {
            return videoElement.videoWidth / videoElement.videoHeight;
        }
        return null;
    }

    function getContainedVideoRect(containerRect, aspectRatio) {
        if (!containerRect || !(containerRect.width > 0) || !(containerRect.height > 0) || !(aspectRatio > 0)) {
            return null;
        }

        const containerAspectRatio = containerRect.width / containerRect.height;
        if (containerAspectRatio > aspectRatio) {
            const height = containerRect.height;
            const width = height * aspectRatio;
            const left = containerRect.left + ((containerRect.width - width) / 2);
            return {
                left,
                top: containerRect.top,
                right: left + width,
                bottom: containerRect.top + height,
            };
        }

        const width = containerRect.width;
        const height = width / aspectRatio;
        const top = containerRect.top + ((containerRect.height - height) / 2);
        return {
            left: containerRect.left,
            top,
            right: containerRect.left + width,
            bottom: top + height,
        };
    }

    function getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, side) {
        const breakpoints = new Set([0, frameHeight]);
        for (const rect of contentRects) {
            breakpoints.add(Math.max(0, Math.min(frameHeight, rect.top)));
            breakpoints.add(Math.max(0, Math.min(frameHeight, rect.bottom)));
        }

        let bestRect = { width: 0, height: 0 };
        let bestArea = 0;

        for (const top of Array.from(breakpoints).sort((left, right) => left - right)) {
            let availableWidth = frameWidth;
            for (const rect of contentRects) {
                if (rect.bottom <= top || rect.top >= frameHeight) {
                    continue;
                }
                if (side === "left") {
                    availableWidth = Math.min(availableWidth, rect.left);
                } else {
                    availableWidth = Math.min(availableWidth, frameWidth - rect.right);
                }
            }

            const height = frameHeight - top;
            const width = Math.max(0, availableWidth);
            const area = width * height;
            if (area > bestArea) {
                bestArea = area;
                bestRect = { width, height };
            }
        }

        return bestRect;
    }

    function applyStageSafeZone(node, rect) {
        if (!node || !rect || rect.width < 1 || rect.height < 1) {
            if (node) {
                node.hidden = true;
                node.style.width = "0px";
                node.style.height = "0px";
                node.style.setProperty("--player-safe-zone-width", "0px");
                node.style.setProperty("--player-safe-zone-height", "0px");
            }
            return;
        }

        node.hidden = false;
        node.style.width = `${rect.width}px`;
        node.style.height = `${rect.height}px`;
        node.style.setProperty("--player-safe-zone-width", `${rect.width}px`);
        node.style.setProperty("--player-safe-zone-height", `${rect.height}px`);
    }

    function updateStageSafeZones() {
        if (!viewFrame || !stageSafeZones.left || !stageSafeZones.right) {
            return;
        }

        const masterAspectRatio = getVideoAspectRatio(player);
        const leftAspectRatio = getVideoAspectRatio(secondaryPlayers.left) || masterAspectRatio;
        const rightAspectRatio = getVideoAspectRatio(secondaryPlayers.right) || masterAspectRatio;
        if (!(masterAspectRatio > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            return;
        }

        const frameWidth = viewFrame.clientWidth;
        const frameHeight = viewFrame.clientHeight;
        if (!(frameWidth > 0) || !(frameHeight > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            return;
        }

        const frameStyles = getComputedStyle(viewFrame);
        const leftPadding = Number.parseFloat(frameStyles.paddingLeft) || 0;
        const rightPadding = Number.parseFloat(frameStyles.paddingRight) || 0;
        const columnGap = Number.parseFloat(frameStyles.columnGap) || 0;
        const usableWidth = Math.max(0, frameWidth - leftPadding - rightPadding);
        if (!(usableWidth > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            return;
        }

        const contentRects = [];
        const pushContainedRect = (containerRect, aspectRatio) => {
            const contentRect = getContainedVideoRect(containerRect, aspectRatio);
            if (contentRect) {
                contentRects.push(contentRect);
            }
        };

        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: usableWidth,
            height: frameHeight,
        }, masterAspectRatio);

        const doubleShellWidth = Math.max(0, (usableWidth - columnGap) / 2);
        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: doubleShellWidth,
            height: frameHeight,
        }, leftAspectRatio);
        pushContainedRect({
            left: leftPadding + doubleShellWidth + columnGap,
            top: 0,
            width: doubleShellWidth,
            height: frameHeight,
        }, masterAspectRatio);

        const tripleMainHeight = frameHeight * (2 / 3);
        const tripleBottomHeight = frameHeight - tripleMainHeight;
        const tripleBottomShellWidth = Math.min(usableWidth / 2, tripleBottomHeight * (16 / 9));
        const tripleCenterX = leftPadding + (usableWidth / 2);

        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: usableWidth,
            height: tripleMainHeight,
        }, masterAspectRatio);
        pushContainedRect({
            left: tripleCenterX - tripleBottomShellWidth,
            top: tripleMainHeight,
            width: tripleBottomShellWidth,
            height: tripleBottomHeight,
        }, leftAspectRatio);
        pushContainedRect({
            left: tripleCenterX,
            top: tripleMainHeight,
            width: tripleBottomShellWidth,
            height: tripleBottomHeight,
        }, rightAspectRatio);

        const leftRect = getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, "left");
        const rightRect = getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, "right");
        applyStageSafeZone(stageSafeZones.left, leftRect);
        applyStageSafeZone(stageSafeZones.right, rightRect);
    }

    function scheduleStageSafeZoneUpdate() {
        if (stageSafeZoneUpdatePending) {
            return;
        }
        stageSafeZoneUpdatePending = true;
        window.requestAnimationFrame(() => {
            stageSafeZoneUpdatePending = false;
            updateStageSafeZones();
        });
    }

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

    function getClipStart(index) {
        return playlist.slice(0, index).reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function getTotalDuration() {
        return playlist.reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function getCurrentEventTime() {
        return pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
    }

    function getActualPlaybackEventTime() {
        return getClipStart(activeIndex) + player.currentTime;
    }

    function getMinimumTrimGap(totalDuration) {
        return totalDuration >= 60 ? 60 : Math.max(0, totalDuration);
    }

    function ensureTrimRange(totalDuration) {
        if (totalDuration <= 0) {
            return;
        }

        if (!trimInitialized) {
            trimStartTime = 0;
            trimEndTime = totalDuration;
            trimInitialized = true;
            trimEndPinnedToDuration = true;
            return;
        }

        if (trimEndPinnedToDuration) {
            trimEndTime = totalDuration;
        }

        const minimumGap = getMinimumTrimGap(totalDuration);
        trimStartTime = Math.min(Math.max(trimStartTime, 0), totalDuration);
        trimEndTime = Math.min(Math.max(trimEndTime, 0), totalDuration);

        if (trimEndTime - trimStartTime < minimumGap) {
            if (trimEndPinnedToDuration || trimEndTime >= totalDuration) {
                trimEndTime = totalDuration;
                trimStartTime = Math.max(0, trimEndTime - minimumGap);
            } else {
                trimEndTime = Math.min(totalDuration, trimStartTime + minimumGap);
            }
        }
    }

    function clampTrimStart(nextTime, totalDuration) {
        const minimumGap = getMinimumTrimGap(totalDuration);
        return Math.min(Math.max(nextTime, 0), Math.max(0, trimEndTime - minimumGap));
    }

    function clampTrimEnd(nextTime, totalDuration) {
        const minimumGap = getMinimumTrimGap(totalDuration);
        return Math.max(Math.min(nextTime, totalDuration), Math.min(totalDuration, trimStartTime + minimumGap));
    }

    function syncTrimUI(totalDuration) {
        if (!editTrack || !editTrackFill || !startMarkerButton || !endMarkerButton) {
            return;
        }

        if (totalDuration <= 0) {
            editTrack.hidden = true;
            return;
        }

        editTrack.hidden = false;
        const startRatio = totalDuration > 0 ? trimStartTime / totalDuration : 0;
        const endRatio = totalDuration > 0 ? trimEndTime / totalDuration : 1;
        editTrackFill.style.left = `${startRatio * 100}%`;
        editTrackFill.style.width = `${Math.max(0, (endRatio - startRatio) * 100)}%`;
        startMarkerButton.style.left = `${startRatio * 100}%`;
        endMarkerButton.style.left = `${endRatio * 100}%`;
        startMarkerButton.setAttribute("aria-label", `Start marker at ${formatClockTime(trimStartTime)}`);
        endMarkerButton.setAttribute("aria-label", `End marker at ${formatClockTime(trimEndTime)}`);
        syncStartMarkerPopoverUI(totalDuration);
    }

    function setTrimMarkerTime(markerType, nextTime) {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        ensureTrimRange(totalDuration);
        if (markerType === "start") {
            trimStartTime = clampTrimStart(nextTime, totalDuration);
        } else {
            trimEndTime = clampTrimEnd(nextTime, totalDuration);
            trimEndPinnedToDuration = Math.abs(trimEndTime - totalDuration) < 0.01;
        }
        syncTimelineUI();
        schedulePlayerEditsPersistence();
    }

    function getEditTrackTimeFromClientX(clientX) {
        if (!editTrack) {
            return 0;
        }

        const totalDuration = getTotalDuration();
        const rect = editTrack.getBoundingClientRect();
        if (rect.width <= 0 || totalDuration <= 0) {
            return 0;
        }

        const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
        return ratio * totalDuration;
    }

    function updateTrimMarkerFromPointer(markerType, clientX) {
        setTrimMarkerTime(markerType, getEditTrackTimeFromClientX(clientX));
    }

    function bindTrimMarkerDrag(markerButton, markerType) {
        if (!markerButton) {
            return;
        }

        markerButton.addEventListener("pointerdown", (event) => {
            activeTrimMarker = markerType;
            event.preventDefault();
            markerButton.setPointerCapture(event.pointerId);
            updateTrimMarkerFromPointer(markerType, event.clientX);
        });

        markerButton.addEventListener("pointermove", (event) => {
            if (activeTrimMarker !== markerType) {
                return;
            }
            event.preventDefault();
            updateTrimMarkerFromPointer(markerType, event.clientX);
        });

        const finishDragging = (event) => {
            if (activeTrimMarker !== markerType) {
                return;
            }
            event.preventDefault();
            updateTrimMarkerFromPointer(markerType, event.clientX);
            activeTrimMarker = null;
            if (markerButton.hasPointerCapture(event.pointerId)) {
                markerButton.releasePointerCapture(event.pointerId);
            }
        };

        const cancelDragging = (event) => {
            if (activeTrimMarker !== markerType) {
                return;
            }
            activeTrimMarker = null;
            if (markerButton.hasPointerCapture(event.pointerId)) {
                markerButton.releasePointerCapture(event.pointerId);
            }
        };

        markerButton.addEventListener("pointerup", finishDragging);
        markerButton.addEventListener("pointercancel", cancelDragging);
    }

    function formatSpeedText(speedKph) {
        if (speedKph === null) {
            return "";
        }
        const roundedSpeed = Math.round(speedKph);
        return `<span class="player-safe-zone-value-number">${roundedSpeed}</span><span class="player-safe-zone-value-unit">km/h</span>`;
    }

    function formatFsdPercentText(fsdOnPercent) {
        if (fsdOnPercent === null) {
            return "";
        }
        return `FSD ${Math.round(fsdOnPercent)}%`;
    }

    function findTelemetrySampleIndex(timeMs, telemetry) {
        const times = telemetry?.timeMs;
        if (!times || times.length === 0) {
            return -1;
        }

        let low = 0;
        let high = times.length - 1;
        while (low <= high) {
            const middle = Math.floor((low + high) / 2);
            const candidate = times[middle];
            if (candidate <= timeMs) {
                low = middle + 1;
                continue;
            }
            high = middle - 1;
        }

        if (high >= 0) {
            return high;
        }
        return 0;
    }

    function getSpeedKphAtEventTime(eventTime) {
        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample || (sample.presenceBits & SPEED_PRESENT_MASK) === 0) {
            return null;
        }

        return sample.speedCmps * 0.036;
    }

    function getTelemetrySampleAtEventTime(eventTime) {
        const target = pendingEventTime !== null ? findClipForEventTime(eventTime) : { index: activeIndex, offset: player.currentTime };
        const clip = playlist[target.index];
        const telemetry = clip?.telemetry;
        if (!clip || !telemetry || telemetry.sampleCount === 0) {
            return null;
        }

        const sampleIndex = findTelemetrySampleIndex(Math.max(0, target.offset) * 1000, telemetry);
        if (sampleIndex < 0) {
            return null;
        }

        return {
            presenceBits: telemetry.presenceBits[sampleIndex],
            autopilotState: telemetry.autopilotState[sampleIndex],
            speedCmps: telemetry.speedCmps[sampleIndex],
            steeringTenthsDeg: telemetry.steeringTenthsDeg[sampleIndex],
            headingCdeg: telemetry.headingCdeg[sampleIndex],
            flags: telemetry.flags[sampleIndex],
        };
    }

    function syncHeadingUI(eventTime) {
        if (!headingNode || !headingIndicatorNode || !headingLabelNode) {
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample || (sample.presenceBits & HEADING_PRESENT_MASK) === 0) {
            headingIndicatorNode.hidden = true;
            headingNode.hidden = true;
            headingLabelNode.hidden = true;
            headingLabelNode.textContent = "";
            headingNode.style.transform = "rotate(0deg)";
            return;
        }

        const headingDeg = sample.headingCdeg / 100;
        headingIndicatorNode.hidden = false;
        headingNode.hidden = false;
        headingLabelNode.hidden = false;
        headingLabelNode.textContent = getCompassDirectionLabel(headingDeg);
        headingNode.style.transform = `rotate(${headingDeg}deg)`;
    }

    function getCompassDirectionLabel(headingDeg) {
        const normalizedHeading = ((headingDeg % 360) + 360) % 360;
        if (normalizedHeading >= 45 && normalizedHeading < 135) {
            return "E";
        }
        if (normalizedHeading >= 135 && normalizedHeading < 225) {
            return "S";
        }
        if (normalizedHeading >= 225 && normalizedHeading < 315) {
            return "W";
        }
        return "N";
    }

    function syncAutopilotUI(eventTime) {
        if (!autopilotNode) {
            return;
        }

        if (!eventHasAutopilotActivity && !eventHasSteeringAngleData) {
            autopilotNode.hidden = true;
            autopilotNode.style.transform = "rotate(0deg)";
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample) {
            autopilotNode.hidden = true;
            autopilotNode.style.transform = "rotate(0deg)";
            return;
        }

        const isActive = Boolean(sample && (sample.presenceBits & AUTOPILOT_PRESENT_MASK) && sample.autopilotState !== AUTOPILOT_NONE_STATE);
        const steeringAngleDeg = (sample.presenceBits & STEERING_ANGLE_PRESENT_MASK)
            ? sample.steeringTenthsDeg / 10
            : 0;
        autopilotNode.hidden = false;
        autopilotNode.src = isActive ? autopilotNode.dataset.activeSrc : autopilotNode.dataset.inactiveSrc;
        autopilotNode.style.transform = `rotate(${steeringAngleDeg}deg)`;
    }

    function syncBlinkerUI(eventTime) {
        const sample = getTelemetrySampleAtEventTime(eventTime);
        const leftOn = Boolean(sample && (sample.presenceBits & BLINKER_LEFT_PRESENT_MASK) && (sample.flags & BLINKER_LEFT_FLAG_MASK));
        const rightOn = Boolean(sample && (sample.presenceBits & BLINKER_RIGHT_PRESENT_MASK) && (sample.flags & BLINKER_RIGHT_FLAG_MASK));

        if (blinkerLeftNode) {
            blinkerLeftNode.hidden = !leftOn;
        }
        if (blinkerRightNode) {
            blinkerRightNode.hidden = !rightOn;
        }
    }

    function syncBrakeUI(eventTime) {
        if (!brakeNode) {
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        const brakeOn = Boolean(sample && (sample.presenceBits & BRAKE_PRESENT_MASK) && (sample.flags & BRAKE_FLAG_MASK));
        brakeNode.hidden = !brakeOn;
    }

    function syncSpeedUI(eventTime) {
        if (!speedNode) {
            return;
        }
        const speedKph = getSpeedKphAtEventTime(eventTime);
        if (speedKph === null) {
            speedNode.hidden = true;
            speedNode.textContent = "";
            return;
        }
        speedNode.hidden = false;
        speedNode.innerHTML = formatSpeedText(speedKph);
    }

    function syncFsdPercentUI() {
        if (!fsdPercentNode) {
            return;
        }

        if (eventFsdOnPercent === null) {
            fsdPercentNode.hidden = true;
            fsdPercentNode.textContent = "";
            return;
        }

        fsdPercentNode.hidden = false;
        fsdPercentNode.textContent = formatFsdPercentText(eventFsdOnPercent);
    }

    function syncTimelineUI() {
        const eventTime = getCurrentEventTime();
        const totalDuration = getTotalDuration();
        const activeClip = playlist[activeIndex] || null;

        ensureTrimRange(totalDuration);

        if (stageSurface) {
            stageSurface.dataset.hasTelemetry = clipHasTelemetry(activeClip) ? "true" : "false";
        }

        if (currentTimeNode) {
            currentTimeNode.textContent = formatClockTime(eventTime);
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
        syncBlinkerUI(eventTime);
        syncHeadingUI(eventTime);
        syncAutopilotUI(eventTime);
        syncSpeedUI(eventTime);
        syncBrakeUI(eventTime);
        syncFsdPercentUI();
        syncTrimUI(totalDuration);
        syncCameraMarkerUI(totalDuration);
    }

    function findClipForEventTime(eventTime) {
        let accumulated = 0;
        for (let index = 0; index < playlist.length; index += 1) {
            const duration = playlist[index].duration || 0;
            if (eventTime <= accumulated + duration || index === playlist.length - 1) {
                return { index, offset: Math.max(0, eventTime - accumulated) };
            }
            accumulated += duration;
        }
        return { index: 0, offset: 0 };
    }

    function seekToEventTime(eventTime, options = {}) {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        const { autoplay = !player.paused } = options;
        const clampedTime = Math.min(Math.max(eventTime, 0), totalDuration);
        const target = findClipForEventTime(clampedTime);
        pendingEventTime = clampedTime;
        loadClip(target.index, { autoplay, targetTime: target.offset, secondaryShouldPlay: autoplay });
    }

    function findClipBySegmentKey(cameraKey, segmentKey, fallbackIndex) {
        const cameraPlaylist = allPlaylists[cameraKey];
        if (!Array.isArray(cameraPlaylist) || cameraPlaylist.length === 0) {
            return null;
        }

        const matchedClip = cameraPlaylist.find((clip) => clip.segmentKey === segmentKey);
        if (matchedClip) {
            return matchedClip;
        }

        if (fallbackIndex >= 0 && fallbackIndex < cameraPlaylist.length) {
            return cameraPlaylist[fallbackIndex];
        }

        return cameraPlaylist[0];
    }

    function syncSecondaryPlayers(offset, shouldPlay) {
        const secondaryCameraKeys = getSecondaryCameraKeyMap();
        if (!isCompositeView()) {
            for (const secondaryPlayer of Object.values(secondaryPlayers)) {
                if (secondaryPlayer) {
                    secondaryPlayer.pause();
                    if (secondaryPlayer.parentElement) {
                        secondaryPlayer.parentElement.hidden = true;
                    }
                }
            }
            return;
        }

        const masterClip = playlist[activeIndex];
        if (!masterClip) {
            return;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const secondaryShell = secondaryPlayer.parentElement;
            const cameraKey = secondaryCameraKeys[slotKey];
            if (!cameraKey || !hasCameraPlaylist(cameraKey)) {
                secondaryPlayer.pause();
                if (secondaryShell) {
                    secondaryShell.hidden = true;
                }
                continue;
            }

            if (secondaryShell) {
                secondaryShell.hidden = false;
            }

            const targetClip = findClipBySegmentKey(cameraKey, masterClip.segmentKey, activeIndex);
            if (!targetClip) {
                secondaryPlayer.pause();
                if (secondaryShell) {
                    secondaryShell.hidden = true;
                }
                continue;
            }

            secondaryPlayer.dataset.pendingTime = String(offset);
            secondaryPlayer.dataset.shouldPlay = shouldPlay ? "true" : "false";
            if (!secondaryPlayer.currentSrc || !secondaryPlayer.currentSrc.endsWith(targetClip.url)) {
                secondaryPlayer.src = targetClip.url;
                secondaryPlayer.load();
                if (shouldPlay) {
                    const playPromise = secondaryPlayer.play();
                    if (playPromise && typeof playPromise.catch === "function") {
                        playPromise.catch(() => {});
                    }
                }
                continue;
            }

            if (Math.abs(secondaryPlayer.currentTime - offset) > 0.35) {
                secondaryPlayer.currentTime = offset;
            }
            if (shouldPlay) {
                const playPromise = secondaryPlayer.play();
                if (playPromise && typeof playPromise.catch === "function") {
                    playPromise.catch(() => {});
                }
                continue;
            }
            secondaryPlayer.pause();
        }
    }

    function synchronizeSecondaryDrift() {
        if (!isCompositeView()) {
            return;
        }

        for (const secondaryPlayer of Object.values(secondaryPlayers)) {
            if (!secondaryPlayer || secondaryPlayer.readyState < 2) {
                continue;
            }

            if (Math.abs(secondaryPlayer.currentTime - player.currentTime) > 0.35) {
                secondaryPlayer.currentTime = player.currentTime;
            }
        }
    }

    function clearSecondaryPlayers(resetSource = false) {
        for (const secondaryPlayer of Object.values(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            secondaryPlayer.pause();
            if (secondaryPlayer.parentElement) {
                secondaryPlayer.parentElement.hidden = false;
            }
            delete secondaryPlayer.dataset.pendingTime;
            delete secondaryPlayer.dataset.shouldPlay;
            if (!resetSource) {
                continue;
            }
            secondaryPlayer.removeAttribute("src");
            secondaryPlayer.load();
        }
    }

    function getViewTargets(index) {
        const masterClip = playlist[index];
        if (!masterClip) {
            return [];
        }

        const targets = [{ element: player, clip: masterClip }];
        const secondaryCameraKeys = getSecondaryCameraKeyMap();
        if (!isCompositeView()) {
            return targets;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const cameraKey = secondaryCameraKeys[slotKey];
            if (!cameraKey || !hasCameraPlaylist(cameraKey)) {
                continue;
            }

            const clip = findClipBySegmentKey(cameraKey, masterClip.segmentKey, index);
            if (clip) {
                targets.push({ element: secondaryPlayer, clip });
            }
        }
        return targets;
    }

    function applyPendingPlayback(videoElement) {
        const loadToken = Number.parseInt(videoElement.dataset.loadToken || "0", 10);
        if (loadToken !== activeLoadToken) {
            return;
        }

        const pendingTime = Number.parseFloat(videoElement.dataset.pendingTime || "0");
        if (!Number.isNaN(pendingTime) && Math.abs(videoElement.currentTime - pendingTime) > 0.1) {
            videoElement.currentTime = pendingTime;
        }

        if (videoElement === player) {
            pendingEventTime = null;
            syncTimelineUI();
        }

        if (videoElement.dataset.shouldPlay === "true") {
            const playPromise = videoElement.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
            return;
        }
        videoElement.pause();
    }

    function ensureVideoReady(videoElement, url) {
        if (!videoElement.currentSrc || !videoElement.currentSrc.endsWith(url)) {
            videoElement.src = url;
        }
        videoElement.load();

        if (videoElement.readyState >= 1) {
            applyPendingPlayback(videoElement);
        }
    }

    function loadViewAtIndex(index, targetTime, shouldPlay) {
        const targets = getViewTargets(index);
        if (targets.length === 0) {
            return;
        }

        const loadToken = ++activeLoadToken;
        activeIndex = index;
        syncTimelineUI();

        for (const { element, clip } of targets) {
            element.dataset.loadToken = String(loadToken);
            element.dataset.pendingTime = String(targetTime);
            element.dataset.shouldPlay = shouldPlay ? "true" : "false";
            ensureVideoReady(element, clip.url);
        }

        syncSecondaryPlayers(targetTime, shouldPlay);

        preloadNextSegment(index + 1);
    }

    function preloadNextSegment(nextIndex) {
        if (nextIndex < 0 || nextIndex >= playlist.length) {
            return;
        }

        const targets = getViewTargets(nextIndex);
        for (const { element, clip } of targets) {
            const preloaderKey = element === player ? "master" : element.dataset.secondarySlot;
            const preloader = preloaderKey ? preloadPlayers[preloaderKey] : null;
            if (!preloader) {
                continue;
            }
            if (!preloader.currentSrc || !preloader.currentSrc.endsWith(clip.url)) {
                preloader.src = clip.url;
            }
            preloader.load();
        }
    }

    function loadClip(index, options = {}) {
        const { autoplay = false, targetTime = 0, secondaryShouldPlay = autoplay } = options;
        const clip = playlist[index];
        if (!clip) {
            return;
        }

        ensureTelemetryLoaded(clip).then(() => {
            syncTimelineUI();
        });
        loadViewAtIndex(index, targetTime, secondaryShouldPlay);
    }

    player.addEventListener("ended", () => {
        if (activeIndex >= playlist.length - 1) {
            syncTimelineUI();
            return;
        }
        loadClip(activeIndex + 1, { autoplay: true, targetTime: 0, secondaryShouldPlay: true });
    });

    player.addEventListener("loadedmetadata", () => {
        applyPendingPlayback(player);
        syncPlaybackMarkerCheckpoint(getCurrentEventTime());
        syncTimelineUI();
        scheduleStageSafeZoneUpdate();
    });

    player.addEventListener("timeupdate", () => {
        const eventTime = getCurrentEventTime();
        if (maybeApplyPlaybackCameraMarker(eventTime)) {
            return;
        }
        synchronizeSecondaryDrift();
        lastPlaybackEventTime = eventTime;
        syncTimelineUI();
    });
    player.addEventListener("play", () => {
        const eventTime = getCurrentEventTime();
        if (maybeApplyCurrentPlaybackViewMarker(eventTime)) {
            return;
        }
        syncPlaybackMarkerCheckpoint(getCurrentEventTime());
        syncSecondaryPlayers(player.currentTime, true);
        syncTimelineUI();
    });
    player.addEventListener("pause", () => {
        syncPlaybackMarkerCheckpoint(getCurrentEventTime());
        syncSecondaryPlayers(player.currentTime, false);
        syncTimelineUI();
    });

    for (const secondaryPlayer of Object.values(secondaryPlayers)) {
        if (!secondaryPlayer) {
            continue;
        }

        secondaryPlayer.addEventListener("loadedmetadata", () => {
            applyPendingPlayback(secondaryPlayer);
            scheduleStageSafeZoneUpdate();
        });
    }

    if (typeof ResizeObserver === "function" && viewFrame) {
        const stageResizeObserver = new ResizeObserver(() => {
            scheduleStageSafeZoneUpdate();
        });
        stageResizeObserver.observe(viewFrame);
    } else {
        window.addEventListener("resize", scheduleStageSafeZoneUpdate);
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

    if (toggleButton) {
        toggleButton.addEventListener("click", togglePlayback);
    }

    if (setStartButton) {
        setStartButton.addEventListener("click", () => {
            setTrimMarkerTime("start", getCurrentEventTime());
        });
    }

    if (setEndButton) {
        setEndButton.addEventListener("click", () => {
            setTrimMarkerTime("end", getCurrentEventTime());
        });
    }

    if (addCameraMarkerButton) {
        addCameraMarkerButton.addEventListener("click", () => {
            addCameraMarker(getCurrentEventTime());
        });
    }

    bindStartMarkerInteraction();
    bindTrimMarkerDrag(endMarkerButton, "end");

    document.addEventListener("pointerdown", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        if (target.closest(".player-edit-camera-marker-shell")
            || target.closest(".player-edit-start-marker-popover")
            || target.closest("[data-player-start-marker]")
            || target.closest("[data-player-add-camera-marker]")) {
            return;
        }
        const shouldSync = activeCameraMarkerId !== null || startMarkerPopoverOpen;
        if (activeCameraMarkerId !== null) {
            activeCameraMarkerId = null;
        }
        if (!startMarkerPopoverOpen) {
            if (!shouldSync) {
                return;
            }
            syncTimelineUI();
            return;
        }
        startMarkerPopoverOpen = false;
        syncTimelineUI();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }
        if (activeCameraMarkerId === null && !startMarkerPopoverOpen) {
            return;
        }
        activeCameraMarkerId = null;
        startMarkerPopoverOpen = false;
        syncTimelineUI();
    });

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

    function populatePlaylistDurations(playlistToPopulate) {
        return populateClipDurations(playlistToPopulate, player, durationCache, syncTimelineUI).catch(() => {
            playlistToPopulate.forEach((clip) => {
                clip.duration = Number.isFinite(clip.duration) ? clip.duration : 0;
            });
            return playlistToPopulate;
        });
    }

    function preloadTelemetryForPlaylist(playlistToPopulate) {
        playlistToPopulate.forEach((clip) => {
            ensureTelemetryLoaded(clip).then(() => {
                if (playlistToPopulate === playlist) {
                    syncTimelineUI();
                }
            });
        });
    }

    function ensureTelemetryLoaded(clip) {
        if (!clip?.telemetryUrl || !clipHasTelemetry(clip)) {
            if (clip) {
                clip.telemetry = null;
                clip.telemetryLoaded = true;
            }
            return Promise.resolve(null);
        }
        if (clip.telemetryLoaded) {
            return Promise.resolve(clip.telemetry);
        }
        if (clip.telemetryPromise) {
            return clip.telemetryPromise;
        }

        const cachedPromise = telemetryCache.get(clip.telemetryUrl);
        if (cachedPromise) {
            clip.telemetryPromise = cachedPromise.then((telemetry) => {
                clip.telemetry = telemetry;
                clip.telemetryLoaded = true;
                return telemetry;
            });
            return clip.telemetryPromise;
        }

        const telemetryPromise = fetch(clip.telemetryUrl)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load telemetry: ${response.status}`);
                }
                return response.arrayBuffer();
            })
            .then(decodeTelemetryBuffer)
            .catch(() => null);

        telemetryCache.set(clip.telemetryUrl, telemetryPromise);
        clip.telemetryPromise = telemetryPromise.then((telemetry) => {
            clip.telemetry = telemetry;
            clip.telemetryLoaded = true;
            return telemetry;
        });
        return clip.telemetryPromise;
    }

    function switchCamera(nextCameraKey) {
        applyViewSelection(activeLayout, nextCameraKey);
    }

    function switchLayout(nextLayout) {
        applyViewSelection(nextLayout, activeCameraKey);
    }

    for (const button of layoutButtons) {
        button.addEventListener("click", () => {
            const nextLayout = button.dataset.layoutOption;
            if (!nextLayout) {
                return;
            }
            switchLayout(nextLayout);
        });
    }

    for (const button of cameraButtons) {
        button.addEventListener("click", () => {
            const nextCameraKey = button.dataset.cameraTarget;
            if (!nextCameraKey) {
                return;
            }
            switchCamera(nextCameraKey);
        });
    }

    populatePlaylistDurations(playlist).then(() => {
        if (!savedPlayerEditsHydrated) {
            hydrateSavedPlayerEdits(rawSavedEdits);
            persistedPlayerEditsSignature = getPlayerEditsSignature(buildPlayerEditsPayload());
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
}

