import { createDeleteModalController } from "./delete-modal.js";

export function initViewerDelete() {
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