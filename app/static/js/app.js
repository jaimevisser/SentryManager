function initPage() {
    document.documentElement.dataset.js = "ready";
    initIndexSelection();
    initViewerDelete();
    initEventPlayer();
}

const INDEX_SELECTION_LONG_PRESS_MS = 450;
const INDEX_SELECTION_MOVE_TOLERANCE_PX = 12;

function getDeletePrompt(selectionCount) {
    if (selectionCount === 1) {
        return {
            title: "Delete selected clip?",
            message: "This permanently deletes the selected clip from disk.",
            actionLabel: "Delete clip",
        };
    }

    return {
        title: `Delete ${selectionCount} selected clips?`,
        message: `This permanently deletes ${selectionCount} selected clips from disk.`,
        actionLabel: "Delete clips",
    };
}

function createDeleteModalController() {
    const deleteModal = document.querySelector("[data-index-delete-modal]");
    const deleteModalPanel = deleteModal?.querySelector(".selection-delete-modal-panel") || null;
    const deleteModalTitle = deleteModal?.querySelector("h2") || null;
    const deleteModalMessage = document.querySelector("[data-index-delete-message]");
    const deleteModalCancelButton = document.querySelector("[data-index-delete-cancel]");
    const deleteModalConfirmButton = document.querySelector("[data-index-delete-confirm]");

    function isOpen() {
        return Boolean(deleteModal?.open);
    }

    function show(selectionCount) {
        const prompt = getDeletePrompt(selectionCount);

        if (!deleteModal || typeof deleteModal.showModal !== "function") {
            return Promise.resolve(window.confirm(prompt.title));
        }

        if (deleteModalTitle) {
            deleteModalTitle.textContent = prompt.title;
        }
        if (deleteModalMessage) {
            deleteModalMessage.textContent = prompt.message;
        }
        if (deleteModalConfirmButton) {
            deleteModalConfirmButton.textContent = prompt.actionLabel;
        }

        return new Promise((resolve) => {
            const handleClose = () => {
                resolve(deleteModal.returnValue === "confirm");
            };

            deleteModal.addEventListener("close", handleClose, { once: true });
            deleteModal.showModal();
            deleteModalCancelButton?.focus();
        });
    }

    deleteModal?.addEventListener("click", (event) => {
        if (!deleteModalPanel) {
            return;
        }

        const panelRect = deleteModalPanel.getBoundingClientRect();
        const clickedInsidePanel = (
            event.clientX >= panelRect.left
            && event.clientX <= panelRect.right
            && event.clientY >= panelRect.top
            && event.clientY <= panelRect.bottom
        );
        if (!clickedInsidePanel) {
            deleteModal.close("cancel");
        }
    });

    return { isOpen, show };
}

function initIndexSelection() {
    const cards = Array.from(document.querySelectorAll("[data-index-card]"));
    const deleteButton = document.querySelector("[data-index-delete-button]");
    if (cards.length === 0 || !deleteButton) {
        return;
    }

    const deleteModal = createDeleteModalController();
    const selectedPaths = new Set();
    const body = document.body;
    let selectionMode = false;
    let deleteInFlight = false;
    let pendingLongPressTimer = 0;
    let pendingPointerId = null;
    let pendingPointerX = 0;
    let pendingPointerY = 0;
    let suppressNextClick = false;

    function syncSelectionUi() {
        for (const card of cards) {
            const eventPath = card.dataset.eventPath || "";
            card.classList.toggle("is-selected", selectedPaths.has(eventPath));
        }

        const hasSelection = selectedPaths.size > 0;
        const selectionLabel = hasSelection
            ? `Delete ${selectedPaths.size} selected ${selectedPaths.size === 1 ? "clip" : "clips"}`
            : "Delete selected clips";

        deleteButton.hidden = !hasSelection;
        deleteButton.disabled = !hasSelection || deleteInFlight;
        deleteButton.setAttribute("aria-label", selectionLabel);
        deleteButton.title = selectionLabel;

        if (selectionMode && !hasSelection) {
            selectionMode = false;
            delete body.dataset.selectionMode;
        }
    }

    function exitSelectionMode() {
        selectionMode = false;
        selectedPaths.clear();
        delete body.dataset.selectionMode;
        syncSelectionUi();
    }

    function toggleCardSelection(card) {
        const eventPath = card.dataset.eventPath;
        if (!eventPath) {
            return;
        }

        if (selectedPaths.has(eventPath)) {
            selectedPaths.delete(eventPath);
        } else {
            selectedPaths.add(eventPath);
        }

        syncSelectionUi();
    }

    function enterSelectionMode(card) {
        const eventPath = card.dataset.eventPath;
        if (!eventPath) {
            return;
        }

        selectionMode = true;
        body.dataset.selectionMode = "true";
        selectedPaths.clear();
        selectedPaths.add(eventPath);
        syncSelectionUi();
    }

    function clearPendingLongPress() {
        if (pendingLongPressTimer) {
            window.clearTimeout(pendingLongPressTimer);
        }

        pendingLongPressTimer = 0;
        pendingPointerId = null;
    }

    function startPendingLongPress(card, event) {
        clearPendingLongPress();
        pendingPointerId = event.pointerId;
        pendingPointerX = event.clientX;
        pendingPointerY = event.clientY;
        pendingLongPressTimer = window.setTimeout(() => {
            suppressNextClick = true;
            clearPendingLongPress();

            if (selectionMode) {
                exitSelectionMode();
                return;
            }

            enterSelectionMode(card);
        }, INDEX_SELECTION_LONG_PRESS_MS);
    }

    document.addEventListener("keydown", (event) => {
        if (deleteModal.isOpen()) {
            return;
        }
        if (event.key !== "Escape" || !selectionMode || deleteInFlight) {
            return;
        }
        exitSelectionMode();
    });

    for (const card of cards) {
        const link = card.querySelector("[data-photo-link]");
        if (!link) {
            continue;
        }

        link.addEventListener("pointerdown", (event) => {
            if (deleteInFlight || deleteModal.isOpen()) {
                return;
            }
            if (event.pointerType === "mouse" && event.button !== 0) {
                return;
            }

            startPendingLongPress(card, event);
        });

        link.addEventListener("pointermove", (event) => {
            if (event.pointerId !== pendingPointerId) {
                return;
            }

            const moveDistance = Math.hypot(event.clientX - pendingPointerX, event.clientY - pendingPointerY);
            if (moveDistance > INDEX_SELECTION_MOVE_TOLERANCE_PX) {
                clearPendingLongPress();
            }
        });

        link.addEventListener("pointerup", clearPendingLongPress);
        link.addEventListener("pointercancel", clearPendingLongPress);
        link.addEventListener("pointerleave", clearPendingLongPress);

        link.addEventListener("contextmenu", (event) => {
            if (!selectionMode && !suppressNextClick) {
                return;
            }
            event.preventDefault();
        });

        link.addEventListener("click", (event) => {
            if (suppressNextClick) {
                suppressNextClick = false;
                event.preventDefault();
                event.stopPropagation();
                return;
            }

            if (!selectionMode || deleteInFlight || deleteModal.isOpen()) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            toggleCardSelection(card);
        });
    }

    deleteButton.addEventListener("click", async () => {
        if (deleteInFlight || selectedPaths.size === 0) {
            return;
        }

        const selectionCount = selectedPaths.size;
        const confirmed = await deleteModal.show(selectionCount);
        if (!confirmed) {
            return;
        }

        deleteInFlight = true;
        syncSelectionUi();

        try {
            const response = await fetch(deleteButton.dataset.deleteUrl || "/events/delete", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    eventPaths: Array.from(selectedPaths),
                }),
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                const message = typeof payload?.error === "string" ? payload.error : "Delete failed.";
                throw new Error(message);
            }
            window.location.reload();
        } catch (error) {
            deleteInFlight = false;
            syncSelectionUi();
            window.alert(error instanceof Error ? error.message : "Delete failed.");
        }
    });
}

function initViewerDelete() {
    const deleteButton = document.querySelector("[data-viewer-delete-button]");
    if (!deleteButton) {
        return;
    }

    const deleteModal = createDeleteModalController();
    let deleteInFlight = false;

    deleteButton.addEventListener("click", async () => {
        const eventPath = deleteButton.dataset.eventPath;
        if (deleteInFlight || !eventPath) {
            return;
        }

        const confirmed = await deleteModal.show(1);
        if (!confirmed) {
            return;
        }

        deleteInFlight = true;
        deleteButton.disabled = true;

        try {
            const response = await fetch(deleteButton.dataset.deleteUrl || "/events/delete", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    eventPaths: [eventPath],
                }),
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                const message = typeof payload?.error === "string" ? payload.error : "Delete failed.";
                throw new Error(message);
            }
            window.location.assign(deleteButton.dataset.deleteRedirectUrl || "/");
        } catch (error) {
            deleteInFlight = false;
            deleteButton.disabled = false;
            window.alert(error instanceof Error ? error.message : "Delete failed.");
        }
    });
}

function initEventPlayer() {
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
    const autopilotNode = document.querySelector("[data-player-autopilot]");
    const brakeNode = document.querySelector("[data-player-brake]");
    const blinkerRightNode = document.querySelector("[data-player-blinker-right]");
    const fsdPercentNode = document.querySelector("[data-player-fsd-percent]");
    const scrubber = document.querySelector("[data-player-scrub]");
    const eventMarker = document.querySelector("[data-player-event-marker]");
    const toggleButton = document.querySelector("[data-player-toggle]");
    const toggleIcon = document.querySelector("[data-player-toggle-icon]");
    const layoutButtons = Array.from(document.querySelectorAll("[data-layout-option]"));
    const cameraButtons = Array.from(document.querySelectorAll("[data-camera-target]"));
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

    function getSecondaryCameraKeyMap() {
        if (activeLayout === "single") {
            return { left: null, right: null };
        }
        if (activeLayout === "double") {
            return { left: getCameraOffsetKey(activeCameraKey, -1), right: null };
        }
        return {
            left: getCameraOffsetKey(activeCameraKey, -1),
            right: getCameraOffsetKey(activeCameraKey, 1),
        };
    }

    function getVisibleCameraKeys() {
        const visibleCameraKeys = new Set([activeCameraKey]);
        const secondaryCameraKeys = getSecondaryCameraKeyMap();
        for (const cameraKey of Object.values(secondaryCameraKeys)) {
            if (cameraKey && hasCameraPlaylist(cameraKey)) {
                visibleCameraKeys.add(cameraKey);
            }
        }
        return visibleCameraKeys;
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

    function formatSpeedText(speedKph) {
        if (speedKph === null) {
            return "";
        }
        const roundedSpeed = Math.round(speedKph);
        return `<span class="player-status-value-number">${roundedSpeed}</span><span class="player-status-value-unit">km/h</span>`;
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
            flags: telemetry.flags[sampleIndex],
        };
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
            speedNode.textContent = "";
            return;
        }
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
        const eventTime = pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
        const totalDuration = getTotalDuration();
        const activeClip = playlist[activeIndex] || null;

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
        syncAutopilotUI(eventTime);
        syncSpeedUI(eventTime);
        syncBrakeUI(eventTime);
        syncFsdPercentUI();
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
        syncTimelineUI();
        scheduleStageSafeZoneUpdate();
    });

    player.addEventListener("timeupdate", () => {
        synchronizeSecondaryDrift();
        syncTimelineUI();
    });
    player.addEventListener("play", () => {
        syncSecondaryPlayers(player.currentTime, true);
        syncTimelineUI();
    });
    player.addEventListener("pause", () => {
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

    if (toggleButton) {
        toggleButton.addEventListener("click", () => {
            if (player.paused) {
                const playPromise = player.play();
                if (playPromise && typeof playPromise.catch === "function") {
                    playPromise.catch(() => {});
                }
                return;
            }
            player.pause();
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
        if (!hasCameraPlaylist(nextCameraKey) || nextCameraKey === activeCameraKey) {
            return;
        }

        const currentEventTime = pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
        const wantsPlayback = !player.paused;
        activeCameraKey = nextCameraKey;
        playlist = allPlaylists[activeCameraKey];
        activeIndex = 0;
        pendingEventTime = currentEventTime;
        playlistReady = false;
        syncTimelineUI();

        populatePlaylistDurations(playlist).then(() => {
            playlistReady = true;
            preloadTelemetryForPlaylist(playlist);
            pendingEventTime = currentEventTime;
            seekToEventTime(currentEventTime, { autoplay: wantsPlayback });
        });
    }

    function switchLayout(nextLayout) {
        if (!["single", "double", "triple"].includes(nextLayout) || nextLayout === activeLayout) {
            return;
        }

        const currentEventTime = pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
        const wantsPlayback = !player.paused;
        activeLayout = nextLayout;
        pendingEventTime = currentEventTime;
        syncTimelineUI();
        if (!playlistReady) {
            return;
        }
        seekToEventTime(currentEventTime, { autoplay: wantsPlayback });
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

const TELEMETRY_MAGIC = "SEI1";
const TELEMETRY_FORMAT_VERSION = 1;
const TELEMETRY_HEADER_STRUCT_SIZE = 20;
const CAMERA_LAYOUT_SEQUENCE = ["front", "right_pillar", "right_repeater", "back", "left_repeater", "left_pillar"];
const SPEED_PRESENT_MASK = 1 << 3;
const STEERING_ANGLE_PRESENT_MASK = 1 << 5;
const BLINKER_LEFT_PRESENT_MASK = 1 << 6;
const BLINKER_RIGHT_PRESENT_MASK = 1 << 7;
const BRAKE_PRESENT_MASK = 1 << 8;
const AUTOPILOT_PRESENT_MASK = 1 << 9;
const AUTOPILOT_NONE_STATE = 0;
const BLINKER_LEFT_FLAG_MASK = 0x01;
const BLINKER_RIGHT_FLAG_MASK = 0x02;
const BRAKE_FLAG_MASK = 0x04;
const TELEMETRY_COLUMNS = [
    { key: "timeMs", ctor: Uint32Array },
    { key: "presenceBits", ctor: Uint16Array },
    { key: "messageVersion", ctor: Uint16Array },
    { key: "frameSeqNo", ctor: BigUint64Array },
    { key: "gearState", ctor: Uint8Array },
    { key: "autopilotState", ctor: Uint8Array },
    { key: "flags", ctor: Uint8Array },
    { key: "speedCmps", ctor: Uint16Array },
    { key: "acceleratorCenti", ctor: Uint16Array },
    { key: "steeringTenthsDeg", ctor: Int16Array },
    { key: "headingCdeg", ctor: Uint16Array },
    { key: "latitudeE7", ctor: Int32Array },
    { key: "longitudeE7", ctor: Int32Array },
    { key: "accelXMmps2", ctor: Int16Array },
    { key: "accelYMmps2", ctor: Int16Array },
    { key: "accelZMmps2", ctor: Int16Array },
];

function decodeTelemetryBuffer(arrayBuffer) {
    const view = new DataView(arrayBuffer);
    const magic = String.fromCharCode(
        view.getUint8(0),
        view.getUint8(1),
        view.getUint8(2),
        view.getUint8(3)
    );
    const formatVersion = view.getUint16(4, true);
    const headerSize = view.getUint16(6, true);
    const sampleCount = view.getUint32(8, true);

    if (magic !== TELEMETRY_MAGIC || formatVersion !== TELEMETRY_FORMAT_VERSION) {
        throw new Error("Unsupported telemetry sidecar format");
    }

    const telemetry = { sampleCount };
    for (let index = 0; index < TELEMETRY_COLUMNS.length; index += 1) {
        const { key, ctor } = TELEMETRY_COLUMNS[index];
        const offset = view.getUint32(TELEMETRY_HEADER_STRUCT_SIZE + (index * 4), true);
        if (sampleCount === 0 || offset === 0) {
            telemetry[key] = new ctor(0);
            continue;
        }
        if (offset < headerSize || offset >= arrayBuffer.byteLength) {
            throw new Error(`Invalid telemetry offset for ${key}`);
        }
        telemetry[key] = new ctor(arrayBuffer, offset, sampleCount);
    }

    return telemetry;
}

async function populateClipDurations(playlist, player, durationCache, onDurationUpdate) {
    if (playlist.length === 0) {
        return playlist;
    }

    const activeUrl = playlist[0].url;
    const standardDuration = activeUrl ? await getStandardDuration(player, activeUrl, durationCache) : 0;

    playlist.forEach((clip) => {
        clip.duration = standardDuration;
    });

    if (playlist.length > 1) {
        const lastIndex = playlist.length - 1;
        loadClipDuration(playlist[lastIndex].url, durationCache).then((lastDuration) => {
            playlist[lastIndex].duration = lastDuration || standardDuration;
            if (typeof onDurationUpdate === "function") {
                onDurationUpdate();
            }
        });
    }

    return playlist;
}

async function getStandardDuration(player, expectedUrl, durationCache) {
    const cached = durationCache.get(expectedUrl);
    if (cached !== undefined) {
        return cached;
    }

    const cachedDuration = Array.from(durationCache.values()).find((duration) => duration > 0);
    if (cachedDuration !== undefined) {
        durationCache.set(expectedUrl, cachedDuration);
        return cachedDuration;
    }

    if (Number.isFinite(player.duration) && player.duration > 0) {
        durationCache.set(expectedUrl, player.duration);
        return player.duration;
    }

    return getPlayerMetadataDuration(player, expectedUrl, durationCache);
}

function getPlayerMetadataDuration(player, expectedUrl, durationCache) {
    const cached = durationCache.get(expectedUrl);
    if (cached !== undefined) {
        return Promise.resolve(cached);
    }

    return new Promise((resolve) => {
        const finish = (duration) => {
            cleanup();
            const safeDuration = Number.isFinite(duration) ? duration : 0;
            durationCache.set(expectedUrl, safeDuration);
            resolve(safeDuration);
        };

        const onLoadedMetadata = () => {
            if (!player.currentSrc || !player.currentSrc.includes(expectedUrl)) {
                return;
            }
            finish(player.duration);
        };

        const onError = () => finish(0);
        const timeoutId = window.setTimeout(() => finish(player.duration), 4000);

        const cleanup = () => {
            window.clearTimeout(timeoutId);
            player.removeEventListener("loadedmetadata", onLoadedMetadata);
            player.removeEventListener("error", onError);
        };

        if (Number.isFinite(player.duration) && player.duration > 0) {
            finish(player.duration);
            return;
        }

        player.addEventListener("loadedmetadata", onLoadedMetadata);
        player.addEventListener("error", onError);
    });
}

function loadClipDuration(url, durationCache) {
    const cached = durationCache.get(url);
    if (cached !== undefined) {
        return Promise.resolve(cached);
    }

    return new Promise((resolve) => {
        const probe = document.createElement("video");
        probe.preload = "metadata";
        probe.src = url;
        const timeoutId = window.setTimeout(() => {
            cleanup();
            durationCache.set(url, 0);
            resolve(0);
        }, 4000);

        const cleanup = () => {
            window.clearTimeout(timeoutId);
            probe.removeAttribute("src");
            probe.load();
        };

        probe.addEventListener(
            "loadedmetadata",
            () => {
                const duration = Number.isFinite(probe.duration) ? probe.duration : 0;
                cleanup();
                durationCache.set(url, duration);
                resolve(duration);
            },
            { once: true }
        );

        probe.addEventListener(
            "error",
            () => {
                cleanup();
                durationCache.set(url, 0);
                resolve(0);
            },
            { once: true }
        );
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPage, { once: true });
} else {
    initPage();
}