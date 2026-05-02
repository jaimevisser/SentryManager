export function createEventPlayerEditingController({
    documentObject,
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
    getActiveLayout,
    getActiveCameraKey,
    hasCameraPlaylist,
    normalizeViewSelection,
    applyViewSelection,
    normalizePersistedTime,
    formatClockTime,
    onStateChanged,
    schedulePlayerEditsPersistence,
}) {
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

    const cameraMarkerNodes = new Map();
    const startMarkerViewSelection = {
        layout: getActiveLayout(),
        cameraKey: getActiveCameraKey(),
    };
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

    const startMarkerPopover = editTrack && startMarkerButton
        ? documentObject.createElement("div")
        : null;
    const startMarkerPopoverButtons = [];

    if (startMarkerPopover && editTrack) {
        startMarkerPopover.className = "player-edit-camera-popover player-edit-start-marker-popover";
        startMarkerPopover.hidden = true;
        startMarkerPopoverButtons.push(...createViewSelectionControls(startMarkerPopover));
        editTrack.append(startMarkerPopover);
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
            const controlButton = documentObject.createElement("button");
            controlButton.type = "button";
            controlButton.className = "player-camera-overlay-button";
            controlButton.setAttribute("aria-label", blueprint.ariaLabel);
            if (blueprint.type === "layout") {
                controlButton.dataset.viewLayoutOption = blueprint.value;
            } else {
                controlButton.dataset.viewCameraTarget = blueprint.value;
            }

            const icon = documentObject.createElement("img");
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

    function buildPlayerEditsPayload(exportFormat) {
        normalizeViewSelection(startMarkerViewSelection);
        return {
            trimStartTime: normalizePersistedTime(trimStartTime),
            trimEndTime: normalizePersistedTime(trimEndTime),
            exportFormat,
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
                cameraKey: typeof rawMarker.cameraKey === "string" ? rawMarker.cameraKey : getActiveCameraKey(),
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
        onStateChanged();
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
        onStateChanged();
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
        if (selection.layout !== getActiveLayout()) {
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

    function createCameraMarkerNode(marker) {
        if (!editTrack) {
            return null;
        }

        const shell = documentObject.createElement("div");
        shell.className = "player-edit-camera-marker-shell";
        shell.dataset.markerId = String(marker.id);

        const button = documentObject.createElement("button");
        button.type = "button";
        button.className = "player-edit-marker player-edit-marker-camera";

        const icon = documentObject.createElement("img");
        icon.className = "player-edit-marker-icon";
        icon.src = editTrack.dataset.markerCameraIconUrl || "/static/mdi/marker-camera.svg";
        icon.alt = "";
        icon.setAttribute("aria-hidden", "true");
        button.append(icon);

        let draggedDuringPointerSequence = false;
        let pointerStartX = 0;
        let pointerStartY = 0;

        const popover = documentObject.createElement("div");
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
            onStateChanged();
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
                onStateChanged();
                schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            markerState.cameraKey = nextCameraKey;
            normalizeCameraMarker(markerState);
            onStateChanged();
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
            const cameraMarkerLabel = `Camera marker at ${formatClockTime(marker.time)}`;
            node.button.setAttribute("aria-label", cameraMarkerLabel);
            node.button.setAttribute("title", cameraMarkerLabel);
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
            layout: getActiveLayout(),
            cameraKey: getActiveCameraKey(),
        });
        cameraMarkers = [...cameraMarkers, marker];
        sortCameraMarkers();
        startMarkerPopoverOpen = false;
        activeCameraMarkerId = marker.id;
        onStateChanged();
        schedulePlayerEditsPersistence();
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
            onStateChanged();
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
                onStateChanged();
                schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            startMarkerViewSelection.cameraKey = nextCameraKey;
            normalizeViewSelection(startMarkerViewSelection);
            onStateChanged();
            schedulePlayerEditsPersistence();
        });
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
        const startMarkerLabel = `Start marker at ${formatClockTime(trimStartTime)}`;
        const endMarkerLabel = `End marker at ${formatClockTime(trimEndTime)}`;
        startMarkerButton.setAttribute("aria-label", startMarkerLabel);
        startMarkerButton.setAttribute("title", startMarkerLabel);
        endMarkerButton.setAttribute("aria-label", endMarkerLabel);
        endMarkerButton.setAttribute("title", endMarkerLabel);
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
        onStateChanged();
        schedulePlayerEditsPersistence();
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

    function bindEditingControls() {
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

        documentObject.addEventListener("pointerdown", (event) => {
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
                onStateChanged();
                return;
            }
            startMarkerPopoverOpen = false;
            onStateChanged();
        });

        documentObject.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") {
                return;
            }
            if (activeCameraMarkerId === null && !startMarkerPopoverOpen) {
                return;
            }
            activeCameraMarkerId = null;
            startMarkerPopoverOpen = false;
            onStateChanged();
        });
    }

    return {
        buildPlayerEditsPayload,
        hydrateSavedPlayerEdits,
        getTrimStartTime: () => trimStartTime,
        getTrimEndTime: () => trimEndTime,
        ensureTrimRange,
        syncTrimUI,
        syncCameraMarkerUI,
        getPlaybackMarkerIdAtOrBefore,
        syncPlaybackMarkerCheckpoint,
        maybeApplyPlaybackCameraMarker,
        maybeApplyCurrentPlaybackViewMarker,
        bindEditingControls,
    };
}