function syncOverlayButtonState(button, isActive, isDisabled = false) {
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
    button.disabled = isDisabled;
    const icon = button.querySelector(".player-camera-overlay-icon");
    if (icon?.dataset.activeSrc && icon?.dataset.inactiveSrc) {
        icon.src = isActive ? icon.dataset.activeSrc : icon.dataset.inactiveSrc;
    }
}

function createViewSelectionControls(documentObject, popover, controlBlueprints) {
    const controlButtons = [];
    for (const blueprint of controlBlueprints) {
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

function syncViewSelectionControls(selection, controlButtons, callbacks) {
    callbacks.normalizeViewSelection(selection);
    const visibleCameraKeys = callbacks.getVisibleCameraKeysForSelection(selection.layout, selection.cameraKey);
    for (const button of controlButtons) {
        const layoutOption = button.dataset.viewLayoutOption;
        const cameraTarget = button.dataset.viewCameraTarget;
        if (layoutOption) {
            syncOverlayButtonState(button, layoutOption === selection.layout, false);
            continue;
        }
        const isAvailable = Boolean(cameraTarget && callbacks.hasCameraPlaylist(cameraTarget));
        const isActive = Boolean(cameraTarget && visibleCameraKeys.has(cameraTarget));
        syncOverlayButtonState(button, isActive, !isAvailable);
    }
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

export function createEventPlayerMarkerUiController({
    documentObject,
    editTrack,
    startMarkerButton,
    controlBlueprints,
    formatClockTime,
    callbacks,
}) {
    const cameraMarkerNodes = new Map();
    const startMarkerPopover = editTrack && startMarkerButton
        ? documentObject.createElement("div")
        : null;
    const startMarkerPopoverButtons = [];

    if (startMarkerPopover && editTrack) {
        startMarkerPopover.className = "player-edit-camera-popover player-edit-start-marker-popover";
        startMarkerPopover.hidden = true;
        startMarkerPopoverButtons.push(...createViewSelectionControls(documentObject, startMarkerPopover, controlBlueprints));
        editTrack.append(startMarkerPopover);
    }

    function syncCameraMarkerPopover(marker, node) {
        if (!node) {
            return;
        }
        syncViewSelectionControls(marker, node.controlButtons, callbacks);
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

        const controlButtons = createViewSelectionControls(documentObject, popover, controlBlueprints);

        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (draggedDuringPointerSequence) {
                draggedDuringPointerSequence = false;
                return;
            }
            callbacks.setStartMarkerPopoverOpen(false);
            callbacks.setActiveCameraMarkerId(callbacks.getActiveCameraMarkerId() === marker.id ? null : marker.id);
            callbacks.onStateChanged();
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
            shell.classList.toggle("is-removing", callbacks.isCameraMarkerPointerOutsideLane(event.clientY));
            callbacks.setCameraMarkerTime(marker.id, callbacks.getEditTrackTimeFromClientX(event.clientX));
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
            const shouldRemoveMarker = event.type !== "pointercancel" && callbacks.isCameraMarkerPointerOutsideLane(event.clientY);
            shell.classList.remove("is-removing");
            if (shouldRemoveMarker) {
                callbacks.removeCameraMarker(marker.id);
                return;
            }
            callbacks.setCameraMarkerTime(marker.id, callbacks.getEditTrackTimeFromClientX(event.clientX));
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

            const markerState = callbacks.findCameraMarker(marker.id);
            if (!markerState) {
                return;
            }

            const nextLayout = controlButton.dataset.viewLayoutOption;
            if (nextLayout) {
                markerState.layout = nextLayout;
                callbacks.normalizeCameraMarker(markerState);
                callbacks.onStateChanged();
                callbacks.schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !callbacks.hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            markerState.cameraKey = nextCameraKey;
            callbacks.normalizeCameraMarker(markerState);
            callbacks.onStateChanged();
            callbacks.schedulePlayerEditsPersistence();
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

        const startMarkerViewSelection = callbacks.getStartMarkerViewSelection();
        callbacks.normalizeViewSelection(startMarkerViewSelection);
        const startRatio = totalDuration > 0 ? callbacks.getTrimStartTime() / totalDuration : 0;
        startMarkerPopover.style.left = `${startRatio * 100}%`;
        startMarkerPopover.hidden = !callbacks.getStartMarkerPopoverOpen();
        startMarkerPopover.dataset.align = getCameraMarkerPopoverAlign(callbacks.getTrimStartTime(), totalDuration);
        startMarkerButton.classList.toggle("is-open", callbacks.getStartMarkerPopoverOpen());
        syncViewSelectionControls(startMarkerViewSelection, startMarkerPopoverButtons, callbacks);
    }

    function syncCameraMarkerUI(totalDuration) {
        if (!editTrack) {
            return;
        }

        const cameraMarkers = callbacks.getCameraMarkers();
        const activeIds = new Set(cameraMarkers.map((marker) => marker.id));
        for (const [markerId, node] of cameraMarkerNodes.entries()) {
            if (activeIds.has(markerId)) {
                continue;
            }
            node.shell.remove();
            cameraMarkerNodes.delete(markerId);
        }

        for (const marker of cameraMarkers) {
            callbacks.normalizeCameraMarker(marker);
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
            node.button.classList.toggle("is-open", callbacks.getActiveCameraMarkerId() === marker.id);
            node.popover.hidden = callbacks.getActiveCameraMarkerId() !== marker.id;
            node.popover.dataset.align = getCameraMarkerPopoverAlign(marker.time, totalDuration);
            syncCameraMarkerPopover(marker, node);
        }
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
            callbacks.setActiveCameraMarkerId(null);
            callbacks.setStartMarkerPopoverOpen(!callbacks.getStartMarkerPopoverOpen());
            callbacks.onStateChanged();
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
            callbacks.setStartMarkerPopoverOpen(false);
            event.preventDefault();
            callbacks.updateTrimMarkerFromPointer("start", event.clientX);
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
            callbacks.setStartMarkerPopoverOpen(false);
            event.preventDefault();
            callbacks.updateTrimMarkerFromPointer("start", event.clientX);
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

            const startMarkerViewSelection = callbacks.getStartMarkerViewSelection();
            const nextLayout = controlButton.dataset.viewLayoutOption;
            if (nextLayout) {
                startMarkerViewSelection.layout = nextLayout;
                callbacks.normalizeViewSelection(startMarkerViewSelection);
                callbacks.onStateChanged();
                callbacks.schedulePlayerEditsPersistence();
                return;
            }

            const nextCameraKey = controlButton.dataset.viewCameraTarget;
            if (!nextCameraKey || !callbacks.hasCameraPlaylist(nextCameraKey)) {
                return;
            }
            startMarkerViewSelection.cameraKey = nextCameraKey;
            callbacks.normalizeViewSelection(startMarkerViewSelection);
            callbacks.onStateChanged();
            callbacks.schedulePlayerEditsPersistence();
        });
    }

    return {
        bindStartMarkerInteraction,
        syncCameraMarkerUI,
        syncStartMarkerPopoverUI,
    };
}