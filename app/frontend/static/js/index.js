import { createDeleteModalController } from "./delete-modal.js";

export function initIndexPage() {
    initIndexSelection();
}

const INDEX_SELECTION_LONG_PRESS_MS = 450;
const INDEX_SELECTION_MOVE_TOLERANCE_PX = 12;

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
