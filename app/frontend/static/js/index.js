import { createDeleteModalController } from "./delete-modal.js";

export function initIndexPage() {
    initIndexSelection();
}

const INDEX_SELECTION_LONG_PRESS_MS = 450;
const INDEX_SELECTION_MOVE_TOLERANCE_PX = 12;
const COMBINE_ELIGIBILITY_DEBOUNCE_MS = 180;

function initIndexSelection() {
    const cards = Array.from(document.querySelectorAll("[data-index-card]"));
    const combineButton = document.querySelector("[data-index-combine-button]");
    const deleteButton = document.querySelector("[data-index-delete-button]");
    if (cards.length === 0 || !deleteButton) {
        return;
    }

    const deleteModal = createDeleteModalController();
    const selectedPaths = new Set();
    const body = document.body;
    let selectionMode = false;
    let combineInFlight = false;
    let deleteInFlight = false;
    let pendingLongPressTimer = 0;
    let pendingPointerId = null;
    let pendingPointerX = 0;
    let pendingPointerY = 0;
    let suppressNextClick = false;
    let combineEligibilityTimer = 0;
    let combineEligibilityAbortController = null;
    let combineEligibilityPending = false;
    let combineEligibilityKnown = false;
    let combineEligibilityAllowed = false;
    let combineEligibilitySignature = "";
    const combineEligibilityCache = new Map();

    function getSelectedCards() {
        return cards.filter((card) => selectedPaths.has(card.dataset.eventPath || ""));
    }

    function getSortedSelectedPaths() {
        return Array.from(selectedPaths).sort();
    }

    function isPotentiallyCombinableSelection() {
        const selectedCards = getSelectedCards();
        if (selectedCards.length < 2) {
            return false;
        }
        for (const card of selectedCards) {
            if ((card.dataset.eventCategory || "") !== "SavedClips") {
                return false;
            }
        }
        return true;
    }

    function clearCombineEligibilityTimer() {
        if (combineEligibilityTimer) {
            window.clearTimeout(combineEligibilityTimer);
        }
        combineEligibilityTimer = 0;
    }

    function abortCombineEligibilityRequest() {
        if (combineEligibilityAbortController) {
            combineEligibilityAbortController.abort();
            combineEligibilityAbortController = null;
        }
    }

    function resetCombineEligibilityState() {
        clearCombineEligibilityTimer();
        abortCombineEligibilityRequest();
        combineEligibilityPending = false;
        combineEligibilityKnown = false;
        combineEligibilityAllowed = false;
        combineEligibilitySignature = "";
    }

    async function requestCombineEligibility(eventPaths, signature) {
        if (!combineButton) {
            return;
        }

        const cachedEligibility = combineEligibilityCache.get(signature);
        if (cachedEligibility) {
            combineEligibilityPending = false;
            combineEligibilityKnown = true;
            combineEligibilityAllowed = Boolean(cachedEligibility.allowed);
            combineEligibilitySignature = signature;
            syncSelectionUi();
            return;
        }

        abortCombineEligibilityRequest();
        const abortController = new AbortController();
        combineEligibilityAbortController = abortController;
        combineEligibilityPending = true;
        combineEligibilityKnown = false;
        combineEligibilityAllowed = false;
        combineEligibilitySignature = signature;
        syncSelectionUi();

        try {
            const response = await fetch(combineButton.dataset.combineEligibilityUrl || "/events/combine/eligibility", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    eventPaths,
                }),
                signal: abortController.signal,
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                throw new Error(typeof payload?.error === "string" ? payload.error : "Could not verify clip combine eligibility.");
            }

            const allowed = Boolean(payload?.allowed);
            combineEligibilityCache.set(signature, { allowed });
            if (combineEligibilitySignature !== signature) {
                return;
            }

            combineEligibilityPending = false;
            combineEligibilityKnown = true;
            combineEligibilityAllowed = allowed;
            combineEligibilityAbortController = null;
            syncSelectionUi();
        } catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") {
                return;
            }
            if (combineEligibilitySignature !== signature) {
                return;
            }
            combineEligibilityPending = false;
            combineEligibilityKnown = true;
            combineEligibilityAllowed = false;
            combineEligibilityAbortController = null;
            syncSelectionUi();
        }
    }

    function scheduleCombineEligibilityRefresh() {
        if (!combineButton) {
            return;
        }

        if (!selectionMode || deleteInFlight || combineInFlight || !isPotentiallyCombinableSelection()) {
            resetCombineEligibilityState();
            syncSelectionUi();
            return;
        }

        const eventPaths = getSortedSelectedPaths();
        const signature = eventPaths.join("\n");
        if (combineEligibilityKnown && combineEligibilitySignature === signature) {
            syncSelectionUi();
            return;
        }

        clearCombineEligibilityTimer();
        combineEligibilityTimer = window.setTimeout(() => {
            combineEligibilityTimer = 0;
            void requestCombineEligibility(eventPaths, signature);
        }, COMBINE_ELIGIBILITY_DEBOUNCE_MS);
        syncSelectionUi();
    }

    function syncSelectionUi() {
        for (const card of cards) {
            const eventPath = card.dataset.eventPath || "";
            card.classList.toggle("is-selected", selectedPaths.has(eventPath));
        }

        const hasSelection = selectedPaths.size > 0;
        const canAttemptCombineSelection = hasSelection && isPotentiallyCombinableSelection();
        const canCombineSelection = canAttemptCombineSelection
            && combineEligibilityKnown
            && combineEligibilityAllowed;
        const selectionLabel = hasSelection
            ? `Delete ${selectedPaths.size} selected ${selectedPaths.size === 1 ? "clip" : "clips"}`
            : "Delete selected clips";
        const combineLabel = hasSelection
            ? `Combine ${selectedPaths.size} selected ${selectedPaths.size === 1 ? "clip" : "clips"}`
            : "Combine selected clips";

        deleteButton.hidden = !hasSelection;
        deleteButton.disabled = !hasSelection || deleteInFlight || combineInFlight;
        deleteButton.setAttribute("aria-label", selectionLabel);
        deleteButton.title = selectionLabel;

        if (combineButton) {
            combineButton.hidden = !canCombineSelection;
            combineButton.disabled = !canCombineSelection || combineInFlight || deleteInFlight || combineEligibilityPending;
            combineButton.setAttribute("aria-label", combineLabel);
            combineButton.title = combineLabel;
        }

        if (selectionMode && !hasSelection) {
            selectionMode = false;
            delete body.dataset.selectionMode;
        }
    }

    function exitSelectionMode() {
        selectionMode = false;
        selectedPaths.clear();
        delete body.dataset.selectionMode;
        resetCombineEligibilityState();
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

        scheduleCombineEligibilityRefresh();
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
        scheduleCombineEligibilityRefresh();
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
        if (event.key !== "Escape" || !selectionMode || deleteInFlight || combineInFlight) {
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
            if (deleteInFlight || combineInFlight || deleteModal.isOpen()) {
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

            if (!selectionMode || deleteInFlight || combineInFlight || deleteModal.isOpen()) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            toggleCardSelection(card);
        });
    }

    deleteButton.addEventListener("click", async () => {
        if (deleteInFlight || combineInFlight || selectedPaths.size === 0) {
            return;
        }

        const selectionCount = selectedPaths.size;
        const confirmed = await deleteModal.show(selectionCount);
        if (!confirmed) {
            return;
        }

        deleteInFlight = true;
        resetCombineEligibilityState();
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

    combineButton?.addEventListener("click", async () => {
        if (combineInFlight || deleteInFlight || selectedPaths.size === 0 || !combineEligibilityKnown || !combineEligibilityAllowed) {
            return;
        }

        combineInFlight = true;
        resetCombineEligibilityState();
        syncSelectionUi();

        try {
            const response = await fetch(combineButton.dataset.combineUrl || "/events/combine", {
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
                const message = typeof payload?.error === "string" ? payload.error : "Combine failed.";
                throw new Error(message);
            }
            window.location.reload();
        } catch (error) {
            combineInFlight = false;
            syncSelectionUi();
            window.alert(error instanceof Error ? error.message : "Combine failed.");
        }
    });
}
