import { createDeleteModalController } from "./delete-modal.js";

export function initViewerDelete() {
    const deleteButton = document.querySelector("[data-viewer-delete-button]");
    const uncombineButton = document.querySelector("[data-viewer-uncombine-button]");
    if (!deleteButton && !uncombineButton) {
        return;
    }

    const deleteModal = createDeleteModalController();
    let deleteInFlight = false;
    let uncombineInFlight = false;

    deleteButton.addEventListener("click", async () => {
        const eventPath = deleteButton.dataset.eventPath;
        if (deleteInFlight || uncombineInFlight || !eventPath) {
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

    uncombineButton?.addEventListener("click", async () => {
        const eventPath = uncombineButton.dataset.eventPath;
        if (deleteInFlight || uncombineInFlight || !eventPath) {
            return;
        }

        const confirmed = await deleteModal.show({
            title: "Uncombine this clip?",
            message: "This removes the combined clip metadata and returns the individual clips to the index.",
            actionLabel: "Uncombine clip",
        });
        if (!confirmed) {
            return;
        }

        uncombineInFlight = true;
        uncombineButton.disabled = true;
        if (deleteButton) {
            deleteButton.disabled = true;
        }

        try {
            const response = await fetch(uncombineButton.dataset.uncombineUrl || `/events/${eventPath}/uncombine`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                const message = typeof payload?.error === "string" ? payload.error : "Uncombine failed.";
                throw new Error(message);
            }
            window.location.assign(uncombineButton.dataset.uncombineRedirectUrl || "/");
        } catch (error) {
            uncombineInFlight = false;
            uncombineButton.disabled = false;
            if (deleteButton) {
                deleteButton.disabled = false;
            }
            window.alert(error instanceof Error ? error.message : "Uncombine failed.");
        }
    });
}